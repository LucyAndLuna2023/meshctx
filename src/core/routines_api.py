"""Routines API (WP6, MCTX-PLAN-2026-0903 P1-3) — 例行值守的管理与派活。

/auth 语义与 task_cards_api 一致 (owner 归因 + 写操作拒匿名 + 跨 owner 403):
- /api/routines 已加入 auth_v2._AUTH_WHITELIST_PREFIXES (main 接线)
- 端内 _owner/_reject_anon/_plan 复用 task_cards_api 同款帮助函数 (避免 import main 循环)

spawn 工厂 (make_spawn_fn): 供 lifespan 启动 RoutineScheduler 注入 —
配额 try_consume_spawn → TaskCard(enqueue) → 失败 refund (与 create_card 同语义);
个人版免费软提示不硬阻断语义由 HubQuota 内部保证, 此处与 /api/tasks/cards 创建路径一致。
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("meshctx.routines_api")

router = APIRouter(prefix="/api/routines", tags=["Routines"])


async def _owner(request: Request) -> str:
    try:
        from src.main import _current_user_id
        return await _current_user_id(request)
    except Exception:
        from src.core.auth_v2 import _authenticate, _is_loopback_client
        try:
            identity, is_admin = await _authenticate(request)
            if identity:
                return "admin" if is_admin else f"key:{identity}"
            if _is_loopback_client(request):
                return "local"
        except Exception:
            pass
    return ""


async def _plan(request: Request) -> str:
    try:
        from src.main import _plan_of_user
        plan = await _plan_of_user(request)
        return plan or "free"
    except Exception:
        return "free"


async def _reject_anon(owner: str):
    if not owner:
        raise HTTPException(401, "需要登录 (本机回环可免登录使用)")


def _store():
    from src.core.routines import RoutineStore
    return RoutineStore()


def make_spawn_fn():
    """后台派活 (配额 + enqueue, 与 /api/tasks/cards 创建同语义; 同步, 供调度线程)。"""
    from src.core.task_cards import get_card_worker, get_hub_quota, TaskCard

    def spawn(routine, now_ts: float) -> bool:
        owner = routine.owner
        if not owner or not routine.enabled:
            return False
        try:
            prompt = routine.render_prompt(now_ts)
            worker = get_card_worker()
            hq = get_hub_quota()
            concurrent = worker.running_count()
            q = hq.try_consume_spawn(owner, plan=routine.plan,
                                     concurrent_now=concurrent)
            if not q["ok"]:
                logger.info("routine %s 配额不足跳过 (owner=%s): %s",
                            routine.id, owner, q.get("reason"))
                return False
            card = TaskCard(owner=owner, plan=routine.plan,
                            title=(routine.title or routine.name or prompt[:60]),
                            prompt=prompt, model=routine.model or "")
            if routine.max_rounds:
                card.extra["max_rounds"] = int(routine.max_rounds)
            wc = float(routine.wall_clock or 300)
            card.extra["wall_clock"] = max(30, min(wc, 7200))
            card.extra["quota"] = q
            card.extra["routine_id"] = routine.id
            if not worker.enqueue(card):
                hq.refund_spawn(owner)      # 入队失败退回 (P4 004meshctx 语义)
                return False
            logger.info("routine %s 派活成功 (owner=%s, card=%s)",
                        routine.id, owner, card.id)
            return True
        except Exception:
            logger.exception("routine %s spawn 异常", routine.id)
            return False
    return spawn


def _validate(body: dict) -> None:
    """轻量校验 (错误直接 HTTPException)。"""
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt 不能为空 (值守要做什么)")
    if len(prompt) > 8000:
        raise HTTPException(400, "prompt 过长 (>8000)")
    kind = str(body.get("kind") or "interval")
    if kind not in ("interval", "cron"):
        raise HTTPException(400, "kind 仅支持 interval|cron")
    if kind == "cron":
        from src.core.routines import CronMatcher
        try:
            CronMatcher(str(body.get("schedule") or ""))
        except Exception as e:
            raise HTTPException(400, f"cron 表达式无效: {e}")
    else:
        try:
            if float(body.get("schedule", "3600")) < 10:
                raise ValueError("interval 最短 10s")
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f"interval schedule 无效: {e}")


@router.post("")
async def create_routine(request: Request):
    from src.core.routines import Routine
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    owner = await _owner(request)
    await _reject_anon(owner)
    _validate(body)
    plan = await _plan(request)
    r = Routine(
        owner=owner,
        prompt=str(body["prompt"]).strip(),
        name=str(body.get("name") or "")[:80],
        kind=str(body.get("kind") or "interval"),
        schedule=str(body.get("schedule") or ("3600" if body.get("kind") != "cron" else "* * * * *")),
        enabled=bool(body.get("enabled", True)),
        title=str(body.get("title") or "")[:120],
        model=str(body.get("model") or ""),
        max_rounds=int(body.get("max_rounds") or 0),
        wall_clock=float(body.get("wall_clock") or 300.0),
        plan=plan,
    )
    _store().save(r)
    return r.to_dict()


@router.get("")
async def list_routines(request: Request) -> List[dict]:
    owner = await _owner(request)
    await _reject_anon(owner)
    return [r.to_dict() for r in _store().list() if r.owner == owner]


@router.get("/{rid}")
async def get_routine(rid: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    r = _store().get(rid)
    if r is None or r.owner != owner:
        raise HTTPException(404, "routine 不存在")
    return r.to_dict()


@router.patch("/{rid}")
async def update_routine(rid: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    store = _store()
    r = store.get(rid)
    if r is None or r.owner != owner:
        raise HTTPException(404, "routine 不存在")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    # 允许修改字段 (enabled 开关/名称/标题/模型/执行参数/调度)
    allowed = {"name", "title", "model", "enabled", "max_rounds",
               "wall_clock", "prompt", "kind", "schedule"}
    changed = False
    for k, v in body.items():
        if k not in allowed:
            continue
        if k == "prompt":
            v = str(v).strip()
            if not v or len(v) > 8000:
                raise HTTPException(400, "prompt 无效")
        if k in ("kind", "schedule"):
            probe = dict(r.to_dict())
            probe.update({k: v, "kind": body.get("kind", r.kind),
                          "schedule": body.get("schedule", r.schedule)})
            _validate({"prompt": r.prompt, "kind": probe["kind"],
                       "schedule": probe["schedule"]})
        if k == "max_rounds":
            v = int(v or 0)
        if k == "wall_clock":
            v = float(v or 300.0)
        if k == "enabled":
            v = bool(v)
        setattr(r, k, v)
        changed = True
    if changed:
        store.save(r)
    return r.to_dict()


@router.delete("/{rid}")
async def delete_routine(rid: str, request: Request):
    owner = await _owner(request)
    await _reject_anon(owner)
    r = _store().get(rid)
    if r is None or r.owner != owner:
        raise HTTPException(404, "routine 不存在")
    _store().remove(rid)
    return {"ok": True, "id": rid}


@router.post("/{rid}/run")
async def run_routine_now(rid: str, request: Request):
    """立即触发一次 (手动) — 走同一配额/enqueue 路径。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    store = _store()
    r = store.get(rid)
    if r is None or r.owner != owner:
        raise HTTPException(404, "routine 不存在")
    spawn = make_spawn_fn()
    now = time.time()
    ok = spawn(r, now)
    if ok:
        store.mark_fired(rid, True, ts=now)
        return {"ok": True, "id": rid}
    return {"ok": False, "id": rid, "reason": "配额不足或派活失败 (稍后自动重试)"}

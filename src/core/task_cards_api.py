# -*- coding: utf-8 -*-
"""Task Cards API — Agent 派活中心 HTTP 层 (开源真实实现, AGPLv3)

端点 (main.py include_router):
  POST   /api/tasks/cards             一句话派活 → 后台任务卡
  GET    /api/tasks/cards             我的任务卡列表 (owner 过滤)
  GET    /api/tasks/cards/{id}        单卡详情 (timeline/result/pending)
  POST   /api/tasks/cards/{id}/cancel 取消
  POST   /api/tasks/cards/{id}/retry  重试 (复制为新卡)
  POST   /api/tasks/cards/{id}/approve  审批决定 (agree/reject/custom)
  GET    /api/tasks/quota             配额状态

鉴权: /api/tasks/ 前缀在认证白名单 (auth_v2.py:46), 端内自行归因:
  _current_user_id → admin/key:{name}/local/"" — 未认证远程拒绝写操作。
计划: personal 全开 (free); team/enterprise 组织治理在私有库 (team_hub) 扩展。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("meshctx.task_cards_api")

router = APIRouter(prefix="/api/tasks", tags=["Task Cards"])


def _store():
    from src.core.task_cards import TaskCardStore
    return TaskCardStore()


def _worker():
    from src.core.task_cards import get_card_worker
    return get_card_worker()


async def _owner(request: Request) -> str:
    """当前用户 id (main._current_user_id 语义复用, 避免 import main 循环)。"""
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


@router.post("/cards")
async def create_card(request: Request):
    """一句话派活 → 入队后台任务卡。body: {prompt|message, model?, title?, plan?,
    max_rounds?, wall_clock?(秒, 默认300, 范围30-7200)}"""
    import json
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    prompt = str(body.get("prompt") or body.get("message") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt 不能为空 (一句话描述任务)")
    if len(prompt) > 8000:
        raise HTTPException(400, "prompt 过长 (>8000)")
    owner = await _owner(request)
    await _reject_anon(owner)
    plan = await _plan(request)

    # 配额前门: 复用 ResourceManager.pre_task 语义 (轻量) + HubQuota 本地表
    from src.core.task_cards import TaskCard, get_hub_quota
    hq = get_hub_quota()
    worker = _worker()
    concurrent = worker.running_count()
    q = hq.try_consume_spawn(owner, plan=plan, concurrent_now=concurrent)

    # 个人版不硬阻断 (软提示); 付费硬限出口保留 (q["ok"] False 仅 team/enterprise 命中)
    if not q["ok"]:
        raise HTTPException(429, f"配额不足: {q['reason']}")

    card = TaskCard(owner=owner, plan=plan,
                    title=str(body.get("title") or prompt[:60]),
                    prompt=prompt,
                    model=str(body.get("model") or ""))
    # 可选执行参数: max_rounds (固定轮次), wall_clock (秒, 默认 300)
    if body.get("max_rounds"):
        card.extra["max_rounds"] = int(body["max_rounds"])
    wc = body.get("wall_clock")
    if wc:
        card.extra["wall_clock"] = max(30, min(float(wc), 7200))
    card.extra["quota"] = q
    if not worker.enqueue(card):
        raise HTTPException(503, "任务队列未就绪 (worker 未启动)")
    hq.ensure_rules(owner, plan)
    return {"card_id": card.id, "status": card.status.value, "quota": q}


@router.get("/cards")
async def list_cards(request: Request, status: Optional[str] = None,
                     limit: int = 50):
    """我的任务卡列表 (owner 过滤, 新→旧)。"""
    from src.core.task_cards import CardStatus
    owner = await _owner(request)
    await _reject_anon(owner)
    want = None
    if status:
        try:
            want = CardStatus(status)
        except ValueError:
            raise HTTPException(400, f"未知 status: {status}")
    cards = _store().list_cards(owner=owner, status=want)
    out = []
    for c in cards[:max(1, min(limit, 200))]:
        d = c.to_dict()
        d.pop("timeline", None)  # 列表不携带长事件
        out.append(d)
    return {"cards": out, "total": len(cards), "owner": owner}


@router.get("/cards/{card_id}")
async def get_card(card_id: str, request: Request):
    """单卡详情 (含 timeline)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    card = _store().load(card_id)
    if card is None:
        raise HTTPException(404, f"任务卡 {card_id} 不存在")
    if card.owner != owner:
        raise HTTPException(403, "无权查看他人任务卡")
    return card.to_dict()


@router.get("/cards/{card_id}/stream")
async def stream_card(card_id: str, request: Request):
    """任务卡事件 SSE 流 (可选实时订阅; 前端可用轮询代替)。

    语义: 连接后立即推送当前卡全量, 之后每 1s 推送增量 (status/timeline 变化);
    卡进入终止态 (completed/failed/cancelled) 后推送 final 并结束。
    前端简单做法: 用轮询 (/api/tasks/cards/{id}); 本端点供实时 UI 使用。
    """
    from fastapi.responses import StreamingResponse
    from src.core.task_cards import CardStatus
    owner = await _owner(request)
    await _reject_anon(owner)
    store = _store()
    first = store.load(card_id)
    if first is None:
        raise HTTPException(404, f"任务卡 {card_id} 不存在")
    if first.owner != owner:
        raise HTTPException(403, "无权查看他人任务卡")

    import asyncio
    import json as _json

    TERMINAL = (CardStatus.COMPLETED, CardStatus.FAILED, CardStatus.CANCELLED)

    async def _gen():
        last_sig = ""
        while True:
            card = store.load(card_id)
            if card is None:
                yield "data: {\"event\":\"gone\"}\n\n"
                return
            sig = f"{card.status.value}:{len(card.timeline)}:{card.updated_at}"
            if sig != last_sig:
                last_sig = sig
                payload = card.to_dict()
                if card.status in TERMINAL:
                    yield f"data: {_json.dumps({'event':'final', 'card': payload})}\n\n"
                    return
                yield f"data: {_json.dumps({'event':'update', 'card': payload})}\n\n"
            # 心跳
            yield ": ping\n\n"
            try:
                await asyncio.wait_for(asyncio.sleep(1.0), timeout=2.0)
            except Exception:
                return

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str, request: Request):
    """删除一张历史任务卡 (仅终止态卡可删; 运行中需先取消)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    store = _store()
    card = store.load(card_id)
    if card is None:
        raise HTTPException(404, f"任务卡 {card_id} 不存在")
    if card.owner != owner:
        raise HTTPException(403, "无权操作他人任务卡")
    from src.core.task_cards import CardStatus
    if card.status not in (CardStatus.COMPLETED, CardStatus.FAILED,
                           CardStatus.CANCELLED):
        raise HTTPException(409, "运行中的任务卡不能删除 — 请先取消")
    ok = store.delete(card_id)
    if not ok:
        raise HTTPException(500, "删除失败")
    return {"card_id": card_id, "deleted": True}


@router.post("/cards/{card_id}/cancel")
async def cancel_card(card_id: str, request: Request):
    """取消任务卡 (排队中直接取消; 运行中置 cancel_requested 优雅中断)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    card = _store().load(card_id)
    if card is None:
        raise HTTPException(404, f"任务卡 {card_id} 不存在")
    if card.owner != owner:
        raise HTTPException(403, "无权操作他人任务卡")
    ok = _worker().cancel(card_id)
    return {"card_id": card_id, "cancel_requested": ok}


@router.post("/cards/{card_id}/retry")
async def retry_card(card_id: str, request: Request):
    """重试: 以相同 prompt 复制为新卡入队 (原卡保留)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    old = _store().load(card_id)
    if old is None:
        raise HTTPException(404, f"任务卡 {card_id} 不存在")
    if old.owner != owner:
        raise HTTPException(403, "无权操作他人任务卡")
    from src.core.task_cards import TaskCard, get_hub_quota
    worker = _worker()
    q = get_hub_quota().try_consume_spawn(owner, plan=old.plan,
                                          concurrent_now=worker.running_count())
    card = TaskCard(owner=owner, plan=old.plan, title=f"[重试] {old.title}",
                    prompt=old.prompt, model=old.model)
    if not worker.enqueue(card):
        raise HTTPException(503, "任务队列未就绪")
    return {"card_id": card.id, "retry_of": card_id, "status": card.status.value}


@router.post("/cards/{card_id}/approve")
async def approve_card(card_id: str, request: Request):
    """任务卡审批决定。body: {action: agree|reject|custom, text?}"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效 JSON")
    action = str(body.get("action") or "")
    if action not in ("agree", "reject", "custom"):
        raise HTTPException(400, "action 需为 agree/reject/custom")
    text = str(body.get("text") or "")
    owner = await _owner(request)
    await _reject_anon(owner)
    store = _store()
    card = store.load(card_id)
    if card is None:
        raise HTTPException(404, f"任务卡 {card_id} 不存在")
    if card.owner != owner:
        raise HTTPException(403, "无权操作他人任务卡")
    pending = card.approval_pending
    if not pending or not pending.get("request_id"):
        raise HTTPException(400, "该任务卡当前无待审批操作")
    req_id = pending["request_id"]
    worker = _worker()
    found = worker.decide_approval(req_id, action, text)
    if not found:
        # 可能已超时/已处理 → 回读最新状态
        card2 = store.load(card_id)
        raise HTTPException(409, "审批请求已超时或已处理" if card2 and not card2.approval_pending
                           else "审批请求不存在")
    # future 已 resolve → 卡线程 worker 会继续执行并最终落盘; 这里仅同步 pending 状态
    # 便于轮询接口立即看到"已决策" (不重复 save, 避免与 worker 落盘竞争)
    return {"card_id": card_id, "action": action, "decided": True}


@router.get("/quota")
async def quota_status(request: Request):
    """配额状态 (开源本地表, 个人版软提示)。"""
    owner = await _owner(request)
    await _reject_anon(owner)
    plan = await _plan(request)
    from src.core.task_cards import get_hub_quota, PLAN_LIMITS
    hq = get_hub_quota()
    lim = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    # 实际用量从 quota_manager 读 (先确保规则存在)
    used = 0
    qm = hq._get_qm()
    if qm is not None:
        try:
            hq.ensure_rules(owner, plan)
            _, remaining, _ = qm.check(f"{hq.QUOTA_KEY_DAILY}:{owner}", units=0)
            used = max(0, lim["spawns_per_day"] - remaining)
        except Exception:
            pass
    worker = _worker()
    return {"plan": plan, "limits": lim,
            "used_today": used,
            "running": worker.running_count()}


__all__ = ["router"]

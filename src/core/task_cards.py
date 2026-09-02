# -*- coding: utf-8 -*-
"""Task Cards — Agent 派活中心 (开源真实实现, AGPLv3)

一句话派活 → 后台任务卡片 → 可见进度/结果/取消/重试 + 配额计量。

设计要点 (2026-09-02 004meshctx, 基于 4 份架构勘察):
- 复用而非重造:
  * run_agent_loop (src/agent_loop.py) 为唯一统一 agent 循环, CardWorker 只做编排。
  * work_engine (src/work_engine.py) 的原子 JSON 持久化范式。
  * quota_manager / usage_meter (src/core/) 完整但零接线 —— 本模块接线。
  * agent_tasks.TaskStatus 状态机语义保持一致。
- 服务端没有后台 LLM runner: CardWorker 由 FastAPI lifespan 启动全局 asyncio 消费者。
- 会话与任务隔离: 任务卡独立 store (~/.meshctx/task_cards/), 不塞 conversations。
- 开源/闭源边界: 本文件开源 (个人版免费全功能); 组织级治理 (团队共享/配额预算/
  Always-approve 域/审计/SSO) 在私有库 stub→真实现, 本模块只留 plan 维度软提示。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.task_cards")

CARDS_DIR = pathlib.Path.home() / ".meshctx" / "task_cards"

# 卡状态 (与 agent_tasks.TaskStatus 语义一致, 便于既有代码互认)
class CardStatus(str, Enum):
    QUEUED = "queued"          # 等待 worker 领取
    RUNNING = "running"        # agent 循环执行中
    WAITING_APPROVAL = "waiting_approval"  # 危险动作等待审批
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# 本地套餐阈值 (开源默认表; team/enterprise 覆盖表在私有库 business_plans)
# 单位: 并发派活卡数上限 / 每日派活次数上限 (soft 提示, 非硬墙)
PLAN_LIMITS: Dict[str, Dict[str, int]] = {
    "free":      {"max_concurrent": 3, "spawns_per_day": 50},
    "team":      {"max_concurrent": 10, "spawns_per_day": 200},
    "enterprise": {"max_concurrent": 50, "spawns_per_day": 1000},
}

# 卡保留: 每用户最多保留多少张 (自动清理最旧 completed/failed)
MAX_CARDS_PER_OWNER = 200


class TaskCard:
    """一张派活任务卡 (与 work_engine.WorkJob 同范式, 但面向"一句话派活")。"""

    def __init__(self, **kw):
        self.id: str = kw.get("id") or uuid.uuid4().hex[:12]
        self.owner: str = kw.get("owner") or "local"      # _current_user_id 语义
        self.plan: str = kw.get("plan") or "free"          # free/team/enterprise
        self.title: str = kw.get("title") or ""
        self.prompt: str = kw.get("prompt") or ""          # 一句话任务
        self.model: str = kw.get("model") or ""            # 空=默认模型
        self.status: CardStatus = CardStatus(kw.get("status") or CardStatus.QUEUED)
        self.created_at: float = float(kw.get("created_at") or time.time())
        self.updated_at: float = float(kw.get("updated_at") or self.created_at)
        self.started_at: Optional[float] = kw.get("started_at")
        self.finished_at: Optional[float] = kw.get("finished_at")
        self.timeline: List[Dict[str, Any]] = kw.get("timeline") or []  # 事件日志
        self.result: Optional[str] = kw.get("result")                   # 最终文本
        self.error: Optional[str] = kw.get("error")
        # 审批挂起: {request_id, command, reason} 或 None
        self.approval_pending: Optional[Dict[str, Any]] = kw.get("approval_pending")
        self.cancel_requested: bool = bool(kw.get("cancel_requested"))
        self.extra: Dict[str, Any] = kw.get("extra") or {}

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self) if False else {
            "id": self.id, "owner": self.owner, "plan": self.plan,
            "title": self.title, "prompt": self.prompt, "model": self.model,
            "status": self.status.value if isinstance(self.status, CardStatus) else self.status,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "timeline": self.timeline, "result": self.result, "error": self.error,
            "approval_pending": self.approval_pending,
            "cancel_requested": self.cancel_requested, "extra": self.extra,
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskCard":
        return cls(**d)

    def touch(self):
        self.updated_at = time.time()

    def log(self, kind: str, **payload):
        self.timeline.append({"t": time.time(), "kind": kind, **payload})
        self.touch()

    # ── 状态迁移 ──
    def mark(self, status: CardStatus, **kw):
        self.status = CardStatus(status) if not isinstance(status, CardStatus) else status
        for k, v in kw.items():
            setattr(self, k, v)
        if status == CardStatus.RUNNING and not self.started_at:
            self.started_at = time.time()
        if status in (CardStatus.COMPLETED, CardStatus.FAILED, CardStatus.CANCELLED):
            self.finished_at = time.time()
        self.touch()


def _atomic_write(path: pathlib.Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:  # 0600: 任务含用户提示词
        os.chmod(path, 0o600)
    except Exception:
        pass


class TaskCardStore:
    """任务卡持久化 (原子 JSON, 每卡一文件)。线程安全。"""

    def __init__(self, base_dir: Optional[pathlib.Path] = None):
        self._dir = pathlib.Path(base_dir or CARDS_DIR)
        self._lock = threading.RLock()

    def _path(self, card_id: str) -> pathlib.Path:
        return self._dir / f"{card_id}.json"

    def save(self, card: TaskCard) -> TaskCard:
        with self._lock:
            _atomic_write(self._path(card.id), card.to_dict())
        return card

    def load(self, card_id: str) -> Optional[TaskCard]:
        p = self._path(card_id)
        if not p.exists():
            return None
        try:
            with self._lock:
                return TaskCard.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("task_card load %s failed: %s", card_id, e)
            return None

    def delete(self, card_id: str) -> bool:
        p = self._path(card_id)
        with self._lock:
            if p.exists():
                try:
                    p.unlink()
                    return True
                except Exception:
                    return False
        return False

    def list_cards(self, owner: Optional[str] = None,
                   status: Optional[CardStatus] = None) -> List[TaskCard]:
        if not self._dir.exists():
            return []
        want = CardStatus(status) if isinstance(status, str) and status else status
        out: List[TaskCard] = []
        with self._lock:
            for p in sorted(self._dir.glob("*.json")):
                try:
                    c = TaskCard.from_dict(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    continue
                if owner and c.owner != owner:
                    continue
                if want is not None and c.status != want:
                    continue
                out.append(c)
        out.sort(key=lambda c: c.created_at, reverse=True)
        return out

    def prune(self, owner: str, keep: int = MAX_CARDS_PER_OWNER) -> int:
        """清理该 owner 最旧的 completed/failed/cancelled 卡, 保留 keep 张。"""
        cards = self.list_cards(owner=owner)
        terminal = [c for c in cards if c.status in (
            CardStatus.COMPLETED, CardStatus.FAILED, CardStatus.CANCELLED)]
        terminal.sort(key=lambda c: c.finished_at or c.created_at)
        removed = 0
        while len(terminal) > keep:
            old = terminal.pop(0)
            if self.delete(old.id):
                removed += 1
        return removed


class HubQuota:
    """配额计量 — 接线 quota_manager/usage_meter (开源本地表, soft 提示)。

    用法 (main.py /api/tasks 层调用):
        hq = get_hub_quota()
        ok, used, remaining, reason = hq.try_consume_spawn("local", plan="free")
    """

    QUOTA_KEY_DAILY = "task_cards:spawns:day"
    QUOTA_KEY_CONCURRENT = "task_cards:concurrent"

    def __init__(self):
        self._qm = None
        self._um = None
        self._lock = threading.Lock()

    def _get_qm(self):
        if self._qm is None:
            try:
                from src.core.quota_manager import get_quota_manager
                self._qm = get_quota_manager()
            except Exception as e:
                logger.warning("quota_manager unavailable: %s", e)
        return self._qm

    def _get_um(self):
        if self._um is None:
            try:
                from src.core.usage_meter import get_usage_meter
                self._um = get_usage_meter()
            except Exception as e:
                logger.warning("usage_meter unavailable: %s", e)
        return self._um

    def _limits(self, plan: str) -> Dict[str, int]:
        return PLAN_LIMITS.get(plan or "free", PLAN_LIMITS["free"])

    def ensure_rules(self, owner: str, plan: str = "free"):
        """幂等注册本地配额规则 (软限制, 不阻断个人版)。"""
        qm = self._get_qm()
        if qm is None:
            return
        lim = self._limits(plan)
        try:
            qm.set_quota(f"{self.QUOTA_KEY_DAILY}:{owner}", max_units=lim["spawns_per_day"],
                         window="day", level="user", limit_type="soft", enabled=True)
        except Exception as e:
            logger.debug("quota rule daily: %s", e)

    def try_consume_spawn(self, owner: str, plan: str = "free",
                          concurrent_now: int = 0) -> Dict[str, Any]:
        """尝试消耗一次派活额度。返回 {ok, used, remaining, reason}。

        personal 免费版: 仅软提示不硬阻断 (plan 阈值超了也给 ok, 标记 warned);
        team/enterprise 硬限由私有库 business_plans 层覆盖 (本函数保留 plan 参数出口)。
        """
        qm = self._get_qm()
        lim = self._limits(plan)
        res = {"ok": True, "warned": False, "reason": "",
               "used": 0, "remaining": lim["spawns_per_day"],
               "concurrent_now": concurrent_now,
               "max_concurrent": lim["max_concurrent"]}
        # 并发软提示
        if concurrent_now >= lim["max_concurrent"]:
            res["warned"] = True
            res["reason"] = f"concurrent limit {lim['max_concurrent']} reached (soft)"
        if qm is None:
            return res
        try:
            used, remaining, allowed = qm.consume(
                f"{self.QUOTA_KEY_DAILY}:{owner}", units=1, user_id=owner)
            res["used"] = used
            res["remaining"] = remaining
            if not allowed and plan in ("team", "enterprise"):
                # 付费版硬限: 由私有层决定; 这里软失败交给上层
                res["ok"] = False
                res["reason"] = f"daily spawn quota exceeded (plan={plan})"
        except Exception as e:
            logger.debug("quota consume: %s", e)
        return res

    def record_usage(self, owner: str, model: str, tokens_in: int = 0,
                     tokens_out: int = 0, cost_usd: float = 0.0):
        um = self._get_um()
        if um is None:
            return
        try:
            um.record_usage(tenant=owner, metric="task_card_tokens", model=model or "",
                            value=tokens_in + tokens_out)
            if cost_usd:
                um.record_usage(tenant=owner, metric="task_card_cost", model=model or "",
                                value=cost_usd)
        except Exception as e:
            logger.debug("usage record: %s", e)


_hub_quota: Optional[HubQuota] = None
def get_hub_quota() -> HubQuota:
    global _hub_quota
    if _hub_quota is None:
        _hub_quota = HubQuota()
    return _hub_quota


# ═══ 后台 Worker (编排 run_agent_loop) ═══
class CardWorker:
    """全局 asyncio 队列消费者 — 由 FastAPI lifespan 启动。

    run_fn: Optional 执行回调 (T2 注入 run_agent_loop 链; 单测注入 fake 便于验证编排)。
    """

    def __init__(self):
        self._store = TaskCardStore()
        self._queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running: Dict[str, asyncio.Task] = {}
        self._run_fn: Optional[Callable[[TaskCard], Awaitable[Dict[str, Any]]]] = None
        self._started = False
        self._stopping = False
        # 审批协调: card_id → asyncio.Future (等待 Web /api/tasks/cards/{id}/approve 决定)
        self._approval_futures: Dict[str, "asyncio.Future"] = {}
        self._approval_lock = threading.Lock()

    # ── 生命周期 ──
    def start(self, run_fn: Optional[Callable[[TaskCard], Awaitable[Dict[str, Any]]]] = None,
              loop: Optional[asyncio.AbstractEventLoop] = None):
        if self._started:
            return
        self._run_fn = run_fn
        self._started = True
        self._stopping = False
        loop = loop or asyncio.get_event_loop()
        self._task = loop.create_task(self._consume())

    async def stop(self):
        self._stopping = True
        for t in list(self._running.values()):
            t.cancel()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._started = False

    # ── 对外 ──
    def enqueue(self, card: TaskCard) -> bool:
        """入队并立即落盘。返回是否成功入队。"""
        if self._stopping or not self._started:
            return False
        self._store.save(card)
        self._queue.put_nowait(card.id)
        return True

    def cancel(self, card_id: str) -> bool:
        """请求取消: 置 cancel_requested 并尝试取消正在跑的任务。"""
        card = self._store.load(card_id)
        if card is None:
            return False
        card.cancel_requested = True
        self._store.save(card)
        t = self._running.get(card_id)
        if t is not None:
            t.cancel()
            return True
        # 排队中: 直接标记取消
        if card.status == CardStatus.QUEUED:
            card.mark(CardStatus.CANCELLED, error="cancelled before start")
            self._store.save(card)
        return True

    def running_count(self) -> int:
        return len(self._running)

    # ── 审批协调 (卡级 pending → Web decide → future resolve) ──
    def register_approval(self, card: TaskCard, request_id: str,
                          name: str, args: Dict, reason: str):
        """agent 请求审批时: 落盘 pending + 登记 future (循环所在线程)。"""
        loop = asyncio.get_event_loop()
        fut: "asyncio.Future" = loop.create_future()
        with self._approval_lock:
            self._approval_futures[request_id] = fut
        card.approval_pending = {
            "request_id": request_id, "name": name, "args": args,
            "reason": reason, "ts": time.time(), "card_id": card.id,
        }
        card.status = CardStatus.WAITING_APPROVAL
        card.touch()
        self._store.save(card)
        return fut

    def decide_approval(self, request_id: str, action: str, text: str = "") -> bool:
        """Web 端决定: 写回卡并 resolve future。返回是否找到。"""
        fut = None
        with self._approval_lock:
            fut = self._approval_futures.pop(request_id, None)
        if fut is None or fut.done():
            return False
        # 由调用线程触发 (decide 来自 HTTP 协程 → run_until_complete 不安全,
        # 用 call_soon_threadsafe 交给事件循环)
        loop = fut.get_loop()
        loop.call_soon_threadsafe(
            fut.set_result, {"action": action, "text": text})
        return True

    def pending_approval_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        card = self._store.load(card_id)
        return card.approval_pending if card else None

    # ── 内部 ──
    async def _consume(self):
        while not self._stopping:
            try:
                card_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.2)
                continue
            card = self._store.load(card_id)
            if card is None or card.status == CardStatus.CANCELLED:
                continue
            # 并发上限 (soft)
            lim = PLAN_LIMITS.get(card.plan, PLAN_LIMITS["free"])
            if self.running_count() >= lim["max_concurrent"]:
                # 不丢卡: 退回队列等待 (轮询式回队, 简单可靠)
                await asyncio.sleep(0.5)
                self._queue.put_nowait(card_id)
                continue
            t = asyncio.get_event_loop().create_task(self._run_one(card))
            self._running[card_id] = t
        self._started = False

    async def _run_one(self, card: TaskCard):
        card.mark(CardStatus.RUNNING)
        self._store.save(card)
        try:
            if self._run_fn is None:
                raise RuntimeError("CardWorker.run_fn not set (lifespan 未注入执行器)")
            out = await self._run_fn(card)
            if card.cancel_requested:
                card.mark(CardStatus.CANCELLED, error="cancelled by user")
            else:
                card.mark(CardStatus.COMPLETED, result=out.get("result") or "")
                if out.get("error"):
                    card.error = out["error"]
            # 审批残留清理
            card.approval_pending = None
        except asyncio.CancelledError:
            card.mark(CardStatus.CANCELLED, error="cancelled by user")
        except Exception as e:
            logger.exception("task card %s failed", card.id)
            card.mark(CardStatus.FAILED, error=str(e))
        finally:
            self._store.save(card)
            self._running.pop(card.id, None)
            try:
                self._store.prune(card.owner)
            except Exception:
                pass


_worker: Optional[CardWorker] = None
def get_card_worker() -> CardWorker:
    global _worker
    if _worker is None:
        _worker = CardWorker()
    return _worker


def reset_worker_for_tests():
    """测试用: 重置全局 worker/store (避免跨测试污染)。"""
    global _worker
    w = _worker
    if w is not None and w._started:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(w.stop())
        except Exception:
            pass
    _worker = None
    import shutil
    try:
        shutil.rmtree(str(CARDS_DIR))
    except Exception:
        pass


# 导出面
__all__ = [
    "TaskCard", "CardStatus", "TaskCardStore", "HubQuota", "CardWorker",
    "PLAN_LIMITS", "CARDS_DIR", "MAX_CARDS_PER_OWNER",
    "get_hub_quota", "get_card_worker", "reset_worker_for_tests",
]

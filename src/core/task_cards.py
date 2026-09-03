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
from dataclasses import dataclass, field
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
        return {
            "id": self.id, "owner": self.owner, "plan": self.plan,
            "title": self.title, "prompt": self.prompt, "model": self.model,
            "status": self.status.value if isinstance(self.status, CardStatus) else self.status,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "timeline": self.timeline, "result": self.result, "error": self.error,
            "approval_pending": self.approval_pending,
            "cancel_requested": self.cancel_requested, "extra": self.extra,
        }

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
    # tmp 文件名带唯一后缀 (pid+uuid): 多个 store 实例 (worker 线程 vs API
    # 线程) 并发写同一卡时, 各自 tmp 不冲突 (原固定 .tmp 会互相 os.replace
    # 导致 FileNotFoundError, 审计 e2e 实测暴露)
    tmp = path.with_name(f"{path.stem}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        # 失败时清理残留 tmp
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
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
            # 先确保规则存在 (幂等) — 否则 consume 无规则可记账
            self.ensure_rules(owner, plan)
            used, remaining, allowed = qm.consume(
                f"{self.QUOTA_KEY_DAILY}:{owner}", units=1)
            # consume 返回消费前的 used/remaining; 消费后剩余 = remaining - 1
            res["used"] = used + 1
            res["remaining"] = max(0, remaining - 1)
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

    def check_usage(self, owner: str, plan: str = "free") -> Dict[str, Any]:
        """公共配额查询 (替代外部直调私有 _get_qm, P3 002codex/P4 004meshctx)。"""
        qm = self._get_qm()
        lim = self._limits(plan)
        used = 0
        if qm is not None:
            try:
                self.ensure_rules(owner, plan)
                _, remaining, _ = qm.check(f"{self.QUOTA_KEY_DAILY}:{owner}", units=0)
                used = max(0, lim["spawns_per_day"] - remaining)
            except Exception:
                pass
        return {"plan": plan, "limits": lim, "used_today": used,
                "remaining": max(0, lim["spawns_per_day"] - used)}

    def refund_spawn(self, owner: str):
        """退回一次派活额度 (入队失败等场景, P4 004meshctx)。"""
        qm = self._get_qm()
        if qm is None:
            return
        key = f"{self.QUOTA_KEY_DAILY}:{owner}"
        try:
            usage = qm.get_usage(key)
            if usage is not None and usage.used > 0:
                usage.used = max(0, usage.used - 1)
                usage.last_updated = time.time()
                qm._save()
        except Exception as e:
            logger.debug("quota refund: %s", e)


_hub_quota: Optional[HubQuota] = None
def get_hub_quota() -> HubQuota:
    global _hub_quota
    if _hub_quota is None:
        _hub_quota = HubQuota()
    return _hub_quota


# ═══ 后台 Worker (编排 run_agent_loop) ═══
class CardWorker:
    """后台任务卡 worker — 独立线程 + 专属事件循环。

    设计 (2026-09-02, 004meshctx 排查): run_agent_loop 内部同步迭代模型流
    (openai SDK for-chunk), 若直接跑在 uvicorn 主事件循环的后台任务里,
    同步网络等待会饿死所有 HTTP 响应 → worker 必须跑在独立线程的专属
    asyncio loop 上。enqueue/cancel/decide 从任意线程调用, 经
    call_soon_threadsafe 投递到 worker loop, 线程安全。
    """

    def __init__(self):
        self._store = TaskCardStore()
        self._queue: "asyncio.Queue[str]" = asyncio.Queue()  # 仅 worker loop 内访问
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._consume_task: Optional[asyncio.Task] = None
        self._running: Dict[str, asyncio.Task] = {}   # 仅 worker loop 内访问
        self._run_fn: Optional[Callable[[TaskCard], Awaitable[Dict[str, Any]]]] = None
        self._started = False
        self._stopping = False
        self._state_lock = threading.Lock()
        # 审批协调: request_id → asyncio.Future (卡临时 loop 内创建)
        self._approval_futures: Dict[str, "asyncio.Future"] = {}
        # card_id → set(request_id): 卡终结时清理防泄漏
        self._approval_by_card: Dict[str, set] = {}
        self._approval_lock = threading.Lock()
        # 运行中取消集合 (P2-1 002meshctx): cancel() 跨线程登记, interrupt_check
        # 查此集合 — 卡线程内存对象 cancel_requested 不随外部 cancel 更新
        self._cancelled: set = set()
        # 审批已决集合 (P3 004meshctx): decide 成功登记, save_card 强制清 pending
        self._approval_decided: set = set()
        self._cancel_lock = threading.Lock()

    # ── 生命周期 ──
    def start(self, run_fn: Optional[Callable[[TaskCard], Awaitable[Dict[str, Any]]]] = None,
              loop: Optional[asyncio.AbstractEventLoop] = None,
              recover: bool = True):
        with self._state_lock:
            if self._started:
                return
            self._run_fn = run_fn
            self._started = True
            self._stopping = False
            self._queue = asyncio.Queue()  # 绑定 worker loop
        if loop is not None:
            # 测试注入: 直接用给定 loop (调用方负责 run_until_complete/close)
            self._loop = loop
            self._consume_task = loop.create_task(self._consume())
            if recover:
                self._recover_interrupted()
            return
        self._thread = threading.Thread(target=self._thread_main,
                                        name="task-cards-worker", daemon=True)
        self._thread.start()
        if recover:
            # 等待 worker loop 就绪后恢复遗留卡 (running/queued)
            for _ in range(100):
                if self._loop is not None:
                    self._recover_interrupted()
                    break
                time.sleep(0.02)

    def _recover_interrupted(self, max_age_hours: float = 6.0):
        """进程重启后恢复遗留卡: running/queued (上次中断未完成) 重新入队。

        只恢复 created_at 在 RECOVER_WINDOW (默认最近 6h) 内的卡 — 防止
        重启时把很久以前的僵尸卡全部重跑 (坏模型 key 会逐个长阻塞队列)。

        - queued: 直接重新入队
        - running: 标记回 queued 重新执行 (卡内 timeline 保留, 结果会覆盖)
        - waiting_approval: 审批未来已随进程丢失 → 标记 failed (需用户重新派发)
        """
        if self._loop is None or self._loop.is_closed():
            return
        try:
            cards = self._store.list_cards()
        except Exception:
            return
        cutoff = time.time() - max_age_hours * 3600
        for card in sorted(cards, key=lambda c: c.created_at):
            if card.created_at < cutoff:
                # 僵尸卡 (超出恢复窗口): running/waiting 转 failed 标记, queued 丢弃
                try:
                    if card.status in (CardStatus.RUNNING, CardStatus.WAITING_APPROVAL):
                        fresh = self._store.load(card.id)
                        if fresh:
                            fresh.mark(CardStatus.FAILED,
                                       error="服务重启且超出恢复窗口, 任务已终止 — 请重新派发")
                            self._store.save(fresh)
                            logger.info("task_cards: 超窗卡 %s 终止 (created %.0fs 前)",
                                        card.id, time.time() - card.created_at)
                    elif card.status == CardStatus.QUEUED:
                        # 从未开始且超窗 → 直接清理
                        self._store.delete(card.id)
                        logger.info("task_cards: 超窗排队卡 %s 清理", card.id)
                except Exception as e:
                    logger.warning("task_cards: 超窗卡 %s 处理失败: %s", card.id, e)
                continue
            try:
                if card.status == CardStatus.QUEUED:
                    self._submit(self._queue.put_nowait, card.id)
                    logger.info("task_cards: 恢复排队卡 %s", card.id)
                elif card.status == CardStatus.RUNNING:
                    fresh = self._store.load(card.id)
                    if fresh:
                        fresh.mark(CardStatus.QUEUED, error=None)
                        fresh.cancel_requested = False
                        self._store.save(fresh)
                    self._submit(self._queue.put_nowait, card.id)
                    logger.info("task_cards: 恢复中断卡 %s (running→queued)", card.id)
                elif card.status == CardStatus.WAITING_APPROVAL:
                    fresh = self._store.load(card.id)
                    if fresh:
                        fresh.mark(CardStatus.FAILED,
                                   error="服务重启, 审批上下文丢失 — 请重新派发任务")
                        self._store.save(fresh)
                    logger.info("task_cards: 终止待审批卡 %s (重启丢失审批)", card.id)
            except Exception as e:
                logger.warning("task_cards: 恢复卡 %s 失败: %s", card.id, e)

    def _thread_main(self):
        """worker 线程: 专属事件循环常驻。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._consume_task = loop.create_task(self._consume())
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._loop = None

    def _submit(self, fn, *args):
        """投递到 worker loop (任意线程可调)。"""
        if self._loop is None or self._loop.is_closed():
            return False
        self._loop.call_soon_threadsafe(fn, *args)
        return True

    def stop(self):
        """停止 worker (线程安全)。

        线程模式: 投递清理到 worker loop 并同步 join;
        loop 注入模式 (测试): 在当前 loop run_until_complete 清理 (防
        "Task destroyed but pending" GC 警告, P3-1 004meshctx)。
        """
        with self._state_lock:
            if not self._started:
                return
            self._stopping = True

        def _stop_in_loop():
            for t in list(self._running.values()):
                t.cancel()
            if self._consume_task is not None and not self._consume_task.done():
                self._consume_task.cancel()

        loop = self._loop
        if loop is not None and not loop.is_closed():
            if self._thread is not None:
                # 线程模式: 投递后让线程 loop 执行并停止
                self._submit(_stop_in_loop)
                try:
                    loop.call_later(0.3, loop.stop)
                except RuntimeError:
                    pass
            else:
                # loop 注入模式 (测试): 直接 run_until_complete 清理
                try:
                    loop.run_until_complete(
                        asyncio.gather(*[t for t in self._running.values()],
                                       return_exceptions=True))
                    if self._consume_task is not None and not self._consume_task.done():
                        self._consume_task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(self._consume_task, return_exceptions=True))
                except Exception:
                    pass
        self._started = False
        # 线程模式: 等待线程退出 (loop 已 stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def join(self, timeout: float = 3.0):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # ── 对外 ──
    def enqueue(self, card: TaskCard) -> bool:
        """入队并立即落盘 (任意线程可调)。返回是否成功入队。"""
        with self._state_lock:
            if self._stopping or not self._started:
                return False
        self._store.save(card)
        return self._submit(self._queue.put_nowait, card.id)

    def cancel(self, card_id: str) -> bool:
        """请求取消 (线程安全)。

        语义:
        - 终止态卡 (completed/failed/cancelled): 返回 False, 无操作 (P3 002meshctx)
        - QUEUED (尚未被 worker 领取): 同步置 CANCELLED — consume 领取时
          重新 load 会看到 CANCELLED 而跳过。
        - RUNNING/WAITING_APPROVAL: 登记 _cancelled 集合 (interrupt_check 查
          集合, 及时中断, P2-1 002meshctx) + 落盘标志 + 投递 task.cancel()
        """
        card = self._store.load(card_id)
        if card is None:
            return False
        if card.status in (CardStatus.COMPLETED, CardStatus.FAILED,
                           CardStatus.CANCELLED):
            return False  # 终止态卡不可取消
        card.cancel_requested = True
        if card.status == CardStatus.QUEUED:
            # 未被领取 → 同步标记取消 (consume 后到会跳过)
            card.mark(CardStatus.CANCELLED, error="cancelled before start")
            self._store.save(card)
            return True
        # RUNNING / WAITING_APPROVAL: 登记集合 (及时中断) + 落盘 + 取消 task
        with self._cancel_lock:
            self._cancelled.add(card_id)
        # WAITING_APPROVAL: 对挂起审批 future 投 reject, 即时解除 waiter 阻塞
        # (P3 002codex — 否则卡线程等满 120s 审批超时才收尾)
        if card.status == CardStatus.WAITING_APPROVAL:
            self._reject_card_approvals(card_id)
        self._store.save(card)
        if self._loop is not None and not self._loop.is_closed():
            def _cancel_in_loop():
                t = self._running.get(card_id)
                if t is not None:
                    t.cancel()
                # 若还在队列 (极少见窗口), 移除
                try:
                    self._queue._queue.remove(card_id)
                except (ValueError, AttributeError):
                    pass
            self._submit(_cancel_in_loop)
        return True

    def is_cancelled(self, card_id: str) -> bool:
        """运行中取消查询 (跨线程, interrupt_check 用, P2-1 002meshctx)。"""
        with self._cancel_lock:
            return card_id in self._cancelled

    def save_card(self, card: TaskCard) -> TaskCard:
        """合并外部状态后落盘 (卡线程节流 save 用, P3 004meshctx)。

        外部 (API approve/cancel) 可能已清盘 approval_pending / 置取消 —
        卡线程内存对象不感知, 直接 save 会把陈旧 pending/cancel_requested
        回写覆盖。故以磁盘最新状态合并关键字段再落盘。
        """
        try:
            # 审批已决: worker 级集合为准 (decide 跨线程登记, 比磁盘可靠 —
            # 防卡线程抢先 save 回写 pending 后 API 再清盘的竞争窗口)
            with self._cancel_lock:
                decided = card.id in self._approval_decided
            if decided:
                if card.approval_pending is not None:
                    card.approval_pending = None
                if card.status == CardStatus.WAITING_APPROVAL:
                    card.status = CardStatus.RUNNING
            fresh = self._store.load(card.id)
            if fresh is not None:
                # 外部已取消 → 同步内存
                if fresh.cancel_requested and not card.cancel_requested:
                    card.cancel_requested = True
        except Exception:
            pass
        self._store.save(card)
        return card

    def running_count(self) -> int:
        if self._loop is None or self._loop.is_closed():
            return 0
        # _running 仅 worker loop 内变更; 读近似值即可 (CPython dict len 原子)
        return len(self._running)

    # ── 审批协调 (卡级 pending → Web decide → future resolve) ──
    def register_approval(self, card: TaskCard, request_id: str,
                          name: str, args: Dict, reason: str):
        """agent 请求审批时: 落盘 pending + 登记 future。

        注: run_card 在卡的临时 asyncio.run loop 内调用本方法,
        get_event_loop() 即该卡 loop; decide 经 fut.get_loop() 投递同 loop,
        跨线程安全自洽。
        """
        loop = asyncio.get_event_loop()
        fut: "asyncio.Future" = loop.create_future()
        with self._approval_lock:
            self._approval_futures[request_id] = fut
            # 登记 card→request 映射, 供卡终结时清理 (防 future 泄漏)
            self._approval_by_card.setdefault(card.id, set()).add(request_id)
        card.approval_pending = {
            "request_id": request_id, "name": name, "args": args,
            "reason": reason, "ts": time.time(), "card_id": card.id,
        }
        card.status = CardStatus.WAITING_APPROVAL
        card.touch()
        self._store.save(card)
        return fut

    def decide_approval(self, request_id: str, action: str, text: str = "") -> bool:
        """Web 端决定: 写回卡并 resolve future (任意线程可调)。"""
        fut = None
        decided_card = None
        with self._approval_lock:
            fut = self._approval_futures.pop(request_id, None)
            # 同步清理 card→request 映射并记录已决 card。
            # 只登记真正包含该 request_id 的卡: 对无关卡 discard 后
            # not-in-reqs 恒真, 会把 decided_card 覆盖为迭代末尾的无关卡
            # (P2-2 002meshctx 多卡并发审批跨卡污染)。
            for card_id, reqs in list(self._approval_by_card.items()):
                if request_id in reqs:
                    reqs.discard(request_id)
                    decided_card = card_id
                    if not reqs:
                        self._approval_by_card.pop(card_id, None)
                    break
        if fut is None or fut.done():
            return False
        if decided_card is not None:
            # 登记"该卡审批已决" — save_card 合并时强制清 pending 防回写 (P3 004meshctx)
            with self._cancel_lock:
                self._approval_decided.add(decided_card)
        loop = fut.get_loop()
        try:
            loop.call_soon_threadsafe(
                fut.set_result, {"action": action, "text": text})
        except RuntimeError:
            return False
        return True

    def _reject_card_approvals(self, card_id: str):
        """取消时对卡内全部挂起审批 future 投 reject, 即时解除 waiter 阻塞
        (P3 002codex: 原仅登记 _cancelled, WAITING_APPROVAL 卡线程仍阻塞在
        wait_for(fut, 120s) 直到审批超时才收尾)。decide 竞争幂等: 谁先 pop 谁生效。
        """
        with self._approval_lock:
            reqs = self._approval_by_card.get(card_id)
            if not reqs:
                return
            resolved = []
            for rid in list(reqs):
                fut = self._approval_futures.pop(rid, None)
                if fut is not None and not fut.done():
                    resolved.append(fut)
                reqs.discard(rid)
            if not reqs:
                self._approval_by_card.pop(card_id, None)
        for fut in resolved:
            loop = fut.get_loop()
            try:
                loop.call_soon_threadsafe(
                    fut.set_result,
                    {"action": "reject",
                     "text": "[取消] 用户取消任务，挂起审批已拒绝。"})
            except RuntimeError:
                pass

    def cleanup_approvals_for_card(self, card_id: str):
        """卡终结时清理其残留审批 future (防慢泄漏: 超时/取消卡永不 decide)。"""
        with self._approval_lock:
            reqs = self._approval_by_card.pop(card_id, None)
            if not reqs:
                return
            removed = 0
            for rid in reqs:
                fut = self._approval_futures.pop(rid, None)
                if fut is not None and not fut.done():
                    try:
                        loop = fut.get_loop()
                        loop.call_soon_threadsafe(
                            fut.set_result,
                            {"action": "reject", "text": "[任务已终止] 审批请求取消"})
                    except RuntimeError:
                        pass
                removed += 1
            if removed:
                logger.info("task_cards: 清理卡 %s 的 %d 个残留审批 future", card_id, removed)

    def pending_approval_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        card = self._store.load(card_id)
        return card.approval_pending if card else None

    # ── 内部 (worker loop 内) ──
    async def _consume(self):
        while not self._stopping:
            try:
                card_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            except Exception:
                # loop 关闭/停止中 → 直接退出 (防 "no running event loop")
                if self._stopping or (self._loop is not None and self._loop.is_closed()):
                    break
                try:
                    await asyncio.sleep(0.2)
                except (asyncio.CancelledError, RuntimeError):
                    break
                continue
            card = self._store.load(card_id)
            if card is None or card.status == CardStatus.CANCELLED:
                continue
            # 并发上限 (soft)
            lim = PLAN_LIMITS.get(card.plan, PLAN_LIMITS["free"])
            if len(self._running) >= lim["max_concurrent"]:
                try:
                    await asyncio.sleep(0.5)
                except (asyncio.CancelledError, RuntimeError):
                    break
                self._queue.put_nowait(card_id)
                continue
            t = asyncio.get_event_loop().create_task(self._run_one(card))
            self._running[card_id] = t
        # loop.stop 由 stop() 调度

    def _run_card_in_thread(self, card_id: str):
        """在独立线程跑一张卡 (run_agent_loop 内部同步迭代 SDK 流, 不能占用
        worker 调度 loop — 每个卡一个临时线程 + asyncio.run, 互不阻塞)。"""
        import asyncio as _ai
        try:
            card = self._store.load(card_id)
            if card is None or card.status == CardStatus.CANCELLED:
                return
            if self._run_fn is None:
                raise RuntimeError("CardWorker.run_fn not set (lifespan 未注入执行器)")
            out = _ai.run(self._run_fn(card))
            card = self._store.load(card_id) or card
            if card.cancel_requested:
                card.mark(CardStatus.CANCELLED, error="cancelled by user")
            else:
                card.mark(CardStatus.COMPLETED, result=out.get("result") or "")
                if out.get("error"):
                    card.error = out["error"]
            card.approval_pending = None
        except asyncio.CancelledError:
            card = self._store.load(card_id)
            if card:
                card.mark(CardStatus.CANCELLED, error="cancelled by user")
        except Exception as e:
            logger.exception("task card %s failed (thread)", card_id)
            card = self._store.load(card_id)
            if card:
                card.mark(CardStatus.FAILED, error=str(e))
        finally:
            # 卡终结: 清审批残留 (P4 004meshctx) + 清取消登记 (P2-1) + 落盘终态
            if card is not None:
                card.approval_pending = None
                card.cancel_requested = False
                self._store.save(card)
            with self._cancel_lock:
                self._cancelled.discard(card_id)
                self._approval_decided.discard(card_id)
            # 清理该卡残留审批 future (超时/取消的审批 request 永不 decide → 防泄漏)
            try:
                self.cleanup_approvals_for_card(card_id)
            except Exception:
                pass
            with self._state_lock:
                self._running.pop(card_id, None)
            try:
                self._store.prune(card.owner if card else "local")
            except Exception:
                pass

    async def _run_one(self, card: TaskCard):
        # 竞态防护: 领取后/启动前可能被 cancel 同步置 CANCELLED → 重新 load 最新态
        fresh = self._store.load(card.id)
        if fresh is not None:
            card = fresh
        if card.status == CardStatus.CANCELLED:
            self._running.pop(card.id, None)
            return
        card.mark(CardStatus.RUNNING)
        self._store.save(card)
        # 同步阻塞型 agent 执行 → 线程池 (每卡独立线程, 不占 worker 调度 loop)
        await asyncio.to_thread(self._run_card_in_thread, card.id)
        self._running.pop(card.id, None)


_worker: Optional["CardWorker"] = None


def get_card_worker() -> CardWorker:
    global _worker
    if _worker is None:
        _worker = CardWorker()
    return _worker


def reset_worker_for_tests():
    """测试用: 重置全局 worker/store (避免跨测试污染)。"""
    global _worker
    w = _worker
    if w is not None:
        w.stop()
        w.join(timeout=2.0)
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

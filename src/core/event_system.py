"""
meshctx Event System — 异步事件驱动引擎
=========================================

基于发布/订阅模式的事件总线, 支持通配符匹配、优先级队列、
死信队列和事件溯源。

核心功能:
  1. EventBus — 事件总线, 发布/订阅核心
  2. Event — 事件数据结构 (type/payload/timestamp/source)
  3. subscribe/unsubscribe — 按事件类型注册/移除 handler
  4. emit/publish — 同步 + 异步发布
  5. 通配符订阅 — "user.*" 匹配 "user.login" / "user.logout"
  6. 事件优先级 — CRITICAL/HIGH/NORMAL/LOW
  7. 死信队列 — 处理失败的事件自动入队, 支持重试
  8. 事件溯源日志 — 完整的事件历史记录

使用示例:
  bus = get_event_system()
  bus.subscribe("user.login", handle_login, priority=EventPriority.HIGH)
  bus.subscribe("user.*", audit_all_user_events)
  await bus.emit(Event(type="user.login", payload={"user_id": 123}))

代码量: ~700 行
"""

import asyncio
import fnmatch
import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, Awaitable

logger = logging.getLogger("meshctx.event_system")


# ═══════════════════════════════════════════════════════════
# 枚举与常量
# ═══════════════════════════════════════════════════════════

class EventPriority(IntEnum):
    """事件优先级 — 数值越小优先级越高。"""
    CRITICAL = 0
    HIGH = 10
    NORMAL = 20
    LOW = 30


DEFAULT_EVENT_PRIORITY = EventPriority.NORMAL
DEFAULT_DEAD_LETTER_RETRY_MAX = 3
DEFAULT_DEAD_LETTER_RETRY_DELAY = 5.0  # 秒
DEFAULT_EVENT_HISTORY_MAX = 10_000
DEFAULT_HANDLER_TIMEOUT = 30.0  # 秒


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class Event:
    """事件数据结构。

    Attributes:
        type: 事件类型, 支持点分命名, e.g. "user.login", "system.startup"
        payload: 事件负载数据
        timestamp: 事件创建时间 (Unix timestamp)
        source: 事件来源, e.g. "agent-1", "gateway"
        id: 事件唯一 ID
        priority: 事件优先级
        correlation_id: 关联 ID (用于追踪分布式调用链)
        metadata: 额外元数据
    """
    type: str
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
            "priority": self.priority.name,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }


@dataclass(order=True)
class _PrioritizedEvent:
    """内部优先级队列条目 (按 priority + timestamp 排序)。"""
    priority: int
    timestamp: float
    event: Event = field(compare=False)


@dataclass
class DeadLetterEntry:
    """死信队列条目 — 记录处理失败的事件。"""
    event: Event
    error: str                          # 错误信息
    handler_name: str                   # 处理失败的 handler 名称
    failed_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = DEFAULT_DEAD_LETTER_RETRY_MAX
    next_retry_at: float = 0.0          # 下次重试时间

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def schedule_retry(self, delay: float = None) -> None:
        """排定下次重试 (指数退避)。"""
        delay = delay or DEFAULT_DEAD_LETTER_RETRY_DELAY * (2 ** self.retry_count)
        self.next_retry_at = time.time() + delay
        self.retry_count += 1


@dataclass
class EventSystemStats:
    """EventSystem 统计信息。"""
    total_emitted: int = 0
    total_delivered: int = 0
    total_failed: int = 0
    total_dead_letter: int = 0
    total_dead_letter_retried: int = 0
    active_subscriptions: int = 0
    wildcard_subscriptions: int = 0
    events_per_second: float = 0.0
    last_updated: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_emitted": self.total_emitted,
            "total_delivered": self.total_delivered,
            "total_failed": self.total_failed,
            "total_dead_letter": self.total_dead_letter,
            "total_dead_letter_retried": self.total_dead_letter_retried,
            "active_subscriptions": self.active_subscriptions,
            "wildcard_subscriptions": self.wildcard_subscriptions,
            "events_per_second": round(self.events_per_second, 2),
            "last_updated": self.last_updated,
        }


# ═══════════════════════════════════════════════════════════
# EventBus — 事件总线
# ═══════════════════════════════════════════════════════════

class EventBus:
    """事件总线 — 发布/订阅引擎。

    核心职责:
    - 管理订阅 (精确 + 通配符)
    - 按优先级分发事件
    - 处理 handler 超时和异常
    - 死信队列管理
    - 事件溯源日志

    线程安全: 内部使用 asyncio.Lock + threading.Lock 保护共享状态。
    """

    def __init__(self):
        # type → list of (handler, is_async, priority)
        self._exact_subscriptions: Dict[str, List[Tuple[Callable, bool, EventPriority]]] = defaultdict(list)
        # wildcard_pattern → list of (handler, is_async, priority)
        self._wildcard_subscriptions: Dict[str, List[Tuple[Callable, bool, EventPriority]]] = defaultdict(list)

        # 事件溯源日志 (环形缓冲区)
        self._event_history: deque = deque(maxlen=DEFAULT_EVENT_HISTORY_MAX)
        self._event_history_lock = threading.Lock()

        # 死信队列
        self._dead_letter_queue: deque = deque()
        self._dead_letter_lock = threading.Lock()

        # 统计
        self.stats = EventSystemStats()
        self._stats_lock = threading.Lock()
        self._emit_count_window: deque = deque()  # 用于计算 events_per_second

        # 异步基础设施
        self._running = False
        self._event_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._lock = asyncio.Lock()

        # handler 注册/注销锁
        self._sub_lock = threading.Lock()

    # ── 订阅管理 ───────────────────────────────────────────

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Optional[Awaitable[None]]],
        priority: EventPriority = EventPriority.NORMAL,
    ) -> str:
        """订阅事件。

        Args:
            event_type: 事件类型, 支持通配符 "user.*" / "*.login" / "system.*.error"
            handler: 处理函数, 接收 Event 作为唯一参数, 可以是同步或异步函数
            priority: handler 优先级 (同类型内部排序)

        Returns:
            str: subscription_id, 用于后续 unsubscribe

        Raises:
            ValueError: event_type 为空
        """
        if not event_type or not event_type.strip():
            raise ValueError("event_type cannot be empty")

        subscription_id = f"sub_{uuid.uuid4().hex[:16]}"
        is_async = asyncio.iscoroutinefunction(handler)
        is_wildcard = "*" in event_type or "?" in event_type

        with self._sub_lock:
            entry = (handler, is_async, priority, subscription_id)
            if is_wildcard:
                self._wildcard_subscriptions[event_type].append(entry)
                self._wildcard_subscriptions[event_type].sort(key=lambda x: x[2])
            else:
                self._exact_subscriptions[event_type].append(entry)
                self._exact_subscriptions[event_type].sort(key=lambda x: x[2])

        self._update_subscription_stats()
        logger.debug(
            f"Subscribed: id={subscription_id} type={event_type} "
            f"priority={priority.name} wildcard={is_wildcard}"
        )
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """取消订阅。

        Args:
            subscription_id: subscribe() 返回的订阅 ID

        Returns:
            bool: 是否成功取消
        """
        with self._sub_lock:
            # 搜索精确订阅
            for evt_type, handlers in list(self._exact_subscriptions.items()):
                for entry in list(handlers):
                    if len(entry) >= 4 and entry[3] == subscription_id:
                        handlers.remove(entry)
                        if not handlers:
                            del self._exact_subscriptions[evt_type]
                        self._update_subscription_stats()
                        logger.debug(f"Unsubscribed exact: id={subscription_id}")
                        return True

            # 搜索通配符订阅
            for pattern, handlers in list(self._wildcard_subscriptions.items()):
                for entry in list(handlers):
                    if len(entry) >= 4 and entry[3] == subscription_id:
                        handlers.remove(entry)
                        if not handlers:
                            del self._wildcard_subscriptions[pattern]
                        self._update_subscription_stats()
                        logger.debug(f"Unsubscribed wildcard: id={subscription_id}")
                        return True

        logger.warning(f"Subscription not found: {subscription_id}")
        return False

    def unsubscribe_all(self, event_type: str = None) -> int:
        """批量取消订阅。

        Args:
            event_type: 指定事件类型 (None = 全部)

        Returns:
            int: 取消的订阅数
        """
        count = 0
        with self._sub_lock:
            if event_type:
                count += len(self._exact_subscriptions.pop(event_type, []))
                count += len(self._wildcard_subscriptions.pop(event_type, []))
            else:
                for handlers in self._exact_subscriptions.values():
                    count += len(handlers)
                for handlers in self._wildcard_subscriptions.values():
                    count += len(handlers)
                self._exact_subscriptions.clear()
                self._wildcard_subscriptions.clear()

        self._update_subscription_stats()
        logger.info(f"Unsubscribed {count} handlers total")
        return count

    # ── 事件发布 ───────────────────────────────────────────

    def emit(
        self,
        event: Event,
        timeout: float = DEFAULT_HANDLER_TIMEOUT,
    ) -> None:
        """同步发布事件 (fire-and-forget)。

        将事件放入优先级队列, 由后台 worker 异步分发。
        不会阻塞调用方。

        Args:
            event: Event 实例
            timeout: handler 超时 (秒)
        """
        if not self._running:
            logger.warning("EventBus not started; event may not be delivered")

        # 记录溯源
        self._record_event(event)

        # 入队
        prioritized = _PrioritizedEvent(
            priority=event.priority.value,
            timestamp=event.timestamp,
            event=event,
        )
        self._event_queue.put_nowait(prioritized)

        with self._stats_lock:
            self.stats.total_emitted += 1
            self.stats.last_updated = time.time()

    async def publish(
        self,
        event: Event,
        timeout: float = DEFAULT_HANDLER_TIMEOUT,
    ) -> List[Any]:
        """异步发布事件并收集所有 handler 返回结果。

        等待所有匹配的 handler 执行完毕, 收集返回值。

        Args:
            event: Event 实例
            timeout: 单个 handler 超时 (秒)

        Returns:
            List[Any]: 所有 handler 的返回值 (None 被过滤)
        """
        self._record_event(event)
        handlers = self._find_handlers(event.type)

        if not handlers:
            logger.debug(f"No handlers for event: {event.type}")
            return []

        results = []
        for handler, is_async, priority in handlers:
            try:
                if is_async:
                    result = await asyncio.wait_for(handler(event), timeout=timeout)
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, handler, event),
                        timeout=timeout,
                    )
                if result is not None:
                    results.append(result)
                self._increment_delivered()
            except asyncio.TimeoutError:
                logger.error(
                    f"Handler timeout for event '{event.type}' "
                    f"(handler={handler.__name__}, timeout={timeout}s)"
                )
                self._handle_failure(event, handler, f"Timeout after {timeout}s")
            except Exception as e:
                logger.error(
                    f"Handler error for event '{event.type}': {e}",
                    exc_info=True,
                )
                self._handle_failure(event, handler, str(e))

        with self._stats_lock:
            self.stats.total_delivered += 1
            self.stats.last_updated = time.time()

        return results

    # ── 生命周期 ───────────────────────────────────────────

    async def start(self) -> None:
        """启动 EventBus 后台 worker 和死信队列处理。"""
        if self._running:
            return

        async with self._lock:
            if self._running:
                return
            self._running = True
            self._shutdown_event.clear()
            self._task = asyncio.create_task(self._worker_loop())
            logger.info("EventBus started (worker + dead-letter processor)")

    async def shutdown(self, grace_period: float = 5.0) -> None:
        """优雅关闭 EventBus。

        Args:
            grace_period: 等待 worker 完成的宽限期 (秒)
        """
        if not self._running:
            return

        logger.info("Shutting down EventBus...")
        self._shutdown_event.set()
        self._running = False

        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=grace_period)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        logger.info("EventBus shut down")

    # ── 死信队列 ───────────────────────────────────────────

    def get_dead_letter_entries(self, limit: int = 100) -> List[DeadLetterEntry]:
        """获取死信队列条目。

        Args:
            limit: 最大返回数
        """
        with self._dead_letter_lock:
            return list(self._dead_letter_queue)[:limit]

    def dead_letter_count(self) -> int:
        """死信队列当前长度。"""
        with self._dead_letter_lock:
            return len(self._dead_letter_queue)

    def purge_dead_letters(self) -> int:
        """清空死信队列。

        Returns:
            int: 清除的条目数
        """
        with self._dead_letter_lock:
            count = len(self._dead_letter_queue)
            self._dead_letter_queue.clear()
        logger.info(f"Purged {count} dead-letter entries")
        return count

    def retry_dead_letters(self, max_entries: int = 50) -> int:
        """重试死信队列中的事件 (同步, 重新入队)。

        Args:
            max_entries: 最大重试条目数

        Returns:
            int: 重试的事件数
        """
        retried = 0
        with self._dead_letter_lock:
            remaining = deque()
            while self._dead_letter_queue and retried < max_entries:
                entry = self._dead_letter_queue.popleft()
                if entry.can_retry():
                    entry.schedule_retry()
                    # 重新放入普通队列
                    prioritized = _PrioritizedEvent(
                        priority=entry.event.priority.value,
                        timestamp=time.time(),
                        event=entry.event,
                    )
                    self._event_queue.put_nowait(prioritized)
                    retried += 1
                else:
                    remaining.append(entry)
            # 放回无法重试的条目
            self._dead_letter_queue.extendleft(reversed(remaining))

        with self._stats_lock:
            self.stats.total_dead_letter_retried += retried

        logger.info(f"Retried {retried} dead-letter events")
        return retried

    # ── 事件溯源 ───────────────────────────────────────────

    def get_event_history(
        self,
        event_type: str = None,
        limit: int = 100,
    ) -> List[Event]:
        """获取事件溯源日志。

        Args:
            event_type: 按类型过滤 (支持通配符), None = 全部
            limit: 最大返回数
        """
        with self._event_history_lock:
            events = list(self._event_history)

        if event_type:
            if "*" in event_type or "?" in event_type:
                events = [e for e in events if fnmatch.fnmatch(e.type, event_type)]
            else:
                events = [e for e in events if e.type == event_type]

        return events[-limit:]

    def get_event_by_id(self, event_id: str) -> Optional[Event]:
        """按 ID 查找事件。"""
        with self._event_history_lock:
            for e in self._event_history:
                if e.id == event_id:
                    return e
        return None

    # ── 统计 ───────────────────────────────────────────────

    def get_stats(self) -> EventSystemStats:
        """获取统计快照。"""
        with self._stats_lock:
            # 计算 events_per_second
            now = time.time()
            cutoff = now - 10  # 最近 10 秒
            while self._emit_count_window and self._emit_count_window[0] < cutoff:
                self._emit_count_window.popleft()
            self.stats.events_per_second = len(self._emit_count_window) / 10.0
            self.stats.last_updated = now

            self.stats.active_subscriptions = self._count_subscriptions()
            self.stats.wildcard_subscriptions = len(self._wildcard_subscriptions)

            return self.stats

    # ── 内部方法 ───────────────────────────────────────────

    async def _worker_loop(self) -> None:
        """后台 worker: 消费优先级队列并分发事件。"""
        logger.debug("EventBus worker loop started")

        while self._running or not self._event_queue.empty():
            try:
                # 非阻塞获取, 支持 shutdown
                try:
                    prioritized = await asyncio.wait_for(
                        self._event_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    if self._shutdown_event.is_set():
                        break
                    continue

                event = prioritized.event
                handlers = self._find_handlers(event.type)

                if not handlers:
                    continue

                # 并发执行所有 handler
                tasks = []
                for handler, is_async, priority in handlers:
                    task = asyncio.create_task(
                        self._invoke_handler(event, handler, is_async)
                    )
                    tasks.append(task)

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                with self._stats_lock:
                    self.stats.total_delivered += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBus worker error: {e}", exc_info=True)

        logger.debug("EventBus worker loop stopped")

    async def _invoke_handler(
        self,
        event: Event,
        handler: Callable,
        is_async: bool,
        timeout: float = DEFAULT_HANDLER_TIMEOUT,
    ) -> None:
        """调用单个 handler, 处理超时和异常。"""
        try:
            if is_async:
                await asyncio.wait_for(handler(event), timeout=timeout)
            else:
                loop = asyncio.get_running_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, handler, event),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            logger.error(
                f"Handler timeout: {handler.__name__} for event '{event.type}'"
            )
            self._handle_failure(
                event, handler, f"Timeout after {timeout}s"
            )
        except Exception as e:
            logger.error(
                f"Handler error: {handler.__name__} for event '{event.type}': {e}",
                exc_info=True,
            )
            self._handle_failure(event, handler, str(e))

    def _find_handlers(
        self, event_type: str
    ) -> List[Tuple[Callable, bool, EventPriority]]:
        """查找匹配某个事件类型的所有 handler (精确 + 通配符)。

        返回按优先级排序的 handler 列表。
        """
        results: List[Tuple[Callable, bool, EventPriority]] = []

        with self._sub_lock:
            # 精确匹配
            for handler, is_async, priority, _ in self._exact_subscriptions.get(
                event_type, []
            ):
                results.append((handler, is_async, priority))

            # 通配符匹配
            for pattern, handlers in self._wildcard_subscriptions.items():
                if fnmatch.fnmatch(event_type, pattern):
                    for handler, is_async, priority, _ in handlers:
                        results.append((handler, is_async, priority))

        # 按优先级排序
        results.sort(key=lambda x: x[2])
        return results

    def _record_event(self, event: Event) -> None:
        """记录事件到溯源日志。"""
        with self._event_history_lock:
            self._event_history.append(event)

    def _handle_failure(
        self, event: Event, handler: Callable, error: str
    ) -> None:
        """处理 handler 失败: 放入死信队列。"""
        entry = DeadLetterEntry(
            event=event,
            error=error,
            handler_name=getattr(handler, "__name__", str(handler)),
        )

        with self._dead_letter_lock:
            self._dead_letter_queue.append(entry)

        with self._stats_lock:
            self.stats.total_failed += 1
            self.stats.total_dead_letter += 1

        logger.warning(
            f"Dead-letter: event={event.type} handler={entry.handler_name} error={error[:100]}"
        )

    def _increment_delivered(self) -> None:
        """记录一次成功投递 (用于速率计算)。"""
        with self._stats_lock:
            self.stats.total_delivered += 1
            self._emit_count_window.append(time.time())

    def _count_subscriptions(self) -> int:
        """统计活跃订阅数。"""
        count = 0
        for handlers in self._exact_subscriptions.values():
            count += len(handlers)
        for handlers in self._wildcard_subscriptions.values():
            count += len(handlers)
        return count

    def _update_subscription_stats(self) -> None:
        """更新订阅统计。"""
        with self._stats_lock:
            self.stats.active_subscriptions = self._count_subscriptions()
            self.stats.wildcard_subscriptions = len(self._wildcard_subscriptions)


# ═══════════════════════════════════════════════════════════
# 全局实例管理
# ═══════════════════════════════════════════════════════════

_global_event_system: Optional[EventBus] = None
_global_lock = threading.Lock()


def get_event_system() -> EventBus:
    """惰性初始化全局 EventBus 单例。

    线程安全, 确保整个进程只有一个 EventSystem 实例。

    Returns:
        EventBus: 全局事件总线
    """
    global _global_event_system
    if _global_event_system is None:
        with _global_lock:
            if _global_event_system is None:
                _global_event_system = EventBus()
                logger.info("Created global EventSystem instance")
    return _global_event_system


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def subscribe(
    event_type: str,
    handler: Callable[[Event], Optional[Awaitable[None]]],
    priority: EventPriority = EventPriority.NORMAL,
) -> str:
    """便捷订阅函数 — 自动使用全局 EventBus。

    Example:
        subscribe("user.login", on_user_login, EventPriority.HIGH)
    """
    return get_event_system().subscribe(event_type, handler, priority)


def emit(
    event_type: str,
    payload: Any = None,
    source: str = "",
    priority: EventPriority = EventPriority.NORMAL,
    correlation_id: str = None,
) -> None:
    """便捷发布函数 — 自动构造 Event 并通过全局 EventBus 发布。

    Example:
        emit("user.login", {"user_id": 123}, source="oauth")
    """
    event = Event(
        type=event_type,
        payload=payload,
        source=source,
        priority=priority,
        correlation_id=correlation_id,
    )
    get_event_system().emit(event)


# ═══════════════════════════════════════════════════════════
# CLI 诊断工具
# ═══════════════════════════════════════════════════════════

async def _cli_main():
    """CLI 诊断入口。"""
    print("=" * 60)
    print("  meshctx Event System — 诊断工具")
    print("=" * 60)

    bus = EventBus()
    received_events: List[Event] = []

    # 注册 handler
    async def on_user_login(event: Event):
        received_events.append(event)
        print(f"  [handler] user.login: {event.payload}")

    async def on_user_logout(event: Event):
        received_events.append(event)
        print(f"  [handler] user.logout: {event.payload}")

    async def on_user_wildcard(event: Event):
        received_events.append(event)
        print(f"  [wildcard] user.*: {event.type}")

    sub_id1 = bus.subscribe("user.login", on_user_login)
    sub_id2 = bus.subscribe("user.logout", on_user_logout)
    sub_id3 = bus.subscribe("user.*", on_user_wildcard, priority=EventPriority.LOW)

    print(f"\n[1] 注册了 3 个订阅:")
    print(f"    - {sub_id1}: user.login")
    print(f"    - {sub_id2}: user.logout")
    print(f"    - {sub_id3}: user.* (wildcard)")

    # 发布事件
    print("\n[2] 发布事件...")
    results = await bus.publish(
        Event(type="user.login", payload={"user_id": 123, "method": "password"})
    )
    await bus.publish(
        Event(type="user.logout", payload={"user_id": 123, "reason": "timeout"})
    )

    print(f"\n[3] 收到 {len(received_events)} 个 handler 调用")
    print(f"    预期: 4 个 (login×2 + logout×2, 含 wildcard)")

    # 取消订阅 wildcard
    bus.unsubscribe(sub_id3)
    print(f"\n[4] 取消 wildcard 订阅后, 再次发布...")
    received_events.clear()
    await bus.publish(
        Event(type="user.login", payload={"user_id": 456})
    )
    print(f"    收到 {len(received_events)} 个 handler 调用 (预期: 1)")

    # 统计
    stats = bus.get_stats()
    print(f"\n[5] 统计:")
    print(f"    总发布: {stats.total_emitted}")
    print(f"    总投递: {stats.total_delivered}")
    print(f"    活跃订阅: {stats.active_subscriptions}")

    print("\n✅ EventSystem 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_cli_main())

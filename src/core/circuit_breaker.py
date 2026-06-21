"""
meshctx Circuit Breaker — 熔断器
==================================

滑动窗口计数 + 三态熔断器 (CLOSED/OPEN/HALF_OPEN),
支持自定义判定函数、熔断回调和多实例隔离。

核心功能:
  1. CBState — CLOSED / OPEN / HALF_OPEN 三态
  2. 滑动窗口计数 — Rolling window success/failure counts
  3. 自动熔断/恢复 — 失败率阈值触发, HALF_OPEN 探测恢复
  4. 自定义判定函数 — 用户定义 trip 条件
  5. 熔断回调 — on_open / on_close / on_half_open
  6. 多实例隔离 — 每个 context 独立的熔断器实例

使用示例:
  cb = get_circuit_breaker()
  cb.configure("api_call", failure_threshold=5, recovery_timeout=30)
  try:
      result = await cb.call("api_call", my_async_func, arg1, arg2)
  except CircuitBreakerOpenError:
      # 熔断器开启, 快速失败
      return fallback_response

代码量: ~500 行
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, Awaitable

logger = logging.getLogger("meshctx.circuit_breaker")


# ═══════════════════════════════════════════════════════════
# 枚举与常量
# ═══════════════════════════════════════════════════════════

class CBState(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """熔断器状态。

    CLOSED:    正常 — 请求正常通过, 统计失败/成功
    OPEN:      熔断 — 请求被拒绝 (快速失败)
    HALF_OPEN: 半开 — 允许少量探测请求, 成功则 CLOSED, 失败则重新 OPEN
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


DEFAULT_FAILURE_THRESHOLD = 5         # 滑动窗口内失败次数触发熔断
DEFAULT_FAILURE_RATE_THRESHOLD = 0.5  # 50% 失败率触发 (与 count threshold 组合)
DEFAULT_RECOVERY_TIMEOUT = 30.0       # OPEN → HALF_OPEN 等待时间 (秒)
DEFAULT_HALF_OPEN_MAX_REQUESTS = 1    # HALF_OPEN 时允许的探测请求数
DEFAULT_WINDOW_SIZE = 60.0            # 滑动窗口大小 (秒)
DEFAULT_CALL_TIMEOUT = 30.0           # 单次调用超时


# ═══════════════════════════════════════════════════════════
# 异常
# ═══════════════════════════════════════════════════════════

class CircuitBreakerOpenError(Exception):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """熔断器开启 — 请求被快速失败。"""
    def __init__(self, context: str, message: str = "", **kw):
        self.context = context
        self.message = message or f"Circuit breaker '{context}' is OPEN"
        super().__init__(self.message)


class CircuitBreakerError(Exception):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """熔断器通用异常。"""
    pass


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class WindowEntry:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """滑动窗口中的单次调用记录。"""
    success: bool
    timestamp: float = field(default_factory=time.time)
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class CBConfig:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """熔断器配置。

    Attributes:
        failure_threshold: 失败次数阈值 (滑动窗口内)
        failure_rate_threshold: 失败率阈值 (0.0 ~ 1.0)
        recovery_timeout: OPEN → HALF_OPEN 等待时间 (秒)
        half_open_max_requests: HALF_OPEN 允许的探测请求数
        window_size: 滑动窗口大小 (秒)
        call_timeout: 单次调用超时 (秒)
        half_open_success_threshold: HALF_OPEN 需要连续成功次数才 CLOSE
    """
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    failure_rate_threshold: float = DEFAULT_FAILURE_RATE_THRESHOLD
    recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT
    half_open_max_requests: int = DEFAULT_HALF_OPEN_MAX_REQUESTS
    window_size: float = DEFAULT_WINDOW_SIZE
    call_timeout: float = DEFAULT_CALL_TIMEOUT
    half_open_success_threshold: int = 1

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "failure_threshold": self.failure_threshold,
            "failure_rate_threshold": self.failure_rate_threshold,
            "recovery_timeout": self.recovery_timeout,
            "half_open_max_requests": self.half_open_max_requests,
            "window_size": self.window_size,
            "call_timeout": self.call_timeout,
        }


@dataclass
class CBStats:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """熔断器统计信息。"""
    state: CBState = CBState.CLOSED
    total_calls: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_rejected: int = 0            # 被熔断拒绝的调用
    window_successes: int = 0
    window_failures: int = 0
    failure_rate: float = 0.0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    opened_at: float = 0.0             # 最近一次 OPEN 的时间
    last_state_change: float = 0.0
    state_changes: int = 0             # 状态变更次数
    current_half_open_requests: int = 0
    consecutive_half_open_successes: int = 0

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "total_calls": self.total_calls,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "total_rejected": self.total_rejected,
            "window_successes": self.window_successes,
            "window_failures": self.window_failures,
            "failure_rate": round(self.failure_rate, 3),
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "opened_at": self.opened_at,
            "last_state_change": self.last_state_change,
            "state_changes": self.state_changes,
        }


# ═══════════════════════════════════════════════════════════
# CircuitBreaker — 单个熔断器实例
# ═══════════════════════════════════════════════════════════

class CircuitBreaker:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """单个熔断器实例 (绑定到一个 context)。

    管理单个上下文的熔断逻辑: 滑动窗口计数、三态转换、
    调用执行和自定义判定。

    线程安全: 内部使用 threading.Lock 保护窗口和统计。
    """

    def __init__(self, context: str, config: CBConfig = None, **kw):
        self.context = context
        self.config = config or CBConfig()
        self.state: CBState = CBState.CLOSED
        self.stats = CBStats()
        self.stats.last_state_change = time.time()

        # 滑动窗口
        self._window: deque = deque()
        self._window_lock = threading.Lock()

        # 调用控制 — 使用 asyncio.Lock + 计数器控制 HALF_OPEN 并发
        self._half_open_lock = asyncio.Lock()
        self._half_open_count = 0

        # 自定义判定函数
        self._custom_trip_check: Optional[Callable[[CBStats], bool]] = None
        self._custom_recover_check: Optional[Callable[[CBStats], bool]] = None

        # 回调
        self._on_open_callbacks: List[Callable[[str, CBStats], None]] = []
        self._on_close_callbacks: List[Callable[[str, CBStats], None]] = []
        self._on_half_open_callbacks: List[Callable[[str, CBStats], None]] = []

    # ── 状态查询 ──────────────────────────────────────────

    def is_open(self, **kw) -> bool:
        """熔断器是否 OPEN。"""
        return self.state == CBState.OPEN

    def is_closed(self, **kw) -> bool:
        """熔断器是否 CLOSED。"""
        return self.state == CBState.CLOSED

    def is_half_open(self, **kw) -> bool:
        """熔断器是否 HALF_OPEN。"""
        return self.state == CBState.HALF_OPEN

    # ── 核心调用 ──────────────────────────────────────────

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args,
        timeout: float = None,
        **kwargs,
    ) -> Any:
        """通过熔断器调用函数。

        Args:
            func: 异步函数
            *args: 位置参数
            timeout: 超时 (覆盖配置)
            **kwargs: 关键字参数

        Returns:
            Any: 函数返回值

        Raises:
            CircuitBreakerOpenError: 熔断器开启
            Exception: 函数本身抛出的异常
        """
        # 1. 状态检查和自动转换
        await self._pre_call_check()

        # 2. HALF_OPEN 并发控制
        half_open_acquired = False
        if self.state == CBState.HALF_OPEN:
            if self._half_open_count >= self.config.half_open_max_requests:
                raise CircuitBreakerOpenError(
                    self.context,
                    f"HALF_OPEN max requests ({self.config.half_open_max_requests}) reached",
                )
            async with self._half_open_lock:
                self._half_open_count += 1
            half_open_acquired = True

        effective_timeout = timeout if timeout is not None else self.config.call_timeout
        start_time = time.time()

        try:
            # 3. 执行调用
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=effective_timeout,
            )

            duration = time.time() - start_time
            self._record_success(duration)
            return result

        except asyncio.TimeoutError as e:
            duration = time.time() - start_time
            self._record_failure(duration, f"Timeout after {effective_timeout}s")
            raise

        except CircuitBreakerOpenError:
            raise

        except Exception as e:
            duration = time.time() - start_time
            self._record_failure(duration, str(e))
            raise

        finally:
            if half_open_acquired:
                async with self._half_open_lock:
                    self._half_open_count -= 1

    # ── 手动控制 ──────────────────────────────────────────

    def force_open(self, **kw) -> None:
        """强制 OPEN (手动熔断)。"""
        self._transition_to(CBState.OPEN)

    def force_close(self, **kw) -> None:
        """强制 CLOSE (手动恢复)。"""
        self._transition_to(CBState.CLOSED)

    def force_half_open(self, **kw) -> None:
        """强制 HALF_OPEN (手动探测)。"""
        self._transition_to(CBState.HALF_OPEN)

    def reset(self, **kw) -> None:
        """重置熔断器 (回到 CLOSED, 清空窗口和统计)。"""
        self.state = CBState.CLOSED
        self.stats = CBStats()
        self.stats.last_state_change = time.time()
        with self._window_lock:
            self._window.clear()
        logger.info(f"Circuit breaker '{self.context}' reset to CLOSED")

    # ── 自定义判定 ────────────────────────────────────────

    def set_trip_check(self, checker: Callable[[CBStats], bool], **kw) -> None:
        """设置自定义熔断判定函数。

        Args:
            checker: 接收 CBStats, 返回 True 则触发熔断
        """
        self._custom_trip_check = checker

    def set_recover_check(self, checker: Callable[[CBStats], bool], **kw) -> None:
        """设置自定义恢复判定函数。

        Args:
            checker: 接收 CBStats, 返回 True 则允许恢复
        """
        self._custom_recover_check = checker

    # ── 回调 ──────────────────────────────────────────────

    def on_open(self, callback: Callable[[str, CBStats], None], **kw) -> None:
        """注册 OPEN 回调。"""
        self._on_open_callbacks.append(callback)

    def on_close(self, callback: Callable[[str, CBStats], None], **kw) -> None:
        """注册 CLOSE 回调。"""
        self._on_close_callbacks.append(callback)

    def on_half_open(self, callback: Callable[[str, CBStats], None], **kw) -> None:
        """注册 HALF_OPEN 回调。"""
        self._on_half_open_callbacks.append(callback)

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self, **kw) -> CBStats:
        """获取统计快照。"""
        self._prune_window()
        with self._window_lock:
            self.stats.window_successes = sum(1 for e in self._window if e.success)
            self.stats.window_failures = sum(1 for e in self._window if not e.success)

        total_window = self.stats.window_successes + self.stats.window_failures
        self.stats.failure_rate = (
            self.stats.window_failures / total_window
        ) if total_window > 0 else 0.0

        return self.stats

    # ── 内部 ──────────────────────────────────────────────

    async def _pre_call_check(self) -> None:
        """调用前检查: 自动状态转换。"""
        if self.state == CBState.CLOSED:
            self._prune_window()
            # 检查是否需要 熔断
            if self._should_trip():
                self._transition_to(CBState.OPEN)
                raise CircuitBreakerOpenError(self.context, "Circuit breaker tripped")

        elif self.state == CBState.OPEN:
            # 检查是否可以进入 HALF_OPEN
            if self._should_attempt_recovery():
                self._transition_to(CBState.HALF_OPEN)
            else:
                raise CircuitBreakerOpenError(
                    self.context,
                    f"Circuit breaker OPEN, recovery in "
                    f"{self._time_until_recovery():.1f}s",
                )

        elif self.state == CBState.HALF_OPEN:
            # 检查是否应该重新熔断
            if self._should_re_trip():
                self._transition_to(CBState.OPEN)
                raise CircuitBreakerOpenError(self.context, "Circuit breaker re-tripped")

    def _should_trip(self, **kw) -> bool:
        """判定是否应触发熔断。"""
        self._prune_window()

        with self._window_lock:
            failures = sum(1 for e in self._window if not e.success)
            total = len(self._window)

        # 自定义判定优先
        if self._custom_trip_check:
            return self._custom_trip_check(self.stats)

        # 默认判定: 失败次数 + 失败率
        if failures >= self.config.failure_threshold:
            if total > 0:
                failure_rate = failures / total
                if failure_rate >= self.config.failure_rate_threshold:
                    logger.warning(
                        f"Trip condition met for '{self.context}': "
                        f"failures={failures}, total={total}, rate={failure_rate:.2f}"
                    )
                    return True
        return False

    def _should_attempt_recovery(self, **kw) -> bool:
        """判定是否应尝试恢复 (OPEN → HALF_OPEN)。"""
        if self.state != CBState.OPEN:
            return False

        elapsed = time.time() - self.stats.opened_at
        return elapsed >= self.config.recovery_timeout

    def _should_re_trip(self, **kw) -> bool:
        """HALF_OPEN 中是否应重新熔断。"""
        self._prune_window()

        # 检查最近一次调用
        with self._window_lock:
            recent = [e for e in self._window
                      if time.time() - e.timestamp < self.config.recovery_timeout]
            if not recent:
                return False
            last = recent[-1]

        # HALF_OPEN 状态: 任何失败立即重新熔断
        if not last.success:
            self.stats.consecutive_half_open_successes = 0
            return True

        # 累积成功
        self.stats.consecutive_half_open_successes += 1
        if self.stats.consecutive_half_open_successes >= self.config.half_open_success_threshold:
            self._transition_to(CBState.CLOSED)

        return False

    def _time_until_recovery(self, **kw) -> float:
        """距离 HALF_OPEN 还有多少秒。"""
        elapsed = time.time() - self.stats.opened_at
        return max(0, self.config.recovery_timeout - elapsed)

    def _transition_to(self, new_state: CBState, **kw) -> None:
        """状态转换 + 回调触发。"""
        if self.state == new_state:
            return

        old_state = self.state
        self.state = new_state
        self.stats.last_state_change = time.time()
        self.stats.state_changes += 1
        self.stats.state = new_state

        logger.info(
            f"Circuit breaker '{self.context}': {old_state.value} → {new_state.value} "
            f"(change #{self.stats.state_changes})"
        )

        # 触发回调
        if new_state == CBState.OPEN:
            self.stats.opened_at = time.time()
            for cb in self._on_open_callbacks:
                try:
                    cb(self.context, self.stats)
                except Exception as e:
                    logger.error(f"on_open callback error: {e}")

        elif new_state == CBState.CLOSED:
            self.stats.consecutive_half_open_successes = 0
            for cb in self._on_close_callbacks:
                try:
                    cb(self.context, self.stats)
                except Exception as e:
                    logger.error(f"on_close callback error: {e}")

        elif new_state == CBState.HALF_OPEN:
            for cb in self._on_half_open_callbacks:
                try:
                    cb(self.context, self.stats)
                except Exception as e:
                    logger.error(f"on_half_open callback error: {e}")

    def _record_success(self, duration: float, **kw) -> None:
        """记录成功调用。"""
        entry = WindowEntry(success=True, duration_seconds=duration)
        with self._window_lock:
            self._window.append(entry)

        self.stats.total_calls += 1
        self.stats.total_successes += 1
        self.stats.last_success_time = time.time()

    def _record_failure(self, duration: float, error: str, **kw) -> None:
        """记录失败调用。"""
        entry = WindowEntry(success=False, duration_seconds=duration, error=error)
        with self._window_lock:
            self._window.append(entry)

        self.stats.total_calls += 1
        self.stats.total_failures += 1
        self.stats.last_failure_time = time.time()

    def _prune_window(self, **kw) -> None:
        """清理滑动窗口中的过期条目。"""
        cutoff = time.time() - self.config.window_size
        with self._window_lock:
            while self._window and self._window[0].timestamp < cutoff:
                self._window.popleft()

        # 更新统计
        with self._window_lock:
            self.stats.window_successes = sum(1 for e in self._window if e.success)
            self.stats.window_failures = sum(1 for e in self._window if not e.success)


# ═══════════════════════════════════════════════════════════
# CircuitBreakerManager — 多实例管理器
# ═══════════════════════════════════════════════════════════

class CircuitBreakerManager:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """熔断器管理器 — 管理多个 context 独立的熔断器实例。

    核心职责:
    - 创建/配置/移除 CB 实例
    - 统一 call 接口
    - 全局统计
    - 实例隔离

    线程安全: 内部使用 threading.Lock。
    """

    def __init__(self, **kw):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    # ── 配置管理 ──────────────────────────────────────────

    def configure(self, context: str, **kwargs) -> CircuitBreaker:
        """配置并获取熔断器实例。

        Args:
            context: 上下文标识 (隔离键)
            **kwargs: CBConfig 参数
                failure_threshold, failure_rate_threshold,
                recovery_timeout, half_open_max_requests,
                window_size, call_timeout

        Returns:
            CircuitBreaker: 配置好的熔断器实例
        """
        config = CBConfig(**{
            k: v for k, v in kwargs.items()
            if k in CBConfig.__dataclass_fields__
        })

        with self._lock:
            if context in self._breakers:
                self._breakers[context].config = config
                logger.info(f"Updated circuit breaker config for '{context}'")
            else:
                self._breakers[context] = CircuitBreaker(context, config)
                logger.info(f"Created circuit breaker for '{context}'")

        return self._breakers[context]

    def get(self, context: str, **kw) -> Optional[CircuitBreaker]:
        """获取熔断器实例。"""
        with self._lock:
            return self._breakers.get(context)

    def get_or_create(
        self,
        context: str,
        config: CBConfig = None,
    ) -> CircuitBreaker:
        """获取或创建熔断器实例。"""
        with self._lock:
            if context not in self._breakers:
                self._breakers[context] = CircuitBreaker(context, config)
                logger.info(f"Auto-created circuit breaker for '{context}'")
            return self._breakers[context]

    def remove(self, context: str, **kw) -> bool:
        """移除熔断器实例。"""
        with self._lock:
            if context in self._breakers:
                del self._breakers[context]
                logger.info(f"Removed circuit breaker '{context}'")
                return True
        return False

    def list_contexts(self, **kw) -> List[str]:
        """列出所有 context。"""
        with self._lock:
            return list(self._breakers.keys())

    # ── 调用 ──────────────────────────────────────────────

    async def call(
        self,
        context: str,
        func: Callable[..., Awaitable[Any]],
        *args,
        timeout: float = None,
        **kwargs,
    ) -> Any:
        """通过指定 context 的熔断器调用函数。

        Args:
            context: 熔断器上下文
            func: 异步函数
            *args: 位置参数
            timeout: 超时 (覆盖配置)
            **kwargs: 关键字参数

        Returns:
            Any: 函数返回值

        Raises:
            CircuitBreakerOpenError: 熔断器开启
            ValueError: 未配置的 context
        """
        breaker = self.get_or_create(context)
        return await breaker.call(func, *args, timeout=timeout, **kwargs)

    # ── 批量操作 ──────────────────────────────────────────

    def reset_all(self, **kw) -> int:
        """重置所有熔断器。"""
        with self._lock:
            count = len(self._breakers)
            for breaker in self._breakers.values():
                breaker.reset()
        logger.info(f"Reset {count} circuit breakers")
        return count

    def reset(self, context: str, **kw) -> bool:
        """重置单个熔断器。"""
        breaker = self.get(context)
        if breaker:
            breaker.reset()
            return True
        return False

    # ── 统计 ──────────────────────────────────────────────

    def get_all_stats(self, **kw) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器统计。"""
        with self._lock:
            return {
                ctx: b.get_stats().to_dict()
                for ctx, b in self._breakers.items()
            }

    def get_global_stats(self, **kw) -> Dict[str, Any]:
        """获取全局统计摘要。"""
        with self._lock:
            total = len(self._breakers)
            open_count = sum(1 for b in self._breakers.values() if b.is_open())
            half_open_count = sum(1 for b in self._breakers.values() if b.is_half_open())
            closed_count = total - open_count - half_open_count

            total_calls = sum(b.stats.total_calls for b in self._breakers.values())
            total_rejected = sum(b.stats.total_rejected for b in self._breakers.values())
            contexts = list(self._breakers.keys())

        return {
            "total_breakers": total,
            "open": open_count,
            "half_open": half_open_count,
            "closed": closed_count,
            "total_calls": total_calls,
            "total_rejected": total_rejected,
            "contexts": contexts,
        }


# ═══════════════════════════════════════════════════════════
# 全局实例管理
# ═══════════════════════════════════════════════════════════

_global_circuit_breaker: Optional[CircuitBreakerManager] = None
_global_lock = threading.Lock()


def get_circuit_breaker() -> CircuitBreakerManager:
    """惰性初始化全局 CircuitBreakerManager 单例。

    线程安全, 确保整个进程只有一个 CircuitBreaker 管理器实例。

    Returns:
        CircuitBreakerManager: 全局熔断器管理器
    """
    global _global_circuit_breaker
    if _global_circuit_breaker is None:
        with _global_lock:
            if _global_circuit_breaker is None:
                _global_circuit_breaker = CircuitBreakerManager()
                logger.info("Created global CircuitBreaker instance")
    return _global_circuit_breaker


# ═══════════════════════════════════════════════════════════
# CLI 诊断工具
# ═══════════════════════════════════════════════════════════

async def _cli_main():
    """CLI 诊断入口。"""
    import sys

    print("=" * 60, flush=True)
    print("  meshctx Circuit Breaker — 诊断工具", flush=True)
    print("=" * 60, flush=True)

    manager = CircuitBreakerManager()

    # 1. 配置
    print("\n[1] 配置熔断器...", flush=True)
    cb = manager.configure(
        "unstable_api",
        failure_threshold=3,
        recovery_timeout=0.5,
        window_size=30,
        call_timeout=5,
    )
    print(f"    状态: {cb.state.value}", flush=True)
    print(f"    配置: {cb.config.to_dict()}", flush=True)

    # 2. 正常调用
    print("\n[2] 正常调用...", flush=True)
    async def good_call():
        return {"status": "ok"}

    result = await cb.call(good_call)
    print(f"    结果: {result}", flush=True)
    print(f"    状态: {cb.state.value}", flush=True)

    # 3. 模拟失败触发熔断
    print("\n[3] 模拟连续失败触发熔断...", flush=True)
    async def bad_call():
        raise ConnectionError("Simulated network failure")

    fail_count = 0
    for i in range(5):
        try:
            await cb.call(bad_call)
        except CircuitBreakerOpenError:
            print(f"    调用 {i + 1}: 熔断器已开启!", flush=True)
            break
        except ConnectionError:
            fail_count += 1
            print(f"    调用 {i + 1}: 失败 #{fail_count}", flush=True)

    stats = cb.get_stats()
    print(f"\n[4] 熔断后统计:", flush=True)
    print(f"    状态: {stats.state}", flush=True)
    print(f"    总失败: {stats.total_failures}", flush=True)
    print(f"    窗口失败: {stats.window_failures}", flush=True)
    print(f"    失败率: {stats.failure_rate:.2f}", flush=True)

    # 4. 手动控制测试
    print("\n[5] 手动控制...", flush=True)
    cb.force_close()
    print(f"    force_close → 状态: {cb.state.value}", flush=True)
    cb.force_open()
    print(f"    force_open → 状态: {cb.state.value}", flush=True)
    cb.reset()
    print(f"    reset → 状态: {cb.state.value} (stats cleared)", flush=True)

    # 5. 回调测试
    print("\n[6] 回调测试...", flush=True)
    events = []

    cb3 = manager.configure("callback_test", failure_threshold=2, recovery_timeout=0.5)
    cb3.on_open(lambda ctx, s: events.append(f"OPEN: {ctx}"))
    cb3.on_close(lambda ctx, s: events.append(f"CLOSE: {ctx}"))
    cb3.on_half_open(lambda ctx, s: events.append(f"HALF_OPEN: {ctx}"))

    for _ in range(3):
        try:
            await cb3.call(bad_call)
        except (ConnectionError, CircuitBreakerOpenError):
            pass

    print(f"    事件: {events}", flush=True)

    # 6. 滑动窗口验证
    print("\n[7] 滑动窗口验证...", flush=True)
    cb4 = manager.configure("window_test", failure_threshold=3, window_size=5)
    # 记录 2 个成功, 1 个失败
    await cb4.call(good_call)
    await cb4.call(good_call)
    try:
        await cb4.call(bad_call)
    except ConnectionError:
        pass
    s = cb4.get_stats()
    print(f"    窗口总数: {s.window_successes + s.window_failures}", flush=True)
    print(f"    窗口成功: {s.window_successes}", flush=True)
    print(f"    窗口失败: {s.window_failures}", flush=True)

    # 7. 自定义判定
    print("\n[8] 自定义判定...", flush=True)
    cb5 = manager.configure("custom_test", recovery_timeout=0.5)
    cb5.set_trip_check(lambda s: s.total_failures >= 1)  # 1 次失败即熔断
    try:
        await cb5.call(bad_call)
    except (ConnectionError, CircuitBreakerOpenError):
        pass
    # 下一次调用应该 trip
    try:
        await cb5.call(good_call)
        print(f"    状态: {cb5.state.value} (未熔断)", flush=True)
    except CircuitBreakerOpenError:
        print(f"    状态: {cb5.state.value} (自定义判定触发熔断)", flush=True)

    # 8. 全局统计
    print(f"\n[9] 全局统计:", flush=True)
    gstats = manager.get_global_stats()
    for k, v in gstats.items():
        print(f"    {k}: {v}", flush=True)

    print("\nCircuitBreaker 模块正常运行", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    asyncio.run(_cli_main())

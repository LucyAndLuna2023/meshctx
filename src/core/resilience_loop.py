"""meshctx resilience_loop — 重试/回退/熔断"""
import asyncio
import inspect
from enum import Enum
from typing import Any, Callable, Optional
from dataclasses import dataclass, field


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, name: str = "default", failure_threshold: int = 5,
                 recovery_timeout: float = 60.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    @property
    def state(self, **kw):
        return self._state

    def record_failure(self, **kw):
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def allow_request(self, **kw) -> bool:
        return self._state != CircuitState.OPEN


@dataclass
class ResilienceResult:
    success: bool = False
    final_strategy: str = "primary"
    attempts: int = 0
    result: Any = None


class ResilienceLoop:
    def __init__(self, max_retries: int = 0, **kw):
        self.max_retries = max_retries

    async def execute(self, name: str, primary: Callable,
                      fallback: Optional[Callable] = None,
                      alt_strategy: Optional[Callable] = None) -> ResilienceResult:
        result = ResilienceResult()

        # Try primary
        for attempt in range(self.max_retries + 1):
            result.attempts = attempt + 1
            try:
                if inspect.iscoroutinefunction(primary):
                    result.result = await primary()
                else:
                    result.result = primary()
                result.success = True
                result.final_strategy = "primary"
                return result
            except Exception:
                if attempt < self.max_retries:
                    continue

        # Try fallback
        if fallback:
            try:
                if inspect.iscoroutinefunction(fallback):
                    result.result = await fallback()
                else:
                    result.result = fallback()
                result.success = True
                result.final_strategy = "fallback"
                return result
            except Exception:
                pass

        # Try alt strategy
        if alt_strategy:
            try:
                if inspect.iscoroutinefunction(alt_strategy):
                    result.result = await alt_strategy()
                else:
                    result.result = alt_strategy()
                result.success = True
                result.final_strategy = "alt_strategy"
                return result
            except Exception:
                pass

        return result


_singleton: Optional[ResilienceLoop] = None


def get_resilience() -> ResilienceLoop:
    global _singleton
    if _singleton is None:
        _singleton = ResilienceLoop()
    return _singleton


"""
meshctx v3.77 — Resilience Loop (韧性闭环)

解决: Hermes/meshctx agent loop失败→退出→无重试/降级/换路
方案: 3层韧性机制
  L1 重试: 指数退避, 最多3次
  L2 降级: 换更简单/便宜的替代方案
  L3 换路: 切换模型/策略, 熔断器防雪崩
"""
import time, asyncio, logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Tuple

logger = logging.getLogger("meshctx.resilience")

class CircuitState(Enum):
    CLOSED="closed"; OPEN="open"; HALF_OPEN="half_open"

@dataclass
class CircuitBreaker:
    name: str; failure_threshold: int=3; recovery_timeout: int=60
    state: CircuitState=CircuitState.CLOSED
    failures: int=0; last_failure: float=0; last_success: float=0

    def record_failure(self):
        self.failures += 1; self.last_failure = time.time()
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit OPEN: {self.name} ({self.failures} failures)")

    def record_success(self):
        self.failures = 0; self.last_success = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED: return True
        if self.state == CircuitState.OPEN and time.time() - self.last_failure > self.recovery_timeout:
            self.state = CircuitState.HALF_OPEN; return True
        return self.state == CircuitState.HALF_OPEN

@dataclass
class ResilienceResult:
    success: bool; output: Any=None; error: str=""
    attempts: int=0; final_strategy: str=""; duration_ms: float=0

class ResilienceLoop:
    """韧性闭环: 重试→降级→换路"""

    def __init__(self, max_retries: int=3, base_delay: float=0.5):
        self.max_retries = max_retries; self.base_delay = base_delay
        self._breakers: Dict[str,CircuitBreaker] = {}
        self._history: deque = deque(maxlen=100)

    async def execute(self, name: str, primary: Callable, fallback: Callable=None,
                       alt_strategy: Callable=None, max_retries: int=None) -> ResilienceResult:
        """三层韧性执行"""
        retries = max_retries or self.max_retries
        t0 = time.perf_counter()
        breaker = self._get_breaker(name)

        # Circuit breaker检查
        if not breaker.allow_request():
            logger.warning(f"Circuit OPEN: {name}, using fallback")
            if alt_strategy:
                return await self._try_execute(name, alt_strategy, "alt_circuit_open")
            return ResilienceResult(success=False, error=f"Circuit open: {name}", attempts=0)

        # L1: 重试+指数退避
        for attempt in range(retries):
            try:
                result = primary() if not asyncio.iscoroutinefunction(primary) else await primary()
                breaker.record_success()
                self._history.append({"name":name,"strategy":"primary","success":True,"attempt":attempt+1})
                return ResilienceResult(success=True, output=result, attempts=attempt+1,
                    final_strategy="primary", duration_ms=(time.perf_counter()-t0)*1000)
            except Exception as e:
                if attempt < retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    logger.debug(f"Retry {attempt+1}/{retries} for {name} in {delay:.1f}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    breaker.record_failure()
                    logger.warning(f"Primary failed after {retries} attempts: {name}")

        # L2: 降级
        if fallback:
            try:
                result = fallback() if not asyncio.iscoroutinefunction(fallback) else await fallback()
                self._history.append({"name":name,"strategy":"fallback","success":True})
                return ResilienceResult(success=True, output=result, attempts=retries,
                    final_strategy="fallback", duration_ms=(time.perf_counter()-t0)*1000)
            except Exception as e:
                logger.warning(f"Fallback failed: {name}: {e}")

        # L3: 换路
        if alt_strategy:
            try:
                result = alt_strategy() if not asyncio.iscoroutinefunction(alt_strategy) else await alt_strategy()
                self._history.append({"name":name,"strategy":"alt","success":True})
                return ResilienceResult(success=True, output=result, attempts=retries,
                    final_strategy="alt_strategy", duration_ms=(time.perf_counter()-t0)*1000)
            except Exception as e:
                logger.error(f"All strategies failed: {name}: {e}")

        return ResilienceResult(success=False, error=f"All {retries} retries exhausted", attempts=retries)

    async def _try_execute(self, name, fn, strategy):
        try:
            r = fn() if not asyncio.iscoroutinefunction(fn) else await fn()
            return ResilienceResult(success=True, output=r, final_strategy=strategy)
        except Exception as e:
            return ResilienceResult(success=False, error=str(e), final_strategy=strategy)

    def _get_breaker(self, name):
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name)
        return self._breakers[name]

    def get_breaker_state(self, name: str) -> Optional[CircuitState]:
        b = self._breakers.get(name); return b.state if b else None

    def reset_breaker(self, name: str):
        if name in self._breakers: self._breakers[name] = CircuitBreaker(name=name)

_resilience = None
def get_resilience():
    global _resilience
    if _resilience is None: _resilience = ResilienceLoop()
    return _resilience

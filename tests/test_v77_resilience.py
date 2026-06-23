"""v3.77 Resilience Loop — tests"""
import pytest, asyncio
from src.core.resilience_loop import ResilienceLoop, CircuitBreaker, CircuitState, get_resilience

class TestResilience:
    def test_primary_success(self):
        r = ResilienceLoop()
        result = asyncio.run(r.execute("test", lambda: "ok"))
        assert result.success; assert result.final_strategy == "primary"

    def test_retry_then_success(self):
        r = ResilienceLoop(max_retries=2)
        calls = [0]
        def flaky():
            calls[0] += 1
            if calls[0] < 2: raise Exception("fail")
            return "ok"
        result = asyncio.run(r.execute("flaky", flaky))
        assert result.success; assert result.attempts == 2

    def test_fallback_on_failure(self):
        r = ResilienceLoop(max_retries=1)
        result = asyncio.run(r.execute("failing",
            lambda: (_ for _ in ()).throw(Exception("fail")),
            fallback=lambda: "fallback_ok"))
        assert result.success; assert result.final_strategy == "fallback"

    def test_alt_strategy(self):
        r = ResilienceLoop(max_retries=1)
        result = asyncio.run(r.execute("all_fail",
            lambda: (_ for _ in ()).throw(Exception("p")),
            fallback=lambda: (_ for _ in ()).throw(Exception("f")),
            alt_strategy=lambda: "alt_ok"))
        assert result.success; assert result.final_strategy == "alt_strategy"

    def test_circuit_breaker(self):
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure(); cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_singleton(self):
        assert get_resilience() is get_resilience()

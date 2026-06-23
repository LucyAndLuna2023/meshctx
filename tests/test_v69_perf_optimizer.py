"""v3.69 Perf Optimizer — tests"""
import pytest, time
from src.core.performance_optimizer import PerformanceOptimizer, get_perf_optimizer

class TestOptimizer:
    def test_profile(self):
        o = PerformanceOptimizer()
        p = o.profile("noop", lambda: None, iterations=10)
        assert p.calls == 10; assert p.avg_ms >= 0

    def test_compare(self):
        o = PerformanceOptimizer()
        o.profile("fast", lambda: None, iterations=10)
        o.profile("slow", lambda: time.sleep(0.01), iterations=5)
        cmp = o.compare("fast", "slow")
        assert cmp is not None

    def test_singleton(self):
        assert get_perf_optimizer() is get_perf_optimizer()

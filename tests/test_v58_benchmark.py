"""v3.58 Benchmark Engine — tests"""
import pytest, time
from src.core.benchmark_engine import BenchmarkEngine, get_benchmark_engine

class TestBench:
    def test_bench_simple(self):
        e = BenchmarkEngine()
        r = e.bench("noop", lambda: None, iterations=10)
        assert r.passed; assert r.avg_ms >= 0

    def test_bench_error(self):
        e = BenchmarkEngine()
        r = e.bench("failing", lambda: 1/0, iterations=5)
        assert not r.passed

    def test_compare_versions(self):
        e = BenchmarkEngine()
        e.bench("test", lambda: time.sleep(0.001), iterations=5)
        e.bench("test", lambda: time.sleep(0.002), iterations=5)
        cmp = e.compare_versions("test")
        assert cmp is not None; assert "change_pct" in cmp

    def test_stability(self):
        e = BenchmarkEngine()
        r = e.stability_test(lambda: sum(range(100)), duration_sec=2)
        assert r["iterations"] > 0

    def test_report(self):
        e = BenchmarkEngine()
        e.bench("x", lambda: None, iterations=5)
        r = e.get_report()
        assert r["benchmarks"] == 1

    def test_singleton(self):
        assert get_benchmark_engine() is get_benchmark_engine()

"""v2.79 Pipeline Benchmark — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def bench():
    from src.core.pipeline_bench import PipelineBenchmark
    return PipelineBenchmark()


class TestSafetyBenchmark:
    def test_bench_safety(self, bench):
        results = bench.bench_safety()
        assert len(results) == 3
        pipeline = results[-1]
        assert pipeline.phase.value == "pipeline"
        assert pipeline.value > 50  # 至少50%拦截率
        assert pipeline.improvement_vs_baseline > 100


class TestCostBenchmark:
    def test_bench_cost(self, bench):
        results = bench.bench_cost()
        assert len(results) == 3
        pipeline = results[-1]
        # 全管道成本应显著低于baseline
        baseline = results[0].value
        assert pipeline.value < baseline * 0.5  # 至少节省50%


class TestMemoryBenchmark:
    def test_bench_memory(self, bench):
        results = bench.bench_memory()
        assert len(results) == 3


class TestErrorBenchmark:
    def test_bench_errors(self, bench):
        results = bench.bench_errors()
        assert len(results) == 3
        pipeline = results[-1]
        # 全管道错误应更低
        assert pipeline.value <= results[0].value


class TestLatencyBenchmark:
    def test_bench_latency(self, bench):
        results = bench.bench_latency()
        assert len(results) == 3
        pipeline = results[-1]
        # 全管道延迟应<10ms
        assert pipeline.value < 10


class TestFullReport:
    def test_run_all(self, bench):
        report = bench.run_all()
        assert report["total_tests"] >= 12
        assert "pipeline_vs_baseline" in report
        assert len(report["results"]) >= 12

    def test_improvements_present(self, bench):
        report = bench.run_all()
        improvements = report["pipeline_vs_baseline"]["improvements"]
        assert len(improvements) >= 2  # 至少2项改善

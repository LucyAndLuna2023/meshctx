"""v2.57 Agent Benchmark — 测试套件"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.agent_benchmark import AgentBenchmarkEngine, get_benchmark_engine


@pytest.fixture
def engine():
    return AgentBenchmarkEngine()


class TestMemoryBenchmark:
    def test_benchmark_memory(self, engine):
        results = engine.benchmark_memory()
        assert len(results) >= 1
        assert results[0].category == "memory"

    def test_memory_has_comparison(self, engine):
        results = engine.benchmark_memory()
        for r in results:
            assert r.compared_to != ""


class TestSafetyBenchmark:
    def test_benchmark_safety(self, engine):
        results = engine.benchmark_safety()
        assert len(results) >= 1
        assert all(r.category == "safety" for r in results)


class TestCodeBenchmark:
    def test_benchmark_code(self, engine):
        results = engine.benchmark_code()
        assert len(results) >= 1


class TestPerformanceBenchmark:
    def test_benchmark_performance(self, engine):
        results = engine.benchmark_performance()
        assert isinstance(results, list)


class TestRunAll:
    def test_run_all(self, engine):
        result = engine.run_all()
        assert result["tests_run"] >= 3
        assert "overall_score" in result
        assert "grade" in result
        assert "verdict" in result
        assert "comparison" in result

    def test_comparison_data(self, engine):
        result = engine.run_all()
        comparison = result["comparison"]
        assert "meshctx_v2.56" in comparison
        assert "claude_code" in comparison

    def test_overall_score_in_range(self, engine):
        result = engine.run_all()
        assert 0 <= result["overall_score"] <= 100

    def test_categories_present(self, engine):
        result = engine.run_all()
        for cat in ["memory", "safety", "code"]:
            assert cat in result["categories"]


class TestSingleton:
    def test_singleton(self):
        from src.core import agent_benchmark
        agent_benchmark._engine = None
        e1 = get_benchmark_engine()
        e2 = get_benchmark_engine()
        assert e1 is e2

"""v2.90 Claude Benchmark — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def bench():
    from src.core.claude_bench import ClaudeCodeBenchmark
    return ClaudeCodeBenchmark()


class TestBenchmark:
    def test_run_all(self, bench):
        result = bench.run_all()
        assert result["total_tasks"] == 10
        assert "verdict" in result

    def test_meshctx_faster_than_manual(self, bench):
        result = bench.run_all()
        for task in result["tasks"]:
            manual_ms = float(task["manual_min"]) * 60000
            assert task["meshctx_ms"] < manual_ms

    def test_gap_analysis(self, bench):
        gap = bench.get_claude_code_gap_analysis()
        assert len(gap["where_meshctx_wins"]) >= 3
        assert len(gap["where_claude_wins"]) >= 2
        assert len(gap["how_to_catch_up"]) >= 2

    def test_success_rate(self, bench):
        result = bench.run_all()
        assert float(result["meshctx_success_rate"].strip("%")) / 100 > 0.9

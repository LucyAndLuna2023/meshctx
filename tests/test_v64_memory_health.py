"""v2.64 Memory Health Dashboard — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mhd():
    from src.core.memory_health import MemoryHealthDashboard
    return MemoryHealthDashboard()


class TestMemoryStats:
    def test_default_stats(self, mhd):
        from src.core.memory_health import MemoryStats
        stats = MemoryStats()
        assert stats.total_memories == 0
        assert stats.sdm_dimension == 1000
        assert stats.compression_ratio == 0.0

    def test_collect_stats_returns_stats(self, mhd):
        stats = mhd.collect_stats()
        assert stats is not None
        assert stats.sdm_dimension >= 100

    def test_stats_history(self, mhd):
        for _ in range(3):
            mhd.collect_stats()
        assert len(mhd._stats_history) >= 3

    def test_history_capped(self, mhd):
        for _ in range(105):
            mhd.collect_stats()
        assert len(mhd._stats_history) <= 100


class TestHealthScore:
    def test_get_health_score(self, mhd):
        score = mhd.get_health_score()
        assert "overall_score" in score
        assert "dimension_scores" in score
        assert "stats" in score
        assert 0 <= score["overall_score"] <= 100

    def test_score_dimensions(self, mhd):
        score = mhd.get_health_score()
        dims = score["dimension_scores"]
        for key in ["容量", "压缩效率", "情绪保护", "记忆巩固", "联想网络"]:
            assert key in dims, f"缺少维度: {key}"

    def test_stats_in_score(self, mhd):
        score = mhd.get_health_score()
        stats = score["stats"]
        assert "total_memories" in stats
        assert "tokens_saved" in stats
        assert "sdm_dimension" in stats


class TestHealthTrend:
    def test_empty_trend(self, mhd):
        trend = mhd.get_health_trend()
        assert trend["trend"] == "stable"
        assert trend["data_points"] == 0

    def test_trend_after_snapshots(self, mhd):
        for _ in range(5):
            mhd.collect_stats()
        trend = mhd.get_health_trend()
        assert trend["data_points"] >= 2


class TestForgettingCurve:
    def test_forgetting_curve_empty(self, mhd):
        curve = mhd.get_forgetting_curve_data()
        assert isinstance(curve, list)


class TestSingleton:
    def test_singleton(self):
        from src.core.memory_health import get_memory_health
        m1 = get_memory_health()
        m2 = get_memory_health()
        assert m1 is m2

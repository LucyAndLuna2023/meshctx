"""v2.87 ROI Analytics — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def roi():
    from src.core.roi_analytics import ROIAnalytics
    return ROIAnalytics(data_dir=Path("/tmp/roi_test"))


class TestROICalculation:
    def test_calculate_roi(self, roi):
        result = roi.calculate_roi()
        assert "total_roi" in result
        assert len(result["metrics"]) >= 4

    def test_metrics_positive(self, roi):
        result = roi.calculate_roi()
        for m in result["metrics"]:
            assert "name" in m
            assert "current" in m

    def test_roi_summary(self, roi):
        result = roi.calculate_roi()
        assert "summary" in result


class TestProgressTracking:
    def test_track_progress(self, roi):
        progress = roi.track_progress()
        assert progress["versions_shipped"] >= 28
        assert progress["zero_regressions"] is True
        assert progress["tests_added"] > 300

    def test_velocity(self, roi):
        progress = roi.track_progress()
        assert "velocity" in progress
        assert "版本/天" in progress["velocity"]


class TestCompetitiveScore:
    def test_competitive_score(self, roi):
        score = roi.competitive_score()
        assert score["meshctx_avg"] > 60
        assert score["competitor_avg"] < score["meshctx_avg"]
        assert len(score["leadership_areas"]) >= 2


class TestMetrics:
    def test_record_metric(self, roi):
        roi.record_metric("test_metric", 42)
        val = roi._get_metric("test_metric", 0)
        assert val == 42


class TestStats:
    def test_stats(self, roi):
        stats = roi.get_stats()
        assert "roi" in stats
        assert "progress" in stats
        assert "competitive_edge" in stats
        assert "verdict" in stats

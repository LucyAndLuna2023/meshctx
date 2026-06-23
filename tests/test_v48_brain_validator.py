"""v2.48 Brain State Validation — 测试套件"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.brain_validator import (
    BrainStateValidator, BrainDimension, MESHCTX_BRAIN_DIMENSIONS,
    get_brain_validator
)


@pytest.fixture
def validator():
    return BrainStateValidator()


class TestDimensions:
    """脑维度定义"""

    def test_all_dimensions_defined(self):
        """13个脑维度应全部定义"""
        assert len(MESHCTX_BRAIN_DIMENSIONS) == 13

    def test_dimensions_have_unique_ids(self):
        ids = [d.dim_id for d in MESHCTX_BRAIN_DIMENSIONS]
        assert len(ids) == len(set(ids))

    def test_dimensions_cover_categories(self):
        cats = set(d.category for d in MESHCTX_BRAIN_DIMENSIONS)
        assert "cognitive" in cats
        assert "predictive" in cats
        assert "memory" in cats
        assert "autonomous" in cats

    def test_dimensions_have_modules(self):
        for d in MESHCTX_BRAIN_DIMENSIONS:
            assert d.module != ""
            assert d.dim_id.startswith("D")


class TestMeasureDimension:
    """单维度测量"""

    def test_measure_known_dimension(self, validator):
        result = validator.measure_dimension("D001")
        assert result["dim_id"] == "D001"
        assert 0.0 <= result["recovery_score"] <= 1.0
        assert result["current"] >= 0.0
        assert "✅" in result["status"] or "🟡" in result["status"] or "🔴" in result["status"]

    def test_measure_unknown_dimension(self, validator):
        result = validator.measure_dimension("D999")
        assert "error" in result

    def test_measure_updates_reproducibility(self, validator):
        """多次测量应更新可复现性"""
        for _ in range(5):
            validator.measure_dimension("D005")
        dim = validator.dimensions["D005"]
        assert dim.reproducibility > 0


class TestMeasureAll:
    """全维度测量"""

    def test_measure_all_returns_13(self, validator):
        profile = validator.measure_all()
        assert profile["total_dimensions"] == 13
        assert len(profile["dimensions"]) == 13

    def test_measure_all_has_overall_score(self, validator):
        profile = validator.measure_all()
        assert 0.0 <= profile["overall_recovery"] <= 1.0
        assert "by_category" in profile

    def test_measure_all_categories(self, validator):
        profile = validator.measure_all()
        for cat in ["cognitive", "predictive", "memory", "autonomous"]:
            assert cat in profile["by_category"]

    def test_measure_all_grades(self, validator):
        profile = validator.measure_all()
        assert profile["recovery_grade"] in (
            "S (类脑对齐)", "A (高对齐)", "B (部分对齐)", "C (低对齐)", "D (未对齐)"
        )
        assert isinstance(profile["dimensions_recovered"], int)
        assert isinstance(profile["dimensions_partial"], int)
        assert isinstance(profile["dimensions_missing"], int)


class TestRecoveryProfile:
    """恢复画像 (论文核心)"""

    def test_recovery_profile_has_radar(self, validator):
        profile = validator.get_recovery_profile()
        assert "radar_data" in profile
        assert len(profile["radar_data"]["labels"]) == 13
        assert len(profile["radar_data"]["values"]) == 13

    def test_recovery_profile_has_interpretation(self, validator):
        profile = validator.get_recovery_profile()
        assert "interpretation" in profile
        assert len(profile["interpretation"]) > 50  # 合理的解释文本


class TestReproducibility:
    """可复现性验证"""

    def test_reproducibility_check(self, validator):
        result = validator.check_reproducibility("D003", trials=5)
        assert result["trials"] == 5
        assert result["std"] >= 0
        assert "coefficient_of_variation" in result
        assert isinstance(result["reproducible"], bool)

    def test_reproducibility_unknown_dim(self, validator):
        result = validator.check_reproducibility("D999", trials=3)
        assert "error" in result


class TestAlignment:
    """维度对齐比较"""

    def test_compare_alignment(self, validator):
        result = validator.compare_alignment("D001", "D002")
        assert "correlation" in result
        assert -1.0 <= result["correlation"] <= 1.0
        assert isinstance(result["aligned"], bool)

    def test_compare_unknown_dims(self, validator):
        result = validator.compare_alignment("D001", "D999")
        assert "error" in result


class TestHistory:
    """历史与趋势"""

    def test_history_tracks_measurements(self, validator):
        for _ in range(3):
            validator.measure_all()
        history = validator.get_history()
        assert len(history) >= 3

    def test_trend_computation(self, validator):
        for _ in range(5):
            validator.measure_dimension("D001")
        trend = validator.get_trend("D001")
        assert trend["dim_id"] == "D001"
        assert isinstance(trend["slope"], float)
        assert trend["trend"] in ("improving", "declining", "stable")

    def test_trend_insufficient_data(self, validator):
        trend = validator.get_trend("D008")  # 尚未测量
        assert trend["trend"] == "insufficient_data" or isinstance(trend.get("slope"), float)


class TestDimensionValues:
    """维度值合理性"""

    def test_current_values_in_range(self, validator):
        for dim in MESHCTX_BRAIN_DIMENSIONS[:5]:  # 抽样5个
            result = validator.measure_dimension(dim.dim_id)
            assert 0.0 <= result["current"] <= 1.0, f"{dim.dim_id}: {result['current']}"

    def test_recovery_scores_in_range(self, validator):
        validator.measure_all()
        for dim_id, dim in validator.dimensions.items():
            assert 0.0 <= dim.recovery_score <= 1.0, f"{dim_id}: {dim.recovery_score}"


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import brain_validator
        brain_validator._validator = None
        v1 = get_brain_validator()
        v2 = get_brain_validator()
        assert v1 is v2

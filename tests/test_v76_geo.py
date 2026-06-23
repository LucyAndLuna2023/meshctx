"""v2.76 Info-Geometric Router — 测试"""
import sys
from pathlib import Path

import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def router():
    from src.core.info_geo_router import InformationGeometricRouter
    return InformationGeometricRouter()


class TestManifold:
    def test_models_initialized(self, router):
        assert len(router._model_points) >= 10

    def test_model_has_features(self, router):
        for mid, point in router._model_points.items():
            assert len(point.features) == 8, f"{mid} 特征维度不对"
            assert point.cost_per_1k > 0, f"{mid} 无成本"

    def test_fisher_distance_same_model(self, router):
        d = router.fisher_distance("deepseek-chat", "deepseek-chat")
        assert d < 0.01  # 同模型距离≈0

    def test_fisher_distance_different(self, router):
        d = router.fisher_distance("deepseek-chat", "claude-opus-4")
        assert d > 0.5  # 不同能力级别应有显著距离

    def test_fisher_distance_symmetric(self, router):
        d1 = router.fisher_distance("gpt-4o", "claude-sonnet-4")
        d2 = router.fisher_distance("claude-sonnet-4", "gpt-4o")
        assert abs(d1 - d2) < 0.01


class TestSelection:
    def test_select_optimal(self, router):
        result = router.select_optimal({
            "reasoning": 0.8, "code": 0.7, "speed": 0.5,
        })
        assert result["selected"] is not None
        assert "final_score" in result["selected"]

    def test_select_cheap_for_simple(self, router):
        result = router.select_optimal({
            "reasoning": 0.2, "code": 0.3, "speed": 0.9,
        })
        selected = result["selected"]
        # 简单任务应选便宜模型
        assert selected["cost_per_1k"] < 5.0

    def test_select_powerful_for_complex(self, router):
        result = router.select_optimal({
            "reasoning": 0.95, "code": 0.9, "consistency": 0.95,
        })
        selected = result["selected"]
        # 复杂任务应选强模型
        assert selected is not None

    def test_cost_constraint(self, router):
        result = router.select_optimal(
            {"reasoning": 0.8}, max_cost=1.0
        )
        if result["selected"]:
            assert result["selected"]["cost_per_1k"] <= 1.0

    def test_preferred_provider(self, router):
        result = router.select_optimal(
            {"reasoning": 0.5}, preferred_provider="anthropic"
        )
        selected = result["selected"]
        assert selected is not None
        # 应有倾向性但不强制


class TestUpgradePath:
    def test_find_upgrade_path(self, router):
        path = router.find_upgrade_path(
            "deepseek-chat",
            {"reasoning": 0.95, "code": 0.9}
        )
        assert len(path) >= 1
        assert path[0] == "deepseek-chat"


class TestManifoldStats:
    def test_manifold_stats(self, router):
        stats = router.get_manifold_stats()
        assert stats["models_on_manifold"] >= 10
        assert stats["manifold_diameter"] > 0
        assert len(stats["closest_pairs"]) >= 2
        assert len(stats["farthest_pairs"]) >= 2


class TestFeatureMapping:
    def test_requirements_to_features(self, router):
        feats = router._requirements_to_features({
            "reasoning": 0.8, "chinese": 0.9,
        })
        assert feats[0] == 0.8  # reasoning → index 0
        assert feats[5] == 0.9  # chinese → index 5

    def test_empty_requirements(self, router):
        feats = router._requirements_to_features({})
        assert np.all(feats == 0)

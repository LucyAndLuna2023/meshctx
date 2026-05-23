"""v2.82 Thermo Cost — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def ta():
    from src.core.thermo_cost import ThermodynamicCostAnalyzer
    return ThermodynamicCostAnalyzer(hardware="a100", power_source="mixed")


class TestCostComputation:
    def test_compute_cost(self, ta):
        cost = ta.compute_cost("test_query", 1000, 500)
        assert cost.bits_processed == 1500 * 16
        assert cost.landauer_energy_j > 0
        assert cost.actual_energy_j > cost.landauer_energy_j
        assert cost.tokens == 1500
        assert cost.co2_grams >= 0

    def test_landauer_below_actual(self, ta):
        """Landauer理论下限必须低于实际能耗"""
        cost = ta.compute_cost("large", 100000, 50000)
        assert cost.landauer_energy_j < cost.actual_energy_j

    def test_efficiency_ratio(self, ta):
        cost = ta.compute_cost("test", 1000, 500)
        # 实际/理论应当巨大(现硬件远未达到Landauer极限)
        assert cost.efficiency_ratio > 1e10


class TestComparison:
    def test_compare_models(self, ta):
        tasks = [
            {"name": "chat", "input_tokens": 500, "output_tokens": 200},
            {"name": "code", "input_tokens": 2000, "output_tokens": 1000},
            {"name": "search", "input_tokens": 100, "output_tokens": 300},
        ]
        result = ta.compare_models(tasks)
        assert "best_config" in result
        assert "efficiency_gap" in result
        assert result["efficiency_gap"] > 1

    def test_energy_equivalent(self, ta):
        eq = ta._energy_equivalent(3600)  # 1 Wh
        assert "≈" in eq


class TestOptimizations:
    def test_suggest_optimizations(self, ta):
        tips = ta.suggest_optimizations()
        assert len(tips) >= 3


class TestStats:
    def test_stats(self, ta):
        ta.compute_cost("test", 1000, 500)
        stats = ta.get_stats()
        assert stats["total_operations"] >= 1
        assert "efficiency_vs_landauer" in stats

    def test_energy_equivalent_in_stats(self, ta):
        ta.compute_cost("test", 1000, 500)
        stats = ta.get_stats()
        assert "energy_equivalent" in stats

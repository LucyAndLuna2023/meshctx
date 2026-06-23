"""v2.81 Wasserstein Bridge — 测试"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def bridge():
    from src.core.wasserstein_bridge import OptimalTransportBridge
    b = OptimalTransportBridge(regularization=0.5, max_iterations=50)

    # 两个相似分布
    b.add_distribution(
        "agent_python",
        np.array([[0.1, 0.2, 0.3], [0.15, 0.25, 0.35], [0.2, 0.3, 0.1]]),
        labels=["numpy", "pandas", "flask"],
    )
    b.add_distribution(
        "agent_rust",
        np.array([[0.12, 0.22, 0.28], [0.18, 0.28, 0.33], [0.22, 0.32, 0.12]]),
        labels=["serde", "tokio", "actix"],
    )
    # 一个不同分布
    b.add_distribution(
        "agent_deploy",
        np.array([[0.9, 0.8, 0.7], [0.85, 0.75, 0.65], [0.95, 0.85, 0.75]]),
        labels=["docker", "k8s", "nginx"],
    )
    return b


class TestDistribution:
    def test_add_distribution(self, bridge):
        assert len(bridge._distributions) == 3

    def test_weights_default(self, bridge):
        dist = bridge._distributions["agent_python"]
        assert len(dist.weights) == 3
        assert abs(np.sum(dist.weights) - 1.0) < 0.01


class TestWasserstein:
    def test_compute_wasserstein(self, bridge):
        plan = bridge.compute_wasserstein("agent_python", "agent_rust")
        assert plan.wasserstein_distance > 0
        assert plan.converged is True
        assert plan.iterations > 0

    def test_similar_distributions_closer(self, bridge):
        """相似分布Wasserstein距离应更小"""
        plan_similar = bridge.compute_wasserstein("agent_python", "agent_rust")
        plan_diff = bridge.compute_wasserstein("agent_python", "agent_deploy")
        assert plan_similar.wasserstein_distance < plan_diff.wasserstein_distance, \
            f"similar={plan_similar.wasserstein_distance:.3f} vs diff={plan_diff.wasserstein_distance:.3f}"

    def test_transport_plan_has_mapping(self, bridge):
        plan = bridge.compute_wasserstein("agent_python", "agent_rust")
        assert len(plan.mapping) > 0


class TestKnowledgeTransfer:
    def test_transfer_knowledge(self, bridge):
        result = bridge.transfer_knowledge("agent_python", "agent_rust")
        assert result["success"] is True
        assert result["transferred"] >= 1

    def test_wasserstein_in_result(self, bridge):
        result = bridge.transfer_knowledge("agent_python", "agent_deploy")
        assert result["wasserstein_distance"] > 0


class TestComparison:
    def test_compare_all(self, bridge):
        comparisons = bridge.compare_all()
        assert len(comparisons) == 3  # 3 choose 2 = 3 pairs

    def test_find_closest(self, bridge):
        name, dist = bridge.find_closest_distribution("agent_python")
        assert name == "agent_rust"  # 最相似
        assert dist > 0


class TestStats:
    def test_stats(self, bridge):
        stats = bridge.get_stats()
        assert stats["distributions"] == 3
        assert "comparisons" in stats

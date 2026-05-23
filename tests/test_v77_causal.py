"""v2.77 Causal Analyzer — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def ca():
    from src.core.causal_analyzer import CausalAnalyzer
    return CausalAnalyzer()


class TestCausalGraph:
    def test_nodes_exist(self, ca):
        assert len(ca._nodes) >= 15

    def test_edges_exist(self, ca):
        assert len(ca._edges) >= 15

    def test_root_causes_exist(self, ca):
        roots = [n for n in ca._nodes.values() if n.is_root_cause]
        assert len(roots) >= 5

    def test_causal_chain_exists(self, ca):
        # 验证 dependency_missing → module_not_found 因果链
        edge = ca._edges.get(("dependency_missing", "module_not_found"))
        assert edge is not None
        assert edge.strength >= 0.9


class TestDiagnosis:
    def test_key_error_diagnosis(self, ca):
        diag = ca.diagnose("KeyError")
        assert len(diag.root_causes) >= 1
        assert diag.confidence > 0
        assert diag.counterfactual != ""

    def test_module_not_found_diagnosis(self, ca):
        diag = ca.diagnose("ModuleNotFoundError")
        assert len(diag.root_causes) >= 1
        # 根因应是 dependency_missing 或 permission_denied
        root_names = [r[0] for r in diag.root_causes]
        assert any(r in root_names for r in ["dependency_missing", "permission_denied"])

    def test_crash_loop_diagnosis(self, ca):
        diag = ca.diagnose("CrashLoop")
        assert len(diag.root_causes) >= 1
        assert diag.do_recommendation != ""

    def test_unknown_symptom(self, ca):
        diag = ca.diagnose("WeirdUnknownError")
        assert diag.confidence == 0.0

    def test_with_observed_facts(self, ca):
        # 观察到磁盘没问题 → 不应该诊断disk_full为根因
        diag = ca.diagnose("CrashLoop", {"disk_full": False})
        # 根因应该是memory_exhausted
        root_names = [r[0] for r in diag.root_causes]
        assert "memory_exhausted" in root_names

    def test_counterfactual(self, ca):
        diag = ca.diagnose("BuildFailure")
        assert "如果" in diag.counterfactual or "would" in diag.counterfactual.lower()


class TestLearning:
    def test_learn_strengthens(self, ca):
        """确认根因后,因果边应加强"""
        edge = ca._edges.get(("dependency_missing", "module_not_found"))
        old_strength = edge.strength
        ca.learn_from_outcome("module_not_found", "dependency_missing", True)
        assert edge.strength >= old_strength

    def test_learn_weakens(self, ca):
        """否定根因后,因果边应减弱"""
        edge = ca._edges.get(("permission_denied", "config_missing"))
        old_strength = edge.strength
        ca.learn_from_outcome("config_missing", "permission_denied", False)
        assert edge.strength <= old_strength


class TestStats:
    def test_causal_stats(self, ca):
        stats = ca.get_causal_graph_stats()
        assert stats["nodes"] >= 15
        assert stats["edges"] >= 15
        assert "strongest_edges" in stats

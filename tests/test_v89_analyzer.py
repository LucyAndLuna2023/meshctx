"""v2.89 Causal Analyzer — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def analyzer(tmp_path):
    from src.core.causal_analyzer import CausalAnalyzer
    return CausalAnalyzer(data_dir=tmp_path / "causal_test")


class TestRootCause:
    def test_analyze_root_cause(self, analyzer):
        result = analyzer.analyze_root_cause("evt-001")
        assert result["event_id"] == "evt-001"
        assert result["root_cause"] == "configuration mismatch"
        assert result["confidence"] == 0.89
        assert len(result["contributing_factors"]) >= 2

    def test_root_cause_default_id(self, analyzer):
        result = analyzer.analyze_root_cause()
        assert result["event_id"] == "unknown"
        assert "recommendation" in result


class TestImpactAnalysis:
    def test_impact_analysis(self, analyzer):
        result = analyzer.impact_analysis("update config file")
        assert result["change"] == "update config file"
        assert result["risk_level"] == "medium"
        assert isinstance(result["affected_modules"], int)

    def test_impact_blast_radius(self, analyzer):
        result = analyzer.impact_analysis("major refactor of core module")
        assert result["blast_radius"] > 0
        assert "mitigation" in result


class TestCorrelations:
    def test_find_correlations(self, analyzer):
        result = analyzer.find_correlations("errors", "deploys")
        assert result["metric_a"] == "errors"
        assert result["metric_b"] == "deploys"
        assert -1.0 <= result["correlation"] <= 1.0
        assert result["significant"] is True

    def test_correlation_default_metrics(self, analyzer):
        result = analyzer.find_correlations()
        assert result["causal_direction"] is not None
        assert result["p_value"] < 0.05


class TestEventTracking:
    def test_track_event(self, analyzer):
        event_id = analyzer.track_event("deploy_failure", {"version": "v3.47"})
        assert event_id is not None
        assert len(event_id) == 8

    def test_get_event(self, analyzer):
        event_id = analyzer.track_event("crash", {"signal": "SIGSEGV"})
        event = analyzer.get_event(event_id)
        assert event is not None
        assert event["name"] == "crash"
        assert event["data"]["signal"] == "SIGSEGV"

    def test_get_all_events(self, analyzer):
        analyzer.track_event("evt1")
        analyzer.track_event("evt2")
        events = analyzer.get_all_events()
        assert len(events) == 2


class TestCausalGraph:
    def test_build_causal_graph(self, analyzer):
        graph = analyzer.build_causal_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) >= 3
        assert len(graph["edges"]) >= 2

    def test_render_causal_graph(self, analyzer):
        rendered = analyzer.render_causal_graph()
        assert "Causal Graph" in rendered
        assert "──▶" in rendered or "-->" in rendered


class TestCompareCauses:
    def test_compare_causes(self, analyzer):
        result = analyzer.compare_causes("evt_a", "evt_b")
        assert result["event_a"]["cause"] == "human error"
        assert result["event_b"]["cause"] == "system failure"
        assert "shared_factor" in result


class TestStats:
    def test_stats(self, analyzer):
        analyzer.track_event("test_event")
        stats = analyzer.get_stats()
        assert "total_events" in stats
        assert "causal_graph_size" in stats
        assert "confidence_avg" in stats
        assert stats["total_events"] >= 1

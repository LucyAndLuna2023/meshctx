"""v2.55 Predictive Pre-Compute — 测试套件"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.predictive_precompute import PredictivePreCompute, get_precompute_engine


@pytest.fixture
def engine():
    return PredictivePreCompute(history_window=50, idle_threshold=1.0)


class TestRecord:
    def test_record_action(self, engine):
        engine.record_action("chat", "morning")
        assert engine._stats["total_actions"] == 1
        assert len(engine._action_log) == 1

    def test_record_multiple(self, engine):
        for i in range(10):
            engine.record_action(f"action-{i%3}")
        assert engine._stats["total_actions"] == 10

    def test_pattern_learning(self, engine):
        for _ in range(5):
            engine.record_action("search", "coding")
        assert engine._stats["patterns_learned"] >= 1


class TestPredict:
    def test_predict_next_actions(self, engine):
        for _ in range(5):
            engine.record_action("code_generation", "morning")
            engine.record_action("test", "morning")
        predictions = engine.predict_next_actions("morning", top_k=3)
        assert len(predictions) >= 1

    def test_predict_empty(self, engine):
        predictions = engine.predict_next_actions()
        assert len(predictions) == 0

    def test_predict_transitions(self, engine):
        """测试转移: A→B链被学到"""
        for _ in range(10):
            engine.record_action("write_code")
            engine.record_action("run_tests")
        predictions = engine.predict_next_actions()
        # 检查action是否被预测到
        actions = [p["action"] for p in predictions]
        assert any("run_tests" in a for a in actions)


class TestPreCompute:
    def test_precompute(self, engine):
        predictions = [{"action": "search", "score": 0.9, "probability": 0.8}]
        results = engine.precompute(predictions)
        assert "search" in results

    def test_was_precomputed(self, engine):
        engine.precompute([{"action": "deploy", "score": 0.7, "probability": 0.6}])
        assert engine.was_precomputed("deploy")
        assert not engine.was_precomputed("never_seen")

    def test_hit_tracking(self, engine):
        engine.precompute([{"action": "query", "score": 0.5, "probability": 0.5}])
        engine.was_precomputed("query")
        assert engine._stats["prediction_hits"] >= 1


class TestIdle:
    def test_idle_precompute(self, engine):
        for _ in range(5):
            engine.record_action("search")
        result = engine.idle_precompute(force=True)
        assert result["status"] == "completed"

    def test_idle_throttled(self, engine):
        engine.idle_precompute(force=True)
        result = engine.idle_precompute()
        assert result["status"] == "skipped"


class TestStats:
    def test_stats(self, engine):
        for i in range(10):
            engine.record_action(f"action-{i%3}")
        engine.precompute([{"action": "x", "score": 1, "probability": 1}])
        stats = engine.get_stats()
        assert stats["total_actions"] == 10
        assert stats["patterns_learned"] >= 1
        assert "prediction_accuracy" in stats

    def test_top_patterns(self, engine):
        for _ in range(10):
            engine.record_action("frequent_action")
        stats = engine.get_stats()
        tops = stats.get("top_patterns", [])
        if tops:
            assert tops[0]["action"] == "frequent_action"


class TestEdgeCases:
    def test_clear_precomputed(self, engine):
        engine.precompute([{"action": "x", "score": 1, "probability": 1}])
        engine.clear_precomputed()
        assert not engine.was_precomputed("x")

    def test_history_window_limit(self, engine):
        small = PredictivePreCompute(history_window=10)
        for i in range(20):
            small.record_action(f"action-{i}")
        assert len(small._action_log) <= 10


class TestSingleton:
    def test_singleton(self):
        from src.core import predictive_precompute
        predictive_precompute._engine = None
        e1 = get_precompute_engine()
        e2 = get_precompute_engine()
        assert e1 is e2

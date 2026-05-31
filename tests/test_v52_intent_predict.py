"""v3.52 Intent Prediction v2 — tests"""
import pytest
import time
from src.core.intent_predict_v2 import (
    IntentPredictionEngine, IntentPrediction, IntentCategory,
    PredictionSource, get_intent_engine,
)

class TestIntentCategory:
    def test_classify_code(self):
        engine = IntentPredictionEngine()
        assert engine._classify_action("write code") == IntentCategory.CODE
        assert engine._classify_action("implement feature") == IntentCategory.CODE

    def test_classify_debug(self):
        engine = IntentPredictionEngine()
        assert engine._classify_action("fix bug") == IntentCategory.DEBUG
        assert engine._classify_action("debug crash") == IntentCategory.DEBUG

    def test_classify_deploy(self):
        engine = IntentPredictionEngine()
        assert engine._classify_action("deploy to production") == IntentCategory.DEPLOY

    def test_classify_unknown(self):
        engine = IntentPredictionEngine()
        assert engine._classify_action("hello world") == IntentCategory.UNKNOWN

class TestRecordAction:
    def test_record_updates_history(self):
        engine = IntentPredictionEngine()
        engine.record_action("write feature X", IntentCategory.CODE)
        assert len(engine._action_history) == 1

    def test_record_updates_temporal(self):
        engine = IntentPredictionEngine()
        for _ in range(3):
            engine.record_action("fix bug", IntentCategory.DEBUG)
        assert len(engine._temporal_patterns) > 0

    def test_record_builds_context_chain(self):
        engine = IntentPredictionEngine()
        engine.record_action("write code", IntentCategory.CODE)
        engine.record_action("test code", IntentCategory.TEST)
        engine.record_action("write code", IntentCategory.CODE)
        engine.record_action("test code", IntentCategory.TEST)
        assert len(engine._context_chains) > 0

class TestPrediction:
    def test_predict_empty(self):
        engine = IntentPredictionEngine()
        preds = engine.predict()
        assert isinstance(preds, list)

    def test_predict_after_records(self):
        engine = IntentPredictionEngine()
        for _ in range(5):
            engine.record_action("deploy app", IntentCategory.DEPLOY)
        preds = engine.predict()
        assert len(preds) > 0, "Should predict deploy at this time"

    def test_predict_respects_max(self):
        engine = IntentPredictionEngine()
        engine.config["max_predictions"] = 2
        for i in range(10):
            engine.record_action(f"action_{i}", IntentCategory.CODE)
        preds = engine.predict()
        assert len(preds) <= 2
    def test_contextual_prediction(self):
        engine = IntentPredictionEngine()
        for _ in range(5):
            engine.record_action("write function", IntentCategory.CODE)
            engine.record_action("run tests", IntentCategory.TEST)
        preds = engine.predict()
        # Should have at least one prediction from either temporal or contextual
        assert len(preds) > 0, f"Expected predictions, got none"

class TestMergePredictions:
    def test_merge_same_category(self):
        engine = IntentPredictionEngine()
        p1 = IntentPrediction(category=IntentCategory.CODE, confidence=0.5)
        p2 = IntentPrediction(category=IntentCategory.CODE, confidence=0.3)
        merged = engine._merge_predictions([p1, p2])
        assert len(merged) == 1
        assert merged[0].confidence > 0.5

    def test_merge_different_categories(self):
        engine = IntentPredictionEngine()
        p1 = IntentPrediction(category=IntentCategory.CODE, confidence=0.5)
        p2 = IntentPrediction(category=IntentCategory.DEBUG, confidence=0.3)
        merged = engine._merge_predictions([p1, p2])
        assert len(merged) == 2

class TestCrossAgent:
    def test_inject_signal(self):
        engine = IntentPredictionEngine()
        engine.inject_cross_agent_signal("CVE-2026 found", "security_profile")
        assert len(engine._cross_agent_signals) == 1

class TestWeights:
    def test_adjust_weights(self):
        engine = IntentPredictionEngine()
        old = engine._weights[PredictionSource.TEMPORAL]
        engine.adjust_weights(PredictionSource.TEMPORAL, 0.1)
        assert engine._weights[PredictionSource.TEMPORAL] != old

    def test_weights_normalized(self):
        engine = IntentPredictionEngine()
        total = sum(engine._weights.values())
        assert abs(total - 1.0) < 0.01

class TestStats:
    def test_get_stats(self):
        engine = IntentPredictionEngine()
        engine.record_action("test", IntentCategory.TEST)
        stats = engine.get_stats()
        assert stats["action_history"] == 1
        assert "weights" in stats

class TestSingleton:
    def test_singleton(self):
        e1 = get_intent_engine()
        e2 = get_intent_engine()
        assert e1 is e2

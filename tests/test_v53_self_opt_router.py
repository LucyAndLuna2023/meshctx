"""v3.53 Self-Optimizing Router — tests"""
import pytest
from src.core.self_opt_router import SelfOptimizingRouter, ModelPerformance, get_self_opt_router

class TestModelPerformance:
    def test_success_rate(self):
        mp = ModelPerformance(model_name="test", total_calls=10, success=8)
        assert mp.success_rate == 0.8

    def test_health_score(self):
        mp = ModelPerformance(model_name="test", total_calls=10, success=10)
        score = mp.health_score
        assert 50 <= score <= 100

class TestRouter:
    def test_record_call(self):
        r = SelfOptimizingRouter()
        r.record_call("deepseek-chat", "code", True, 500, 0.001)
        assert "deepseek-chat" in r._performances
        assert r._performances["deepseek-chat"].total_calls == 1

    def test_routing_rule_creation(self):
        r = SelfOptimizingRouter()
        for _ in range(10):
            r.record_call("deepseek-chat", "code", True, 300, 0.001)
        assert "code" in r._routing_rules

    def test_route_simple(self):
        r = SelfOptimizingRouter()
        r.record_call("deepseek-chat", "code", True, 300, 0.001)
        model = r.route("code")
        assert isinstance(model, str)

    def test_route_simple_complexity(self):
        r = SelfOptimizingRouter()
        for _ in range(5):
            r.record_call("gpt-4o-mini", "chat", True, 200, 0.01)
        model = r.route("chat", complexity="simple")
        assert model is not None

    def test_exclusion_on_failures(self):
        r = SelfOptimizingRouter()
        r._consecutive_fail_threshold = 2
        r.record_call("bad-model", "code", False, 5000, 0, "TIMEOUT")
        r.record_call("bad-model", "code", False, 5000, 0, "TIMEOUT")
        assert "bad-model" in r._excluded_models

    def test_recovery_on_success(self):
        r = SelfOptimizingRouter()
        r._consecutive_fail_threshold = 2
        r.record_call("flaky", "code", False, 5000, 0, "TIMEOUT")
        r.record_call("flaky", "code", False, 5000, 0, "TIMEOUT")
        assert "flaky" in r._excluded_models
        r.record_call("flaky", "code", True, 100, 0.001)
        assert "flaky" not in r._excluded_models

    def test_get_best_for_task(self):
        r = SelfOptimizingRouter()
        for _ in range(5):
            r.record_call("model-a", "code", True, 100, 0.001)
            r.record_call("model-b", "code", False, 5000, 0, "TIMEOUT")
        best = r.get_best_for_task("code")
        assert best is not None

    def test_fallback_when_all_excluded(self):
        r = SelfOptimizingRouter()
        r._consecutive_fail_threshold = 1
        r.record_call("only-model", "task", False, 100, 0, "error")
        model = r.route("task")
        assert model == "only-model" or model == "deepseek-v4-flash"

    def test_stats(self):
        r = SelfOptimizingRouter()
        r.record_call("deepseek-v4-flash", "code", True, 300, 0.001)
        stats = r.get_stats()
        assert stats["models_tracked"] == 1
        assert "deepseek-v4-flash" in stats["performances"]

    def test_empty_route(self):
        r = SelfOptimizingRouter()
        model = r.route("unknown_task")
        assert model == "deepseek-v4-flash"

    def test_singleton(self):
        r1 = get_self_opt_router()
        r2 = get_self_opt_router()
        assert r1 is r2

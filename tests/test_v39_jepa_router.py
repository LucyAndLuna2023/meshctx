"""
MeshCtx v3.39 — JEPA Smart Router Tests
"""
import pytest


class TestModelProfile:
    def test_profile_creation(self):
        from src.core.jepa_router import ModelProfile
        p = ModelProfile("test-model", "openai", 1.0, 2.0, 85, 100, 64000, ["coding"])
        assert p.name == "test-model"
        assert p.capability_score == 85
        assert "coding" in p.strengths


class TestJEPAModelRouter:
    def test_route_simple_query(self):
        from src.core.jepa_router import JEPAModelRouter, get_jepa_router
        router = get_jepa_router()
        result = router.route("hello world")
        assert "model" in result
        assert "cost_per_query_est" in result
        assert result["domain"] == "general"
    
    def test_route_coding_query(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        result = router.route("write a python function to sort a list")
        assert result["domain"] == "coding"
    
    def test_route_math_query(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        result = router.route("calculate the integral of x^2 from 0 to 1")
        assert result["domain"] == "math"
    
    def test_route_complex_query_prefers_capable(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        result = router.route("design a distributed system architecture for handling 1M requests per second with fault tolerance")
        # Complex queries need capable models
        assert result["capability_score"] >= 70
    
    def test_route_with_budget(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        result = router.route("hello", max_budget=0.001)
        assert "model" in result or "error" in result
    
    def test_stats_accumulate(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        before = router.total_routes
        router.route("test query 1")
        router.route("test query 2")
        assert router.total_routes == before + 2
    
    def test_get_stats(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        router.route("test")
        stats = router.get_stats()
        assert "total_routes" in stats
        assert "total_cost_saved" in stats
        assert "jepa_enabled" in stats
        assert stats["jepa_enabled"] is True
    
    def test_domain_detection(self):
        from src.core.jepa_router import JEPAModelRouter
        router = JEPAModelRouter()
        assert router._estimate_domain("write python code") == "coding"
        assert router._estimate_domain("calculate 2+2") == "math"
        assert router._estimate_domain("tell me a story") == "creative"
        assert router._estimate_domain("what time is it") == "general"
    
    def test_complexity_estimation(self):
        from src.core.jepa_router import JEPAModelRouter
        router = JEPAModelRouter()
        c1 = router._estimate_complexity("hello")
        c2 = router._estimate_complexity("design implement optimize refactor algorithm architecture")
        assert c2 > c1
    
    def test_record_outcome(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        router.route("test")
        router.record_outcome("deepseek-chat", True, 0.9)
        assert len(router.route_history) >= 1
    
    def test_free_model_available(self):
        from src.core.jepa_router import get_jepa_router
        router = get_jepa_router()
        # llama-4-scout is free
        free_exists = any(m.cost_per_1k_input == 0.0 for m in router.models.values())
        assert free_exists

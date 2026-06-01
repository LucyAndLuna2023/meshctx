"""
MeshCtx v3.66 — JEPA Router Tests
"""
import pytest
from src.core.jepa_router import JEPARouter, TaskEncoding


class TestTaskEncoding:
    def test_encoding_defaults(self):
        e = TaskEncoding()
        assert e.complexity == 0.5
        assert e.domain == "general"
        assert e.expected_tokens == 500


class TestJEPARouter:
    def test_router_init(self):
        router = JEPARouter()
        assert router is not None
        
    def test_encode_task(self):
        router = JEPARouter()
        e = router.encode_task("write a python function to sort a list")
        assert isinstance(e, TaskEncoding)
        assert e.complexity > 0
        
    def test_encode_coding_task(self):
        router = JEPARouter()
        e = router.encode_task("def quick_sort(arr):", domain="code")
        assert e.complexity > 0
        assert e.domain == "code"
        
    def test_predict_best_model(self):
        router = JEPARouter()
        model, score = router.predict_best_model("hello world")
        assert isinstance(model, str)
        assert isinstance(score, float)
        
    def test_predict_coding_prefers_code_model(self):
        router = JEPARouter()
        model, score = router.predict_best_model("write a python decorator", domain="code")
        assert isinstance(model, str)
        
    def test_predict_with_budget(self):
        router = JEPARouter()
        model, score = router.predict_best_model("summarize this article", max_cost=0.20)
        assert isinstance(model, str)
        
    def test_get_stats(self):
        router = JEPARouter()
        stats = router.get_stats()
        assert isinstance(stats, dict)
        assert "models" in stats

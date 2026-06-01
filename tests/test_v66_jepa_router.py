"""v3.66 JEPA Router — tests"""
import pytest
from src.core.jepa_router import JEPARouter, TaskEncoding, get_jepa_router

class TestJEPA:
    def test_encode_complex(self):
        r = JEPARouter()
        e = r.encode_task("implement authentication system")
        assert e.complexity > 0.5

    def test_encode_simple(self):
        r = JEPARouter()
        e = r.encode_task("check status")
        assert e.complexity < 0.6

    def test_predict_code(self):
        r = JEPARouter()
        model, conf = r.predict_best_model("write a Python function", "code")
        assert model in r._model_registry
        assert 0 < conf <= 1.0

    def test_predict_with_budget(self):
        r = JEPARouter()
        model, _ = r.predict_best_model("complex analysis", "analysis", max_cost=1.0)
        assert r._model_registry[model]["cost"] <= 1.0

    def test_stats(self):
        r = JEPARouter()
        r.predict_best_model("test", "general")
        s = r.get_stats()
        assert s["predictions"] >= 1

    def test_singleton(self):
        assert get_jepa_router() is get_jepa_router()

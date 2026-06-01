"""v3.67 Model Compare — tests"""
import pytest
from src.core.model_compare import ModelCompareEngine, ModelResponse, get_compare_engine

def fake_exec(prompt, model):
    return f"[{model}] {prompt[:20]}"

class TestCompare:
    def test_compare(self):
        e = ModelCompareEngine()
        result = e.compare("test prompt", executor=fake_exec)
        assert len(result.responses) >= 3

    def test_score(self):
        e = ModelCompareEngine()
        responses = [
            ModelResponse(model="a",response="hi",latency_ms=100),
            ModelResponse(model="b",response="hello world",latency_ms=500,error="timeout")
        ]
        scored = e.score_responses(responses)
        assert scored[0].score >= scored[-1].score

    def test_singleton(self):
        assert get_compare_engine() is get_compare_engine()

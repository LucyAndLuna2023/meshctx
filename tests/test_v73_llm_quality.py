"""v3.73 LLM Quality — tests"""
import pytest
from src.core.llm_quality import LLMQualityEvaluator, get_quality_evaluator

class TestQuality:
    def test_evaluate_good(self):
        e = LLMQualityEvaluator()
        s = e.evaluate("What is Python?", "Python is a programming language used for web development, data science, and AI.")
        assert s.overall > 0.3

    def test_evaluate_empty(self):
        e = LLMQualityEvaluator()
        s = e.evaluate("test", "")
        assert s.overall < 0.5

    def test_compare(self):
        e = LLMQualityEvaluator()
        results = e.compare_models("test", {"a":"hello world","b":"hi"})
        assert "a" in results

    def test_singleton(self):
        assert get_quality_evaluator() is get_quality_evaluator()

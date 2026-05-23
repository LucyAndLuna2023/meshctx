"""v2.73 Cross Validator — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def cv():
    from src.core.cross_validator import CrossValidator
    return CrossValidator(min_agents=2)


@pytest.fixture
def agree_responses():
    from src.core.cross_validator import AgentResponse
    return [
        AgentResponse(agent_id="A", model="deepseek", answer="答案是42。Python是一种高级编程语言。", confidence=0.9),
        AgentResponse(agent_id="B", model="claude", answer="答案是42。Python是高级编程语言。", confidence=0.85),
        AgentResponse(agent_id="C", model="gpt", answer="答案是42。Python是一种高级语言。", confidence=0.92),
    ]

@pytest.fixture
def disagree_responses():
    from src.core.cross_validator import AgentResponse
    return [
        AgentResponse(agent_id="A", model="deepseek", answer="答案是42", confidence=0.5),
        AgentResponse(agent_id="B", model="claude", answer="答案是100", confidence=0.4),
        AgentResponse(agent_id="C", model="gpt", answer="没有答案", confidence=0.3),
    ]


class TestSimilarity:
    def test_identical(self, cv):
        sim = cv._compute_similarity("hello world", "hello world")
        assert sim > 0.9

    def test_different(self, cv):
        sim = cv._compute_similarity("hello world", "goodbye moon")
        assert sim < 0.5

    def test_similar_meaning(self, cv):
        sim = cv._compute_similarity(
            "Python is a programming language",
            "Python is a high-level programming language"
        )
        assert sim > 0.4


class TestValidation:
    def test_full_agreement(self, cv, agree_responses):
        result = cv.validate("什么是Python?", agree_responses)
        assert result.consensus.value in ("full", "high")
        assert result.hallucination_risk < 0.5

    def test_divergent(self, cv, disagree_responses):
        result = cv.validate("答案是什么?", disagree_responses)
        assert result.consensus.value in ("partial", "divergent")
        assert result.hallucination_risk > 0.2

    def test_insufficient_agents(self, cv):
        from src.core.cross_validator import AgentResponse
        result = cv.validate("test", [AgentResponse(agent_id="A", model="test", answer="ok")])
        assert "需要至少" in result.summary

    def test_generates_summary(self, cv, agree_responses):
        result = cv.validate("test", agree_responses)
        assert result.summary != ""

    def test_fact_markers(self, cv, agree_responses):
        result = cv.validate("test", agree_responses)
        assert "hallucination_signals" in result.fact_check_results


class TestCoreExtraction:
    def test_extract_removes_code(self, cv):
        core = cv._extract_core("答案是42 ```python\nprint('hello')\n``` 结束")
        assert "```" not in core
        assert "结束" in core


class TestStats:
    def test_stats(self, cv, agree_responses):
        cv.validate("test", agree_responses)
        stats = cv.get_stats()
        assert stats["total_validations"] >= 1

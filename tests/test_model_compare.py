"""
v3.87 Model Compare Blind Test — 测试用例

验证:
  1. 并行多模型对比
  2. 盲测匿名评分
  3. 三维评分 (速度/质量/成本)
  4. 排行榜排名
  5. 错误处理降级
  6. 单例模式
  7. 完整管线
  8. 权重可配置
  9. 向后兼容
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Fake Executor for Testing ──────────────────────────────

import time as _time

_model_latencies = {
    "fast-model": 0.02,
    "mid-model": 0.05,
    "slow-model": 0.15,
    "deepseek-chat": 0.03,
    "gpt-4o-mini": 0.06,
    "claude-3-haiku": 0.04,
}


def fake_exec(prompt, model):
    """Simulate model execution with varying latency and response length."""
    delay = _model_latencies.get(model, 0.05)
    _time.sleep(delay)
    # Different models give different length/quality responses
    templates = {
        "fast-model": f"[{model}] Short answer to: {prompt[:30]}",
        "mid-model": f"[{model}] Detailed response addressing: {prompt[:50]}. "
                     "Here is a comprehensive analysis with multiple perspectives "
                     "and thorough examination of the topic at hand.",
        "slow-model": f"[{model}] Very comprehensive and thoughtful response to: "
                      f"{prompt[:50]}. This includes detailed analysis, examples, "
                      "and citations that make the answer particularly useful.",
        "deepseek-chat": f"[{model}] Complete answer: {prompt[:40]}. "
                         "The key insight is that we need to consider multiple "
                         "factors including context, intent, and constraints.",
        "gpt-4o-mini": f"[{model}] Response: {prompt[:45]}. "
                       "Based on the available information, the answer involves "
                       "several important considerations worth exploring.",
        "claude-3-haiku": f"[{model}] Answer to '{prompt[:35]}': "
                          "I'll provide a thorough analysis. First, let's examine "
                          "the core elements, then we can draw conclusions.",
    }
    return templates.get(model, f"[{model}] default response to: {prompt[:40]}")


def fake_exec_with_error(prompt, model):
    """Simulate a model that always fails."""
    if model == "broken-model":
        raise RuntimeError("Simulated API failure")
    return fake_exec(prompt, model)


# ── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def engine():
    from src.core.model_compare import ModelCompareEngine
    return ModelCompareEngine(max_workers=5)


@pytest.fixture
def engine_no_blind():
    from src.core.model_compare import ModelCompareEngine
    return ModelCompareEngine(max_workers=5, blind=False)


# ═══════════════════════════════════════════════════════════
# Test Cases
# ═══════════════════════════════════════════════════════════


class TestParallelCompare:
    """Test 1: 并行多模型对比"""

    def test_parallel_execution(self, engine):
        models = ["fast-model", "mid-model", "slow-model"]
        result = engine.compare("What is AI?", models=models, executor=fake_exec)
        assert result.model_count == 3
        assert len(result.responses) == 3
        # Parallel should be faster than sum of individual latencies
        assert result.total_time_ms < 500  # Should complete quickly in parallel

    def test_sequential_execution(self, engine):
        models = ["fast-model", "mid-model", "slow-model"]
        result = engine.compare(
            "What is AI?", models=models, executor=fake_exec, parallel=False
        )
        assert result.model_count == 3
        assert len(result.responses) == 3

    def test_all_models_returned(self, engine):
        models = ["deepseek-chat", "gpt-4o-mini", "claude-3-haiku"]
        result = engine.compare("Explain quantum computing", models=models,
                                executor=fake_exec)
        returned_models = {r.model for r in result.responses}
        assert returned_models == set(models)

    def test_no_models_returns_empty(self, engine):
        result = engine.compare("test", models=[], executor=fake_exec)
        assert result.model_count == 0
        assert len(result.responses) == 0

    def test_empty_prompt_handled(self, engine):
        result = engine.compare("", models=["fast-model"], executor=fake_exec)
        assert result.model_count == 1
        assert len(result.responses) == 0


class TestBlindTesting:
    """Test 2: 盲测匿名评分"""

    def test_blind_ids_assigned(self, engine):
        models = ["fast-model", "mid-model", "slow-model"]
        result = engine.compare("Test prompt", models=models, executor=fake_exec,
                                blind=True)
        for r in result.responses:
            assert r.blind_id, f"Model {r.model} missing blind_id"
            assert r.blind_id.startswith("Model-")

    def test_blind_ids_are_unique(self, engine):
        models = ["a", "b", "c"]
        result = engine.compare("Test", models=models, executor=fake_exec, blind=True)
        blind_ids = [r.blind_id for r in result.responses]
        assert len(blind_ids) == len(set(blind_ids)), "Blind IDs must be unique"

    def test_blind_disabled_no_ids(self, engine_no_blind):
        models = ["fast-model", "mid-model"]
        result = engine_no_blind.compare(
            "Test", models=models, executor=fake_exec, blind=False
        )
        for r in result.responses:
            assert r.blind_id == ""

    def test_reveal_blind_mapping(self, engine):
        models = ["deepseek-chat", "gpt-4o-mini", "claude-3-haiku"]
        result = engine.compare("Test", models=models, executor=fake_exec, blind=True)
        mapping = engine.reveal_blind_mapping(result.responses)
        assert len(mapping) == 3
        for r in result.responses:
            assert mapping[r.blind_id] == r.model


class TestScoringDimensions:
    """Test 3: 三维评分 (速度/质量/成本)"""

    def test_speed_scoring(self, engine):
        models = ["fast-model", "slow-model"]
        result = engine.compare("Test speed", models=models, executor=fake_exec)
        scored = result.leaderboard
        fast_model = next(r for r in scored if r.model == "fast-model")
        slow_model = next(r for r in scored if r.model == "slow-model")
        # Faster model should score higher on speed
        assert fast_model.speed_score > slow_model.speed_score, (
            f"Fast: {fast_model.speed_score}, Slow: {slow_model.speed_score}"
        )

    def test_quality_scoring(self, engine):
        models = ["fast-model", "mid-model"]  # mid-model gives longer response
        result = engine.compare("Tell me about AI in detail",
                                models=models, executor=fake_exec)
        scored = result.leaderboard
        # mid-model gives longer/detailed response → higher quality
        mid = next(r for r in scored if r.model == "mid-model")
        fast = next(r for r in scored if r.model == "fast-model")
        assert mid.quality_score >= fast.quality_score, (
            f"Mid quality: {mid.quality_score}, Fast quality: {fast.quality_score}"
        )

    def test_cost_scoring(self, engine):
        models = ["fast-model", "mid-model"]
        result = engine.compare("Test cost", models=models, executor=fake_exec)
        for r in result.responses:
            assert r.cost_score >= 0.0
            assert r.cost_score <= 100.0

    def test_overall_score_in_range(self, engine):
        models = ["deepseek-chat", "gpt-4o-mini", "claude-3-haiku"]
        result = engine.compare("Test scoring", models=models, executor=fake_exec)
        for r in result.responses:
            if not r.error:
                assert 0.0 <= r.score <= 100.0, f"{r.model} score={r.score} out of range"

    def test_error_models_score_zero(self, engine):
        models = ["broken-model", "fast-model"]
        result = engine.compare("Test", models=models, executor=fake_exec_with_error)
        broken = next(r for r in result.responses if r.model == "broken-model")
        assert broken.score == 0.0
        assert broken.speed_score == 0.0
        assert broken.error != ""


class TestLeaderboard:
    """Test 4: 排行榜排名"""

    def test_leaderboard_sorted_by_score(self, engine):
        models = ["fast-model", "mid-model", "slow-model"]
        result = engine.compare("Rank test", models=models, executor=fake_exec)
        board = result.leaderboard
        assert len(board) == 3
        scores = [r.score for r in board]
        assert scores == sorted(scores, reverse=True), f"Not sorted: {scores}"

    def test_leaderboard_from_history(self, engine):
        engine.compare("First test", models=["fast-model"], executor=fake_exec)
        engine.compare("Second test", models=["mid-model"], executor=fake_exec)
        board = engine.get_leaderboard()
        assert len(board) == 1  # Latest result only
        assert board[0].model == "mid-model"

    def test_format_leaderboard(self, engine):
        result = engine.compare("Format test", models=["fast-model", "mid-model"],
                                executor=fake_exec)
        formatted = engine.format_leaderboard()
        assert "Leaderboard" in formatted
        assert "Rank" in formatted

    def test_format_leaderboard_blind(self, engine):
        result = engine.compare("Blind format", models=["fast-model", "mid-model"],
                                executor=fake_exec, blind=True)
        formatted = engine.format_leaderboard(blind=True)
        # In blind mode, real model names should NOT appear
        for r in result.responses:
            assert r.model not in formatted.split("Model-")[0] if formatted else True


class TestErrorHandling:
    """Test 5: 错误处理降级"""

    def test_mixed_errors_and_success(self, engine):
        models = ["broken-model", "fast-model", "mid-model"]
        result = engine.compare("Mixed test", models=models,
                                executor=fake_exec_with_error)
        assert result.error_count == 1
        assert len(result.leaderboard) == 3
        # Broken model should be last (score=0)
        assert result.leaderboard[-1].model == "broken-model"

    def test_all_models_error(self, engine):
        def always_fail(prompt, model):
            raise RuntimeError("All failed")

        result = engine.compare("All fail", models=["a", "b"], executor=always_fail)
        assert result.error_count == 2
        for r in result.responses:
            assert r.error
            assert r.score == 0.0

    def test_executor_none_fallback(self, engine):
        """No executor provided — should use simulated response fallback."""
        result = engine.compare("Fallback test", models=["deepseek-chat"])
        assert result.error_count == 0
        assert len(result.responses) == 1
        assert "simulated" in result.responses[0].response.lower()


class TestSingleton:
    """Test 6: 单例模式"""

    def test_singleton_same_instance(self):
        from src.core.model_compare import get_compare_engine
        e1 = get_compare_engine()
        e2 = get_compare_engine()
        assert e1 is e2


class TestFullPipeline:
    """Test 7: 完整管线 compare_and_rank"""

    def test_compare_and_rank(self, engine):
        result = engine.compare_and_rank(
            "Full pipeline test",
            models=["fast-model", "mid-model", "slow-model"],
            executor=fake_exec,
        )
        assert result.model_count == 3
        assert len(result.leaderboard) == 3
        assert result.leaderboard[0].score >= result.leaderboard[-1].score

    def test_get_stats(self, engine):
        engine.compare("Stats test", models=["fast-model"], executor=fake_exec)
        stats = engine.get_stats()
        assert stats["comparisons"] >= 1
        assert "scoring_weights" in stats
        assert "blind_enabled" in stats
        assert "parallel_enabled" in stats

    def test_get_history(self, engine):
        engine.compare("H1", models=["fast-model"], executor=fake_exec)
        engine.compare("H2", models=["mid-model"], executor=fake_exec)
        history = engine.get_history()
        assert len(history) >= 2


class TestWeightsConfigurable:
    """Test 8: 权重可配置"""

    def test_custom_weights(self):
        from src.core.model_compare import ModelCompareEngine
        custom = ModelCompareEngine(
            scoring_weights={"speed": 0.8, "quality": 0.1, "cost": 0.1}
        )
        assert custom.weights["speed"] > 0.7

    def test_weight_normalization(self):
        from src.core.model_compare import ModelCompareEngine
        custom = ModelCompareEngine(
            scoring_weights={"speed": 80, "quality": 10, "cost": 10}
        )
        total = sum(custom.weights.values())
        assert abs(total - 1.0) < 0.01, f"Weights not normalized: {custom.weights}"


class TestBackwardCompat:
    """Test 9: 向后兼容"""

    def test_compare_models_function(self):
        from src.core.model_compare import compare_models
        responses = compare_models("Backward compat test",
                                   models=["fast-model"], executor=fake_exec)
        assert isinstance(responses, list)
        assert len(responses) == 1

    def test_compare_models_stream_function(self):
        from src.core.model_compare import compare_models_stream
        responses = compare_models_stream("Stream test",
                                          models=["mid-model"], executor=fake_exec)
        assert isinstance(responses, list)
        assert len(responses) == 1


class TestModelRegistry:
    """Test 10: 模型注册表"""

    def test_list_known_models(self, engine):
        models = engine.list_known_models()
        assert len(models) >= 20
        assert "deepseek-v4-flash" in models
        assert "gpt-4o-mini" in models
        assert "claude-sonnet-4-latest" in models

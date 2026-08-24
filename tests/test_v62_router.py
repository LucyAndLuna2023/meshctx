"""v2.62 Smart Model Router — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def router():
    from src.core.smart_router import SmartModelRouter, get_model_router
    return SmartModelRouter()


class TestComplexityEstimation:
    @pytest.mark.parametrize("prompt,expected_min", [
        ("答案是42", 1),  # TRIVIAL
        ("hello world", 1),
        ("什么是Python", 1),  # 太短，TRIVIAL
        ("解释一下深度学习", 3),  # MODERATE — "解释"信号触发
        ("帮我重构这段代码并优化性能", 3),  # 短重构→MODERATE
        ("设计一个分布式微服务架构包含负载均衡", 4),  # COMPLEX
        ("implement a multi-agent system", 4),
        ("从零设计", 5),
        ("python sql query example", 2),
    ])
    def test_complexity_estimation(self, router, prompt, expected_min):
        complexity = router.estimate_complexity(prompt)
        assert complexity.value >= expected_min, \
            f"'{prompt}' 复杂度应该 >= {expected_min}, 实际 {complexity}"

    def test_long_prompt_higher_complexity(self, router):
        short = router.estimate_complexity("hi")
        long_prompt = "架构设计 " * 500
        long = router.estimate_complexity(long_prompt)
        assert long.value >= short.value

    def test_trivial_questions(self, router):
        from src.core.smart_router import TaskComplexity
        assert router.estimate_complexity("yes") == TaskComplexity.TRIVIAL
        assert router.estimate_complexity("no thanks") == TaskComplexity.TRIVIAL


class TestModelRouting:
    def test_budget_task_uses_budget_model(self, router):
        decision = router.route("hello world", "chat")
        assert decision.selected_model != ""
        model = router._DEFAULT_MODELS.get(decision.selected_model)
        assert model is not None
        # BUDGET tier应该选便宜的
        assert model.tier.value <= 2

    def test_complex_task_uses_premium(self, router):
        decision = router.route(
            "设计一个分布式微服务架构，包含负载均衡、服务发现、容错机制",
            "architecture"
        )
        assert decision.complexity.value >= 4

    def test_route_returns_reasoning(self, router):
        decision = router.route("帮我写一个排序算法", "code")
        assert "任务复杂度" in decision.reasoning
        assert decision.selected_model in decision.reasoning

    def test_fallback_model_different(self, router):
        decision = router.route("复杂的人工智能系统设计", "architecture")
        assert decision.fallback_model != ""

    def test_preferred_provider(self, router):
        decision = router.route(
            "写一个函数", "code",
            preferred_provider="anthropic"
        )
        model = router._DEFAULT_MODELS.get(decision.selected_model)
        assert model is not None
        assert model.provider == "anthropic"


class TestUsageTracking:
    def test_record_usage_updates_stats(self, router):
        router.record_usage("deepseek-v4-flash", "chat", 1000, 500, 200.0)
        stats = router._stats["deepseek-v4-flash"]
        assert stats["calls"] == 1
        assert stats["total_tokens"] == 1500
        assert stats["total_cost"] > 0

    def test_multiple_records_aggregate(self, router):
        for _ in range(5):
            router.record_usage("deepseek-v4-flash", "chat", 200, 100, 50.0)
        assert router._stats["deepseek-v4-flash"]["calls"] == 5

    def test_cost_calculation(self, router):
        router.record_usage("gpt-4o", "code", 10000, 5000, 1000.0)
        cost = router._stats["gpt-4o"]["total_cost"]
        # gpt-4o: 2.5/1k input + 10/1k output
        expected = (10000/1000)*2.5 + (5000/1000)*10.0
        assert abs(cost - expected) < 0.01


class TestUsageReport:
    def test_empty_report(self, router):
        report = router.get_usage_report()
        assert report["total_calls"] == 0
        assert report["total_cost_usd"] == 0

    def test_report_after_usage(self, router):
        router.record_usage("deepseek-chat", "chat", 5000, 2000, 100.0)
        router.record_usage("claude-sonnet-4", "code", 8000, 4000, 500.0)
        report = router.get_usage_report()
        assert report["total_calls"] == 2
        assert report["total_cost_usd"] > 0
        assert len(report["by_model"]) == 2
        assert len(report["by_task"]) == 2

    def test_optimization_tips(self, router):
        # 过度使用高级模型
        for _ in range(20):
            router.record_usage("claude-opus-4", "chat", 1000, 500, 0.1)
        tips = router.get_optimization_tips()
        assert len(tips) > 0, "应该给出优化建议"


class TestBudgetControl:
    def test_budget_cap_unlimited(self, router):
        assert router.can_afford(1000.0) is True

    def test_budget_cap_enforced(self, router):
        router.set_budget(1.0)
        router._spent_today = 0.9
        assert router.can_afford(0.05) is True
        assert router.can_afford(0.2) is False

    def test_budget_in_report(self, router):
        router.set_budget(10.0)
        router.record_usage("deepseek-chat", "chat", 1000, 500, 0)
        report = router.get_usage_report()
        assert report["budget_cap"] == 10.0


class TestModelInfo:
    def test_all_models_have_cost(self, router):
        for model_id, info in router._DEFAULT_MODELS.items():
            assert info.cost_per_1k_input > 0, \
                f"{model_id} 缺少input价格"
            assert info.cost_per_1k_output > 0, \
                f"{model_id} 缺少output价格"

    def test_model_count(self, router):
        assert len(router._DEFAULT_MODELS) >= 10

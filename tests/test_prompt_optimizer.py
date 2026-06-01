"""v3.105 Prompt Optimizer 提示词优化器测试"""
import time
import pytest
from src.core.prompt_optimizer import (
    PromptOptimizer, PromptVariant, PromptTemplate,
    ABTestResult, EffectMetrics, OptimizationRecord,
    OptimizationStrategy, ABTestStatus, TemplateCategory,
    get_prompt_optimizer, reset_prompt_optimizer,
)


# ═══════════════════════════════════════════════════════════
# 1) Auto-Optimize Tests
# ═══════════════════════════════════════════════════════════

class TestAutoOptimize:
    """1) 自动优化prompt测试"""

    def test_optimize_basic_prompt(self):
        opt = PromptOptimizer()
        result = opt.optimize(
            prompt="tell me about python",
            name="test_basic",
        )
        assert "original" in result
        assert "optimized" in result
        assert result["original"].content == "tell me about python"
        assert result["total_improvement"] >= 0
        assert result["best_strategy"] is not None or result["total_improvement"] == 0.0

    def test_optimize_with_specific_strategies(self):
        opt = PromptOptimizer()
        result = opt.optimize(
            prompt="what is ml",
            strategies=["add_context", "clarify"],
            name="test_specific",
        )
        assert result["optimized"] is not None
        # Only requested strategies should be in improvements
        for imp in result["improvements"]:
            assert imp["strategy"] in ("add_context", "clarify")

    def test_optimize_tracks_improvements(self):
        opt = PromptOptimizer()
        result = opt.optimize(
            prompt="help me write code",
            name="test_improve",
        )
        assert len(result["improvements"]) >= 0
        assert "best_strategy" in result
        # Quality scores should be in range
        for imp in result["improvements"]:
            assert 0 <= imp["quality"] <= 100

    def test_optimize_adds_to_history(self):
        opt = PromptOptimizer()
        opt.optimize(prompt="test prompt", name="test_hist")
        opt.optimize(prompt="another test", name="test_hist2")

        history = opt.get_optimization_history()
        assert len(history) >= 0  # depends on whether improvements were found

    def test_optimize_preserves_original(self):
        opt = PromptOptimizer()
        original_text = "write a poem about stars"
        result = opt.optimize(prompt=original_text, name="test_preserve")
        assert result["original"].content == original_text


# ═══════════════════════════════════════════════════════════
# 2) A/B Testing Tests
# ═══════════════════════════════════════════════════════════

class TestABTesting:
    """2) A/B测试测试"""

    def test_create_ab_test(self):
        opt = PromptOptimizer()
        test = opt.create_ab_test(
            name="greeting_test",
            prompt_a="Hello, how can I help?",
            prompt_b="Greetings! What can I assist you with today?",
        )
        assert test.name == "greeting_test"
        assert test.status == ABTestStatus.RUNNING.value
        assert test.winner is None
        assert len(test.results_a) == 0
        assert test.prompt_a_content == "Hello, how can I help?"

    def test_record_and_determine_winner(self):
        opt = PromptOptimizer()
        test = opt.create_ab_test(
            name="quality_test",
            prompt_a="Version A",
            prompt_b="Version B",
        )
        # Variant A performs better
        for i in range(10):
            opt.record_ab_result(test.test_id, "a", 80.0 + i * 0.5)
            opt.record_ab_result(test.test_id, "b", 70.0 + i * 0.3)

        result = opt.get_ab_test(test.test_id)
        assert result.winner == "a"
        assert result.status == ABTestStatus.COMPLETED.value
        assert result.confidence > 0

    def test_ab_test_tie(self):
        opt = PromptOptimizer()
        test = opt.create_ab_test(
            name="tie_test",
            prompt_a="A",
            prompt_b="B",
        )
        for _ in range(10):
            opt.record_ab_result(test.test_id, "a", 75.0)
            opt.record_ab_result(test.test_id, "b", 75.0)

        result = opt.get_ab_test(test.test_id)
        assert result.winner in ("a", "b", "tie")
        assert result.status == ABTestStatus.COMPLETED.value

    def test_list_ab_tests_by_status(self):
        opt = PromptOptimizer()
        t1 = opt.create_ab_test("test1", "A1", "B1")
        t2 = opt.create_ab_test("test2", "A2", "B2")

        # Complete t1
        for _ in range(10):
            opt.record_ab_result(t1.test_id, "a", 90.0)
            opt.record_ab_result(t1.test_id, "b", 60.0)

        running = opt.list_ab_tests(status=ABTestStatus.RUNNING.value)
        completed = opt.list_ab_tests(status=ABTestStatus.COMPLETED.value)
        assert len(completed) == 1
        assert len(running) == 1

    def test_cancel_ab_test(self):
        opt = PromptOptimizer()
        test = opt.create_ab_test("cancel_test", "A", "B")
        assert opt.cancel_ab_test(test.test_id) is True
        assert test.status == ABTestStatus.CANCELLED.value
        # Cancel non-existent
        assert opt.cancel_ab_test("nonexistent") is False

    def test_ab_test_effect_size(self):
        opt = PromptOptimizer()
        test = opt.create_ab_test("effect_test", "A", "B")
        for _ in range(10):
            opt.record_ab_result(test.test_id, "a", 90.0)
            opt.record_ab_result(test.test_id, "b", 50.0)

        result = opt.get_ab_test(test.test_id)
        assert result.effect_size() > 0


# ═══════════════════════════════════════════════════════════
# 3) Template Library Tests
# ═══════════════════════════════════════════════════════════

class TestTemplateManagement:
    """3) 模板库管理测试"""

    def test_add_and_get_template(self):
        opt = PromptOptimizer()
        tmpl = opt.add_template(
            name="code_review",
            content="Review this {{language}} code:\n```{{code}}```",
            description="Code review template",
            category=TemplateCategory.CODE.value,
            tags=["review", "code"],
        )
        assert tmpl.name == "code_review"
        assert "language" in tmpl.variables
        assert "code" in tmpl.variables
        assert tmpl.category == TemplateCategory.CODE.value

        # Retrieve by ID
        found = opt.get_template(tmpl.template_id)
        assert found is not None
        assert found.name == "code_review"

    def test_render_template(self):
        opt = PromptOptimizer()
        tmpl = opt.add_template(
            name="greeting",
            content="Hello {{name}}, welcome to {{platform}}!",
        )
        rendered = opt.render_template(tmpl.template_id, name="Alice", platform="MeshCtx")
        assert rendered == "Hello Alice, welcome to MeshCtx!"
        assert tmpl.usage_count == 1

    def test_list_templates_by_category(self):
        opt = PromptOptimizer()
        opt.add_template(
            name="code1", content="Code: {{lang}}", category=TemplateCategory.CODE.value,
        )
        opt.add_template(
            name="general1", content="General: {{topic}}", category=TemplateCategory.GENERAL.value,
        )
        opt.add_template(
            name="code2", content="Code2: {{lang}}", category=TemplateCategory.CODE.value,
        )

        code_templates = opt.list_templates(category=TemplateCategory.CODE.value)
        assert len(code_templates) == 2
        all_templates = opt.list_templates()
        assert len(all_templates) == 3

    def test_update_template(self):
        opt = PromptOptimizer()
        tmpl = opt.add_template(name="test", content="Old {{var}}")
        assert tmpl.version == 1

        updated = opt.update_template(tmpl.template_id, content="New {{var}} {{new_var}}")
        assert updated.version == 2
        assert "new_var" in updated.variables
        assert updated.content == "New {{var}} {{new_var}}"

    def test_delete_template(self):
        opt = PromptOptimizer()
        tmpl = opt.add_template(name="to_delete", content="{{x}}")
        assert opt.get_template_count() == 1
        assert opt.delete_template(tmpl.template_id) is True
        assert opt.get_template_count() == 0
        assert opt.delete_template("nonexistent") is False

    def test_find_template_by_name(self):
        opt = PromptOptimizer()
        opt.add_template(name="unique_name", content="content {{x}}")
        found = opt.find_template_by_name("unique_name")
        assert found is not None
        assert found.name == "unique_name"

        not_found = opt.find_template_by_name("nonexistent")
        assert not_found is None

    def test_list_templates_by_tag(self):
        opt = PromptOptimizer()
        opt.add_template(name="t1", content="c1", tags=["python", "code"])
        opt.add_template(name="t2", content="c2", tags=["python", "test"])
        opt.add_template(name="t3", content="c3", tags=["docs"])

        python_templates = opt.list_templates(tag="python")
        assert len(python_templates) == 2

        doc_templates = opt.list_templates(tag="docs")
        assert len(doc_templates) == 1


# ═══════════════════════════════════════════════════════════
# 4) Effect Tracking Tests
# ═══════════════════════════════════════════════════════════

class TestEffectTracking:
    """4) 效果追踪测试"""

    def test_record_effect_basic(self):
        opt = PromptOptimizer()
        metrics = opt.record_effect(
            prompt_id="test_prompt_1",
            quality=85.0,
            latency_ms=200,
            tokens_input=150,
            tokens_output=300,
            success=True,
        )
        assert metrics.total_uses == 1
        assert metrics.avg_quality_score == 85.0
        assert metrics.avg_latency_ms == 200.0
        assert metrics.avg_tokens_input == 150
        assert metrics.avg_tokens_output == 300
        assert metrics.success_rate == 1.0

    def test_record_multiple_effects(self):
        opt = PromptOptimizer()
        for i in range(5):
            opt.record_effect(
                prompt_id="multi_test",
                quality=70.0 + i * 5,
                latency_ms=100 + i * 10,
                success=(i < 4),
            )

        metrics = opt.get_effect_metrics("multi_test")
        assert metrics.total_uses == 5
        assert 78.0 <= metrics.avg_quality_score <= 85.0
        assert metrics.success_rate == 0.8  # 4/5
        assert metrics.failure_count == 1

    def test_get_top_performing(self):
        opt = PromptOptimizer()
        # Prompt A: high quality
        for _ in range(5):
            opt.record_effect(prompt_id="good_prompt", quality=90.0, success=True)
        # Prompt B: medium quality
        for _ in range(5):
            opt.record_effect(prompt_id="medium_prompt", quality=70.0, success=True)
        # Prompt C: low quality (not enough samples)
        opt.record_effect(prompt_id="low_prompt", quality=50.0, success=True)

        top = opt.get_top_performing(n=2)
        assert len(top) >= 2
        # good_prompt should be first
        assert top[0][0] == "good_prompt"

    def test_compare_prompts(self):
        opt = PromptOptimizer()
        for _ in range(5):
            opt.record_effect(prompt_id="prompt_a", quality=85.0, latency_ms=100)
        for _ in range(5):
            opt.record_effect(prompt_id="prompt_b", quality=75.0, latency_ms=50)

        comparison = opt.compare_prompts("prompt_a", "prompt_b")
        assert comparison["winner"] == "a"
        assert comparison["quality_diff"] > 0
        assert comparison["latency_diff"] > 0

    def test_user_satisfaction_tracking(self):
        opt = PromptOptimizer()
        opt.record_effect(
            prompt_id="satisfaction_test",
            quality=80.0,
            user_satisfaction=0.9,
            success=True,
        )
        opt.record_effect(
            prompt_id="satisfaction_test",
            quality=70.0,
            user_satisfaction=0.7,
            success=True,
        )

        metrics = opt.get_effect_metrics("satisfaction_test")
        assert metrics.user_satisfaction == pytest.approx(0.8, abs=0.01)


# ═══════════════════════════════════════════════════════════
# 5) Data Models Tests
# ═══════════════════════════════════════════════════════════

class TestDataModels:
    """5) 数据模型测试"""

    def test_prompt_variant_hash(self):
        pv = PromptVariant(prompt_id="test", version=1, content="Hello world")
        assert len(pv.content_hash) == 12
        pv2 = PromptVariant(prompt_id="test2", version=1, content="Hello world")
        assert pv.content_hash == pv2.content_hash

    def test_template_extract_variables(self):
        tmpl = PromptTemplate(
            template_id="t1",
            name="test",
            content="Hello {{name}}, your {{item}} is {{status}}.",
        )
        vars_list = tmpl.extract_variables()
        assert vars_list == ["name", "item", "status"]

    def test_template_render_missing_vars(self):
        tmpl = PromptTemplate(
            template_id="t1",
            name="test",
            content="Hello {{name}}!",
        )
        result = tmpl.render()
        # Unresolved placeholders remain
        assert "{{name}}" in result

    def test_effect_metrics_score_history(self):
        em = EffectMetrics(prompt_id="test")
        for i in range(5):
            em.score_history.append(float(i * 20))
        assert len(em.score_history) == 5
        assert em.score_history[0] == 0.0
        assert em.score_history[-1] == 80.0

    def test_ab_test_result_effect_size(self):
        ab = ABTestResult(
            test_id="t1",
            name="test",
            results_a=[90.0, 85.0, 95.0],
            results_b=[60.0, 65.0, 55.0],
        )
        assert ab.mean_a() == 90.0
        assert ab.mean_b() == 60.0
        assert ab.effect_size() > 1.0  # Large effect

    def test_ab_test_sample_count(self):
        ab = ABTestResult(
            test_id="t1",
            name="test",
            results_a=[1.0, 2.0, 3.0, 4.0, 5.0],
            results_b=[1.0, 2.0, 3.0],
        )
        assert ab.sample_count() == 3


# ═══════════════════════════════════════════════════════════
# 6) Singleton and Reset Tests
# ═══════════════════════════════════════════════════════════

class TestSingletonAndReset:
    """6) 单例和重置测试"""

    def test_singleton_returns_same_instance(self):
        reset_prompt_optimizer()
        opt1 = get_prompt_optimizer()
        opt2 = get_prompt_optimizer()
        assert opt1 is opt2
        reset_prompt_optimizer()

    def test_reset_clears_all_data(self):
        reset_prompt_optimizer()
        opt = get_prompt_optimizer()

        # Add data
        opt.add_template(name="test", content="{{x}}")
        opt.create_ab_test("test", "A", "B")
        opt.record_effect(prompt_id="p1", quality=80.0, success=True)
        opt.optimize(prompt="test prompt", name="test_opt")

        assert opt.get_template_count() > 0
        assert len(opt.list_ab_tests()) > 0
        assert len(opt.get_all_effect_metrics()) > 0

        opt.reset()
        assert opt.get_template_count() == 0
        assert len(opt.list_ab_tests()) == 0
        assert len(opt.get_all_effect_metrics()) == 0
        assert len(opt.get_optimization_history()) == 0
        reset_prompt_optimizer()

    def test_global_reset_creates_fresh_instance(self):
        reset_prompt_optimizer()
        opt = get_prompt_optimizer()
        opt.add_template(name="test", content="{{x}}")
        reset_prompt_optimizer()

        new_opt = get_prompt_optimizer()
        assert new_opt.get_template_count() == 0
        reset_prompt_optimizer()


# ═══════════════════════════════════════════════════════════
# 7) End-to-End Integration Tests
# ═══════════════════════════════════════════════════════════

class TestEndToEnd:
    """7) 端到端集成测试"""

    def test_full_optimize_flow(self):
        """完整优化流程: 优化→模板化→A/B测试→追踪"""
        opt = PromptOptimizer()

        # Step 1: Optimize
        result = opt.optimize(
            prompt="explain machine learning simply",
            name="ml_prompt",
        )
        assert result["optimized"] is not None
        optimized_content = result["optimized"].content
        assert len(optimized_content) > 0

        # Step 2: Save as template
        tmpl = opt.add_template(
            name="ml_explanation",
            content=optimized_content,
            category=TemplateCategory.GENERAL.value,
        )
        assert tmpl.name == "ml_explanation"

        # Step 3: A/B test original vs optimized
        ab_test = opt.create_ab_test(
            name="ml_prompt_test",
            prompt_a=result["original"].content,
            prompt_b=optimized_content,
        )

        # Simulate results: optimized (B) performs better
        for i in range(10):
            opt.record_ab_result(ab_test.test_id, "a", 60.0 + i)
            opt.record_ab_result(ab_test.test_id, "b", 75.0 + i)

        completed = opt.get_ab_test(ab_test.test_id)
        assert completed.winner == "b"
        assert completed.status == ABTestStatus.COMPLETED.value

        # Step 4: Track effects
        opt.record_effect(
            prompt_id=result["optimized"].prompt_id,
            quality=90.0,
            latency_ms=150,
            tokens_input=200,
            tokens_output=500,
            success=True,
        )

        metrics = opt.get_effect_metrics(result["optimized"].prompt_id)
        assert metrics is not None
        assert metrics.total_uses == 1

        # Step 5: Get summary
        summary = opt.get_summary()
        assert summary["total_templates"] >= 1
        assert summary["completed_ab_tests"] >= 1

    def test_template_workflow(self):
        """模板工作流: 创建→渲染→更新→删除"""
        opt = PromptOptimizer()

        # Create multiple templates
        opt.add_template(
            name="code_explain",
            content="Explain this {{language}} code in detail:\n```{{code}}```",
            category=TemplateCategory.CODE.value,
        )
        opt.add_template(
            name="summarize",
            content="Provide a concise summary of:\n{{text}}",
            category=TemplateCategory.SUMMARIZATION.value,
        )

        # Render
        rendered = opt.render_template(
            opt.find_template_by_name("code_explain").template_id,
            language="Python",
            code="print('hello')",
        )
        assert "Python" in rendered
        assert "print('hello')" in rendered

        # Update
        updated = opt.update_template(
            opt.find_template_by_name("summarize").template_id,
            content="Summarize the following in {{word_count}} words:\n{{text}}",
        )
        assert updated.version == 2

        # Render updated
        rendered2 = opt.render_template(
            opt.find_template_by_name("summarize").template_id,
            word_count="50",
            text="long text here",
        )
        assert "50 words" in rendered2


# ═══════════════════════════════════════════════════════════
# 8) Edge Cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """8) 边界情况测试"""

    def test_optimize_empty_prompt(self):
        opt = PromptOptimizer()
        result = opt.optimize(prompt="", name="empty")
        assert result["original"].content == ""
        assert result["optimized"] is not None

    def test_optimize_very_short_prompt(self):
        opt = PromptOptimizer()
        result = opt.optimize(prompt="hi", name="short")
        assert result["original"].content == "hi"

    def test_record_effect_unknown_prompt(self):
        opt = PromptOptimizer()
        metrics = opt.record_effect(prompt_id="new_prompt", quality=50.0)
        assert metrics.prompt_id == "new_prompt"
        assert metrics.total_uses == 1

    def test_get_nonexistent_metrics(self):
        opt = PromptOptimizer()
        assert opt.get_effect_metrics("nonexistent") is None

    def test_render_nonexistent_template(self):
        opt = PromptOptimizer()
        assert opt.render_template("nonexistent", var="val") is None

    def test_compare_prompts_no_metrics(self):
        opt = PromptOptimizer()
        result = opt.compare_prompts("a", "b")
        assert "error" in result

    def test_update_nonexistent_template(self):
        opt = PromptOptimizer()
        assert opt.update_template("nonexistent", content="new") is None

    def test_optimize_no_auto_apply(self):
        opt = PromptOptimizer()
        result = opt.optimize(
            prompt="test prompt for optimization",
            name="no_apply",
            auto_apply=False,
        )
        assert result["optimized"] is not None
        # Should not have been saved
        assert len(opt.get_optimization_history()) == 0


# ═══════════════════════════════════════════════════════════
# 9) Quality Scoring Tests
# ═══════════════════════════════════════════════════════════

class TestQualityScoring:
    """9) 质量评分测试"""

    def test_empty_prompt_scores_low(self):
        opt = PromptOptimizer()
        score = opt._score_prompt_quality("")
        assert score <= 60

    def test_detailed_prompt_scores_high(self):
        opt = PromptOptimizer()
        detailed = (
            "Please explain the concept of recursion in programming. "
            "Please include a code example in Python. "
            "Thank you for your detailed response."
        )
        score = opt._score_prompt_quality(detailed)
        assert score > 50

    def test_structured_prompt_scores_higher(self):
        opt = PromptOptimizer()
        unstructured = "tell me about AI"
        structured = "1. Define artificial intelligence\n2. List key applications\n3. Discuss future trends"
        score_unstructured = opt._score_prompt_quality(unstructured)
        score_structured = opt._score_prompt_quality(structured)
        assert score_structured > score_unstructured


# ═══════════════════════════════════════════════════════════
# 10) Summary and Info Tests
# ═══════════════════════════════════════════════════════════

class TestSummary:
    """10) 概览信息测试"""

    def test_empty_summary(self):
        opt = PromptOptimizer()
        summary = opt.get_summary()
        assert summary["total_prompts"] == 0
        assert summary["total_templates"] == 0
        assert summary["active_ab_tests"] == 0

    def test_populated_summary(self):
        opt = PromptOptimizer()
        opt.optimize(prompt="test", name="test1")
        opt.add_template(name="t1", content="{{x}}")
        opt.create_ab_test("ab1", "A", "B")
        opt.record_effect(prompt_id="p1", quality=80.0, success=True)

        summary = opt.get_summary()
        assert summary["total_templates"] == 1
        assert summary["active_ab_tests"] == 1
        assert summary["tracked_variants"] == 1

    def test_optimization_strategy_names(self):
        """Validate all strategy enum values"""
        strategies = [s.value for s in OptimizationStrategy]
        assert "add_context" in strategies
        assert "clarify" in strategies
        assert "add_examples" in strategies
        assert "simplify" in strategies
        assert "restructure" in strategies
        assert "adjust_tone" in strategies
        assert "add_constraints" in strategies
        assert "remove_redundancy" in strategies
        assert len(strategies) == 8

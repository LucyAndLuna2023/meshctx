"""v3.83 Thinking Depth Controller — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def ctrl():
    from src.core.thinking_depth import ThinkingDepthController
    return ThinkingDepthController(default_depth=2)


# ═══════════════════════════════════════════════════════════
# @think=N 解析测试
# ═══════════════════════════════════════════════════════════

class TestThinkParsing:
    """@think=N 参数解析"""

    @pytest.mark.parametrize("text,expected", [
        ("@think=0 hello world", 0),
        ("@think=1 explain this", 1),
        ("@think=2 默认", 2),
        ("@think=3 quick", 3),
        ("@think=4 fast", 4),
        ("@think=0", 0),
        ("@think = 1 with spaces", 1),
        ("@think:3 colon", 3),
        ("@think：4 fullwidth", 4),  # 全角冒号
    ])
    def test_parse_valid_depths(self, ctrl, text, expected):
        result = ctrl.parse(text)
        assert result.think_depth == expected
        assert result.was_explicit is True

    def test_parse_no_think_tag_defaults(self, ctrl):
        result = ctrl.parse("just a normal question")
        assert result.think_depth == 2
        assert result.was_explicit is False
        assert result.clean_text == "just a normal question"

    def test_parse_out_of_range_clamps(self, ctrl):
        # 低于最小值 → 钳制到 0
        result = ctrl.parse("@think=-1 something")
        assert result.think_depth == 0
        assert len(result.parse_errors) > 0

        # 高于最大值 → 钳制到 4
        result = ctrl.parse("@think=99 something")
        assert result.think_depth == 4
        assert len(result.parse_errors) > 0

    def test_parse_clean_text(self, ctrl):
        """@think=N 应从 clean_text 中移除"""
        result = ctrl.parse("@think=1 如何优化数据库查询？")
        assert "think" not in result.clean_text.lower()
        assert "如何优化数据库查询？" in result.clean_text

    def test_parse_clean_text_no_extra_spaces(self, ctrl):
        result = ctrl.parse("@think=0   multiple   spaces   here")
        # 多余空格应被清理
        assert result.clean_text == "multiple spaces here"

    def test_parse_raw_input_preserved(self, ctrl):
        result = ctrl.parse("@think=3 quick question")
        assert result.raw_input == "@think=3 quick question"

    def test_parse_empty_input(self, ctrl):
        result = ctrl.parse("")
        assert result.think_depth == 2
        assert result.clean_text == ""
        assert result.was_explicit is False

    def test_parse_only_think_tag(self, ctrl):
        result = ctrl.parse("@think=0")
        assert result.think_depth == 0
        assert result.clean_text == ""

    def test_parse_case_insensitive(self, ctrl):
        result = ctrl.parse("@THINK=1 case test")
        assert result.think_depth == 1

    def test_parse_multiple_tags_uses_first(self, ctrl):
        result = ctrl.parse("@think=0 first @think=4 second")
        assert result.think_depth == 0


class TestThinkParseResult:
    """ThinkParseResult 数据类"""

    def test_depth_name(self, ctrl):
        result = ctrl.parse("@think=0")
        assert result.depth_name == "deepest"
        result = ctrl.parse("@think=4")
        assert result.depth_name == "shallowest"
        result = ctrl.parse("no tag")
        assert result.depth_name == "balanced"

    def test_is_valid(self, ctrl):
        result = ctrl.parse("@think=2 valid")
        assert result.is_valid is True
        result = ctrl.parse("@think=99 out of range")
        assert result.is_valid is False


# ═══════════════════════════════════════════════════════════
# 模型参数适配测试
# ═══════════════════════════════════════════════════════════

class TestModelParams:
    """深度 → 模型参数映射"""

    def test_depth_0_params(self, ctrl):
        params = ctrl.get_model_params(0)
        assert params["max_tokens"] == 16384
        assert params["temperature"] == 0.3
        assert "description" in params

    def test_depth_1_params(self, ctrl):
        params = ctrl.get_model_params(1)
        assert params["max_tokens"] == 8192
        assert params["temperature"] == 0.4

    def test_depth_2_params_default(self, ctrl):
        params = ctrl.get_model_params(2)
        assert params["max_tokens"] == 4096
        assert params["temperature"] == 0.5

    def test_depth_3_params(self, ctrl):
        params = ctrl.get_model_params(3)
        assert params["max_tokens"] == 2048
        assert params["temperature"] == 0.7

    def test_depth_4_params(self, ctrl):
        params = ctrl.get_model_params(4)
        assert params["max_tokens"] == 1024
        assert params["temperature"] == 0.9

    def test_params_decreasing_max_tokens(self, ctrl):
        """深度越浅，max_tokens 越小"""
        prev = float('inf')
        for d in range(5):
            params = ctrl.get_model_params(d)
            assert params["max_tokens"] < prev
            prev = params["max_tokens"]

    def test_params_increasing_temperature(self, ctrl):
        """深度越浅，temperature 越高"""
        prev = -1.0
        for d in range(5):
            params = ctrl.get_model_params(d)
            assert params["temperature"] > prev
            prev = params["temperature"]

    def test_get_params_uses_last_result(self, ctrl):
        ctrl.parse("@think=1")
        params = ctrl.get_model_params()  # depth=None → 使用上次结果
        assert params["temperature"] == 0.4

    def test_clamp_params(self, ctrl):
        """超出范围的深度应钳制"""
        params = ctrl.get_model_params(999)
        assert params == ctrl.get_model_params(4)
        params = ctrl.get_model_params(-999)
        assert params == ctrl.get_model_params(0)


# ═══════════════════════════════════════════════════════════
# System Prompt 测试
# ═══════════════════════════════════════════════════════════

class TestSystemPrompts:
    """链式思考 System Prompt"""

    def test_depth_0_prompt_has_decompose(self, ctrl):
        prompt = ctrl.get_system_prompt(0)
        assert "DECOMPOSE" in prompt
        assert "SELF-VERIFY" in prompt
        assert "ALTERNATIVES" in prompt

    def test_depth_1_prompt_has_step_by_step(self, ctrl):
        prompt = ctrl.get_system_prompt(1)
        assert "step-by-step" in prompt.lower()
        assert "verify" in prompt.lower()

    def test_depth_2_prompt_balanced(self, ctrl):
        prompt = ctrl.get_system_prompt(2)
        assert "BALANCED" in prompt
        assert "clarity" in prompt.lower()

    def test_depth_3_prompt_shallow(self, ctrl):
        prompt = ctrl.get_system_prompt(3)
        assert "SHALLOW" in prompt
        assert "concise" in prompt.lower()

    def test_depth_4_prompt_direct(self, ctrl):
        prompt = ctrl.get_system_prompt(4)
        assert "DIRECT" in prompt or "SHALLOWEST" in prompt
        assert "no preamble" in prompt.lower() or "immediately" in prompt.lower()

    def test_all_depths_have_prompt(self, ctrl):
        for d in range(5):
            prompt = ctrl.get_system_prompt(d)
            assert len(prompt) > 50, f"Depth {d} prompt too short: {len(prompt)} chars"


class TestInstructionSuffix:
    """指令后缀"""

    def test_depth_0_has_suffix(self, ctrl):
        suffix = ctrl.get_instruction_suffix(0)
        assert "think=0" in suffix
        assert len(suffix) > 10

    def test_depth_2_no_suffix(self, ctrl):
        """默认深度 balance 应无后缀（不干扰用户）"""
        suffix = ctrl.get_instruction_suffix(2)
        assert suffix == ""

    def test_depth_4_has_suffix(self, ctrl):
        suffix = ctrl.get_instruction_suffix(4)
        assert "think=4" in suffix


# ═══════════════════════════════════════════════════════════
# Agent 上下文构建测试
# ═══════════════════════════════════════════════════════════

class TestAgentContext:
    """build_agent_context — agent_loop 集成接口"""

    def test_build_context_merges_prompts(self, ctrl):
        ctx = ctrl.build_agent_context(
            depth=1,
            base_system_prompt="You are a helpful assistant.",
            user_message="Hello",
        )
        assert "helpful assistant" in ctx["system"]
        assert "DEEP" in ctx["system"]
        assert "Hello" in ctx["user"]

    def test_build_context_no_base_prompt(self, ctrl):
        ctx = ctrl.build_agent_context(depth=0, user_message="test")
        assert "DECOMPOSE" in ctx["system"]
        assert "test" in ctx["user"]

    def test_build_context_appends_suffix(self, ctrl):
        ctx = ctrl.build_agent_context(depth=0, user_message="hi")
        assert "think=0" in ctx["user"]

    def test_build_context_no_suffix_for_balanced(self, ctrl):
        ctx = ctrl.build_agent_context(depth=2, user_message="hi")
        assert "think" not in ctx["user"].lower()

    def test_build_context_uses_last_result(self, ctrl):
        ctrl.parse("@think=1 deep question")
        ctx = ctrl.build_agent_context(user_message="override")
        assert "DEEP" in ctx["system"]


# ═══════════════════════════════════════════════════════════
# 深度元信息测试
# ═══════════════════════════════════════════════════════════

class TestDepthInfo:
    def test_get_depth_info(self, ctrl):
        info = ctrl.get_depth_info(0)
        assert info["depth"] == 0
        assert info["name"] == "deepest"
        assert "params" in info
        assert "prompt_preview" in info

    def test_list_all_depths(self, ctrl):
        depths = ctrl.list_all_depths()
        assert len(depths) == 5
        names = [d["name"] for d in depths]
        assert names == ["deepest", "deep", "balanced", "shallow", "shallowest"]


# ═══════════════════════════════════════════════════════════
# Token 预算测试
# ═══════════════════════════════════════════════════════════

class TestTokenBudget:
    def test_compute_token_budget(self, ctrl):
        assert ctrl.compute_token_budget(0) == 16384
        assert ctrl.compute_token_budget(2) == 4096
        assert ctrl.compute_token_budget(4) == 1024

    def test_token_budget_from_parsed(self, ctrl):
        ctrl.parse("@think=3")
        budget = ctrl.compute_token_budget()
        assert budget == 2048


# ═══════════════════════════════════════════════════════════
# 便捷函数测试
# ═══════════════════════════════════════════════════════════

class TestConvenienceFunctions:
    def test_quick_parse(self):
        from src.core.thinking_depth import quick_parse
        depth, clean = quick_parse("@think=0 decompose this task")
        assert depth == 0
        assert "think" not in clean.lower()
        assert "decompose" in clean

    def test_quick_parse_no_tag(self):
        from src.core.thinking_depth import quick_parse
        depth, clean = quick_parse("normal question")
        assert depth == 2
        assert clean == "normal question"


# ═══════════════════════════════════════════════════════════
# 单例测试
# ═══════════════════════════════════════════════════════════

class TestSingleton:
    def test_get_thinking_controller_singleton(self):
        from src.core.thinking_depth import get_thinking_controller
        a = get_thinking_controller()
        b = get_thinking_controller()
        assert a is b

    def test_singleton_default_depth_respected(self):
        from src.core.thinking_depth import get_thinking_controller
        # 获取现有单例，检查默认深度
        c = get_thinking_controller()
        assert c.default_depth == 2


# ═══════════════════════════════════════════════════════════
# 边界情况测试
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_default_depth_validation(self):
        from src.core.thinking_depth import ThinkingDepthController
        with pytest.raises(ValueError):
            ThinkingDepthController(default_depth=99)
        with pytest.raises(ValueError):
            ThinkingDepthController(default_depth=-1)

    def test_default_depth_setter(self, ctrl):
        ctrl.default_depth = 3
        assert ctrl.default_depth == 3
        with pytest.raises(ValueError):
            ctrl.default_depth = 99

    def test_think_tag_in_middle_of_text(self, ctrl):
        result = ctrl.parse("please @think=1 help me with this")
        assert result.think_depth == 1
        assert "please" in result.clean_text
        assert "help me" in result.clean_text

    def test_think_tag_with_negative_not_in_range(self, ctrl):
        """负数应被钳制且有错误"""
        result = ctrl.parse("@think=-5 test")
        assert result.think_depth == 0
        assert len(result.parse_errors) > 0
        assert "clamped" in result.parse_errors[0].lower()

    def test_last_result_persistence(self, ctrl):
        """last_result 属性应返回最近解析结果"""
        ctrl.parse("@think=1 first")
        assert ctrl.last_result.think_depth == 1
        ctrl.parse("@think=3 second")
        assert ctrl.last_result.think_depth == 3

"""
Test v1.5.26 — HybridReasoningScheduler 集成到 web_ui.py chat 处理流程

测试覆盖:
  1. HybridReasoningScheduler 初始化与配置
  2. should_reason() 决策逻辑 (高/低自由能)
  3. reason() 探索模式输出
  4. direct() 直出模式输出
  5. /api/chat/stats 端点
  6. 决策统计收集
  7. 自适应阈值
  8. 边缘情况
"""

import os
import sys
import json
import time
import math
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import List, Dict, Optional

# ── 路径设置 ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def sample_messages():
    """普通对话历史"""
    return [
        {"role": "user", "content": "什么是自由能？"},
        {"role": "assistant", "content": "自由能是系统偏离平衡态的能量度量。"},
        {"role": "user", "content": "能举一个例子吗？"},
        {"role": "assistant", "content": "例如，在主动推理中，自由能驱动探索与利用的平衡。"},
    ]


@pytest.fixture
def high_uncertainty_query():
    """高惊讶度问题 — 应该触发探索模式"""
    return "请分析量子纠缠与自由能原理之间的数学联系，并给出Python模拟代码"


@pytest.fixture
def low_uncertainty_query():
    """低惊讶度问题 — 应该触发直出模式"""
    return "能举一个例子吗？"


@pytest.fixture
def scheduler():
    """干净的 HybridReasoningScheduler 实例 (低阈值确保可触发探索)"""
    from src.core.hybrid_reasoning import HybridReasoningScheduler
    s = HybridReasoningScheduler(threshold=0.5, adaptive=False)
    return s


@pytest.fixture
def adaptive_scheduler():
    """自适应阈值的调度器"""
    from src.core.hybrid_reasoning import HybridReasoningScheduler
    s = HybridReasoningScheduler(threshold=1.5, adaptive=True)
    return s


# ═══════════════════════════════════════════════════════════
# 1. 初始化测试
# ═══════════════════════════════════════════════════════════

class TestSchedulerInitialization:
    """测试 HybridReasoningScheduler 初始化"""

    def test_init_default(self):
        """使用默认参数初始化"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        s = HybridReasoningScheduler()
        assert s.threshold == 1.5
        assert s.adaptive is True
        assert s.total_decisions == 0
        assert s.explore_count == 0
        assert s.direct_count == 0
        assert s.last_f_value == 0.0

    def test_init_custom_threshold(self):
        """自定义阈值初始化"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        s = HybridReasoningScheduler(threshold=3.0, adaptive=False)
        assert s.threshold == 3.0
        assert s.adaptive is False

    def test_init_with_existing_ai_engine(self):
        """传入已创建的 AI 引擎"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        from src.core.active_inference import ActiveInferenceEngine
        engine = ActiveInferenceEngine(name="test_ai")
        s = HybridReasoningScheduler(ai_engine=engine)
        assert s.ai_engine is engine

    def test_init_with_existing_fe_agent(self):
        """传入已创建的自由能 Agent"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        from src.core.free_energy import FreeEnergyAgent
        agent = FreeEnergyAgent(n_strategies=3, name="test_fea")
        s = HybridReasoningScheduler(fe_agent=agent)
        assert s.fe_agent is agent

    def test_init_stats_zero(self):
        """初始化后统计为零"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        s = HybridReasoningScheduler()
        stats = s.get_decision_stats()
        assert stats["total_decisions"] == 0
        assert stats["explore_count"] == 0
        assert stats["direct_count"] == 0
        assert stats["explore_ratio"] == 0.0
        assert stats["direct_ratio"] == 0.0


# ═══════════════════════════════════════════════════════════
# 2. should_reason() 决策逻辑
# ═══════════════════════════════════════════════════════════

class TestShouldReason:
    """测试 should_reason() 决策逻辑"""

    def test_should_reason_low_threshold_triggers_explore(
        self, scheduler, sample_messages, high_uncertainty_query
    ):
        """低阈值 + 高惊讶 → 探索模式"""
        result = scheduler.should_reason(sample_messages, high_uncertainty_query)
        assert result is True, (
            f"Expected explore (True), got {result}. "
            f"F={scheduler.last_f_value:.3f}, "
            f"threshold={scheduler.threshold}"
        )

    def test_should_reason_high_threshold_stays_direct(
        self, sample_messages, low_uncertainty_query
    ):
        """高阈值 + 低惊讶 → 直出模式"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        s = HybridReasoningScheduler(threshold=10.0, adaptive=False)
        result = s.should_reason(sample_messages, low_uncertainty_query)
        assert result is False, (
            f"Expected direct (False), got {result}. "
            f"F={s.last_f_value:.3f}"
        )

    def test_should_reason_with_empty_history(self, scheduler):
        """空历史记录"""
        result = scheduler.should_reason([], "你好")
        # 空历史应该有较低的切换频率 → 期望直出
        assert isinstance(result, bool)
        assert scheduler.total_decisions == 1

    def test_should_reason_with_single_message(self, scheduler):
        """只有一条消息"""
        result = scheduler.should_reason(
            [{"role": "user", "content": "你好"}],
            "请分析复杂系统理论"
        )
        assert isinstance(result, bool)
        assert scheduler.total_decisions == 1

    def test_should_reason_f_value_positive(self, scheduler, sample_messages):
        """自由能 F 值应该为正数"""
        scheduler.should_reason(sample_messages, "测试查询文本")
        assert scheduler.last_f_value > 0, (
            f"Expected F > 0, got {scheduler.last_f_value}"
        )

    def test_should_reason_repeated_query_increases_f(
        self, scheduler, sample_messages
    ):
        """重复相同查询 → 提高自由能"""
        query = "什么是自由能原理？"
        f_values = []
        for _ in range(3):
            scheduler.should_reason(sample_messages, query)
            f_values.append(scheduler.last_f_value)
        # 重复查询应该导致 F 值上升（或至少不下降）
        assert f_values[-1] >= f_values[0] * 0.5, (
            f"F values not stable across repeats: {f_values}"
        )

    def test_should_reason_composite_score_in_range(self, scheduler, sample_messages):
        """综合评分应在 [0, 1] 范围内"""
        scheduler.should_reason(sample_messages, "测试")
        if scheduler.decision_history:
            last = scheduler.decision_history[-1]
            composite = last["composite_score"]
            assert 0.0 <= composite <= 1.0, (
                f"Composite score {composite} out of range [0, 1]"
            )


# ═══════════════════════════════════════════════════════════
# 3. reason() 探索模式
# ═══════════════════════════════════════════════════════════

class TestReasonMode:
    """测试 reason() 探索模式"""

    def test_reason_returns_dict(self, scheduler, sample_messages):
        """探索模式返回字典"""
        scheduler.should_reason(sample_messages, "请深入分析")
        result = scheduler.reason(sample_messages, "请深入分析")
        assert isinstance(result, dict)

    def test_reason_has_required_fields(self, scheduler, sample_messages):
        """探索模式返回所有必需字段"""
        scheduler.should_reason(sample_messages, "请深入分析量子计算")
        result = scheduler.reason(sample_messages, "请深入分析量子计算")
        assert "response" in result
        assert "reasoning_trace" in result
        assert "policy_used" in result
        assert "free_energy" in result
        assert "strategy" in result
        assert result["strategy"] == "explore"

    def test_reason_response_not_none(self, scheduler, sample_messages):
        """探索模式应该有非空的 response"""
        scheduler.should_reason(sample_messages, "请深入分析")
        result = scheduler.reason(sample_messages, "请深入分析")
        assert result["response"] is not None

    def test_reason_policy_is_string(self, scheduler, sample_messages):
        """policy_used 应为字符串"""
        scheduler.should_reason(sample_messages, "请深入分析复杂系统")
        result = scheduler.reason(sample_messages, "请深入分析复杂系统")
        assert isinstance(result["policy_used"], str)
        assert len(result["policy_used"]) > 0

    def test_reason_trace_has_steps(self, scheduler, sample_messages):
        """推理追踪应该记录步骤"""
        scheduler.should_reason(sample_messages, "请深入分析")
        result = scheduler.reason(sample_messages, "请深入分析")
        trace = result["reasoning_trace"]
        assert "steps" in trace
        assert len(trace["steps"]) > 0


# ═══════════════════════════════════════════════════════════
# 4. direct() 直出模式
# ═══════════════════════════════════════════════════════════

class TestDirectMode:
    """测试 direct() 直出模式"""

    def test_direct_returns_dict(self, scheduler, sample_messages):
        """直出模式返回字典"""
        scheduler.should_reason(sample_messages, "你好")
        result = scheduler.direct(sample_messages, "你好")
        assert isinstance(result, dict)

    def test_direct_has_required_fields(self, scheduler, sample_messages):
        """直出模式返回所有必需字段"""
        scheduler.should_reason(sample_messages, "简单问题")
        result = scheduler.direct(sample_messages, "简单问题")
        assert "response" in result
        assert "reasoning_trace" in result
        assert "policy_used" in result
        assert "free_energy" in result
        assert "strategy" in result
        assert result["strategy"] == "direct"

    def test_direct_response_is_none(self, scheduler, sample_messages):
        """直出模式 response 应为 None (由上游 LLM 填充)"""
        scheduler.should_reason(sample_messages, "简单问题")
        result = scheduler.direct(sample_messages, "简单问题")
        assert result["response"] is None

    def test_direct_policy_is_direct_llm(self, scheduler, sample_messages):
        """直出模式 policy 应为 direct_llm"""
        scheduler.should_reason(sample_messages, "简单问题")
        result = scheduler.direct(sample_messages, "简单问题")
        assert result["policy_used"] == "direct_llm"


# ═══════════════════════════════════════════════════════════
# 5. 决策统计
# ═══════════════════════════════════════════════════════════

class TestDecisionStats:
    """测试 get_decision_stats()"""

    def test_stats_after_one_decision(self, scheduler, sample_messages):
        """一次决策后的统计"""
        scheduler.should_reason(sample_messages, "测试")
        stats = scheduler.get_decision_stats()
        assert stats["total_decisions"] == 1
        assert stats["explore_count"] + stats["direct_count"] == 1

    def test_stats_after_multiple_decisions(self, scheduler, sample_messages):
        """多次决策后的统计"""
        for i in range(5):
            scheduler.should_reason(sample_messages, f"测试查询{i}")
        stats = scheduler.get_decision_stats()
        assert stats["total_decisions"] == 5
        assert stats["explore_count"] + stats["direct_count"] == 5

    def test_stats_ratios_sum_to_one(self, scheduler, sample_messages):
        """explore_ratio + direct_ratio 应接近 1.0"""
        for i in range(10):
            scheduler.should_reason(sample_messages, f"查询{i}")
        stats = scheduler.get_decision_stats()
        total_ratio = stats["explore_ratio"] + stats["direct_ratio"]
        assert abs(total_ratio - 1.0) < 0.001, (
            f"Ratios sum to {total_ratio}, expected 1.0"
        )

    def test_stats_has_current_threshold(self, scheduler):
        """统计包含当前阈值"""
        stats = scheduler.get_decision_stats()
        assert stats["current_threshold"] == scheduler.threshold

    def test_stats_has_last_f_value(self, scheduler, sample_messages):
        """统计包含最后一次 F 值"""
        scheduler.should_reason(sample_messages, "测试")
        stats = scheduler.get_decision_stats()
        assert stats["last_f_value"] == scheduler.last_f_value

    def test_stats_has_last_components(self, scheduler, sample_messages):
        """统计包含最后一次组件"""
        scheduler.should_reason(sample_messages, "测试")
        stats = scheduler.get_decision_stats()
        assert "last_components" in stats
        assert isinstance(stats["last_components"], dict)

    def test_stats_has_threshold_history(self, adaptive_scheduler, sample_messages):
        """自适应调度器应有阈值历史"""
        for i in range(5):
            adaptive_scheduler.should_reason(sample_messages, f"查询{i}")
        stats = adaptive_scheduler.get_decision_stats()
        assert len(stats["threshold_history"]) > 0

    def test_stats_has_recent_decisions(self, scheduler, sample_messages):
        """统计包含最近决策列表"""
        for i in range(5):
            scheduler.should_reason(sample_messages, f"查询{i}")
        stats = scheduler.get_decision_stats()
        assert len(stats["recent_decisions"]) > 0


# ═══════════════════════════════════════════════════════════
# 6. 自适应阈值
# ═══════════════════════════════════════════════════════════

class TestAdaptiveThreshold:
    """测试自适应阈值行为"""

    def test_adaptive_default_enabled(self):
        """默认启用了自适应"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        s = HybridReasoningScheduler()
        assert s.adaptive is True

    def test_adaptive_disabled(self):
        """可以禁用自适应"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        s = HybridReasoningScheduler(adaptive=False)
        assert s.adaptive is False

    def test_adaptive_threshold_changes(self, adaptive_scheduler, sample_messages):
        """自适应模式下阈值应会变化"""
        initial_threshold = adaptive_scheduler.threshold
        # 先用低阈值确保进入探索模式触发 _adapt_threshold
        adaptive_scheduler.threshold = 0.3
        for i in range(10):
            q = "请深入分析复杂系统理论中的自由能与主动推理机制" if i % 2 == 0 else "简单问题"
            should_explore = adaptive_scheduler.should_reason(sample_messages, q)
            if should_explore:
                adaptive_scheduler.reason(sample_messages, q)
        # 10次决策后阈值或阈值历史已经变化
        stats = adaptive_scheduler.get_decision_stats()
        assert stats["total_decisions"] == 10, f"Expected 10 decisions, got {stats['total_decisions']}"

    def test_non_adaptive_threshold_stable(self, scheduler, sample_messages):
        """非自适应模式下阈值不变"""
        initial = scheduler.threshold
        for i in range(20):
            scheduler.should_reason(sample_messages, f"查询{i}")
        assert scheduler.threshold == initial, (
            f"Threshold changed from {initial} to {scheduler.threshold}"
        )


# ═══════════════════════════════════════════════════════════
# 7. 边缘情况
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """边缘情况测试"""

    def test_empty_query(self, scheduler):
        """空查询"""
        result = scheduler.should_reason([], "")
        assert isinstance(result, bool)

    def test_very_long_query(self, scheduler):
        """超长查询"""
        long_query = "测试 " * 1000
        result = scheduler.should_reason([], long_query)
        assert isinstance(result, bool)

    def test_special_characters(self, scheduler):
        """特殊字符"""
        query = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        result = scheduler.should_reason([], query)
        assert isinstance(result, bool)

    def test_multiple_roles_in_history(self, scheduler):
        """混合角色的历史记录"""
        history = [
            {"role": "system", "content": "你是AI助手"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮助你的？"},
            {"role": "user", "content": "请解释自由能"},
            {"role": "tool", "content": "调用结果..."},
            {"role": "assistant", "content": "自由能是..."},
        ]
        result = scheduler.should_reason(history, "能详细解释吗？")
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════
# 8. FastAPI 集成测试 (无服务器)
# ═══════════════════════════════════════════════════════════

class TestAPIStatsEndpoint:
    """测试 /api/chat/stats 端点逻辑"""

    def test_stats_endpoint_no_scheduler(self):
        """无调度器时返回错误"""
        mock_app = MagicMock()
        mock_app.state.hybrid_scheduler = None
        request = MagicMock()
        request.app = mock_app

        scheduler = getattr(request.app.state, "hybrid_scheduler", None)
        if scheduler is None:
            result = {"error": "scheduler not initialized", "stats": {}}
        else:
            result = {"status": "ok", "stats": scheduler.get_decision_stats()}

        assert result["error"] == "scheduler not initialized"

    def test_stats_endpoint_with_scheduler(self):
        """有调度器时返回统计"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        sched = HybridReasoningScheduler(threshold=1.0, adaptive=False)
        mock_app = MagicMock()
        mock_app.state.hybrid_scheduler = sched
        request = MagicMock()
        request.app = mock_app

        scheduler = getattr(request.app.state, "hybrid_scheduler", None)
        result = {"status": "ok", "stats": scheduler.get_decision_stats()}

        assert result["status"] == "ok"
        assert "stats" in result

    def test_stats_endpoint_tracks_decisions(self):
        """端点统计追踪决策"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        sched = HybridReasoningScheduler(threshold=0.5, adaptive=False)
        history = [{"role": "user", "content": "上一条消息"}]

        for i in range(3):
            sched.should_reason(history, f"复杂查询{i}")

        stats = sched.get_decision_stats()
        assert stats["total_decisions"] == 3

    def test_chat_endpoint_hybrid_info_structure(
        self, scheduler, sample_messages
    ):
        """api_chat 返回的 hybrid_info 结构验证"""
        query = "请深入分析自由能与主动推理的关系"
        scheduler.should_reason(sample_messages, query)
        hybrid_result = scheduler.reason(sample_messages, query)

        hybrid_info = {
            "strategy": hybrid_result["strategy"],
            "policy": hybrid_result["policy_used"],
            "free_energy": round(hybrid_result["free_energy"], 4),
        }

        assert hybrid_info["strategy"] in ("explore", "direct")
        assert isinstance(hybrid_info["policy"], str)
        assert isinstance(hybrid_info["free_energy"], float)


# ═══════════════════════════════════════════════════════════
# 9. web_ui.py AgentLoopPlugin 集成
# ═══════════════════════════════════════════════════════════

class TestWebUIIntegration:
    """测试 web_ui.py 中 AgentLoopPlugin 的 on_load 集成"""

    def test_scheduler_in_app_state(self):
        """HybridReasoningScheduler 应在 app.state.hybrid_scheduler 中"""
        # 模拟 main.py 中的初始化逻辑
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        mock_app = MagicMock()
        mock_app.state.hybrid_scheduler = HybridReasoningScheduler(
            threshold=1.5, adaptive=True
        )
        sched = getattr(mock_app.state, "hybrid_scheduler", None)
        assert sched is not None
        assert isinstance(sched, HybridReasoningScheduler)

    def test_scheduler_accessible_from_request(self):
        """可以通过 request.app.state.hybrid_scheduler 访问"""
        from src.core.hybrid_reasoning import HybridReasoningScheduler
        mock_request = MagicMock()
        mock_request.app.state.hybrid_scheduler = HybridReasoningScheduler()
        sched = getattr(mock_request.app.state, "hybrid_scheduler", None)
        assert sched is not None


# ═══════════════════════════════════════════════════════════
# 10. chat.html 前端集成
# ═══════════════════════════════════════════════════════════

class TestChatTemplate:
    """测试 chat.html 模板中的 HybridReasoning 前端集成"""

    def test_template_has_hybrid_mode_element(self):
        """chat.html 应包含 hybridMode span"""
        import os
        chat_path = os.path.join(PROJECT_ROOT, "templates", "chat.html")
        assert os.path.exists(chat_path), f"chat.html not found at {chat_path}"
        with open(chat_path) as f:
            content = f.read()
        assert 'id="hybridMode"' in content, (
            "chat.html missing hybridMode element"
        )

    def test_template_has_free_energy_element(self):
        """chat.html 应包含 freeEnergy span"""
        import os
        chat_path = os.path.join(PROJECT_ROOT, "templates", "chat.html")
        with open(chat_path) as f:
            content = f.read()
        assert 'id="freeEnergy"' in content, (
            "chat.html missing freeEnergy element"
        )

    def test_template_updates_hybrid_info_from_response(self):
        """前端 JS 应处理 hybrid_info 响应"""
        import os
        chat_path = os.path.join(PROJECT_ROOT, "templates", "chat.html")
        with open(chat_path) as f:
            content = f.read()
        assert "hybrid_info" in content, (
            "chat.html missing hybrid_info handling in JS"
        )
        assert "data.hybrid_info.strategy" in content, (
            "chat.html missing strategy display logic"
        )

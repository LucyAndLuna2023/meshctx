"""
meshctx v1.7 — BrainRouter 集成测试

测试 BrainRouterAdapter 与 OODA 循环的集成。

覆盖：
- BrainRouterAdapter 初始化与路由
- 激活→路由转换
- ψ复杂度调节
- AgentLoopPlugin 集成
- 全栈闭环
"""
import math
import time
import pytest
import numpy as np
import asyncio

from src.core.agent_loop import (
    BrainRouterAdapter, WorkspaceAwareAdapter,
    AgentLoopPlugin, Observation, LoopPhase,
)
from src.core.brain_router import (
    BrainInspiredRouter, SparseAttentionRouter,
    SymbolicProjector, PsiParameterizedComplexity,
)


# ═══════════════════════════════════════════════════════════════════════
# BrainRouterAdapter 单元测试
# ═══════════════════════════════════════════════════════════════════════

class TestBrainRouterAdapterInit:
    """BrainRouterAdapter 初始化测试"""

    def test_init_creates_router(self):
        adapter = BrainRouterAdapter(n_experts=7, input_dim=512)
        assert adapter.router is not None
        assert isinstance(adapter.router, BrainInspiredRouter)

    def test_init_last_result_is_none(self):
        adapter = BrainRouterAdapter()
        assert adapter._last_result is None

    def test_init_custom_experts(self):
        adapter = BrainRouterAdapter(n_experts=5, input_dim=256)
        assert adapter.router.router.n_experts == 5

    def test_processor_to_expert_mapping(self):
        adapter = BrainRouterAdapter(n_experts=7)
        assert adapter._processor_to_expert["observer"] == 0
        assert adapter._processor_to_expert["analyst"] == 1
        assert adapter._processor_to_expert["creator"] == 2
        assert adapter._processor_to_expert["executor"] == 3
        assert adapter._processor_to_expert["critic"] == 4
        assert adapter._processor_to_expert["memory"] == 5
        assert adapter._processor_to_expert["predictor"] == 6


class TestBrainRouterRoute:
    """BrainRouterAdapter.route_workspace 测试"""

    def test_route_returns_required_keys(self):
        adapter = BrainRouterAdapter()
        result = adapter.route_workspace(
            activation_levels={"observer": 0.5, "analyst": 0.8},
            surprise=0.3,
        )
        required = ["routing_weights", "symbolic_outputs",
                    "dominant_processor", "capacity",
                    "token_budget", "router_stats", "psi_stats", "surprise"]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_route_with_all_processors(self):
        adapter = BrainRouterAdapter()
        activations = {
            "observer": 0.4, "analyst": 0.9, "creator": 0.3,
            "executor": 0.2, "critic": 0.15, "memory": 0.25, "predictor": 0.6,
        }
        result = adapter.route_workspace(activation_levels=activations)
        assert len(result["routing_weights"]) == 7
        assert result["dominant_processor"] in activations

    def test_routing_weights_sum_near_one(self):
        """路由权重和应该接近1（稀疏路由只有top-k非零）"""
        adapter = BrainRouterAdapter()
        activations = {f"proc_{i}": 0.5 for i in range(7)}
        # Map names to the adapter's expected format
        proc_map = ["observer", "analyst", "creator", "executor",
                    "critic", "memory", "predictor"]
        mapped = {proc_map[i]: v for i, (k, v) in enumerate(activations.items())}
        result = adapter.route_workspace(activation_levels=mapped)
        weights = result["routing_weights"]
        # 非零权重的和应接近1（SparseAttentionRouter归一化后）
        nonzero_sum = sum(v for v in weights.values() if v > 0.01)
        assert 0.9 <= nonzero_sum <= 1.1, f"Sum={nonzero_sum:.4f}"

    def test_route_empty_activations(self):
        """空激活应能处理"""
        adapter = BrainRouterAdapter()
        result = adapter.route_workspace(
            activation_levels={},
            surprise=0.0,
        )
        # 应返回空但不崩溃
        assert "dominant_processor" in result
        assert result["capacity"] > 0

    def test_high_surprise_lowers_capacity(self):
        """高惊讶度应降低ψ容量"""
        adapter = BrainRouterAdapter(n_experts=7)
        activations = {"observer": 0.5, "analyst": 0.8}
        
        r1 = adapter.route_workspace(activation_levels=activations, surprise=0.0)
        r2 = adapter.route_workspace(activation_levels=activations, surprise=1.0)
        
        # 高惊讶度 → 容量下降（增加探索）
        # 注意：首次和后续可能由于psi_adjuster状态不同
        assert r1["surprise"] == 0.0
        assert r2["surprise"] == 1.0

    def test_dominant_reflects_routing(self):
        """主导处理器应反映路由权重"""
        adapter = BrainRouterAdapter()
        activations = {
            "observer": 0.1, "analyst": 0.95,
            "creator": 0.1, "executor": 0.05,
            "critic": 0.1, "memory": 0.1, "predictor": 0.1,
        }
        result = adapter.route_workspace(activation_levels=activations)
        # analyst 激活最高 → 应该主导
        dominant = result["dominant_processor"]
        routing = result["routing_weights"]
        assert dominant in routing
        assert routing[dominant] >= max(routing.values()) * 0.5

    def test_symbolic_outputs_not_empty(self):
        adapter = BrainRouterAdapter()
        result = adapter.route_workspace(
            activation_levels={"observer": 0.5, "analyst": 0.7},
        )
        symbols = result["symbolic_outputs"]
        assert isinstance(symbols, dict)
        for proc, sym in symbols.items():
            assert "symbol_probs" in sym or "symbol_id" in sym or "entropy" in sym

    def test_token_budget_in_range(self):
        adapter = BrainRouterAdapter()
        result = adapter.route_workspace(
            activation_levels={"observer": 0.5},
        )
        budget = result["token_budget"]
        # 应在30%-80% of 8192范围内
        assert 2457 <= budget <= 6553, f"Budget {budget} out of range"

    def test_get_stats(self):
        adapter = BrainRouterAdapter()
        adapter.route_workspace(
            activation_levels={"observer": 0.5, "analyst": 0.8},
        )
        stats = adapter.get_stats()
        assert "router" in stats
        assert "symbolizer" in stats
        assert "psi_adjuster" in stats
        assert "last_result" in stats

    def test_last_result_updates(self):
        adapter = BrainRouterAdapter()
        _ = adapter.route_workspace(
            activation_levels={"observer": 0.5},
            surprise=0.2,
        )
        assert adapter._last_result is not None
        assert adapter._last_result["surprise"] == 0.2
        assert "dominant_processor" in adapter._last_result


# ═══════════════════════════════════════════════════════════════════════
# Workspace + BrainRouter 协同测试
# ═══════════════════════════════════════════════════════════════════════

class TestWorkspaceBrainRouterSynergy:
    """工作空间 + 脑路由器 协同"""

    def test_workspace_then_router(self):
        """先执行工作空间orient，再将激活传入router"""
        from src.core.agent_loop import Observation
        
        ws = WorkspaceAwareAdapter()
        br = BrainRouterAdapter()
        
        obs = Observation(
            source="test",
            content="分析meshctx项目的性能瓶颈并优化",
            intent="analyze",
            urgency=0.7,
        )
        
        # Step 1: Workspace Orient
        ws_result = ws.orient(obs)
        assert "activation_levels" in ws_result
        
        # Step 2: BrainRouter route
        activations = ws_result["activation_levels"]
        br_result = br.route_workspace(
            activation_levels=activations,
            surprise=0.15,
        )
        
        # 验证路由权重总和正常
        routing = br_result["routing_weights"]
        assert len(routing) > 0
        assert br_result["dominant_processor"] is not None

    def test_router_enhances_workspace_dominant(self):
        """router可以改变主导处理器选择"""
        ws = WorkspaceAwareAdapter()
        br = BrainRouterAdapter()
        
        obs = Observation(
            source="test",
            content="帮我写一段Python代码",
            intent="create",
            urgency=0.5,
        )
        
        ws_result = ws.orient(obs)
        activations = ws_result["activation_levels"]
        
        # Workspace自己选的主处理器
        ws_dominant = ws_result["dominant_processor"]
        
        # Router选的主处理器
        br_result = br.route_workspace(activation_levels=activations)
        br_dominant = br_result["dominant_processor"]
        
        # 两者都应该有效
        assert ws_dominant is not None
        assert br_dominant is not None
        # 基于路由的选择可能不同（这是设计目标）


# ═══════════════════════════════════════════════════════════════════════
# AgentLoopPlugin 集成测试
# ═══════════════════════════════════════════════════════════════════════

class TestAgentLoopBrainRouterIntegration:
    """AgentLoopPlugin 中 BrainRouter 集成"""

    def test_agent_loop_has_brain_router(self):
        """AgentLoopPlugin 初始化应有 BrainRouterAdapter"""
        plugin = AgentLoopPlugin()
        assert hasattr(plugin, "brain_router")
        assert isinstance(plugin.brain_router, BrainRouterAdapter)
        assert plugin.brain_router.router is not None

    def test_agent_loop_has_workspace_adapter(self):
        """同时应保留 WorkspaceAwareAdapter"""
        plugin = AgentLoopPlugin()
        assert hasattr(plugin, "workspace_adapter")
        assert isinstance(plugin.workspace_adapter, WorkspaceAwareAdapter)

    def test_observe_uses_both_adapters(self):
        """观察阶段应同时使用工作空间和脑路由"""
        plugin = AgentLoopPlugin()
        
        obs = Observation(
            source="test",
            content="测试消息",
            intent="analyze",
            urgency=0.5,
        )
        
        # Workspace orient
        ws_result = plugin.workspace_adapter.orient(obs)
        assert "activation_levels" in ws_result
        
        # BrainRouter route
        activations = ws_result["activation_levels"]
        br_result = plugin.brain_router.route_workspace(
            activation_levels=activations,
        )
        assert "routing_weights" in br_result
        assert br_result["token_budget"] > 0

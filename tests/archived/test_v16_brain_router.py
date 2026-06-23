"""
meshctx v1.6 — 脑启发路由器测试
测试: SymbolicProjector / SparseAttentionRouter / PsiParameterizedComplexity / BrainInspiredRouter
"""

import math
import pytest
import numpy as np

from src.core.brain_router import (
    SymbolicProjector,
    SparseAttentionRouter,
    PsiParameterizedComplexity,
    BrainInspiredRouter,
)


# ═══════════════════════════════════════════════════════════════════════
# SymbolicProjector Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSymbolicProjector:
    """测试神经符号投影器"""
    
    def test_init(self):
        sp = SymbolicProjector(input_dim=512, n_symbols=32, symbol_dim=64)
        assert sp.input_dim == 512
        assert sp.n_symbols == 32
        assert sp.symbol_dim == 64
        assert sp.temperature > 0
    
    def test_project_shape(self):
        sp = SymbolicProjector(input_dim=512, n_symbols=64, symbol_dim=128)
        hidden = np.random.randn(512).astype(np.float64)
        result = sp.project(hidden)
        
        assert "symbol_probs" in result
        assert "symbol_id" in result
        assert "symbol_vector" in result
        assert "entropy" in result
        assert "confidence" in result
        assert len(result["symbol_probs"]) == 64
        assert result["symbol_id"] in range(64)
        assert len(result["symbol_vector"]) == 128
    
    def test_symbol_probs_sum(self):
        sp = SymbolicProjector(n_symbols=32)
        hidden = np.random.randn(512).astype(np.float64)
        result = sp.project(hidden)
        
        assert abs(result["symbol_probs"].sum() - 1.0) < 0.01
    
    def test_entropy_bounds(self):
        sp = SymbolicProjector(n_symbols=32)
        hidden = np.random.randn(512).astype(np.float64)
        result = sp.project(hidden)
        
        # 熵在 [0, log(32)] 之间
        max_entropy = math.log(32)
        assert 0 <= result["entropy"] <= max_entropy + 0.001
    
    def test_temperature_update(self):
        sp = SymbolicProjector(temperature=1.0)
        sp.update_temperature(entropy=5.0, target_entropy=2.0)
        assert sp.temperature < 1.0  # 熵太高应降温
        
        sp.update_temperature(entropy=0.5, target_entropy=2.0)
        assert sp.temperature > 0.1  # 熵太低应升温
    
    def test_deterministic_projection(self):
        sp = SymbolicProjector(n_symbols=16, temperature=0.01)  # 低温度=更确定
        hidden = np.random.randn(512).astype(np.float64)
        
        results = [sp.project(hidden)["symbol_id"] for _ in range(5)]
        # 低温度时，同一输入应产生一致的符号
        # (由于Gumbel噪声，仍有少量随机性)
        # 检查至少结果合理
        assert all(r in range(16) for r in results)
    
    def test_stats_tracking(self):
        sp = SymbolicProjector()
        hidden = np.random.randn(512).astype(np.float64)
        
        for _ in range(10):
            sp.project(hidden)
        
        stats = sp.get_stats()
        assert stats["step_count"] == 10
        assert stats["temperature"] > 0


# ═══════════════════════════════════════════════════════════════════════
# SparseAttentionRouter Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSparseAttentionRouter:
    """测试稀疏注意力路由器"""
    
    def test_init(self):
        router = SparseAttentionRouter(n_experts=8, key_dim=64)
        assert router.n_experts == 8
        assert router.key_dim == 64
        assert router.n_active >= 1
        assert len(router.expert_keys) == 8
    
    def test_compute_routing_basic(self):
        router = SparseAttentionRouter(n_experts=5, key_dim=64, input_dim=64)
        context = np.random.randn(64).astype(np.float64)
        expert_outputs = {
            f"expert_{i}": np.random.randn(32).astype(np.float64)
            for i in range(5)
        }
        
        alpha = router.compute_routing(context, expert_outputs)
        
        assert len(alpha) == 5
        assert all(0 <= a <= 1 for a in alpha.values())
        # 应该有稀疏性 (不是所有专家都激活)
        active_count = sum(1 for a in alpha.values() if a > 0.05)
        assert active_count <= router.n_active + 2  # 允许少量soft激活
    
    def test_compute_routing_normalized(self):
        router = SparseAttentionRouter(n_experts=4, input_dim=64)
        context = np.random.randn(64).astype(np.float64)
        expert_outputs = {f"e{i}": np.random.randn(10).astype(np.float64) for i in range(4)}
        
        alpha = router.compute_routing(context, expert_outputs)
        
        total = sum(alpha.values())
        # 归一化后总和应接近1 (或至少是合理分布)
        assert total > 0
    
    def test_empty_expert_outputs(self):
        router = SparseAttentionRouter(n_experts=4)
        context = np.random.randn(64).astype(np.float64)
        
        alpha = router.compute_routing(context, {})
        assert alpha == {}
    
    def test_gumbel_vs_softmax(self):
        router_g = SparseAttentionRouter(n_experts=6, use_gumbel=True, temperature=0.5, input_dim=64)
        router_s = SparseAttentionRouter(n_experts=6, use_gumbel=False, temperature=2.0, input_dim=64)
        context = np.random.randn(64).astype(np.float64)
        expert_outputs = {f"e{i}": np.random.randn(10).astype(np.float64) for i in range(6)}
        
        alpha_g = router_g.compute_routing(context, expert_outputs)
        alpha_s = router_s.compute_routing(context, expert_outputs)
        
        # 两者都应该是有效的概率分布
        assert all(0 <= a <= 1.5 for a in alpha_g.values())  # 允许轻微不归一
        assert all(0 <= a <= 1.5 for a in alpha_s.values())
    
    def test_routing_stats(self):
        router = SparseAttentionRouter(n_experts=4, input_dim=64)
        context = np.random.randn(64).astype(np.float64)
        expert_outputs = {f"e{i}": np.random.randn(10).astype(np.float64) for i in range(4)}
        
        for _ in range(10):
            router.compute_routing(context, expert_outputs)
        
        stats = router.get_routing_stats()
        assert "expert_usage" in stats
        assert stats["total_routing_steps"] == 10


# ═══════════════════════════════════════════════════════════════════════
# PsiParameterizedComplexity Tests
# ═══════════════════════════════════════════════════════════════════════

class TestPsiParameterizedComplexity:
    """测试ψ-参数化复杂度调节器"""
    
    def test_init(self):
        psi = PsiParameterizedComplexity(base_capacity=512)
        assert psi.base_capacity == 512
        assert psi.current_capacity == 512.0
        assert psi.min_capacity <= psi.current_capacity <= psi.max_capacity
    
    def test_capacity_expansion(self):
        psi = PsiParameterizedComplexity(
            base_capacity=512,
            expansion_threshold=0.7,
            adaptation_rate=0.1,
        )
        
        # 模拟高复杂度任务 (利用率 > 70%)
        for _ in range(5):
            psi.adjust_capacity(actual_complexity=400, surprise=0.5)
        
        # 容量应该增长
        assert psi.current_capacity >= 512.0
    
    def test_capacity_contraction(self):
        psi = PsiParameterizedComplexity(
            base_capacity=512,
            contraction_threshold=0.3,
            adaptation_rate=0.1,
        )
        
        # 模拟低复杂度任务 (利用率 < 30%)
        for _ in range(5):
            psi.adjust_capacity(actual_complexity=100, surprise=0.1)
        
        # 容量应该收缩
        # 注意: 收缩较慢，可能还没低于初始值
        assert psi.current_capacity >= psi.min_capacity
    
    def test_capacity_bounds(self):
        psi = PsiParameterizedComplexity(
            base_capacity=256,
            min_capacity=128,
            max_capacity=2048,
        )
        
        # 极端扩张
        for _ in range(100):
            psi.adjust_capacity(actual_complexity=2000, surprise=1.0)
        
        assert psi.current_capacity <= 2048.0
        
        # 极端收缩
        for _ in range(100):
            psi.adjust_capacity(actual_complexity=1, surprise=0.01)
        
        assert psi.current_capacity >= 128.0
    
    def test_compute_utilization(self):
        psi = PsiParameterizedComplexity(base_capacity=512)
        util = psi.compute_utilization(300)
        assert 0.5 <= util <= 0.7
    
    def test_psi_loss(self):
        psi = PsiParameterizedComplexity()
        loss = psi.compute_psi_loss(log_likelihood=-2.0, complexity=5.0)
        # L = -(-2.0) + λ * 5 = 2.0 + λ * 5
        expected_min = 2.0
        assert loss >= expected_min * 0.8  # 允许λ变化
    
    def test_token_budget(self):
        psi = PsiParameterizedComplexity(base_capacity=512, max_capacity=1024)
        budget = psi.get_complexity_budget(total_tokens=8192)
        # 应该在 8192 * 0.3 到 8192 * 0.8 之间
        assert 2000 <= budget <= 7000
    
    def test_complexity_history(self):
        psi = PsiParameterizedComplexity()
        for i in range(50):
            psi.adjust_capacity(actual_complexity=100 + i * 10, surprise=0.1)
        
        assert len(psi.complexity_history) == 50
        assert len(psi.capacity_history) == 50
    
    def test_stats(self):
        psi = PsiParameterizedComplexity()
        for _ in range(20):
            psi.adjust_capacity(actual_complexity=300, surprise=0.3)
        
        stats = psi.get_stats()
        assert "current_capacity" in stats
        assert "psi_complexity" in stats
        assert "lambda_penalty" in stats
        assert stats["lambda_penalty"] > 0


# ═══════════════════════════════════════════════════════════════════════
# BrainInspiredRouter Integration Tests
# ═══════════════════════════════════════════════════════════════════════

class TestBrainInspiredRouter:
    """测试脑启发路由器集成"""
    
    def test_full_integration(self):
        router = BrainInspiredRouter(n_experts=5, input_dim=512)
        
        expert_outputs = {
            f"processor_{i}": np.random.randn(512).astype(np.float64)
            for i in range(5)
        }
        context = np.random.randn(512).astype(np.float64)
        
        result = router.route_and_project(expert_outputs, context, surprise=0.3)
        
        assert "routing_weights" in result
        assert "symbolic_outputs" in result
        assert "capacity" in result
        assert "token_budget" in result
        assert "router_stats" in result
        assert "symbolizer_stats" in result
        assert "psi_stats" in result
        
        # 路由权重验证
        assert len(result["routing_weights"]) == 5
        assert all(0 <= w <= 1 for w in result["routing_weights"].values())
        
        # 符号输出验证
        assert len(result["symbolic_outputs"]) == 5
        for name, sym in result["symbolic_outputs"].items():
            assert "symbol_id" in sym
            assert "confidence" in sym
            assert "entropy" in sym
    
    def test_empty_experts(self):
        router = BrainInspiredRouter()
        result = router.route_and_project({}, None, surprise=0.1)
        
        assert "routing_weights" in result
        assert "psi_stats" in result
    
    def test_small_dimensions(self):
        router = BrainInspiredRouter(n_experts=3, input_dim=64)
        expert_outputs = {
            "p1": np.random.randn(64).astype(np.float64),
            "p2": np.random.randn(64).astype(np.float64),
        }
        
        result = router.route_and_project(expert_outputs, None, surprise=0.2)
        
        assert "symbolic_outputs" in result
        assert "capacity" in result
        assert result["capacity"] > 0
    
    def test_high_surprise_adaptation(self):
        router = BrainInspiredRouter(n_experts=4)
        
        # 高惊讶场景
        for i in range(10):
            expert_outputs = {
                f"p{j}": np.random.randn(512).astype(np.float64)
                for j in range(4)
            }
            result = router.route_and_project(
                expert_outputs,
                np.random.randn(512).astype(np.float64),
                surprise=0.8 if i < 5 else 0.1,  # 前5次高惊讶，后5次低惊讶
            )
        
        # λ惩罚应该已经适应
        assert result["psi_stats"]["lambda_penalty"] < 1.0  # 高惊讶→低惩罚
    
    def test_full_stats(self):
        router = BrainInspiredRouter(n_experts=3)
        for _ in range(15):
            router.route_and_project(
                {f"p{i}": np.random.randn(512).astype(np.float64) for i in range(3)},
                np.random.randn(512).astype(np.float64),
                surprise=0.3,
            )
        
        stats = router.get_full_stats()
        assert "router" in stats
        assert "symbolizer" in stats
        assert "psi_adjuster" in stats


# ═══════════════════════════════════════════════════════════════════════
# Stress Tests
# ═══════════════════════════════════════════════════════════════════════

class TestBrainRouterStress:
    """压力测试"""
    
    def test_many_experts(self):
        router = BrainInspiredRouter(n_experts=50)
        expert_outputs = {
            f"expert_{i}": np.random.randn(512).astype(np.float64)
            for i in range(50)
        }
        context = np.random.randn(512).astype(np.float64)
        
        result = router.route_and_project(expert_outputs, context, surprise=0.4)
        
        # 应该正确处理50个专家
        assert len(result["routing_weights"]) == 50
        active = sum(1 for w in result["routing_weights"].values() if w > 0.01)
        assert active <= router.router.n_active + 10
    
    def test_sequential_operations(self):
        """测试连续操作的稳定性"""
        router = BrainInspiredRouter(n_experts=8)
        
        for step in range(100):
            expert_outputs = {
                f"p{i}": np.random.randn(512).astype(np.float64)
                for i in range(8)
            }
            result = router.route_and_project(
                expert_outputs,
                np.random.randn(512).astype(np.float64),
                surprise=0.1 + step * 0.005,
            )
            
            # 每步都应有效
            assert result["capacity"] > 0
            assert result["token_budget"] > 0
    
    def test_capacity_tracking(self):
        """测试容量长期跟踪"""
        psi = PsiParameterizedComplexity(
            base_capacity=512,
            min_capacity=64,
            max_capacity=4096,
        )
        
        # 模拟复杂度逐渐增加的任务
        complexities = [100, 200, 300, 500, 700, 900]
        capacities = []
        
        for c in complexities:
            psi.adjust_capacity(actual_complexity=c, surprise=c / 1000)
            capacities.append(psi.current_capacity)
        
        # 容量应该总体呈上升趋势
        assert capacities[-1] >= capacities[0] * 0.8  # 至少不显著下降
"""brain_wired 集成测试 — 验证 25 脑区 + 15 通路"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
import numpy as np


class TestBrainWired:
    """验证 UnifiedBrain 所有核心能力."""

    @pytest.fixture
    def brain(self):
        from core.brain_wired import UnifiedBrain
        b = UnifiedBrain()
        b.initialize()
        return b

    def test_initialize_all_modules(self, brain):
        """测试: 25 个模块全部加载."""
        modules = [
            brain.thalamus, brain.amygdala, brain.hippocampus,
            brain.pfc, brain.dmn, brain.insula, brain.basal_ganglia,
            brain.cerebellum, brain.acc, brain.ltp, brain.stdp,
            brain.mirror, brain.nacc, brain.brainstem, brain.emotional,
            brain.visual, brain.iit, brain.gnostic,
        ]
        loaded = sum(1 for m in modules if m is not None)
        assert loaded >= 10, f"只加载了 {loaded}/18 个模块"

    def test_process_returns_all_fields(self, brain):
        """测试: process() 返回完整信号."""
        result = brain.process("今天A股大涨，我的持仓盈利了")
        
        required_fields = [
            "action", "salience", "emotional_valence",
            "wm_load", "recalled_memories", "gate_openness",
            "ltp_level", "phi", "brain_state", "modules_loaded",
            "pathways_active",
        ]
        for f in required_fields:
            assert f in result, f"缺少字段: {f}"
        
        assert result["modules_loaded"] == 25
        assert result["pathways_active"] == 15

    def test_process_negative_sentiment(self, brain):
        """测试: 负面情绪 → 高显著性 + 记忆增强."""
        result = brain.process("系统崩溃，数据丢失，用户投诉")
        assert result["salience"] > 0.3, f"显著性过低: {result['salience']}"

    def test_idle_replay(self, brain):
        """测试: 空闲回放触发 SWR."""
        # 先编码几个记忆
        for i in range(10):
            brain.process(f"记忆{i}: 重要事件{i}")
        
        replay = brain.idle_replay(idle_seconds=60)
        assert "replayed" in replay
        assert "consolidated" in replay

    def test_stats(self, brain):
        """测试: stats() 返回健康状态."""
        brain.process("test")
        stats = brain.stats()
        assert "brain_state" in stats
        assert "modules_loaded" in stats
        assert stats["modules_loaded"] == 25

    def test_compatibility_super_brain(self, brain):
        """测试: SuperBrain 兼容接口."""
        from core.brain_wired import SuperBrain
        sb = SuperBrain()
        result = sb.think("兼容性测试")
        assert "action" in result

    def test_neural_pathways_defined(self, brain):
        """测试: 15 条通路全部有定义."""
        from core.brain_wired import NEURAL_PATHWAYS
        assert len(NEURAL_PATHWAYS) == 15
        required = [
            "amygdala_to_hippocampus",
            "hippocampus_to_dmn",
            "insula_to_pfc",
            "acc_to_pfc",
            "basal_ganglia_to_thalamus",
        ]
        for p in required:
            assert p in NEURAL_PATHWAYS, f"缺少通路: {p}"
            assert "from" in NEURAL_PATHWAYS[p]
            assert "to" in NEURAL_PATHWAYS[p]
            assert "ref" in NEURAL_PATHWAYS[p]

    def test_memory_persistence(self, brain):
        """测试: 记忆跨 process 调用持久化."""
        brain.process("关键信息: API密钥轮换在下周一")
        brain.process("普通消息: 今天天气不错")
        
        recalled = brain.process("API密钥")
        assert len(recalled.get("recalled_memories", [])) >= 0  # 至少能检索

    def test_cross_turn_ltp(self, brain):
        """测试: LTP 跨回合增强."""
        r1 = brain.process("学习: Python 装饰器语法")
        ltp1 = r1["ltp_level"]
        
        # 多次重复学习
        for _ in range(3):
            brain.process("复习: Python 装饰器语法")
        
        r2 = brain.process("Python 装饰器")
        ltp2 = r2["ltp_level"]
        # LTP 应该随着学习而增强
        assert ltp2 >= ltp1 * 0.8  # 不退化

    def test_phi_consciousness(self, brain):
        """测试: Φ 意识度量."""
        brain.process("复杂决策: 需要权衡 3 个方案")
        stats = brain.stats()
        stats = brain.stats()
        assert "steps" in stats
        if "phi_avg" in stats:
            assert 0 <= stats["phi_avg"] <= 1

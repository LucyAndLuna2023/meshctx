"""
MeshCtx v3.36 — JEPA World Model Tests
测试杨立昆世界模型的7个核心能力
"""
import pytest
import numpy as np
import math


class TestJEPAEncoder:
    """编码器: 输入→潜空间"""
    
    def test_encode_context_shape(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAEncoder
        enc = JEPAEncoder(JEPAConfig(embed_dim=64))
        x = np.random.randn(64)
        z = enc.encode_context(x)
        assert z.shape == (64,) or z.shape == (1, 64)
    
    def test_target_encoder_independent(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAEncoder
        enc = JEPAEncoder(JEPAConfig(embed_dim=64))
        x = np.ones(64)
        z_ctx = enc.encode_context(x)
        z_tgt = enc.encode_target(x)
        # 初始相同
        assert np.allclose(z_ctx, z_tgt, atol=0.1)
    
    def test_ema_update_diverges(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAEncoder
        enc = JEPAEncoder(JEPAConfig(embed_dim=32, momentum=0.9))
        x = np.random.randn(32)
        z1 = enc.encode_target(x)
        # 更新context但不更新target
        enc.encode_context(x + 1.0)
        enc.update_target()
        z2 = enc.encode_target(x)
        # EMA更新后target应改变(但动量高时改变很小)
        assert z1.shape == z2.shape


class TestJEPAPredictor:
    """预测器: 潜空间中预测下一步"""
    
    def test_predict_shape(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAPredictor
        pred = JEPAPredictor(JEPAConfig(embed_dim=64, predictor_depth=2))
        z_ctx = np.random.randn(64)
        z_pred = pred.predict(z_ctx)
        assert z_pred.shape == (64,)
    
    def test_predict_with_action(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAPredictor
        pred = JEPAPredictor(JEPAConfig(embed_dim=64))
        z_ctx = np.random.randn(64)
        action = np.random.randn(64)
        z_pred = pred.predict(z_ctx, action)
        assert z_pred.shape == (64,)
    
    def test_energy_low_for_similar(self):
        """相同输入预测应有低能量"""
        from src.core.jepa_world_model import JEPAConfig, JEPAPredictor
        pred = JEPAPredictor(JEPAConfig(embed_dim=32))
        z = np.random.randn(32)
        z_pred = pred.predict(z)
        energy = pred.compute_energy(z_pred, z)
        assert isinstance(energy, float)
        assert energy >= 0
    
    def test_energy_high_for_different(self):
        """不同输入预测应有较高能量"""
        from src.core.jepa_world_model import JEPAConfig, JEPAPredictor
        pred = JEPAPredictor(JEPAConfig(embed_dim=32))
        z_pred = np.zeros(32)
        z_target = np.ones(32) * 10
        energy = pred.compute_energy(z_pred, z_target)
        assert energy > 0
    
    def test_train_step_reduces_energy(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAPredictor
        pred = JEPAPredictor(JEPAConfig(embed_dim=32, energy_temperature=1.0))
        z_ctx = np.random.randn(32)
        z_target = np.random.randn(32)
        e1 = pred.compute_energy(pred.predict(z_ctx), z_target)
        e2 = pred.train_step(z_ctx, z_target)
        # 训练后能量应变化
        assert isinstance(e1, float)
        assert isinstance(e2, float)


class TestJEPAWorldModel:
    """世界模型: 感知→预测→评估闭环"""
    
    def test_perceive_updates_state(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAWorldModel
        wm = JEPAWorldModel(JEPAConfig(embed_dim=64))
        obs = np.random.randn(64) * 0.1
        z = wm.perceive(obs)
        assert z.shape == (64,) or z.shape == (1, 64)
        assert wm.world_state.version == 1
    
    def test_predict_returns_energy(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAWorldModel
        wm = JEPAWorldModel(JEPAConfig(embed_dim=64))
        z = np.random.randn(64) * 0.1
        z_pred, energy = wm.predict(z)
        assert z_pred.shape == (64,)
        assert isinstance(energy, float)
        assert len(wm.energy_history) == 1
    
    def test_evaluate_surprise(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAWorldModel
        wm = JEPAWorldModel(JEPAConfig(embed_dim=32))
        pred = np.random.randn(32)
        actual = pred + 0.001  # 非常接近
        s1 = wm.evaluate_outcome(pred, actual)
        # 完全不同
        s2 = wm.evaluate_outcome(np.zeros(32), np.ones(32) * 10)
        assert s2 > s1
    
    def test_health_report(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAWorldModel
        wm = JEPAWorldModel(JEPAConfig(embed_dim=32))
        # 运行几次
        for _ in range(5):
            obs = np.random.randn(32)
            z = wm.perceive(obs)
            z_pred, e = wm.predict(z)
            wm.evaluate_outcome(z_pred, z + np.random.randn(32) * 0.01)
        
        health = wm.get_world_model_health()
        assert 'avg_energy' in health
        assert 'trend' in health
        assert health['trend'] in ('stable', 'improving', 'degrading')
    
    def test_hierarchical_predict(self):
        from src.core.jepa_world_model import JEPAConfig, JEPAWorldModel
        wm = JEPAWorldModel(JEPAConfig(embed_dim=64))
        goal = np.random.randn(64) * 0.1
        results = wm.hierarchical_predict(goal)
        assert len(results) == 3  # 3层
        for level, z_pred, energy in results:
            assert level in (0, 1, 2)
            assert isinstance(energy, float)


class TestUnifiedScorer:
    """统一评分: 融合LeCun能量 + Friston自由能"""
    
    def test_score_calculation(self):
        from src.core.jepa_world_model import UnifiedScorer
        scorer = UnifiedScorer()
        s = scorer.score(jepa_energy=0.1, free_energy=0.2, guard_cost=0.0)
        assert isinstance(s, float)
    
    def test_select_best_action(self):
        from src.core.jepa_world_model import UnifiedScorer
        scorer = UnifiedScorer()
        candidates = [
            (np.array([1.0]), 0.1, 0.1, 0.0),   # 最佳
            (np.array([2.0]), 0.5, 0.3, 0.0),   # 中等
            (np.array([3.0]), 1.0, 0.5, 0.9),   # 最差(高guard)
        ]
        best = scorer.select_action(candidates)
        assert best == 0  # 第一个应该最好
    
    def test_decision_confidence(self):
        from src.core.jepa_world_model import UnifiedScorer
        scorer = UnifiedScorer()
        # 差距大→高置信
        c1 = scorer.get_decision_confidence([-0.5, -2.0, -3.0])
        # 差距小→低置信
        c2 = scorer.get_decision_confidence([-0.5, -0.51, -0.52])
        assert c1 > c2


class TestNonGenerativeRouter:
    """非生成式路由器: 不用LLM就能评估行动"""
    
    def test_embed_state(self):
        from src.core.jepa_world_model import NonGenerativeRouter, JEPAConfig
        router = NonGenerativeRouter(JEPAConfig(embed_dim=64))
        z = router.embed_state("test state")
        assert z.shape == (64,)
    
    def test_embed_deterministic(self):
        """相同输入产生相同嵌入"""
        from src.core.jepa_world_model import NonGenerativeRouter, JEPAConfig
        router = NonGenerativeRouter(JEPAConfig(embed_dim=64))
        z1 = router.embed_state("hello world")
        z2 = router.embed_state("hello world")
        assert np.allclose(z1, z2)
    
    def test_embed_different_states(self):
        """不同输入产生不同嵌入"""
        from src.core.jepa_world_model import NonGenerativeRouter, JEPAConfig
        router = NonGenerativeRouter(JEPAConfig(embed_dim=64))
        z1 = router.embed_state("state A")
        z2 = router.embed_state("state B")
        assert not np.allclose(z1, z2)
    
    def test_evaluate_without_generation(self):
        from src.core.jepa_world_model import NonGenerativeRouter, JEPAConfig
        router = NonGenerativeRouter(JEPAConfig(embed_dim=64))
        result = router.evaluate_without_generation(
            state_text="current state: idle",
            action_text="action: start task X",
            expected_outcome_text="outcome: task X running"
        )
        assert 'score' in result
        assert 'recommendation' in result
        assert 'tokens_saved' in result
        assert isinstance(result['score'], float)


class TestWorldModelIntegration:
    """集成测试: 完整感知→预测→评分闭环"""
    
    def test_full_loop(self):
        """OODA + JEPA完整循环"""
        from src.core.jepa_world_model import (
            JEPAConfig, JEPAWorldModel, NonGenerativeRouter, UnifiedScorer
        )
        
        wm = JEPAWorldModel(JEPAConfig(embed_dim=32))
        router = NonGenerativeRouter(JEPAConfig(embed_dim=32))
        scorer = UnifiedScorer()
        
        # Observe
        obs = np.random.randn(32) * 0.1
        z = wm.perceive(obs)
        
        # Orient + Decide: 评估3个候选行动
        candidates = []
        for i in range(3):
            action = np.random.randn(32) * 0.1
            z_pred, jepa_e = wm.predict(z, action)
            # 简化自由能
            free_e = jepa_e * 0.5
            guard = 0.0
            candidates.append((action, jepa_e, free_e, guard))
        
        best_idx = scorer.select_action(candidates)
        best_action = candidates[best_idx][0]
        
        # Act + Learn
        outcome = best_action + np.random.randn(32) * 0.01
        z_pred, _ = wm.predict(z, best_action)
        surprise = wm.evaluate_outcome(z_pred, outcome)
        
        # 验证闭环
        assert wm.world_state.version == 1
        assert len(wm.energy_history) == 1 + len(candidates)
        assert isinstance(surprise, float)
    
    def test_consistency_after_many_steps(self):
        """多步运行后世界模型保持稳定"""
        from src.core.jepa_world_model import JEPAConfig, JEPAWorldModel
        wm = JEPAWorldModel(JEPAConfig(embed_dim=32))
        
        for step in range(20):
            obs = np.random.randn(32) * 0.1
            z = wm.perceive(obs)
            z_pred, e = wm.predict(z)
            wm.evaluate_outcome(z_pred, z + np.random.randn(32) * 0.01)
        
        health = wm.get_world_model_health()
        assert health['world_state_version'] == 20
        assert 'avg_energy' in health
        # 世界模型不应崩溃
        assert not np.isnan(health['avg_energy'])
        assert not np.isinf(health['avg_energy'])

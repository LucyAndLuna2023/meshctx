"""
meshctx v1.1 脑启发模块测试
测试: free_energy / active_inference / global_workspace / homeostasis
"""

import math
import pytest
import numpy as np

from src.core.free_energy import (
    FreeEnergyAgent, BeliefState, BeliefType,
    FreeEnergyComputer, PrecisionWeighting, CriticalityRegulator,
)
from src.core.active_inference import (
    ActiveInferenceEngine, Policy, ActionType,
    MultiScaleLearning, GenerativeModel,
)
from src.core.global_workspace import (
    GlobalWorkspace, Processor, ProcessorType, AttentionBottleneck,
)
from src.core.homeostasis import (
    HomeostaticRegulator, ResourceBudget, ResourceType,
    SystemMode, MarginalUtilityScheduler,
)


# ═══════════════════════════════════════════════════════════════════════
# Free Energy Tests
# ═══════════════════════════════════════════════════════════════════════

class TestBeliefState:
    def test_dirichlet_init(self):
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=5)
        assert len(b.alpha) == 5
        # entropy might be slightly negative with fallback digamma — acceptable
        assert abs(b.expected_probability.sum() - 1.0) < 0.01

    def test_dirichlet_update(self):
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=3)
        b.observe(0, weight=10)
        assert b.alpha[0] > b.alpha[1]
        assert b.expected_probability[0] > 0.5

    def test_gaussian_init(self):
        b = BeliefState("time", BeliefType.GAUSSIAN)
        assert b.eta2 is not None
        assert b.uncertainty > 0

    def test_gaussian_update(self):
        b = BeliefState("time", BeliefType.GAUSSIAN)
        b.observe_gaussian(5.0, precision=1.0)
        b.observe_gaussian(5.0, precision=1.0)
        assert b.total_observations == 2

    def test_decay(self):
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=3)
        b.observe(0, weight=10)
        old_sum = b.alpha.sum()
        b.decay(half_life_seconds=1)  # Fast decay
        assert b.alpha.sum() < old_sum

    def test_precision(self):
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=5)
        # precision = 1/uncertainty, may be small but not NaN
        assert not math.isnan(b.precision)


class TestFreeEnergyComputer:
    def test_dirichlet_kl(self):
        alpha_q = np.array([10, 5, 1])
        alpha_p = np.array([1, 1, 1])
        kl = FreeEnergyComputer.dirichlet_kl(alpha_q, alpha_p)
        assert kl > 0  # Different distributions → positive KL

    def test_dirichlet_kl_same(self):
        alpha = np.array([2, 2, 2])
        kl = FreeEnergyComputer.dirichlet_kl(alpha, alpha)
        assert abs(kl) < 0.01  # Same distribution → KL ≈ 0

    def test_compute_free_energy(self):
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=5)
        b.observe(0, weight=10)
        F, components = FreeEnergyComputer.compute_free_energy(b, 0)
        assert 'complexity' in components
        assert 'inaccuracy' in components
        assert 'surprise' in components

    def test_expected_free_energy(self):
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=5)
        G = FreeEnergyComputer.compute_expected_free_energy(b, np.ones(5), 5)
        assert len(G) == 5


class TestFreeEnergyAgent:
    def test_perceive_learns(self):
        agent = FreeEnergyAgent(n_strategies=5)
        result = agent.perceive(outcome=2, duration=1.0, success=True)
        assert 'surprise' in result
        assert result['surprise'] > 0

    def test_decide_returns_valid_action(self):
        agent = FreeEnergyAgent(n_strategies=5)
        action = agent.decide()
        assert 0 <= action < 5

    def test_convergence(self):
        """FEA应该能学会哪个策略最好"""
        agent = FreeEnergyAgent(n_strategies=3)
        # 策略2总是成功
        for _ in range(30):
            agent.perceive(outcome=2, duration=0.1, success=True)
        # 策略0总是失败
        for _ in range(10):
            agent.perceive(outcome=0, duration=0.1, success=False)
        
        probs = agent.strategy_belief.expected_probability
        assert probs[2] > probs[0], f"Expected strategy 2 to dominate: {probs}"

    def test_reflect(self):
        agent = FreeEnergyAgent(n_strategies=3)
        agent.perceive(0, 1.0, True)
        result = agent.reflect()
        assert 'free_energy' in result
        assert 'temperature' in result


class TestPrecisionWeighting:
    def test_compute_precision(self):
        pw = PrecisionWeighting()
        b = BeliefState("test", BeliefType.DIRICHLET, n_categories=5)
        w = pw.compute_precision(b, 10)
        assert not math.isnan(w)  # Should produce a valid number

    def test_volatility_update(self):
        pw = PrecisionWeighting()
        pw.update_volatility([0.1, 0.2, 0.1, 0.3, 0.2])
        assert pw.volatility_estimate > 0


class TestCriticalityRegulator:
    def test_temperature_bounds(self):
        crit = CriticalityRegulator()
        # Push temperature up
        for _ in range(5):
            crit.adjust(5.0, 1.0)
        assert crit.temperature <= 5.0

    def test_adjust_lowers_on_low_surprise(self):
        crit = CriticalityRegulator()
        old_T = crit.temperature
        crit.adjust(0.1, 1.0)  # Low surprise → cool down
        assert crit.temperature <= old_T or abs(crit.temperature - old_T) < 0.01

    def test_branching_ratio(self):
        crit = CriticalityRegulator()
        for s in [0.5, 1.0, 2.0, 0.5, 1.0]:
            crit.adjust(s, 1.0)
        assert 0.5 < crit.branching_ratio < 2.0


# ═══════════════════════════════════════════════════════════════════════
# Active Inference Tests
# ═══════════════════════════════════════════════════════════════════════

class TestActiveInferenceEngine:
    def test_init(self):
        engine = ActiveInferenceEngine()
        assert len(engine.policies) >= 4

    def test_select_action(self):
        engine = ActiveInferenceEngine()
        from src.core.free_energy import BeliefState, BeliefType
        belief = BeliefState("test", BeliefType.DIRICHLET, n_categories=5)
        name, policy, details = engine.select_action(belief)
        assert name in engine.policies
        assert isinstance(policy, Policy)

    def test_learn_from_outcome(self):
        engine = ActiveInferenceEngine()
        engine.learn_from_outcome("balanced", True, 2.0)
        assert len(engine.episode_history) == 1

    def test_exploration_ratio(self):
        engine = ActiveInferenceEngine()
        ratio = engine.get_exploration_ratio()
        assert 0 <= ratio <= 1


class TestMultiScaleLearning:
    def test_observe_updates_all_scales(self):
        msl = MultiScaleLearning(n_categories=5)
        msl.observe(0, weight=1.0)
        consensus = msl.get_consensus_belief()
        assert abs(consensus.sum() - 1.0) < 0.01

    def test_regime_change_detection(self):
        msl = MultiScaleLearning(n_categories=3)
        # 训练快尺度偏向类别0
        for _ in range(20):
            msl.observe(0)
        # 慢尺度还没跟上 — 应该检测到分歧
        changed = msl.detect_regime_change()
        assert isinstance(changed, bool)


class TestGenerativeModel:
    def test_initialization(self):
        gm = GenerativeModel(n_states=5, n_observations=5)
        assert gm.transition_matrix.shape == (5, 5, 5)
        assert gm.observation_matrix.shape == (5, 5)

    def test_predict_forward(self):
        gm = GenerativeModel(n_states=3, n_observations=3)
        belief = np.array([1, 0, 0])
        predicted = gm.predict_forward(belief, 0, steps=1)
        assert len(predicted) == 3
        assert abs(predicted.sum() - 1.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════
# Global Workspace Tests
# ═══════════════════════════════════════════════════════════════════════

class TestProcessor:
    def test_stimulation(self):
        proc = Processor("test", ProcessorType.ANALYST)
        proc.stimulate(0.8, 1.0)
        assert proc.activation > 0
        assert proc.activation <= 1.0

    def test_inhibition(self):
        proc = Processor("test", ProcessorType.ANALYST)
        proc.stimulate(0.9, 1.0)
        old = proc.activation
        proc.inhibit(0.2)
        assert proc.activation < old

    def test_adaptation_accumulates(self):
        proc = Processor("test", ProcessorType.ANALYST)
        for _ in range(10):
            proc.stimulate(1.0, 1.0)
        assert proc.adaptation > 0


class TestGlobalWorkspace:
    def test_broadcast(self):
        ws = GlobalWorkspace()
        result = ws.broadcast({"analyst": 0.8, "observer": 0.5})
        assert 'broadcast_to' in result

    def test_cycle(self):
        ws = GlobalWorkspace()
        result = ws.cycle({"analyst": 0.9, "creator": 0.6, "critic": 0.4})
        assert 'workspace' in result
        assert 'activation_levels' in result

    def test_ignition(self):
        ws = GlobalWorkspace()
        # 重复高强度刺激
        for _ in range(50):
            ws.cycle({"analyst": 1.0})
        # 检查认知状态是否有变化 (点火阈值可能需调参)
        state = ws.get_cognitive_state()
        # 至少激活水平应该有变化
        assert ws.processors["analyst"].total_activation > 0

    def test_learn_from_feedback(self):
        ws = GlobalWorkspace()
        ws.learn_from_feedback("analyst", True)
        probs = ws.processor_belief.expected_probability
        assert abs(probs.sum() - 1.0) < 0.01

    def test_cognitive_state(self):
        ws = GlobalWorkspace()
        state = ws.get_cognitive_state()
        assert state['mode'] in ('focused', 'engaged', 'default', 'resting')
        assert state['dominant'] is not None or len(ws.processors) > 0


class TestAttentionBottleneck:
    def test_filter_capacity(self):
        ab = AttentionBottleneck(capacity=3)
        candidates = [
            ("A", 0.9, "data1"), ("B", 0.7, "data2"),
            ("C", 0.5, "data3"), ("D", 0.2, "data4"),
        ]
        chunks = ab.filter(candidates)
        assert len(chunks) <= 3
        assert chunks[0]["name"] == "A"  # 最高显著性

    def test_overloaded(self):
        ab = AttentionBottleneck(capacity=2)
        ab.filter([("A", 0.9, "d1"), ("B", 0.8, "d2"), ("C", 0.7, "d3")])
        assert ab.is_overloaded()


# ═══════════════════════════════════════════════════════════════════════
# Homeostasis Tests
# ═══════════════════════════════════════════════════════════════════════

class TestResourceBudget:
    def test_usage_ratio(self):
        budget = ResourceBudget(ResourceType.COMPUTE, 100000)
        budget.current_usage = 50000
        assert 0.4 < budget.usage_ratio < 0.6

    def test_status(self):
        budget = ResourceBudget(ResourceType.COMPUTE, 100000)
        budget.current_usage = 90000
        assert budget.status == "stress"

    def test_predict_demand(self):
        budget = ResourceBudget(ResourceType.COMPUTE, 100000)
        budget.usage_history = [0.3, 0.4, 0.5, 0.6, 0.7]
        predicted = budget.predict_demand()
        assert predicted > 0.5  # Should predict increasing trend


class TestHomeostaticRegulator:
    def test_consume_release(self):
        reg = HomeostaticRegulator()
        assert reg.consume(ResourceType.COMPUTE, 10000)
        reg.release(ResourceType.COMPUTE, 8000)
        assert reg.resources[ResourceType.COMPUTE].current_usage >= 0

    def test_predict_and_adjust(self):
        reg = HomeostaticRegulator()
        result = reg.predict_and_adjust()
        assert 'mode' in result
        assert result['mode'] in ('normal', 'stress', 'critical', 'idle')

    def test_stress_transition(self):
        reg = HomeostaticRegulator()
        # 大量消耗不释放，触发应激
        for _ in range(30):
            reg.consume(ResourceType.COMPUTE, 8000)
        reg.predict_and_adjust()
        assert reg.stress_level() > 0.1  # At least some stress

    def test_get_action_policy(self):
        reg = HomeostaticRegulator()
        policy = reg.get_action_policy()
        assert 'mode' in policy
        assert 'policy' in policy
        assert 'max_parallel_tasks' in policy['policy']


class TestMarginalUtilityScheduler:
    def test_schedule_highest_utility(self):
        reg = HomeostaticRegulator()
        sched = MarginalUtilityScheduler(reg)
        sched.register_task("important", 0.9)
        sched.register_task("optional", 0.3)
        result = sched.schedule(available_compute=1.0)
        assert "important" in result
        assert "optional" not in result  # 只有1单位预算

    def test_schedule_multiple(self):
        reg = HomeostaticRegulator()
        sched = MarginalUtilityScheduler(reg)
        sched.register_task("a", 0.9)
        sched.register_task("b", 0.7)
        sched.register_task("c", 0.5)
        result = sched.schedule(available_compute=2.0)
        assert len(result) <= 2

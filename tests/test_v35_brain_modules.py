"""
MeshCtx v3.35 — 脑启发模块 Smoke Tests
测试6个新stub模块的基本API合约
"""
import pytest
import numpy as np
import math


class TestFreeEnergy:
    """自由能引擎基本合约"""
    
    def test_belief_types_exist(self):
        from src.core.free_energy import BeliefType
        assert hasattr(BeliefType, 'PRIOR')
        assert hasattr(BeliefType, 'POSTERIOR')
        assert hasattr(BeliefType, 'PREDICTIVE')
        assert hasattr(BeliefType, 'COUNTERFACTUAL')
    
    def test_belief_state_create(self):
        from src.core.free_energy import BeliefState, BeliefType
        b = BeliefState(mean=np.ones(5), precision=np.ones(5), belief_type=BeliefType.PRIOR)
        assert b.mean.shape == (5,)
        assert isinstance(b.surprise(), float)
    
    def test_free_energy_computer(self):
        from src.core.free_energy import FreeEnergyComputer, BeliefState, BeliefType
        fc = FreeEnergyComputer(temperature=1.0)
        b = BeliefState(mean=np.ones(5), precision=np.ones(5))
        obs = np.ones(5) * 0.9
        fe = fc.compute(b, obs)
        assert isinstance(fe, float)
        assert len(fc.history) == 1
        trend = fc.get_trend()
        assert trend in ("decreasing", "increasing", "stable", "insufficient_data")
    
    def test_precision_weighting(self):
        from src.core.free_energy import PrecisionWeighting
        pw = PrecisionWeighting(sensory_precision=1.0, prior_precision=1.0)
        result = pw.weight(np.array([1.0, 2.0]), np.array([0.5, 0.5]))
        assert result.shape == (2,)
        pw.update_precisions(0.1)
        assert pw.sensory_precision != 1.0
    
    def test_criticality_regulator(self):
        from src.core.free_energy import CriticalityRegulator
        cr = CriticalityRegulator(target_branching_ratio=1.0)
        activity = np.random.randn(100)
        deviation = cr.assess(activity)
        assert isinstance(deviation, float)
        assert isinstance(cr.is_critical, bool)
    
    def test_free_energy_agent(self):
        from src.core.free_energy import FreeEnergyAgent
        agent = FreeEnergyAgent()
        obs = np.ones(8)
        belief = agent.perceive(obs)
        assert belief.mean.shape == (8,)
        action = agent.act(belief, np.zeros(8))
        assert action.shape == (8,)
        stats = agent.get_stats()
        assert 'num_beliefs' in stats


class TestActiveInference:
    """主动推理引擎基本合约"""
    
    def test_policy_and_model(self):
        from src.core.active_inference import Policy, GenerativeModel, ActionType
        policy = Policy(actions=[ActionType.EXPLORE, ActionType.EXPLOIT])
        assert len(policy.actions) == 2
        model = GenerativeModel(state_dim=4, obs_dim=4)
        state = np.ones(4) / 4
        obs = model.generate_observation(state)
        assert obs.shape == (4,)
    
    def test_engine_step(self):
        from src.core.active_inference import ActiveInferenceEngine
        engine = ActiveInferenceEngine(state_dim=8, obs_dim=8)
        obs = np.random.randn(8) * 0.1
        goal = np.ones(8)
        result = engine.step(obs, goal)
        assert 'state' in result
        assert 'actions' in result
        assert 'prediction_error' in result
    
    def test_dual_process(self):
        from src.core.active_inference import DualProcessDecision
        dpd = DualProcessDecision()
        intuition = np.array([1.0, 0.0])
        reasoning = np.array([0.0, 1.0])
        decision = dpd.decide(intuition, reasoning)
        assert decision.shape == (2,)
        dpd.adapt_weights(0.6)
        assert dpd.system2_weight > 0.3


class TestGlobalWorkspace:
    """全局工作空间基本合约"""
    
    def test_processor_types(self):
        from src.core.global_workspace import ProcessorType
        assert hasattr(ProcessorType, 'SENSORY')
        assert hasattr(ProcessorType, 'MEMORY')
        assert hasattr(ProcessorType, 'METACOGNITIVE')
    
    def test_workspace_broadcast(self):
        from src.core.global_workspace import GlobalWorkspace, ProcessorType
        gw = GlobalWorkspace()
        gw.register_processor("vision", ProcessorType.SENSORY)
        gw.register_processor("memory", ProcessorType.MEMORY)
        assert len(gw.processors) == 2
        signal = np.random.randn(8)
        gw.broadcast(signal)
        content = gw.get_conscious_content()
        stats = gw.get_stats()
        assert stats['num_processors'] == 2
    
    def test_attention_bottleneck(self):
        from src.core.global_workspace import AttentionBottleneck, Processor, ProcessorType
        ab = AttentionBottleneck(capacity=1)
        procs = [
            Processor("a", ProcessorType.SENSORY, activation=0.3, salience=0.8),
            Processor("b", ProcessorType.MEMORY, activation=0.5, salience=0.3),
        ]
        selected = ab.select(procs)
        assert len(selected) == 1
        assert selected[0].name == "a"


class TestHomeostasis:
    """内稳态调节器基本合约"""
    
    def test_resource_budget(self):
        from src.core.homeostasis import ResourceBudget, ResourceType
        budget = ResourceBudget(ResourceType.CPU, 100.0)
        assert budget.available == 100.0
        assert budget.consume(30.0)
        assert budget.available == 70.0
        assert not budget.is_critical
    
    def test_regulator_assess(self):
        from src.core.homeostasis import HomeostaticRegulator, SystemMode
        reg = HomeostaticRegulator()
        mode = reg.assess()
        assert mode == SystemMode.ACTIVE
        reg.regulate()
        stats = reg.get_stats()
        assert stats['mode'] == 'active'
    
    def test_marginal_utility(self):
        from src.core.homeostasis import MarginalUtilityScheduler, ResourceBudget, ResourceType
        mus = MarginalUtilityScheduler()
        mus.register_task("task_a", value=10.0, cost=2.0)
        mus.register_task("task_b", value=5.0, cost=1.0)
        assert mus.marginal_utility("task_a") == 5.0
        budget = ResourceBudget(ResourceType.CPU, 5.0)
        scheduled = mus.schedule(budget)
        assert len(scheduled) >= 1


class TestBrainRouter:
    """脑启发路由器基本合约"""
    
    def test_symbolic_projector(self):
        from src.core.brain_router import SymbolicProjector
        sp = SymbolicProjector(symbol_dim=32, vector_dim=128)
        vec = sp.encode("hello")
        assert vec.shape == (128,)
        decoded = sp.decode(vec, top_k=1)
        assert len(decoded) > 0
    
    def test_sparse_attention(self):
        from src.core.brain_router import SparseAttentionRouter
        sar = SparseAttentionRouter(num_experts=8, sparsity=2)
        query = np.random.randn(64) * 0.1
        scores = sar.route(query)
        assert scores.shape == (8,)
        assert np.count_nonzero(scores) <= 2
    
    def test_psi_complexity(self):
        from src.core.brain_router import PsiParameterizedComplexity
        psc = PsiParameterizedComplexity()
        psi = psc.estimate("gpt-4", params=1000000000000)
        assert psi > 0
        optimal = psc.get_optimal_model(5.0, ["small-model", "medium-model", "large-model"])
        assert optimal in ["small-model", "medium-model", "large-model"]
    
    def test_brain_inspired_router(self):
        from src.core.brain_router import BrainInspiredRouter
        bir = BrainInspiredRouter()
        result = bir.route("test query", ["model-a", "model-b", "model-c"])
        assert result in ["model-a", "model-b", "model-c"]
        stats = bir.get_stats()
        assert 'projector' in stats


class TestSuperBrain:
    """超级大脑编排器基本合约"""
    
    def test_hippocampal_replay(self):
        from src.core.super_brain import HippocampalReplay
        hp = HippocampalReplay(max_traces=50)
        for i in range(20):
            hp.encode(f"memory {i}", emotional_tag=0.5 if i % 2 == 0 else -0.3)
        assert len(hp.traces) == 20
        # New traces: should_replay may or may not return True
        can_replay = hp.should_replay()
        assert isinstance(can_replay, bool)
    
    def test_salience_tagger(self):
        from src.core.super_brain import SalienceTagger
        st = SalienceTagger()
        s = st.tag("test", novelty=0.8, emotion=0.5, relevance=0.7)
        assert 0.0 <= s <= 1.0
        assert 0.0 <= st.average_salience() <= 1.0
    
    def test_thalamic_gate(self):
        from src.core.super_brain import ThalamicGate
        tg = ThalamicGate()
        assert tg.gate(0.8, 0.9)
        tg.adapt(overload=True)
        assert tg.gate_openness < 0.7
    
    def test_iit_consciousness(self):
        from src.core.super_brain import IITConsciousness
        iit = IITConsciousness()
        state = np.random.randn(10) * 0.5
        phi = iit.compute_phi(state)
        assert isinstance(phi, float)
        assert iit.average_phi() >= 0
    
    def test_super_brain_orchestrator(self):
        from src.core.super_brain import SuperBrainOrchestrator
        sbo = SuperBrainOrchestrator()
        result = sbo.step("test observation", goal="test goal")
        assert 'salience' in result
        assert 'phi' in result
        assert 'internal_state' in result
        stats = sbo.get_stats()
        assert stats['step_count'] == 1
        assert 'avg_phi' in stats
    
    def test_emotional_consolidation(self):
        from src.core.super_brain import EmotionalConsolidation
        ec = EmotionalConsolidation()
        ec.tag("happy memory", valence=0.8, arousal=0.6)
        ec.tag("neutral memory", valence=0.0, arousal=0.2)
        consolidated = ec.consolidate()
        assert "happy memory" in consolidated
        state = ec.emotional_state()
        assert 'valence' in state
    
    def test_stdp_learner(self):
        from src.core.super_brain import STDPLearner
        stdp = STDPLearner()
        delta_w = stdp.stdp(0, 1, delta_t=10.0)
        assert delta_w > 0
        delta_w_neg = stdp.stdp(0, 1, delta_t=-10.0)
        assert delta_w_neg < 0
        stdp.update_weight(0, 1, 100.0, 110.0)
        assert stdp.weights[0, 1] != 0.5

    def test_default_mode_network(self):
        from src.core.super_brain import DefaultModeNetwork
        dmn = DefaultModeNetwork()
        intro = dmn.introspect()
        assert 'confidence' in intro
        daydream = dmn.mind_wander()
        assert isinstance(daydream, str)
        dmn.update_self_model(success=True)
        assert dmn.self_model['confidence'] > 0.6

    def test_conflict_monitor(self):
        from src.core.super_brain import ConflictMonitor
        cm = ConflictMonitor()
        options = [("A", 0.8), ("B", 0.75), ("C", 0.3)]
        conflict = cm.detect(options)
        assert 0.0 <= conflict <= 1.0

    def test_action_selector(self):
        from src.core.super_brain import ActionSelector
        aselect = ActionSelector()
        aselect.register_action("explore", 0.5)
        aselect.register_action("exploit", 0.7)
        action = aselect.select(np.array([0.5, 0.3]))
        assert action in ("explore", "exploit", "wait")
        aselect.update_value("exploit", 1.0)
        assert aselect.action_values["exploit"] > 0.7

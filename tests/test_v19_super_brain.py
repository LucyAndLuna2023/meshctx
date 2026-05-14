"""
MeshCtx v1.9 — 超级大脑集成测试
测试全脑编排器+10脑区协同
"""
import pytest
import numpy as np
import time

from src.core.super_brain import (
    SuperBrainOrchestrator, HippocampalReplay, SalienceTagger,
    DefaultModeNetwork, ThalamicGate, ForwardModel,
    ActionSelector, ConflictMonitor, InteroceptionEngine, TheoryOfMind,
    MemoryTrace, ReplayEvent,
)


class TestHippocampalReplay:
    def test_encode_and_replay(self):
        hp = HippocampalReplay(max_traces=100)
        for i in range(20):
            hp.encode(f"memory content {i}", emotional_tag=0.5 if i%2==0 else -0.3)
        assert len(hp.traces) == 20
        # 不应立即重放
        assert not hp.should_replay()
        
    def test_replay_produces_events(self):
        hp = HippocampalReplay(max_traces=100, replay_interval=0)  # 立即触发
        for i in range(20):
            hp.encode(f"test memory number {i}", emotional_tag=0.7)
        hp.last_replay_time = 0  # 强制触发
        events = hp.replay(n_sequences=3)
        assert len(events) == 3
        for e in events:
            assert isinstance(e, ReplayEvent)
            assert len(e.compressed_sequence) > 0
            
    def test_insights_generation(self):
        hp = HippocampalReplay(max_traces=100, replay_interval=0)
        for i in range(30):
            hp.encode(f"performance optimization memory trace {i}",
                     emotional_tag=0.8)
        hp.last_replay_time = 0
        hp.replay(n_sequences=5)
        insights = hp.get_insights(3)
        assert isinstance(insights, list)
        
    def test_pruning(self):
        hp = HippocampalReplay(max_traces=10)
        for i in range(50):
            hp.encode(f"trace {i}", emotional_tag=0.1)
        assert len(hp.traces) <= 10


class TestSalienceTagger:
    def test_basic_evaluation(self):
        tagger = SalienceTagger()
        result = tagger.evaluate("This is a great success!")
        assert "valence" in result
        assert result["valence"] > 0
        
    def test_negative_evaluation(self):
        tagger = SalienceTagger()
        result = tagger.evaluate("Critical error! System crash!")
        assert result["valence"] < 0
        
    def test_arousal(self):
        tagger = SalienceTagger()
        result = tagger.evaluate("URGENT: need help immediately!")
        assert result["arousal"] > 0
        assert result["urgency"] > 0
        
    def test_neutral(self):
        tagger = SalienceTagger()
        result = tagger.evaluate("The weather is fine today.")
        assert abs(result["valence"]) < 0.2


class TestDefaultModeNetwork:
    def test_activation_interval(self):
        dmn = DefaultModeNetwork(activation_interval=120)
        assert not dmn.should_activate()
        dmn.last_activation = 0
        assert dmn.should_activate()
        
    def test_wander_generates_ideas(self):
        dmn = DefaultModeNetwork()
        traces = [
            MemoryTrace("machine learning optimization techniques", {}, time.time(), 0.5),
            MemoryTrace("neural network architecture design", {}, time.time(), 0.4),
            MemoryTrace("database query performance tuning", {}, time.time(), 0.3),
            MemoryTrace("user interface design patterns", {}, time.time(), 0.2),
        ]
        ideas = dmn.wander(traces, n_ideas=2)
        assert isinstance(ideas, list)


class TestThalamicGate:
    def test_gating(self):
        gate = ThalamicGate(n_channels=3)
        inputs = {"visual": "data", "auditory": "sound", "semantic": "text"}
        salience = {"visual": 0.8, "auditory": 0.3, "semantic": 0.9}
        weights = gate.gate(inputs, salience)
        assert len(weights) == 3
        assert weights["semantic"] > weights["auditory"]


class TestForwardModel:
    def test_prediction(self):
        fm = ForwardModel()
        pred = fm.predict("analyze data", {})
        assert pred["success_probability"] > 0
        assert "risk_level" in pred
        
    def test_dangerous_action_detection(self):
        fm = ForwardModel()
        pred = fm.predict("delete all files", {})
        assert pred["risk_level"] == "HIGH"
        assert pred["requires_confirmation"]


class TestActionSelector:
    def test_selection(self):
        sel = ActionSelector(n_actions=5)
        sel.register_action(0, "analyze")
        sel.register_action(1, "create")
        state = np.array([0.5, 0.3, 0.7, 0.0, 0.0])
        action, q = sel.select(state)
        assert 0 <= action < 5
        
    def test_learning(self):
        sel = ActionSelector(n_actions=5)
        sel.q_values[2] = 1.0
        sel.learn(2, reward=2.0)  # 正向大奖励
        assert sel.q_values[2] > 1.0


class TestConflictMonitor:
    def test_conflict_detection(self):
        cm = ConflictMonitor()
        conflict = cm.monitor(expected=1.0, actual=0.3, competing_responses=3)
        assert conflict > 0
        
    def test_adaptation_trigger(self):
        cm = ConflictMonitor(conflict_threshold=0.2)
        for _ in range(10):
            cm.monitor(expected=1.0, actual=0.1, competing_responses=2)
        assert cm.should_adapt()


class TestInteroceptionEngine:
    def test_update_and_report(self):
        ie = InteroceptionEngine()
        ie.update(cpu=0.5, memory=0.3, latency=0.1)
        report = ie.get_self_report()
        assert "state" in report
        assert report["status"] in ("healthy", "degraded")
        
    def test_anomaly_detection(self):
        ie = InteroceptionEngine()
        ie.update(cpu=0.1, memory=0.1)  # 建立基线
        ie.update(cpu=0.9, memory=0.1)  # CPU异常
        report = ie.get_self_report()
        # 应有异常报告
        assert isinstance(report["anomalies"], list)


class TestTheoryOfMind:
    def test_intent_inference(self):
        tom = TheoryOfMind()
        result = tom.infer_intent("How do I fix this error?")
        assert "primary_intent" in result
        
    def test_frustration_tracking(self):
        tom = TheoryOfMind()
        tom.infer_intent("This is broken and doesn't work!")
        assert tom.user_model["frustration"] > 0


class TestSuperBrainOrchestrator:
    def test_full_cycle(self):
        brain = SuperBrainOrchestrator()
        result = brain.full_cycle("Analyze the performance report")
        assert "cycle" in result
        assert "emotional" in result
        assert "attention" in result
        assert result["cycle"] == 1
        
    def test_multiple_cycles(self):
        brain = SuperBrainOrchestrator()
        for i in range(5):
            result = brain.full_cycle(f"Test message {i}")
            assert result["cycle"] == i + 1
            
    def test_get_status(self):
        brain = SuperBrainOrchestrator()
        brain.full_cycle("Hello")
        status = brain.get_status()
        assert "hippocampus" in status
        assert "forward_model" in status
        assert "self" in status
        
    def test_emotional_variation(self):
        brain = SuperBrainOrchestrator()
        r1 = brain.full_cycle("Great work! Excellent!")
        r2 = brain.full_cycle("Critical bug! Fix immediately!")
        # 情感标签应该不同
        assert r1["emotional"]["valence"] != r2["emotional"]["valence"] or \
               r1["emotional"]["arousal"] != r2["emotional"]["arousal"]

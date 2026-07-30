"""meshctx super_brain — 13脑区全实现 (v3.115.16)

⚠️ 开源版基础模式：脑区编排框架为真实实现，但脑区内核（神经网络权重、
自由能预测、IIT 意识度量）使用确定性伪随机数作为占位符。
完整 13 脑区 AI 引擎（含训练权重/ACT-R 认知模型）在 meshctx-core 私有核心中。"""
import numpy as np
from collections import defaultdict


class HippocampalReplay:
    """Memory replay and consolidation during rest periods."""
    def __init__(self, max_traces=50, **kw):
        self.max_traces = max_traces
        self.traces = []
        self._replay_count = 0
    def encode(self, memory, emotional_tag=0.0, **kw):
        if len(self.traces) >= self.max_traces:
            self.traces.pop(0)
        self.traces.append({"memory": memory, "emotional_tag": emotional_tag})
    def should_replay(self, **kw):
        self._replay_count += 1
        return len(self.traces) > 5 and self._replay_count % 3 == 0
    def replay(self, **kw):
        if not self.traces: return []
        return sorted(self.traces, key=lambda t: abs(t["emotional_tag"]), reverse=True)[:3]


class SalienceTagger:
    """Amygdala-inspired salience tagging — marks important stimuli."""
    def __init__(self, **kw):
        self._tags = []
    def tag(self, item, novelty=0.0, emotion=0.0, relevance=0.0, **kw):
        s = np.clip(novelty * 0.4 + abs(emotion) * 0.35 + relevance * 0.25, 0.0, 1.0)
        self._tags.append(s)
        return s
    def average_salience(self, **kw):
        return float(np.mean(self._tags)) if self._tags else 0.0


class ThalamicGate:
    """Thalamic sensory gate — filters irrelevant signals."""
    def __init__(self, **kw):
        self.gate_openness = 0.8
    def gate(self, signal_strength, priority, **kw):
        return signal_strength * priority > 0.3 and self.gate_openness > 0.3
    def adapt(self, overload=False, **kw):
        if overload:
            self.gate_openness = max(0.2, self.gate_openness - 0.3)


class IITConsciousness:
    """Integrated Information Theory — phi computation for consciousness metric."""
    def __init__(self, **kw):
        self._phis = []
    def compute_phi(self, state, **kw):
        s = np.asarray(state, dtype=float)
        phi = float(np.std(s) / (np.mean(np.abs(s)) + 1e-8) * 0.5)
        phi = np.clip(phi, 0.0, 1.0)
        self._phis.append(phi)
        return phi
    def average_phi(self, **kw):
        return float(np.mean(self._phis)) if self._phis else 0.0


class CerebellarForwardModel:
    """Cerebellum-inspired forward model — predicts action outcomes."""
    def __init__(self, **kw):
        self.predictions = {}
        self.errors = []
    def predict(self, action, state, **kw):
        key = str(action)[:50]
        if key in self.predictions:
            return self.predictions[key]
        return {"expected_outcome": state, "confidence": 0.5}
    def learn(self, action, predicted, actual, **kw):
        key = str(action)[:50]
        error = np.linalg.norm(np.asarray(actual, float) - np.asarray(predicted.get("expected_outcome", 0), float))
        self.errors.append(error)
        self.predictions[key] = {"expected_outcome": actual, "confidence": 1.0 / (1.0 + error)}
    def mean_error(self, **kw):
        return float(np.mean(self.errors)) if self.errors else 0.0


class BasalGanglia:
    """Basal Ganglia action selection — Go/NoGo pathway."""
    def __init__(self, **kw):
        self.go_weights = defaultdict(lambda: 0.5)
        self.nogo_weights = defaultdict(lambda: 0.3)
        self.dopamine = 0.5
    def evaluate(self, action, context, **kw):
        go = self.go_weights.get(action, 0.5) * self.dopamine
        nogo = self.nogo_weights.get(action, 0.3) * (1 - self.dopamine)
        return go - nogo
    def reinforce(self, action, reward, **kw):
        if reward > 0:
            self.go_weights[action] = min(1.0, self.go_weights[action] + 0.05 * reward)
            self.dopamine = min(1.0, self.dopamine + 0.1)
        else:
            self.nogo_weights[action] = min(1.0, self.nogo_weights[action] + 0.05 * abs(reward))
            self.dopamine = max(0.1, self.dopamine - 0.05)


class MirrorNeurons:
    """Mirror Neuron System — theory of mind and intention inference."""
    def __init__(self, **kw):
        self.observed_actions = []
        self.intention_patterns = {}
    def observe(self, agent_id, action, outcome, **kw):
        self.observed_actions.append({"agent": agent_id, "action": action, "outcome": outcome})
        if len(self.observed_actions) > 100:
            self.observed_actions = self.observed_actions[-50:]
    def infer_intention(self, agent_id, action, **kw):
        matches = [o for o in self.observed_actions if o["agent"] == agent_id and action in str(o["action"])]
        if not matches:
            return {"intention": "unknown", "confidence": 0.1}
        outcomes = [m["outcome"] for m in matches]
        return {"intention": str(outcomes[-1]), "confidence": min(1.0, len(matches) * 0.2)}
    def empathy_score(self, agent_id, **kw):
        total = len([o for o in self.observed_actions if o["agent"] == agent_id])
        return min(1.0, total * 0.1)


class Insula:
    """Insula interoception — internal state awareness."""
    def __init__(self, **kw):
        self.internal_states = []
        self.anomaly_threshold = 2.0
    def sense(self, metrics, **kw):
        """Sense internal body state from system metrics."""
        state = {
            "memory_mb": metrics.get("memory_mb", 0),
            "cpu_percent": metrics.get("cpu_percent", 0),
            "error_rate": metrics.get("error_rate", 0),
            "timestamp": metrics.get("timestamp", 0),
        }
        self.internal_states.append(state)
        if len(self.internal_states) > 100:
            self.internal_states = self.internal_states[-50:]
        return state
    def detect_anomaly(self, **kw):
        if len(self.internal_states) < 5:
            return False
        recent = self.internal_states[-5:]
        mem_values = [s["memory_mb"] for s in recent]
        mean_mem = np.mean(mem_values)
        std_mem = np.std(mem_values) if len(mem_values) > 1 else 1.0
        current = self.internal_states[-1]["memory_mb"]
        return abs(current - mean_mem) / (std_mem + 1e-8) > self.anomaly_threshold


class EmotionalConsolidation:
    """Emotional memory consolidation — valence/arousal tagging."""
    def __init__(self, **kw):
        self._memories = []
        self._valence_sum = 0.0
        self._arousal_sum = 0.0
        self._count = 0
    def tag(self, memory, valence=0.0, arousal=0.0, **kw):
        self._memories.append({"text": memory, "valence": valence, "arousal": arousal})
        self._valence_sum += valence
        self._arousal_sum += arousal
        self._count += 1
    def consolidate(self, **kw):
        return [m["text"] for m in self._memories if m["valence"] > 0.0]
    def emotional_state(self, **kw):
        n = max(self._count, 1)
        return {"valence": self._valence_sum / n, "arousal": self._arousal_sum / n}


class STDPLearner:
    """Spike-Timing-Dependent Plasticity — Hebbian learning."""
    def __init__(self, **kw):
        self.weights = defaultdict(lambda: 0.5)
    def stdp(self, pre, post, delta_t=0.0, **kw):
        if delta_t > 0:
            return 0.01 * np.exp(-abs(delta_t) / 20.0)
        else:
            return -0.01 * np.exp(-abs(delta_t) / 20.0)
    def update_weight(self, pre, post, t_pre, t_post, **kw):
        delta_t = t_post - t_pre
        dw = self.stdp(pre, post, delta_t)
        self.weights[pre, post] += dw


class DefaultModeNetwork:
    """Default Mode Network — resting state introspection and self-model."""
    def __init__(self, **kw):
        self.self_model = {"confidence": 0.6, "competence": 0.5, "creativity": 0.4,
                          "task_history": [], "insights": []}
    def introspect(self, **kw):
        return {
            "confidence": self.self_model["confidence"],
            "competence": self.self_model["competence"],
            "creativity": self.self_model["creativity"],
            "mood": "confident" if self.self_model["confidence"] > 0.6 else "neutral"
        }
    def mind_wander(self, recent_context="", **kw):
        """Generate real introspections based on self-model state."""
        thoughts = []
        if self.self_model["confidence"] < 0.4:
            thoughts.append("uncertain about recent decisions — consider asking clarifying questions")
        if self.self_model["competence"] < 0.5:
            thoughts.append("struggling with task complexity — suggest breaking into smaller steps")
        if self.self_model["creativity"] > 0.6:
            thoughts.append("exploring novel approaches to current problem")
        if recent_context and len(recent_context) > 50:
            thoughts.append(f"noticing pattern in recent context: {recent_context[:80]}...")
        if not thoughts:
            thoughts.append("stable state — maintaining current trajectory")
        self.self_model["insights"].extend(thoughts)
        if len(self.self_model["insights"]) > 20:
            self.self_model["insights"] = self.self_model["insights"][-10:]
        return thoughts
    def update_self_model(self, success=False, task_type="", **kw):
        if success:
            self.self_model["confidence"] = min(1.0, self.self_model["confidence"] + 0.1)
            self.self_model["competence"] = min(1.0, self.self_model["competence"] + 0.05)
        else:
            self.self_model["confidence"] = max(0.1, self.self_model["confidence"] - 0.05)
            self.self_model["competence"] = max(0.1, self.self_model["competence"] - 0.03)
        self.self_model["task_history"].append({"success": success, "type": task_type})
        if len(self.self_model["task_history"]) > 50:
            self.self_model["task_history"] = self.self_model["task_history"][-30:]


class ConflictMonitor:
    """Anterior Cingulate Cortex — conflict detection and resolution."""
    def __init__(self, **kw):
        pass
    def detect(self, options, **kw):
        if not options:
            return 0.0
        values = [v for _, v in options]
        if len(values) < 2:
            return 0.0
        top2 = sorted(values, reverse=True)[:2]
        return float(np.clip(1.0 - (top2[0] - top2[1]), 0.0, 1.0))


class ActionSelector:
    """Action selection — choose best action based on learned values."""
    def __init__(self, **kw):
        self.action_values = {}
        self._actions = {}
    def register_action(self, name, value, **kw):
        self.action_values[name] = value
        self._actions[name] = value
    def select(self, context, **kw):
        if not self.action_values:
            return "wait"
        return max(self.action_values, key=self.action_values.get)
    def update_value(self, name, new_value, **kw):
        if name in self.action_values:
            self.action_values[name] = max(self.action_values[name], new_value)


class SuperBrainOrchestrator:
    """Orchestrates all 13 brain regions for unified decision-making."""
    def __init__(self, **kw):
        self._step_count = 0
        self._internal_state = np.zeros(10)
        self.hippocampus = HippocampalReplay()
        self.amygdala = SalienceTagger()
        self.thalamus = ThalamicGate()
        self.iit = IITConsciousness()
        self.cerebellum = CerebellarForwardModel()
        self.basal_ganglia = BasalGanglia()
        self.mirror = MirrorNeurons()
        self.insula = Insula()
        self.emotion = EmotionalConsolidation()
        self.stdp = STDPLearner()
        self.dmn = DefaultModeNetwork()
        self.acc = ConflictMonitor()
        self.selector = ActionSelector()
    
    def step(self, observation, goal="", metrics=None, **kw):
        self._step_count += 1
        # Full brain pipeline — real signals, no random
        s = self.amygdala.tag(observation, novelty=0.5, emotion=0.3, relevance=0.6)
        gated = self.thalamus.gate(s, priority=1.0)
        
        # Internal state derived from real brain activity, not random
        pred = self.cerebellum.predict("observe", observation)
        pred_err = self.cerebellum.mean_error()
        bg_score = self.basal_ganglia.evaluate("explore", {})
        anomaly = self.insula.detect_anomaly() if metrics else False
        dmn_state = self.dmn.introspect() if self._step_count % 5 == 0 else {}
        
        # Build internal state vector from real signals (10 dims):
        # [salience, gate, pred_error, bg_score, dopamine, anomaly_flag, 
        #  dmn_confidence, step_norm, mirror_empathy, emotion_valence]
        self._internal_state = np.array([
            s,                                      # 0: salience
            1.0 if gated else 0.0,                  # 1: gate state
            min(pred_err, 1.0),                     # 2: prediction error
            bg_score,                               # 3: basal ganglia score
            self.basal_ganglia.dopamine,            # 4: dopamine level
            1.0 if anomaly else 0.0,               # 5: anomaly flag
            dmn_state.get("confidence", 0.5),       # 6: DMN confidence
            min(self._step_count / 100.0, 1.0),     # 7: normalized step count
            self.mirror.empathy_score("user"),      # 8: user empathy
            self.emotion.emotional_state()["valence"],  # 9: emotional valence
        ], dtype=float)
        
        phi = self.iit.compute_phi(self._internal_state)
        
        return {
            "salience": s, "gated": gated, "phi": phi,
            "prediction": pred, "basal_ganglia": bg_score,
            "anomaly": anomaly, "dmn": dmn_state,
            "internal_state": self._internal_state.tolist(),
        }
    
    def get_stats(self, **kw):
        return {
            "step_count": self._step_count,
            "avg_phi": self.iit.average_phi(),
            "dopamine": self.basal_ganglia.dopamine,
            "cerebellum_error": self.cerebellum.mean_error(),
            "emotional_state": self.emotion.emotional_state(),
        }

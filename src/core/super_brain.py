"""
MeshCtx v3.35 — SuperBrain Orchestrator (全脑编排器)
10脑区协同: 海马回放/DMN/丘脑门控/前向模型/动作选择/冲突监控/
内感觉/心理理论/STDP学习/情绪巩固/IIT意识
"""
import time
import math
import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple


@dataclass
class MemoryTrace:
    """记忆痕迹"""
    content: str
    timestamp: float = field(default_factory=time.time)
    emotional_tag: float = 0.0
    importance: float = 0.5
    replay_count: int = 0


@dataclass
class ReplayEvent:
    """回放事件"""
    trace: MemoryTrace
    time: float = field(default_factory=time.time)
    context: str = ""


class HippocampalReplay:
    """海马回放 — 记忆巩固+模式完成"""
    
    def __init__(self, max_traces: int = 100):
        self.traces: List[MemoryTrace] = []
        self.max_traces = max_traces
        self.replay_events: List[ReplayEvent] = []
    
    def encode(self, content: str, emotional_tag: float = 0.0):
        trace = MemoryTrace(content=content, emotional_tag=emotional_tag)
        self.traces.append(trace)
        if len(self.traces) > self.max_traces:
            self.traces = self.traces[-self.max_traces:]
    
    def should_replay(self) -> bool:
        if not self.traces:
            return False
        recent = [t for t in self.traces if time.time() - t.timestamp < 300]
        return len(recent) >= 5
    
    def replay(self, top_k: int = 3) -> List[ReplayEvent]:
        if not self.traces:
            return []
        sorted_traces = sorted(self.traces, key=lambda t: abs(t.emotional_tag) * t.importance, reverse=True)
        events = []
        for trace in sorted_traces[:top_k]:
            trace.replay_count += 1
            events.append(ReplayEvent(trace=trace))
        self.replay_events.extend(events)
        return events


class SalienceTagger:
    """突显标记器 — 评估信息重要性"""
    
    def __init__(self):
        self.tag_history: List[float] = []
    
    def tag(self, content: str, novelty: float, emotion: float, relevance: float) -> float:
        salience = 0.4 * novelty + 0.3 * abs(emotion) + 0.3 * relevance
        self.tag_history.append(salience)
        return min(1.0, max(0.0, salience))
    
    def average_salience(self) -> float:
        return float(np.mean(self.tag_history)) if self.tag_history else 0.5


class DefaultModeNetwork:
    """默认模式网络 — 自发思维+自我参照"""
    
    def __init__(self):
        self.self_model: Dict[str, float] = {"competence": 0.7, "confidence": 0.6, "curiosity": 0.8}
        self.daydreams: List[str] = []
    
    def introspect(self) -> Dict[str, float]:
        return dict(self.self_model)
    
    def mind_wander(self) -> str:
        topics = ["What if we tried a different approach?", "What have we learned recently?",
                   "Are there connections we haven't made?", "What would a better version look like?"]
        topic = topics[len(self.daydreams) % len(topics)]
        self.daydreams.append(topic)
        return topic
    
    def update_self_model(self, success: bool):
        if success:
            self.self_model["confidence"] = min(1.0, self.self_model["confidence"] + 0.05)
            self.self_model["competence"] = min(1.0, self.self_model["competence"] + 0.02)
        else:
            self.self_model["confidence"] = max(0.1, self.self_model["confidence"] - 0.03)


class ThalamicGate:
    """丘脑门控 — 感觉信息筛选"""
    
    def __init__(self):
        self.gate_openness: float = 0.7
        self.filtered_count: int = 0
        self.passed_count: int = 0
    
    def gate(self, signal_strength: float, priority: float) -> bool:
        threshold = 1.0 - self.gate_openness
        passed = (signal_strength * priority) > threshold
        if passed:
            self.passed_count += 1
        else:
            self.filtered_count += 1
        return passed
    
    def adapt(self, overload: bool):
        if overload:
            self.gate_openness = max(0.2, self.gate_openness - 0.1)
        else:
            self.gate_openness = min(1.0, self.gate_openness + 0.05)
    
    @property
    def filter_ratio(self) -> float:
        total = self.filtered_count + self.passed_count
        return self.filtered_count / total if total > 0 else 0.0


class ForwardModel:
    """前向模型 — 行动结果预测"""
    
    def __init__(self):
        self.predictions: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []  # (state, action, outcome)
    
    def predict(self, state: np.ndarray, action: np.ndarray) -> np.ndarray:
        return 0.8 * state + 0.2 * action
    
    def learn(self, state: np.ndarray, action: np.ndarray, actual_outcome: np.ndarray):
        self.predictions.append((state.copy(), action.copy(), actual_outcome.copy()))
        if len(self.predictions) > 50:
            self.predictions = self.predictions[-50:]
    
    def prediction_error(self, state: np.ndarray, action: np.ndarray, outcome: np.ndarray) -> float:
        predicted = self.predict(state, action)
        return float(np.linalg.norm(predicted - outcome))


class ActionSelector:
    """动作选择器 — 基底节决策"""
    
    def __init__(self):
        self.action_values: Dict[str, float] = {}
        self.exploration_rate: float = 0.1
    
    def register_action(self, name: str, initial_value: float = 0.5):
        self.action_values[name] = initial_value
    
    def select(self, state: np.ndarray) -> str:
        if not self.action_values:
            return "wait"
        if np.random.random() < self.exploration_rate:
            return np.random.choice(list(self.action_values.keys()))
        return max(self.action_values, key=self.action_values.get)
    
    def update_value(self, action: str, reward: float, learning_rate: float = 0.1):
        if action in self.action_values:
            self.action_values[action] += learning_rate * (reward - self.action_values[action])


class ConflictMonitor:
    """冲突监控器 — ACC认知冲突检测"""
    
    def __init__(self):
        self.conflict_level: float = 0.0
        self.conflict_history: List[float] = []
    
    def detect(self, options: List[Tuple[str, float]]) -> float:
        if len(options) < 2:
            return 0.0
        values = [v for _, v in options]
        top2 = sorted(values, reverse=True)[:2]
        self.conflict_level = float(1.0 - (top2[0] - top2[1]) / (top2[0] + 1e-10))
        self.conflict_history.append(self.conflict_level)
        return self.conflict_level
    
    def needs_more_processing(self) -> bool:
        return self.conflict_level > 0.5


class InteroceptionEngine:
    """内感觉引擎 — 系统内部状态感知"""
    
    def __init__(self):
        self.internal_state: Dict[str, float] = {"cpu": 0.3, "memory": 0.4, "error_rate": 0.0,
                                                   "response_latency": 0.2, "temperature": 37.0}
    
    def sense(self) -> Dict[str, float]:
        self.internal_state["temperature"] += np.random.normal(0, 0.1)
        self.internal_state["temperature"] = max(36.0, min(39.0, self.internal_state["temperature"]))
        return dict(self.internal_state)
    
    def is_stressed(self) -> bool:
        return (self.internal_state.get("error_rate", 0) > 0.3 or
                self.internal_state.get("response_latency", 0) > 0.7)


class TheoryOfMind:
    """心理理论 — 推断他人意图/信念"""
    
    def __init__(self):
        self.other_models: Dict[str, Dict[str, float]] = {}
    
    def model_other(self, other_id: str, belief: str, confidence: float):
        if other_id not in self.other_models:
            self.other_models[other_id] = {}
        self.other_models[other_id][belief] = confidence
    
    def infer_intention(self, other_id: str, context: str) -> Optional[str]:
        if other_id not in self.other_models:
            return None
        beliefs = self.other_models[other_id]
        return max(beliefs, key=beliefs.get) if beliefs else None
    
    def get_all_models(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self.other_models.items()}


class STDPLearner:
    """STDP学习 — 脉冲时序依赖可塑性"""
    
    def __init__(self, tau_plus: float = 20.0, tau_minus: float = 20.0):
        self.tau_plus = tau_plus
        self.tau_minus = tau_minus
        self.weights: np.ndarray = np.ones((10, 10)) * 0.5
        self.spike_times: Dict[int, float] = {}
    
    def stdp(self, pre_idx: int, post_idx: int, delta_t: float) -> float:
        if delta_t > 0:
            return 0.01 * math.exp(-delta_t / self.tau_plus)
        else:
            return -0.01 * math.exp(delta_t / self.tau_minus)
    
    def update_weight(self, pre_idx: int, post_idx: int, pre_time: float, post_time: float):
        if pre_idx < self.weights.shape[0] and post_idx < self.weights.shape[1]:
            delta_t = post_time - pre_time
            dw = self.stdp(pre_idx, post_idx, delta_t)
            self.weights[pre_idx, post_idx] = max(0.0, min(1.0, self.weights[pre_idx, post_idx] + dw))


class EmotionalConsolidation:
    """情绪巩固 — 杏仁核情绪标记+记忆巩固"""
    
    def __init__(self):
        self.emotional_memory: List[Tuple[str, float, float]] = []  # (memory, valence, arousal)
    
    def tag(self, memory: str, valence: float, arousal: float):
        self.emotional_memory.append((memory, valence, arousal))
        if len(self.emotional_memory) > 100:
            self.emotional_memory = self.emotional_memory[-100:]
    
    def consolidate(self) -> List[str]:
        consolidated = []
        for mem, valence, arousal in self.emotional_memory:
            if abs(valence) > 0.5 or arousal > 0.7:
                consolidated.append(mem)
        return consolidated
    
    def emotional_state(self) -> Dict[str, float]:
        if not self.emotional_memory:
            return {"valence": 0.0, "arousal": 0.0}
        valences = [v for _, v, _ in self.emotional_memory[-20:]]
        arousals = [a for _, _, a in self.emotional_memory[-20:]]
        return {"valence": float(np.mean(valences)), "arousal": float(np.mean(arousals))}


class IITConsciousness:
    """IIT意识度量 — 整合信息理论Φ值"""
    
    def __init__(self):
        self.phi_history: List[float] = []
    
    def compute_phi(self, system_state: np.ndarray) -> float:
        if len(system_state) < 2:
            return 0.0
        total_correlation = float(np.sum(np.abs(np.corrcoef(system_state.reshape(-1, 1).T))))
        phi = total_correlation / len(system_state)
        self.phi_history.append(phi)
        return phi
    
    @property
    def is_conscious(self) -> bool:
        return len(self.phi_history) > 0 and self.phi_history[-1] > 0.1
    
    def average_phi(self) -> float:
        return float(np.mean(self.phi_history)) if self.phi_history else 0.0


class SuperBrainOrchestrator:
    """超级大脑编排器 — 10脑区协同控制"""
    
    def __init__(self, **kwargs):
        self.hippocampus = HippocampalReplay()
        self.salience = SalienceTagger()
        self.dmn = DefaultModeNetwork()
        self.thalamus = ThalamicGate()
        self.forward_model = ForwardModel()
        self.action_selector = ActionSelector()
        self.conflict = ConflictMonitor()
        self.interoception = InteroceptionEngine()
        self.tom = TheoryOfMind()
        self.stdp = STDPLearner()
        self.emotion = EmotionalConsolidation()
        self.iit = IITConsciousness()
        self._step_count = 0
    
    def step(self, observation: str, goal: Optional[str] = None) -> Dict[str, Any]:
        self._step_count += 1
        novelty = min(1.0, self._step_count / 100.0)
        salience_score = self.salience.tag(observation, novelty, 0.3, 0.6)
        self.hippocampus.encode(observation, emotional_tag=0.3)
        passed_gate = self.thalamus.gate(salience_score, 0.5)
        state_vec = np.array([salience_score, novelty, 0.5, 0.3])
        phi = self.iit.compute_phi(state_vec)
        if self.hippocampus.should_replay():
            self.hippocampus.replay(top_k=3)
        internal = self.interoception.sense()
        return {
            "salience": salience_score,
            "passed_gate": passed_gate,
            "phi": phi,
            "is_conscious": self.iit.is_conscious,
            "internal_state": internal,
            "daydream": self.dmn.mind_wander() if self._step_count % 5 == 0 else "",
            "emotional_state": self.emotion.emotional_state(),
        }
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "traces": len(self.hippocampus.traces),
            "replay_events": len(self.hippocampus.replay_events),
            "avg_salience": self.salience.average_salience(),
            "gate_openness": self.thalamus.gate_openness,
            "avg_phi": self.iit.average_phi(),
            "is_conscious": self.iit.is_conscious,
            "tom_models": self.tom.get_all_models(),
            "step_count": self._step_count,
        }

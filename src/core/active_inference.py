"""
MeshCtx v3.35 — Active Inference Engine (Friston主动推理)
策略选择+生成模型+多尺度学习
"""
import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class ActionType(Enum):
    EXPLORE = "explore"
    EXPLOIT = "exploit"
    OBSERVE = "observe"
    INTERVENE = "intervene"
    WAIT = "wait"


@dataclass
class Policy:
    """策略 — 动作序列+期望自由能"""
    actions: List[ActionType]
    expected_free_energy: float = 0.0
    prior_probability: float = 0.5


@dataclass
class GenerativeModel:
    """生成模型 — P(o,s|π) 联合分布"""
    state_dim: int
    obs_dim: int
    A: Optional[np.ndarray] = None  # 似然矩阵 P(o|s)
    B: Optional[np.ndarray] = None  # 转移矩阵 P(s'|s,π)
    D: Optional[np.ndarray] = None  # 先验 P(s₀)
    
    def __post_init__(self):
        if self.A is None:
            self.A = np.eye(self.obs_dim, self.state_dim)
        if self.B is None:
            self.B = np.eye(self.state_dim)
        if self.D is None:
            self.D = np.ones(self.state_dim) / self.state_dim
    
    def generate_observation(self, state: np.ndarray) -> np.ndarray:
        return self.A @ state + np.random.normal(0, 0.1, self.obs_dim)
    
    def predict_state(self, state: np.ndarray, policy: Policy) -> np.ndarray:
        return self.B @ state


class MultiScaleLearning:
    """多尺度学习 — 不同时间尺度的模型更新"""
    
    def __init__(self, scales: List[float] = [1.0, 0.1, 0.01]):
        self.scales = scales
        self.parameters: Dict[float, np.ndarray] = {}
    
    def update(self, key: str, gradient: np.ndarray, step: int):
        for scale in self.scales:
            lr = scale / (1.0 + 0.01 * step)
            if key not in self.parameters:
                self.parameters[key] = np.zeros_like(gradient)
            self.parameters[key] += lr * gradient


class LookaheadPlanner:
    """前瞻规划器 — N步前瞻+树搜索"""
    
    def __init__(self, horizon: int = 3):
        self.horizon = horizon
    
    def plan(self, state: np.ndarray, model: GenerativeModel, goal: np.ndarray) -> List[ActionType]:
        best_actions = [ActionType.EXPLORE]
        best_cost = float('inf')
        for _ in range(10):
            actions = [np.random.choice(list(ActionType)) for _ in range(self.horizon)]
            cost = np.linalg.norm(model.predict_state(state, Policy(actions=actions)) - goal)
            if cost < best_cost:
                best_cost = cost
                best_actions = actions
        return best_actions


class DualProcessDecision:
    """双过程决策 — 系统1(快速直觉)+系统2(慢速推理)"""
    
    def __init__(self):
        self.system1_weight: float = 0.7
        self.system2_weight: float = 0.3
    
    def decide(self, intuition: np.ndarray, reasoning: np.ndarray) -> np.ndarray:
        return self.system1_weight * intuition + self.system2_weight * reasoning
    
    def adapt_weights(self, outcome_error: float):
        if abs(outcome_error) > 0.5:
            self.system2_weight = min(0.8, self.system2_weight + 0.05)
            self.system1_weight = 1.0 - self.system2_weight


class ActiveInferenceEngine:
    """主动推理引擎 — 统一感知-行动"""
    
    def __init__(self, state_dim: int = 8, obs_dim: int = 8, **kwargs):
        self.model = GenerativeModel(state_dim=state_dim, obs_dim=obs_dim)
        self.planner = LookaheadPlanner()
        self.decision = DualProcessDecision()
        self.learner = MultiScaleLearning()
        self.state: np.ndarray = np.ones(state_dim) / state_dim
    
    def perceive(self, observation: np.ndarray) -> np.ndarray:
        self.state = self.model.generate_observation(self.state) * 0.3 + observation * 0.7
        return self.state
    
    def select_action(self, goal: np.ndarray) -> List[ActionType]:
        return self.planner.plan(self.state, self.model, goal)
    
    def step(self, observation: np.ndarray, goal: np.ndarray) -> Dict[str, Any]:
        self.perceive(observation)
        actions = self.select_action(goal)
        prediction = self.model.predict_state(self.state, Policy(actions=actions))
        error = float(np.linalg.norm(prediction - observation))
        self.learner.update('A', np.outer(observation, self.state), 1)
        self.decision.adapt_weights(error)
        return {
            "state": self.state.tolist(),
            "actions": [a.value for a in actions],
            "prediction_error": error,
            "system2_weight": self.decision.system2_weight,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "state_dim": self.model.state_dim,
            "obs_dim": self.model.obs_dim,
            "system2_weight": self.decision.system2_weight,
            "horizon": self.planner.horizon,
        }

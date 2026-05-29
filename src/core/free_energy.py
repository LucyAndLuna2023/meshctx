"""
MeshCtx v3.35 — Free Energy Engine (Friston自由能原理+信息几何+贝叶斯推断)
脑启发架构核心模块。当前为stub，后续填入完整自由能计算引擎。
"""

import math
import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class BeliefType(Enum):
    PRIOR = "prior"
    POSTERIOR = "posterior"
    PREDICTIVE = "predictive"
    COUNTERFACTUAL = "counterfactual"


@dataclass
class BeliefState:
    """信念状态 — 概率分布 + 精度"""
    mean: np.ndarray
    precision: np.ndarray
    belief_type: BeliefType = BeliefType.PRIOR
    free_energy: float = 0.0
    
    def surprise(self) -> float:
        return float(-np.log(max(abs(self.mean.sum()), 1e-10)))


class FreeEnergyComputer:
    """变分自由能计算器 — F = D_KL(Q||P) - E_Q[ln P(o|s)]"""
    
    def __init__(self, temperature: float = 1.0):
        self.temperature = temperature
        self.history: List[float] = []
    
    def compute(self, belief: BeliefState, observation: np.ndarray) -> float:
        complexity = self._kl_divergence(belief)
        accuracy = self._expected_log_likelihood(belief, observation)
        fe = complexity - accuracy
        self.history.append(fe)
        return fe
    
    def _kl_divergence(self, belief: BeliefState) -> float:
        return float(0.5 * np.sum(belief.precision * belief.mean ** 2))
    
    def _expected_log_likelihood(self, belief: BeliefState, observation: np.ndarray) -> float:
        diff = observation - belief.mean
        return float(-0.5 * np.sum(belief.precision * diff ** 2))
    
    def get_trend(self, window: int = 10) -> str:
        if len(self.history) < window:
            return "insufficient_data"
        recent = self.history[-window:]
        slope = sum((i - window/2) * (v - sum(recent)/window) for i, v in enumerate(recent))
        if slope < -0.1: return "decreasing"
        elif slope > 0.1: return "increasing"
        return "stable"
    
    def reset(self):
        self.history.clear()


class PrecisionWeighting:
    """精度加权 — 调节先验vs观测的相对置信度"""
    
    def __init__(self, sensory_precision: float = 1.0, prior_precision: float = 1.0):
        self.sensory_precision = sensory_precision
        self.prior_precision = prior_precision
    
    def weight(self, sensory: np.ndarray, prior: np.ndarray) -> np.ndarray:
        total = self.sensory_precision + self.prior_precision
        return (self.sensory_precision * sensory + self.prior_precision * prior) / total
    
    def update_precisions(self, error: float, learning_rate: float = 0.01):
        self.sensory_precision *= (1.0 + learning_rate * error)
        self.prior_precision *= (1.0 - learning_rate * error * 0.5)


class CriticalityRegulator:
    """临界性调节器 — 维持系统在混沌边缘"""
    
    def __init__(self, target_branching_ratio: float = 1.0):
        self.target = target_branching_ratio
        self.current_branching: float = 1.0
        self.coupling_strength: float = 1.0
    
    def assess(self, activity: np.ndarray) -> float:
        if len(activity) < 2:
            return 0.0
        self.current_branching = float(np.std(activity) / (np.mean(np.abs(activity)) + 1e-10))
        deviation = self.current_branching - self.target
        self.coupling_strength *= (1.0 - 0.1 * deviation)
        self.coupling_strength = max(0.1, min(10.0, self.coupling_strength))
        return deviation
    
    @property
    def is_critical(self) -> bool:
        return 0.9 < self.current_branching < 1.1


class FreeEnergyAgent:
    """自由能Agent — 感知-行动循环"""
    
    def __init__(self):
        self.computer = FreeEnergyComputer()
        self.precision = PrecisionWeighting()
        self.regulator = CriticalityRegulator()
        self.beliefs: Dict[str, BeliefState] = {}
    
    def perceive(self, observation: np.ndarray) -> BeliefState:
        belief = BeliefState(
            mean=observation.copy(),
            precision=np.ones_like(observation),
            belief_type=BeliefType.POSTERIOR,
        )
        belief.free_energy = self.computer.compute(belief, observation)
        self.beliefs[str(id(observation))] = belief
        return belief
    
    def act(self, belief: BeliefState, goal: np.ndarray) -> np.ndarray:
        return self.precision.weight(goal, belief.mean)
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "num_beliefs": len(self.beliefs),
            "free_energy_trend": self.computer.get_trend(),
            "avg_free_energy": float(np.mean(self.computer.history)) if self.computer.history else 0.0,
            "is_critical": self.regulator.is_critical,
            "coupling_strength": self.regulator.coupling_strength,
        }

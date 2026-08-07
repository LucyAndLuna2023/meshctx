"""
Nucleus Accumbens (NAcc) — 伏隔核
==================================
核心功能:
  RewardPredictor  — 奖励预测 (TD learning)
  MotivationSignal — 动机信号 (incentive salience)
  WantingVsLiking  — "想要" vs "喜欢" 分离 (Berridge & Robinson 1998)

参考:
  Schultz W, Dayan P, Montague PR. "A neural substrate of prediction and reward." Science, 1997
  Berridge KC, Robinson TE. "What is the role of dopamine in reward." Brain Res Rev, 1998
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional
from collections import deque


@dataclass
class RewardOutcome:
    predicted: float
    actual: float
    prediction_error: float   # δ = R - V (TD error)
    dopamine_signal: float     # phasic DA


class RewardPredictor:
    """VTA→NAcc TD(λ) learning of reward prediction (v3.115.38)."""

    def __init__(self, n_states: int = 10, learning_rate: float = 0.3, gamma: float = 0.95, lambda_: float = 0.7):
        self.lr = learning_rate
        self.gamma = gamma
        self.lambda_ = lambda_
        self.value = np.zeros(n_states)
        # Eligibility traces — each state has its own trace for multi-step credit assignment
        self.eligibility = np.zeros(n_states)
        self.n_updates = 0
        self._pe_history: deque = deque(maxlen=100)

    def predict(self, state_idx: int) -> float:
        return float(self.value[min(state_idx, len(self.value)-1)])

    def update(self, state_idx: int, reward: float, next_state_idx: Optional[int] = None) -> RewardOutcome:
        idx = min(state_idx, len(self.value)-1)
        predicted = float(self.value[idx])

        if next_state_idx is not None:
            next_v = self.value[min(next_state_idx, len(self.value)-1)]
            td_target = reward + self.gamma * next_v
        else:
            td_target = reward

        pe = td_target - predicted

        # ═══ TD(λ) with eligibility traces (v3.115.38) ═══
        # Decay all eligibility traces: e(s) ← γλ e(s)
        self.eligibility *= self.gamma * self.lambda_
        # Current state gets credit: e(s_t) += 1
        self.eligibility[idx] += 1.0
        # Update ALL states proportionally to their eligibility
        self.value += self.lr * pe * self.eligibility
        self.value = np.clip(self.value, -10.0, 10.0)

        self.n_updates += 1
        self._pe_history.append(pe)

        # Dopamine signal: positive PE → phasic burst, negative → dip
        da = max(0.0, pe) * 0.8 - max(0.0, -pe) * 0.3

        return RewardOutcome(
            predicted=predicted,
            actual=reward,
            prediction_error=float(pe),
            dopamine_signal=float(da)
        )

    def reset_with_optimistic_init(self, optimism: float = 0.5):
        """Optimistic initialization — all states start with positive value to encourage exploration."""
        self.value = np.full(len(self.value), optimism)
        self.eligibility = np.zeros(len(self.value))
        self._pe_history.clear()
        self.n_updates = 0

    def pretrain_hints(self, reward_states: Dict[int, float]):
        """Seed known reward states for faster convergence."""
        for sidx, rval in reward_states.items():
            idx = min(sidx, len(self.value) - 1)
            self.value[idx] = rval

    def mean_pe(self) -> float:
        if not self._pe_history:
            return 0.0
        return float(np.mean(self._pe_history))

    def learning_progress(self) -> float:
        """How much has value function changed recently?"""
        if len(self._pe_history) < 20:
            return 1.0
        recent = list(self._pe_history)[-20:]
        return float(np.std(recent))


class MotivationSignal:
    """NAcc core — incentive salience: how motivated is the agent?"""

    def __init__(self):
        self.tonic_da = 0.3     # baseline dopamine tone
        self.motivation = 0.5   # 0-1 motivation level
        self.satiety = 0.0      # 0-1 how satisfied
        self._da_history: deque = deque(maxlen=50)

    def update(self, dopamine_signal: float, effort_cost: float = 0.0):
        """Update motivation based on dopamine and effort."""
        self._da_history.append(dopamine_signal)

        # Tonic DA adapts slowly
        if self._da_history:
            mean_recent = np.mean(list(self._da_history)[-10:])
            self.tonic_da = 0.9 * self.tonic_da + 0.1 * mean_recent

        # Motivation = tonic DA - satiety - effort
        raw = self.tonic_da - self.satiety - effort_cost
        self.motivation = float(np.clip(raw, 0.0, 1.0))

    def should_act(self, threshold: float = 0.3) -> bool:
        return self.motivation > threshold

    def run_cycle(self, dopamine_signal: float, effort: float = 0.0, satiety_decay: float = 0.005):
        """Single-cycle update for BrainLoop integration."""
        self.update(dopamine_signal, effort)
        self.decay_satiety(satiety_decay)

    def reset(self):
        """Reset to initial state."""
        self.tonic_da = 0.3
        self.motivation = 0.5
        self.satiety = 0.0
        self._da_history.clear()

    def consume_reward(self, reward_magnitude: float):
        """Consuming reward increases satiety."""
        self.satiety = min(1.0, self.satiety + reward_magnitude * 0.2)

    def decay_satiety(self, rate: float = 0.01):
        self.satiety = max(0.0, self.satiety - rate)


class WantingVsLiking:
    """Dissociation between 'wanting' (incentive salience) and 'liking' (hedonic)."""

    def __init__(self):
        self.wanting = 0.5   # incentive salience (DA-driven)
        self.liking = 0.5    # hedonic impact (opioid-driven)
        self.craving = 0.0

    def process_reward(self, reward: float, dopamine: float):
        """Update wanting/liking based on reward outcome — with sensitization (v3.115.38)."""
        # Liking: hedonic impact — moves slowly, no sensitization
        self.liking = 0.9 * self.liking + 0.1 * max(0.0, reward)

        # Wanting: incentive salience — sensitizes with repeated dopamine spikes
        # da_factor > 1 when dopamine is high relative to baseline → wanting grows faster
        da_factor = 1.0 + max(0.0, dopamine - 0.2) * 2.0  # 1.0–2.6× range
        self.wanting = 0.85 * self.wanting + 0.15 * max(0.0, dopamine) * da_factor
        self.wanting = min(self.wanting, 1.0)

        # Craving: mismatch between wanting and liking
        self.craving = max(0.0, self.wanting - self.liking)

    def state(self) -> Dict:
        return {
            'wanting': round(self.wanting, 4),
            'liking': round(self.liking, 4),
            'craving': round(self.craving, 4),
            'dissonance': round(self.wanting - self.liking, 4)
        }

"""
Basal Ganglia Action Selection — 基底节Go/NoGo通路 (v3.115.16)
基于 Mink(1996) 中心-周围抑制 + Frank(2005) 多巴胺门控 + Schultz(1997) TD学习

核心机制:
1. Go/NoGo 双通路 (Mink, 1996; Frank, 2005):
   - Direct Pathway (Go):  皮层→纹状体D1→GPi/SNr→丘脑,  促进动作
   - Indirect Pathway (NoGo): 皮层→纹状体D2→GPe→STN→GPi/SNr→丘脑, 抑制动作
   - Hyperdirect Pathway: 皮层→STN→GPi/SNr, 快速全局抑制 (停止一切)

2. 多巴胺调节 (Schultz et al., 1997; Frank, 2005):
   - D1受体 (Go): 多巴胺↑ → 增强直接通路 → 促进动作
   - D2受体 (NoGo): 多巴胺↑ → 抑制间接通路 → 释放动作
   - 奖励预测误差(RPE): δ = r + γV(s') - V(s)

3. TD学习 (Sutton & Barto, 1998; Schultz, 1997):
   - 纹状体价值函数学习
   - Actor-Critic 架构: Critic(腹侧纹状体) + Actor(背侧纹状体)
   - 经历回放 + eligibility traces

4. 动作选择 (Gurney et al., 2001):
   - 中心-周围抑制: 选中动作通道抑制竞争通道
   - 软max选择 + 温度参数

参考文献:
- Mink JW (1996) The basal ganglia: focused selection and inhibition of competing motor programs
- Frank MJ (2005) Dynamic dopamine modulation in the basal ganglia
- Schultz W et al. (1997) A neural substrate of prediction and reward
- Gurney K et al. (2001) A computational model of action selection in the basal ganglia
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
import time
import math


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ActionCandidate:
    """An action under consideration by the basal ganglia."""
    name: str
    go_signal: float = 0.0        # Direct pathway output
    nogo_signal: float = 0.0      # Indirect pathway output
    selection_strength: float = 0.0
    q_value: float = 0.0
    priority: float = 0.5
    times_selected: int = 0
    total_reward: float = 0.0


@dataclass
class SelectionResult:
    """Result of basal ganglia action selection."""
    selected_action: str
    confidence: float
    go_signal: float
    nogo_signal: float
    rpe: float                    # reward prediction error
    dopamine_level: float
    all_candidates: Dict[str, float]
    was_globally_inhibited: bool


# ─── Striatum — D1/D2 Medium Spiny Neurons ───────────────────────────────────
# MSNs are GABAergic and comprise ~95% of striatal neurons.

class StriatalMSNs:
    """
    Medium Spiny Neurons — D1 (direct/Go) and D2 (indirect/NoGo) populations.

    D1-MSNs (Go): project to GPi/SNr directly. D1 receptors are excitatory (Gs-coupled).
    D2-MSNs (NoGo): project to GPe. D2 receptors are inhibitory (Gi-coupled).

    Cortical input → MSN activation → modulated by dopamine.
    """

    def __init__(self, n_actions: int = 8):
        self.n_actions = n_actions

        # Cortico-striatal weights (learnable)
        self.cortical_weights_D1 = np.ones(n_actions) * 0.5
        self.cortical_weights_D2 = np.ones(n_actions) * 0.5

        # Baseline firing rates
        self.D1_baseline: float = 5.0   # Hz
        self.D2_baseline: float = 15.0  # Hz (D2 MSNs have higher baseline)

        # Lateral inhibition (GABAergic collaterals between MSNs)
        self.lateral_inhibition_weight: float = 0.3

    def compute_msn_activity(self, cortical_inputs: np.ndarray,
                             dopamine: float) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute D1 and D2 MSN activities.

        Cortical inputs → weighted by cortico-striatal synapses → modulated by DA.

        D1: DA ↑ → cAMP ↑ → PKA → increased excitability → MORE Go signal
        D2: DA ↑ → cAMP ↓ → decreased excitability → LESS NoGo signal
        """
        if len(cortical_inputs) < self.n_actions:
            cortical_inputs = np.pad(cortical_inputs,
                                     (0, self.n_actions - len(cortical_inputs)))
        ctx = cortical_inputs[:self.n_actions]

        # D1-MSN: excitatory response to cortical input, amplified by dopamine
        d1_activity = self.D1_baseline + \
            ctx * self.cortical_weights_D1 * (1.0 + dopamine * 1.2)

        # D2-MSN: excitatory response to cortical input, attenuated by dopamine
        d2_activity = self.D2_baseline + \
            ctx * self.cortical_weights_D2 * (1.0 - dopamine * 0.8)

        # Lateral inhibition between MSNs (winner-take-all dynamics)
        for i in range(self.n_actions):
            d1_inhibition = 0.0
            d2_inhibition = 0.0
            for j in range(self.n_actions):
                if i != j:
                    d1_inhibition += d1_activity[j] * self.lateral_inhibition_weight
                    d2_inhibition += d2_activity[j] * self.lateral_inhibition_weight
            d1_activity[i] -= d1_inhibition / (self.n_actions - 1)
            d2_activity[i] -= d2_inhibition / (self.n_actions - 1)

        d1_activity = np.maximum(0.0, d1_activity)
        d2_activity = np.maximum(0.0, d2_activity)

        return d1_activity, d2_activity


# ─── Direct Pathway (Go) ─────────────────────────────────────────────────────
# D1-MSNs → GPi/SNr (inhibitory) → Thalamus (disinhibition)
# Net effect: disinhibit thalamus = GO signal

class DirectPathway:
    """
    Direct (Go) pathway: D1-MSN → GPi/SNr → Thalamus.

    Architecture:
        Cortex (+)→ D1-MSN (-)→ GPi/SNr (-)→ Thalamus (+)→ Cortex
        Net: Cortex → (+) → Cortex (positive feedback loop for selected action)

    Disinhibition: MSN inhibits GPi, GPi inhibits Thalamus.
    MSN activity ↑ → GPi activity ↓ → Thalamus activity ↑ → GO!
    """

    def __init__(self, n_actions: int = 8):
        self.n_actions = n_actions
        # GPi/SNr baseline firing rate (high: ~60-80 Hz tonic inhibition)
        self.gpi_baseline: float = 70.0
        # MSN→GPi synaptic weight (GABAergic = negative)
        self.msn_to_gpi_weight: float = -0.8
        # GPi→Thalamus synaptic weight (GABAergic = negative)
        self.gpi_to_thalamus_weight: float = -1.0

    def forward(self, d1_activity: np.ndarray) -> np.ndarray:
        """
        Compute Go signal via direct pathway.
        High D1 activity → inhibits GPi → disinhibits Thalamus → GO!
        """
        if len(d1_activity) < self.n_actions:
            d1_activity = np.pad(d1_activity,
                                 (0, self.n_actions - len(d1_activity)))

        # MSN inhibits GPi
        gpi_activity = self.gpi_baseline + \
            self.msn_to_gpi_weight * d1_activity[:self.n_actions]
        gpi_activity = np.maximum(0.0, gpi_activity)

        # GPi inhibits Thalamus → disinhibition when GPi is low
        thalamic_activity = 50.0 + self.gpi_to_thalamus_weight * gpi_activity
        # Normalize: higher thalamic = stronger Go signal
        go_signal = np.tanh(thalamic_activity / 30.0) * 0.5 + 0.5

        return go_signal


# ─── Indirect Pathway (NoGo) ──────────────────────────────────────────────────
# D2-MSNs → GPe → STN → GPi/SNr → Thalamus
# Net effect: inhibit thalamus = NoGo signal

class IndirectPathway:
    """
    Indirect (NoGo) pathway: D2-MSN → GPe → STN → GPi/SNr → Thalamus.

    Architecture:
        Cortex (+)→ D2-MSN (-)→ GPe (-)→ STN (+)→ GPi (-)→ Thalamus

    More synapses = more inhibition = NoGo.
    D2-MSN active → inhibits GPe → disinhibits STN → excites GPi → inhibits Thalamus = STOP.
    """

    def __init__(self, n_actions: int = 8):
        self.n_actions = n_actions
        # GPe baseline (high tonic: ~60 Hz)
        self.gpe_baseline: float = 60.0
        # STN baseline (moderate: ~20 Hz)
        self.stn_baseline: float = 20.0
        # Synaptic weights
        self.msn_to_gpe_weight: float = -0.7
        self.gpe_to_stn_weight: float = -0.9
        self.stn_to_gpi_weight: float = 1.2   # glutamatergic (+)
        self.gpi_to_thalamus_weight: float = -1.0

    def forward(self, d2_activity: np.ndarray) -> np.ndarray:
        """
        Compute NoGo signal via indirect pathway.
        High D2 activity → inhibits GPe → disinhibits STN → excites GPi → STOP.
        """
        if len(d2_activity) < self.n_actions:
            d2_activity = np.pad(d2_activity,
                                 (0, self.n_actions - len(d2_activity)))

        # MSN inhibits GPe
        gpe_activity = self.gpe_baseline + self.msn_to_gpe_weight * d2_activity[:self.n_actions]
        gpe_activity = np.maximum(0.0, gpe_activity)

        # GPe inhibits STN → low GPe = high STN
        stn_activity = self.stn_baseline + self.gpe_to_stn_weight * gpe_activity
        stn_activity = np.maximum(0.0, stn_activity)

        # STN excites GPi
        gpi_activity = self.stn_to_gpi_weight * stn_activity

        # GPi inhibits Thalamus → high GPi = high inhibition = NoGo
        thalamic_activity = 50.0 + self.gpi_to_thalamus_weight * gpi_activity
        # Normalize: lower thalamic = stronger NoGo signal
        nogo_signal = 1.0 - (np.tanh(thalamic_activity / 30.0) * 0.5 + 0.5)

        return nogo_signal


# ─── Hyperdirect Pathway ─────────────────────────────────────────────────────
# Cortex → STN (direct, fast) → GPi → global STOP
# The fastest basal ganglia pathway — emergency brake.

class HyperdirectPathway:
    """
    Hyperdirect pathway: Cortex → STN → GPi/SNr → Thalamus.

    Bypasses striatum entirely. Fastest pathway (~10ms).
    Provides global "stop" signal — suppresses all ongoing actions.
    Activated by conflict/error detection (ACC, prefrontal regions).
    """

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.cortical_to_stn_weight: float = 1.5
        self.stn_to_gpi_weight: float = 1.0
        self._recent_stops: deque = deque(maxlen=20)

    def compute_stop_signal(self, global_cortical_drive: float) -> float:
        """
        Compute hyperdirect global inhibition signal.
        High cortical drive → STN burst → GPi activation → global thalamic inhibition.
        """
        # STN activation from cortical drive
        stn_activation = global_cortical_drive * self.cortical_to_stn_weight

        # Global GPi activation → inhibits all thalamic channels
        gpi_global = stn_activation * self.stn_to_gpi_weight

        # Stop signal strength
        stop_signal = np.tanh(gpi_global / 20.0)
        stop_signal = max(0.0, stop_signal)

        self._recent_stops.append(stop_signal)
        return float(stop_signal)

    def should_globally_stop(self, conflict_signal: float,
                             error_signal: float) -> bool:
        """
        Determine if hyperdirect pathway should trigger global stop.
        Triggered by: high conflict (ACC) OR high prediction error.
        """
        combined = max(conflict_signal, error_signal)
        stop = self.compute_stop_signal(combined)
        return stop > self.threshold


# ─── Dopamine Modulation & TD Learning ───────────────────────────────────────
# Schultz(1997) + Frank(2005): DA encodes reward prediction error.

class DopamineSystem:
    """
    Midbrain dopamine neurons (VTA/SNc) encode reward prediction error (RPE).

    δ_t = r_t + γ * V(s_{t+1}) - V(s_t)

    Phasic DA bursts (>15 Hz): positive RPE (better than expected)
    Phasic DA pauses (<1 Hz): negative RPE (worse than expected)
    Tonic DA (~5 Hz): baseline, no prediction error

    DA modulates:
    - D1 receptors (Go pathway): excitatory → DA ↑ = more Go
    - D2 receptors (NoGo pathway): inhibitory → DA ↑ = less NoGo
    Net: DA ↑ = bias toward action; DA ↓ = bias toward inaction
    """

    def __init__(self, baseline_dopamine: float = 0.3,
                 phasic_max: float = 1.0, phasic_min: float = 0.0):
        self.baseline = baseline_dopamine
        self.phasic_max = phasic_max
        self.phasic_min = phasic_min
        self.current_da: float = baseline_dopamine
        self.rpe_history: deque = deque(maxlen=100)
        self.tonic_component: float = baseline_dopamine
        self._recent_rewards: deque = deque(maxlen=30)

    def compute_rpe(self, reward: float, current_value: float,
                    next_value: float, gamma: float = 0.9) -> float:
        """Compute Reward Prediction Error (Schultz et al., 1997)."""
        rpe = reward + gamma * next_value - current_value
        self.rpe_history.append(rpe)
        return rpe

    def update_dopamine(self, rpe: float):
        """
        Update dopamine level from RPE.

        Positive RPE → phasic burst (DA > baseline)
        Negative RPE → phasic dip (DA < baseline)
        Zero RPE → return to baseline

        Also implements adaptive baseline: tonic DA drifts toward average reward rate
        (Niv et al., 2007: average reward rate modulates tonic DA).
        """
        # Phasic component: proportional to RPE
        if rpe > 0:
            phasic = np.tanh(rpe * 3.0) * (self.phasic_max - self.baseline)
        else:
            phasic = np.tanh(rpe * 3.0) * (self.baseline - self.phasic_min)

        # Tonic adaptation: moving average of recent rewards
        self.tonic_component = 0.95 * self.tonic_component + 0.05 * max(0.0, rpe + 0.1)

        self.current_da = np.clip(self.tonic_component + phasic * 0.3, 0.0, 1.0)

    def get_effective_modulation(self) -> Tuple[float, float]:
        """
        Get D1 (excitatory) and D2 (inhibitory) effective modulation.

        DA high → D1 activation ↑ AND D2 inhibition ↑
        Net effect: stronger Go, weaker NoGo → action promotion.
        """
        da = self.current_da
        # D1: sigmoidal activation by DA (EC50 ~ 0.3)
        d1_mod = 1.0 / (1.0 + np.exp(-12.0 * (da - 0.3)))
        # D2: sigmoidal inhibition by DA
        d2_mod = 1.0 - 1.0 / (1.0 + np.exp(-12.0 * (da - 0.25)))
        return float(d1_mod), float(d2_mod)


# ─── TD Value Learning ───────────────────────────────────────────────────────
# Actor-Critic: striatum learns both value (critic) and policy (actor).

class TDValueLearner:
    """
    Temporal Difference value learning for state-action pairs.
    Implements Q-learning with eligibility traces (TD(λ)).
    """

    def __init__(self, n_actions: int = 8, learning_rate: float = 0.1,
                 gamma: float = 0.9, lambda_trace: float = 0.6):
        self.n_actions = n_actions
        self.alpha = learning_rate   # learning rate
        self.gamma = gamma           # discount factor
        self.lambda_ = lambda_trace  # eligibility trace decay

        # Q-values per action
        self.q_values = np.zeros(n_actions)
        # State value (critic) — used for RPE computation
        self.state_value: float = 0.0
        # Eligibility traces per action
        self.eligibility = np.zeros(n_actions)
        # Visit counts (for optimistic initialization)
        self.visit_counts = np.zeros(n_actions)

        # Running stats
        self.total_updates: int = 0

    def get_values(self) -> np.ndarray:
        """Get Q-values with optimism bonus for unexplored actions."""
        optimism_bonus = 1.0 / (1.0 + np.sqrt(self.visit_counts + 1))
        return self.q_values + optimism_bonus * 0.2

    def update_eligibility(self, action_idx: int):
        """Update eligibility traces: reset selected, decay others."""
        self.eligibility *= self.gamma * self.lambda_
        self.eligibility[action_idx] = 1.0  # replacing trace

    def update(self, action_idx: int, reward: float,
               next_q_max: float) -> float:
        """
        TD update for a specific action.

        Q(s,a) ← Q(s,a) + α * [r + γ * max Q(s',a') - Q(s,a)] * eligibility(a)
        """
        self.visit_counts[action_idx] += 1
        self.total_updates += 1

        # TD error
        td_error = reward + self.gamma * next_q_max - self.q_values[action_idx]

        # Update Q-values via eligibility traces
        self.q_values += self.alpha * td_error * self.eligibility

        return td_error

    def update_state_value(self, rpe: float):
        """Update state value via TD(0) on critic."""
        self.state_value += self.alpha * 0.5 * rpe
        self.state_value = np.clip(self.state_value, -2.0, 2.0)


# ─── Action Selection ────────────────────────────────────────────────────────

class ActionSelector:
    """
    Center-surround action selection (Mink, 1996; Gurney et al., 2001).

    Selected action: center — strongly facilitated.
    Competing actions: surround — inhibited.
    Softmax with adaptive temperature.
    """

    def __init__(self, n_actions: int = 8, softmax_temp: float = 1.0):
        self.n_actions = n_actions
        self.softmax_temp = softmax_temp
        self.selection_history: deque = deque(maxlen=50)

    def select_action(self, go_signals: np.ndarray,
                      nogo_signals: np.ndarray,
                      q_values: np.ndarray,
                      temperature: Optional[float] = None,
                      explore: float = 0.05) -> Tuple[int, float, np.ndarray]:
        """
        Select action via center-surround disinhibition.

        Selection score = Go - NoGo + Q-value bonus
        Center-surround: winner suppresses all others.
        """
        if len(go_signals) < self.n_actions:
            go_signals = np.pad(go_signals, (0, self.n_actions - len(go_signals)))
        if len(nogo_signals) < self.n_actions:
            nogo_signals = np.pad(nogo_signals, (0, self.n_actions - len(nogo_signals)))
        if len(q_values) < self.n_actions:
            q_values = np.pad(q_values, (0, self.n_actions - len(q_values)))

        go = go_signals[:self.n_actions]
        nogo = nogo_signals[:self.n_actions]
        qv = q_values[:self.n_actions]

        # Net selection score
        raw_scores = go - nogo * 0.7 + np.tanh(qv) * 0.3

        # Center-surround inhibition: winner-take-all dynamics
        winner_idx = int(np.argmax(raw_scores))
        inhibited_scores = raw_scores.copy()
        for i in range(self.n_actions):
            if i != winner_idx:
                # Distance-based surround inhibition
                dist = abs(i - winner_idx)
                inhibition = 0.3 * np.exp(-dist / 2.0)
                inhibited_scores[i] -= inhibition * raw_scores[winner_idx] * 0.3

        # Softmax with temperature
        temp = temperature if temperature is not None else self.softmax_temp
        exp_scores = np.exp((inhibited_scores - np.max(inhibited_scores)) / max(temp, 0.01))

        # Epsilon-greedy exploration
        if np.random.random() < explore:
            probs = np.ones(self.n_actions) / self.n_actions
        else:
            probs = exp_scores / (exp_scores.sum() + 1e-8)

        selected = int(np.random.choice(self.n_actions, p=probs))
        confidence = float(probs[selected])

        self.selection_history.append(selected)
        return selected, confidence, probs

    def adapt_temperature(self):
        """Adapt softmax temperature based on selection entropy."""
        if len(self.selection_history) < 10:
            return
        # If always selecting same action → increase temperature (more exploration)
        recent = list(self.selection_history)[-20:]
        unique_ratio = len(set(recent)) / max(len(recent), 1)
        if unique_ratio < 0.2:
            self.softmax_temp = min(5.0, self.softmax_temp * 1.3)
        elif unique_ratio > 0.6:
            self.softmax_temp = max(0.1, self.softmax_temp * 0.9)


# ─── Complete BasalGanglia ───────────────────────────────────────────────────

class BasalGanglia:
    """
    Complete basal ganglia action selection system.

    Pipeline:
    Cortical Input → Striatal MSNs (D1/D2) →
        → Direct Pathway (Go)     ↘
        → Indirect Pathway (NoGo) → Action Selector → Selected Action
        → Hyperdirect Pathway (Global Stop)
    Dopamine (RPE) modulates all stages.

    Key features:
    - ~20-50ms action selection latency
    - Dopamine-modulated TD learning of Q-values
    - Center-surround inhibition for clean action selection
    - Hyperdirect pathway for emergency stopping
    - Adaptive exploration/exploitation via softmax temperature
    """

    def __init__(self, n_actions: int = 8,
                 learning_rate: float = 0.1,
                 gamma: float = 0.9):
        self.n_actions = n_actions

        # Submodules
        self.striatum = StriatalMSNs(n_actions=n_actions)
        self.direct_pathway = DirectPathway(n_actions=n_actions)
        self.indirect_pathway = IndirectPathway(n_actions=n_actions)
        self.hyperdirect = HyperdirectPathway()
        self.dopamine = DopamineSystem()
        self.td_learner = TDValueLearner(n_actions=n_actions,
                                          learning_rate=learning_rate,
                                          gamma=gamma)
        self.selector = ActionSelector(n_actions=n_actions)

        # State tracking
        self._last_action_idx: Optional[int] = None
        self._last_go_signals: Optional[np.ndarray] = None
        self._last_nogo_signals: Optional[np.ndarray] = None
        self._last_cortical_inputs: Optional[np.ndarray] = None

        # Action registry
        self.actions: List[str] = [f"action_{i}" for i in range(n_actions)]

    def register_actions(self, action_names: List[str]):
        """Register named actions."""
        self.actions = action_names[:self.n_actions]
        # Pad if fewer actions provided
        while len(self.actions) < self.n_actions:
            self.actions.append(f"action_{len(self.actions)}")

    def select(self, cortical_inputs: np.ndarray,
               reward: float = 0.0,
               conflict_signal: float = 0.0,
               error_signal: float = 0.0) -> SelectionResult:
        """
        Main action selection loop.

        Args:
            cortical_inputs: cortical drive per action (e.g., from PFC)
            reward: recent reward signal (for learning)
            conflict_signal: from ACC (for hyperdirect pathway)
            error_signal: prediction error (for hyperdirect pathway)
        """
        self._last_cortical_inputs = cortical_inputs.copy() if isinstance(
            cortical_inputs, np.ndarray) else np.array(cortical_inputs)

        # 1. Dopamine update from previous action's outcome
        if self._last_action_idx is not None:
            next_q_max = float(np.max(self.td_learner.get_values()))
            current_q = self.td_learner.q_values[self._last_action_idx]
            rpe = self.dopamine.compute_rpe(reward, current_q, next_q_max,
                                            self.td_learner.gamma)
            self.dopamine.update_dopamine(rpe)
            self.td_learner.update_state_value(rpe)
            self.td_learner.update(self._last_action_idx, reward, next_q_max)

        da = self.dopamine.current_da

        # 2. Compute striatal MSN activity
        d1_activity, d2_activity = self.striatum.compute_msn_activity(
            cortical_inputs, da
        )

        # 3. Direct pathway → Go signals
        go_signals = self.direct_pathway.forward(d1_activity)

        # 4. Indirect pathway → NoGo signals
        nogo_signals = self.indirect_pathway.forward(d2_activity)

        # 5. Dopamine modulation of pathway outputs
        d1_mod, d2_mod = self.dopamine.get_effective_modulation()
        go_signals *= (0.5 + 0.5 * d1_mod)
        nogo_signals *= (0.5 + 0.5 * d2_mod)

        # 6. Hyperdirect pathway: check for global stop
        was_stopped = self.hyperdirect.should_globally_stop(conflict_signal,
                                                             error_signal)

        # 7. Action selection (center-surround)
        if was_stopped:
            # Global inhibition: all actions suppressed
            selected_idx = -1
            confidence = 0.0
            probs = np.zeros(self.n_actions)
            selected_name = "NONE (global stop)"
        else:
            q_values = self.td_learner.get_values()
            selected_idx, confidence, probs = self.selector.select_action(
                go_signals, nogo_signals, q_values,
                explore=0.03 + (1.0 - da) * 0.1  # lower DA = more exploration
            )
            selected_name = self.actions[selected_idx] if selected_idx < len(self.actions) else "NONE"

        # 8. Update eligibility traces
        self.td_learner.update_eligibility(selected_idx)

        # 9. Store state for next update
        self._last_action_idx = selected_idx if selected_idx >= 0 else 0
        self._last_go_signals = go_signals
        self._last_nogo_signals = nogo_signals

        # 10. Adapt selector temperature
        self.selector.adapt_temperature()

        # Build action probabilities dict
        all_candidates = {}
        for i in range(min(self.n_actions, len(self.actions))):
            all_candidates[self.actions[i]] = float(probs[i]) if len(probs) > i else 0.0

        return SelectionResult(
            selected_action=selected_name,
            confidence=confidence,
            go_signal=float(go_signals[selected_idx]) if selected_idx >= 0 else 0.0,
            nogo_signal=float(nogo_signals[selected_idx]) if selected_idx >= 0 else 0.0,
            rpe=float(self.dopamine.rpe_history[-1]) if self.dopamine.rpe_history else 0.0,
            dopamine_level=da,
            all_candidates=all_candidates,
            was_globally_inhibited=was_stopped,
        )

    def provide_reward(self, reward: float):
        """Provide reward feedback for the last selected action."""
        if self._last_action_idx is not None and self._last_action_idx >= 0:
            next_q_max = float(np.max(self.td_learner.get_values()))
            current_q = self.td_learner.q_values[self._last_action_idx]
            rpe = self.dopamine.compute_rpe(reward, current_q, next_q_max,
                                            self.td_learner.gamma)
            self.dopamine.update_dopamine(rpe)
            self.td_learner.update(self._last_action_idx, reward, next_q_max)
            self.td_learner.update_state_value(rpe)

    def get_stats(self) -> dict:
        """Return diagnostic statistics."""
        return {
            "n_actions": self.n_actions,
            "dopamine_level": round(self.dopamine.current_da, 3),
            "tonic_da": round(self.dopamine.tonic_component, 3),
            "mean_rpe": round(float(np.mean(self.dopamine.rpe_history))
                              if self.dopamine.rpe_history else 0.0, 4),
            "state_value": round(self.td_learner.state_value, 3),
            "q_values": [round(v, 3) for v in self.td_learner.q_values],
            "softmax_temp": round(self.selector.softmax_temp, 3),
            "total_updates": self.td_learner.total_updates,
            "visit_counts": self.td_learner.visit_counts.tolist(),
        }

    def reset_learning(self):
        """Reset learning state."""
        self.td_learner = TDValueLearner(
            n_actions=self.n_actions,
            learning_rate=self.td_learner.alpha,
            gamma=self.td_learner.gamma,
        )
        self.dopamine = DopamineSystem()
        self._last_action_idx = None

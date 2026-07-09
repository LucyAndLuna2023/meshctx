"""
Thalamic Sensory Gate — 丘脑感觉门控引擎 (v3.115.16)
基于 Crick(1984) 探照灯假说 + Sherman & Guillery(2006) 双模态理论 + McAlonan(2008) 注意调控

核心机制:
1. 感觉门控 (Sensory Gating, Crick 1984):
   - 丘脑网状核(TRN): GABA能抑制, 过滤无关感觉输入
   - 探照灯假说: 选择性注意如聚光灯, ~40Hz同步振荡
   - P50抑制: 重复刺激→响应衰减50%(正常人), 精神分裂症患者缺失

2. 双模态通路 (Sherman & Guillery, 2006):
   - First-order (driver): 感觉器官→皮层, 大EPSP, 高保真
   - Higher-order (modulator): 皮层→丘脑→皮层, 小EPSP, 调控增益
   - 两类通路动态权重调节信息流

3. 注意调制 (McAlonan et al., 2008):
   - 前额叶(PFC)→TRN 自上而下调控
   - 空间注意 vs 特征注意: 分别调制不同TRN分区
   - 适应阈值: 基于近期刺激统计自动调整门控阈值

参考文献:
- Crick F (1984) Function of the thalamic reticular complex: The searchlight hypothesis
- Sherman SM, Guillery RW (2006) Exploring the Thalamus and Its Role in Cortical Function
- McAlonan K et al. (2008) Guarding the gateway to cortex with attention
- Pinault D (2004) The thalamic reticular nucleus: structure, function and concept
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
import time
import math


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class SensoryChannel:
    """A single sensory channel with gating state."""
    name: str
    base_gain: float = 1.0          # first-order driver gain
    modulatory_gain: float = 0.5    # higher-order modulator gain
    adaptive_threshold: float = 0.3
    p50_suppression: float = 0.0    # 0=none, 1=full suppression (normal ~0.5)
    recent_activity: deque = field(default_factory=lambda: deque(maxlen=50))
    trn_inhibition: float = 0.0
    attention_weight: float = 0.0
    last_gate_time: float = 0.0


@dataclass
class GateDecision:
    """Result of thalamic gating for a sensory input."""
    passed: bool
    channel: str
    signal_strength: float
    adaptive_threshold: float
    p50_suppressed: bool
    attention_boost: float
    trn_inhibition: float
    effective_gain: float
    confidence: float


# ─── Thalamic Reticular Nucleus (TRN) ────────────────────────────────────────
# TRN: GABAergic shell surrounding thalamus, provides lateral + feedback inhibition.
# Crick(1984): TRN is the "searchlight" — selectively gates thalamocortical transmission.

class ThalamicReticularNucleus:
    """
    TRN — inhibitory gating network.
    Implements: lateral inhibition, surround suppression, attentional spotlight.
    GABAergic interneurons provide rapid (~5ms) shunting inhibition.
    """

    def __init__(self, n_channels: int = 5, default_inhibition: float = 0.3):
        self.n_channels = n_channels
        # Lateral inhibition matrix: TRN cell_i inhibits thalamocortical cell_j
        # Gaussian neighborhood profile: nearby channels inhibit each other
        self._lateral_weights = np.zeros((n_channels, n_channels))
        for i in range(n_channels):
            for j in range(n_channels):
                dist = abs(i - j)
                if i != j:
                    self._lateral_weights[i, j] = np.exp(-dist**2 / 2.0) * 0.4
                else:
                    self._lateral_weights[i, j] = 0.0  # no self-inhibition via lateral

        # Baseline tonic inhibition (GABA_B mediated)
        self.tonic_inhibition = np.full(n_channels, default_inhibition)
        # Phasic inhibition (GABA_A mediated, fast, stimulus-locked)
        self.phasic_inhibition = np.zeros(n_channels)

    def compute_inhibition(self, channel_activities: np.ndarray,
                           attention_map: np.ndarray) -> np.ndarray:
        """
        Compute TRN-mediated inhibition per channel.

        Lateral: active channels suppress neighbors (surround suppression).
        Tonic: baseline GABA_B conductance.
        Phasic: stimulus-evoked GABA_A, proportional to channel activity.
        Attention: top-down PFC→TRN modulation reduces inhibition on attended channels.
        """
        # Lateral inhibition: active channels inhibit others
        lateral_effect = self._lateral_weights @ channel_activities

        # Phasic: proportional to own activity (self-inhibition via TRN interneuron)
        self.phasic_inhibition = channel_activities * 0.35

        # Attention reduces inhibition on attended channels
        attention_release = 1.0 - attention_map * 0.7

        total_inhibition = (
            self.tonic_inhibition +
            self.phasic_inhibition +
            lateral_effect
        ) * attention_release

        return np.clip(total_inhibition, 0.0, 1.0)

    def spotlight(self, channel_activities: np.ndarray,
                  attention_map: np.ndarray,
                  spotlight_width: float = 1.5) -> np.ndarray:
        """
        Crick's searchlight: enhance attended channel, suppress others.
        Returns effective gain per channel after TRN modulation.
        """
        inhibition = self.compute_inhibition(channel_activities, attention_map)

        # Attended channel gets boosted above inhibition
        n = len(channel_activities)
        spotlight_kernel = np.zeros(n)
        if np.max(attention_map) > 0.01:
            attended_idx = int(np.argmax(attention_map))
            for i in range(n):
                dist = abs(i - attended_idx)
                spotlight_kernel[i] = np.exp(-dist**2 / (2 * spotlight_width**2))

        # Effective gain = driver signal - inhibition + spotlight boost
        effective_gain = channel_activities * (1.0 - inhibition) + \
                         spotlight_kernel * attention_map[attended_idx] * 0.5
        return np.clip(effective_gain, 0.0, 2.0)


# ─── Adaptive Threshold ──────────────────────────────────────────────────────
# P50 suppression + dynamic threshold adaptation based on stimulus statistics.

class AdaptiveThreshold:
    """
    Adaptive gating threshold based on:
    1. P50 suppression: repeated identical stimuli → reduced response (sensory gating)
    2. Novelty-driven dishabituation: novel stimuli reset suppression
    3. Statistic tracking: running mean/variance of signal magnitudes
    """

    def __init__(self, window: int = 100, p50_decay: float = 0.5):
        self.window = window
        self.p50_decay = p50_decay  # factor by which repeated stimuli are suppressed
        self.signal_history: deque = deque(maxlen=window)
        self._running_mean: float = 0.5
        self._running_var: float = 0.1
        self._stimulus_fingerprints: Dict[str, float] = {}  # hash → suppression level
        self._fingerprint_decay: float = 0.05  # recovery per second

    def update_statistics(self, signal_magnitude: float):
        """Update running statistics of signal magnitudes."""
        self.signal_history.append(signal_magnitude)
        if len(self.signal_history) >= 3:
            arr = np.array(self.signal_history)
            self._running_mean = float(np.mean(arr))
            self._running_var = float(np.var(arr))

    def compute_threshold(self, stimulus_fingerprint: str = "",
                          elapsed_since_last: float = 1.0) -> float:
        """
        Compute adaptive gating threshold.
        Returns threshold in [0,1] — signals below this are filtered.
        """
        # Base threshold from signal statistics (z-score based)
        base_threshold = self._running_mean * 0.5 + 0.1

        # P50 suppression: repeated stimulus → higher threshold
        p50_factor = 0.0
        if stimulus_fingerprint and stimulus_fingerprint in self._stimulus_fingerprints:
            # Apply suppression
            p50_factor = self._stimulus_fingerprints[stimulus_fingerprint]
            # Drift recovery: suppression fades with time
            recovery = elapsed_since_last * self._fingerprint_decay * 2.0
            self._stimulus_fingerprints[stimulus_fingerprint] = max(0.0, p50_factor - recovery)
            p50_factor = self._stimulus_fingerprints[stimulus_fingerprint]

        # Update fingerprint suppression
        if stimulus_fingerprint:
            current = self._stimulus_fingerprints.get(stimulus_fingerprint, 0.0)
            self._stimulus_fingerprints[stimulus_fingerprint] = min(
                0.9, current + self.p50_decay * (1.0 - current)
            )

        # Adaptive threshold = base * (1 + p50 suppression)
        threshold = base_threshold * (1.0 + p50_factor)

        return np.clip(threshold, 0.05, 0.9)

    def novelty_reset(self, stimulus_fingerprint: str):
        """Novelty-driven dishabituation: reset P50 for this stimulus."""
        if stimulus_fingerprint in self._stimulus_fingerprints:
            self._stimulus_fingerprints[stimulus_fingerprint] *= 0.3


# ─── Attention Modulation ────────────────────────────────────────────────────
# Top-down attention from PFC modulates thalamic gain.

class AttentionModulator:
    """
    Prefrontal cortex → TRN top-down attention modulation.
    Implements: spatial attention, feature-based attention, sustained vs transient.
    """

    def __init__(self, n_channels: int = 5):
        self.n_channels = n_channels
        # Attention weights per channel (sum ≈ 1 when attending)
        self.attention_map = np.ones(n_channels) / n_channels
        # Sustained attention accumulator
        self.sustained_attention: float = 0.5
        # Temporal dynamics: attention takes ~200ms to shift
        self.attention_inertia: float = 0.85  # smoothing factor

    def set_attention(self, channel_weights: np.ndarray):
        """Set explicit attention weights (e.g., from PFC executive control)."""
        if len(channel_weights) == self.n_channels:
            total = np.sum(np.abs(channel_weights))
            if total > 0:
                self.attention_map = np.abs(channel_weights) / total

    def focus(self, channel_idx: int, intensity: float = 1.0):
        """Focus attention on a single channel."""
        weights = np.ones(self.n_channels) * 0.05
        weights[channel_idx] = intensity
        self.attention_map = weights / weights.sum()

    def shift_attention(self, target_map: np.ndarray, step: float = 0.2):
        """Smooth attention shift with temporal inertia."""
        if len(target_map) == self.n_channels:
            self.attention_map = (self.attention_inertia * self.attention_map +
                                  (1 - self.attention_inertia) * target_map)

    def compute_attention_gain(self, channel_idx: int) -> float:
        """Compute attentional gain for a channel.
        Attended channels: gain > 1.0; unattended: gain < 1.0."""
        baseline = 1.0 / self.n_channels
        attention = self.attention_map[channel_idx]
        # Sigmoid modulation: deviation from uniform attention
        relative = (attention - baseline) / (baseline + 1e-8)
        gain = 1.0 + np.tanh(relative * 3.0) * 0.8
        return float(gain)

    def get_sustained_attention(self) -> float:
        """Return sustained attention level (0=distracted, 1=highly focused)."""
        entropy = -np.sum(self.attention_map * np.log(self.attention_map + 1e-8))
        max_entropy = np.log(self.n_channels)
        focus = 1.0 - (entropy / max_entropy)  # 1 when fully focused
        self.sustained_attention = 0.9 * self.sustained_attention + 0.1 * focus
        return self.sustained_attention


# ─── Dual-Mode Thalamocortical Relay ─────────────────────────────────────────
# Sherman & Guillery(2006): first-order (driver) vs higher-order (modulator) pathways.

class DualModeRelay:
    """
    Dual thalamocortical relay modes.

    First-order (FO): sensory organ → thalamus → layer 4 cortex
    - Large EPSPs, high release probability, faithful transmission
    - "Driver" mode: relays sensory content with high fidelity

    Higher-order (HO): layer 5 cortex → thalamus → layer 4 cortex
    - Small EPSPs, low release probability, modulatory
    - "Modulator" mode: amplifies/contextualizes based on cortical feedback
    - Implicated in corollary discharge and predictive coding
    """

    def __init__(self, fo_gain: float = 1.0, ho_gain: float = 0.4):
        self.fo_gain = fo_gain     # first-order driver gain
        self.ho_gain = ho_gain     # higher-order modulator gain
        # Context-dependent mode switching
        self.mode_mix: float = 0.5  # 0=pure FO, 1=pure HO

    def relay(self, signal: float, cortical_feedback: float = 0.0) -> Tuple[float, float]:
        """
        Relay signal through dual thalamocortical modes.
        Returns: (relayed_signal, mode_used)
        """
        # FO component: faithful relay with slight compression
        fo_output = np.tanh(signal * self.fo_gain * 1.5)

        # HO component: modulated by cortical feedback (amplify relevant, suppress irrelevant)
        ho_output = np.tanh(signal * self.ho_gain + cortical_feedback * 1.2)

        # Mix based on current mode
        relayed = (1.0 - self.mode_mix) * fo_output + self.mode_mix * ho_output

        return float(relayed), self.mode_mix

    def set_mode(self, top_down_control: float):
        """
        Cortical control over mode mixing.
        Low top-down (novel/salient) → more FO (faithful relay).
        High top-down (predictable) → more HO (modulated/contextualized).
        """
        self.mode_mix = np.clip(top_down_control, 0.0, 1.0)


# ─── Complete ThalamicGate ───────────────────────────────────────────────────

class ThalamicGate:
    """
    Complete thalamic sensory gating system.

    Pipeline:
    Input → TRN Inhibition → Adaptive Threshold → Attention Modulation
         → Dual-Mode Relay → Gate Decision

    Key properties:
    - ~5-15ms thalamocortical latency (faithful to biology)
    - P50 suppression at ~50ms ISI
    - Selective attention: ~200ms to shift focus
    - Adaptive to stimulus statistics
    """

    def __init__(self, n_channels: int = 5,
                 default_openness: float = 0.7):
        self.n_channels = n_channels
        self.default_openness = default_openness

        # Submodules
        self.trn = ThalamicReticularNucleus(n_channels)
        self.adaptive_threshold = AdaptiveThreshold()
        self.attention = AttentionModulator(n_channels)
        self.relay = DualModeRelay()

        # Channel registry
        self.channels: Dict[str, SensoryChannel] = {}
        self._default_channels()

        # Global gate openness (controlled by arousal/overload state)
        self.openness: float = default_openness
        self.overload_history: deque = deque(maxlen=20)

        # Stats
        self.total_inputs: int = 0
        self.total_passed: int = 0
        self.total_blocked: int = 0

    def _default_channels(self):
        """Initialize default sensory channels."""
        default_names = ["visual", "auditory", "textual", "system", "interoceptive"]
        for name in default_names:
            self.channels[name] = SensoryChannel(name=name)

    def register_channel(self, name: str, base_gain: float = 1.0,
                         modulatory_gain: float = 0.5):
        """Register a new sensory channel."""
        self.channels[name] = SensoryChannel(
            name=name,
            base_gain=base_gain,
            modulatory_gain=modulatory_gain,
        )
        # Resize TRN lateral weights if needed
        self.n_channels = len(self.channels)
        self.trn = ThalamicReticularNucleus(self.n_channels)
        self.attention = AttentionModulator(self.n_channels)

    def _fingerprint_stimulus(self, content: str, channel: str) -> str:
        """Create a stimulus fingerprint for P50 tracking."""
        import hashlib
        combined = f"{channel}:{content[:80]}"
        return hashlib.md5(combined.encode()).hexdigest()[:16]

    def gate(self, signal_strength: float, channel: str = "textual",
             priority: float = 0.5, content: str = "",
             cortical_feedback: float = 0.0) -> GateDecision:
        """
        Main gating function.

        Args:
            signal_strength: raw signal magnitude [0, 1]
            channel: sensory channel name
            priority: task-relevant priority (top-down)
            content: the actual signal content (for P50 tracking)
            cortical_feedback: top-down modulation from PFC (predictive coding)
        """
        self.total_inputs += 1

        # Ensure channel exists
        if channel not in self.channels:
            self.register_channel(channel)

        ch = self.channels[channel]
        now = time.time()

        # 1. Compute TRN inhibition for all channels
        channel_idx = list(self.channels.keys()).index(channel)
        activities = np.zeros(self.n_channels)
        for i, (name, c) in enumerate(self.channels.items()):
            if c.recent_activity:
                activities[i] = np.mean(list(c.recent_activity)[-5:])

        # 2. Adaptive threshold (P50 suppression)
        fingerprint = self._fingerprint_stimulus(content, channel)
        elapsed = now - ch.last_gate_time if ch.last_gate_time > 0 else 1.0
        threshold = self.adaptive_threshold.compute_threshold(fingerprint, elapsed)
        ch.adaptive_threshold = threshold

        # 3. Attention modulation
        attn_gain = self.attention.compute_attention_gain(channel_idx)

        # 4. TRN inhibition
        inhibition = self.trn.compute_inhibition(activities, self.attention.attention_map)
        trn_inh = float(inhibition[channel_idx])

        # 5. Dual-mode relay (with mode mixing from top-down control)
        relayed_signal, mode = self.relay.relay(signal_strength, cortical_feedback)

        # 6. Combined effective gain
        effective_gain = relayed_signal * attn_gain * self.openness * (1.0 - trn_inh * 0.6)

        # 7. Gating decision
        priority_factor = 0.5 + 0.5 * priority  # priority [0,1] → factor [0.5, 1.0]
        gating_score = effective_gain * priority_factor

        p50_suppressed = False
        if fingerprint in self.adaptive_threshold._stimulus_fingerprints:
            p50_suppressed = (self.adaptive_threshold._stimulus_fingerprints[fingerprint] > 0.3)

        passed = gating_score >= threshold

        # Update stats
        if passed:
            self.total_passed += 1
        else:
            self.total_blocked += 1

        # Update channel state
        ch.recent_activity.append(signal_strength)
        ch.last_gate_time = now
        ch.trn_inhibition = trn_inh
        ch.attention_weight = self.attention.attention_map[channel_idx]

        # Update adaptive threshold statistics
        self.adaptive_threshold.update_statistics(signal_strength)

        return GateDecision(
            passed=passed,
            channel=channel,
            signal_strength=signal_strength,
            adaptive_threshold=threshold,
            p50_suppressed=p50_suppressed,
            attention_boost=attn_gain,
            trn_inhibition=trn_inh,
            effective_gain=effective_gain,
            confidence=float(1.0 - abs(gating_score - threshold)),
        )

    def adapt_openness(self, overload: bool):
        """
        Adapt gate openness based on cognitive load.
        Overload → close gate (reduce openness).
        Recovery → open gate (increase openness).
        """
        if overload:
            self.openness = max(0.15, self.openness - 0.25)
        else:
            self.openness = min(1.0, self.openness + 0.08)
        self.overload_history.append(1.0 if overload else 0.0)

    def set_attention_focus(self, channel: str, intensity: float = 1.0):
        """Set attention focus on a specific sensory channel."""
        for i, name in enumerate(self.channels.keys()):
            if name == channel:
                self.attention.focus(i, intensity)
                break

    def get_gate_stats(self) -> dict:
        """Return gating statistics."""
        pass_rate = self.total_passed / max(1, self.total_inputs)
        return {
            "total_inputs": self.total_inputs,
            "total_passed": self.total_passed,
            "total_blocked": self.total_blocked,
            "pass_rate": round(pass_rate, 3),
            "openness": round(self.openness, 3),
            "overload_ratio": round(np.mean(self.overload_history), 3) if self.overload_history else 0.0,
            "attention_entropy": round(
                -np.sum(self.attention.attention_map *
                        np.log(self.attention.attention_map + 1e-8)), 3
            ),
            "p50_stimuli_tracked": len(self.adaptive_threshold._stimulus_fingerprints),
            "mode_mix": round(self.relay.mode_mix, 3),
        }

    def reset(self):
        """Reset all state (for testing)."""
        self.openness = self.default_openness
        self.overload_history.clear()
        self.total_inputs = 0
        self.total_passed = 0
        self.total_blocked = 0
        self.adaptive_threshold._stimulus_fingerprints.clear()
        self.adaptive_threshold.signal_history.clear()
        for ch in self.channels.values():
            ch.recent_activity.clear()
            ch.last_gate_time = 0.0

"""
STDP Learner — 脉冲时间依赖可塑性引擎 (v3.115.16)
基于 Bi & Poo(1998) STDP + Sutton & Barto(1998) eligibility traces + Hebb(1949) 经典Hebbian

核心机制:
1. Spike-Timing-Dependent Plasticity (Bi & Poo, 1998; Song et al., 2000):
   - Pre-before-post (Δt > 0): LTP — 突触增强, 窗口 ~20ms
   - Post-before-pre (Δt < 0): LTD — 突触减弱, 窗口 ~20-40ms
   - 经典STDP窗口: Δw = A+ * exp(-Δt/τ+) for Δt > 0; Δw = -A- * exp(Δt/τ-) for Δt < 0
   - 成对STDP (pair-based) + 三重STDP (triplet, Pfister & Gerstner, 2006)

2. Eligibility Traces (Sutton & Barto, 1998; Izhikevich, 2007):
   - 资格迹 (eligibility trace): 衰减的记忆, 标记最近活跃的突触
   - TD(λ): 结合即时TD误差与资格迹进行信用分配
   - 衰减率 λ ∈ [0, 1]: λ=0 为TD(0), λ=1 为MC
   - 神经元级别资格迹 + 突触级别资格迹

3. Hebbian Learning (Hebb, 1949):
   - "Cells that fire together, wire together"
   - 经典Hebb: Δw_ij = η * x_i * y_j
   - Oja规则: 规范化版本, Δw = η * y * (x - y*w)
   - BCM规则 (Bienenstock-Cooper-Munro, 1982): 滑动阈值

4. 多巴胺调节 (Schultz et al., 1997; Reynolds et al., 2001):
   - 多巴胺作为全局调节信号, 门控STDP可塑性
   - DA释放 → D1受体激活 → cAMP↑ → PKA → 增强LTP
   - RPE (奖励预测误差) → DA信号 → 调节可塑性幅度

参考文献:
- Bi GQ, Poo MM (1998) Synaptic modifications in cultured hippocampal neurons. J Neurosci
- Song S, Miller KD, Abbott LF (2000) Competitive Hebbian learning through STDP. Nat Neurosci
- Pfister JP, Gerstner W (2006) Triplets of spikes in a model of STDP. Neural Comput
- Sutton RS, Barto AG (1998) Reinforcement Learning: An Introduction
- Izhikevich EM (2007) Solving the distal reward problem through linkage of STDP and DA
- Hebb DO (1949) The Organization of Behavior
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Callable, Union
import time
import math


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class Spike:
    """A single spike event."""
    neuron_id: int
    time: float
    amplitude: float = 1.0

    def __lt__(self, other: 'Spike') -> bool:
        return self.time < other.time


@dataclass
class Synapse:
    """A plastic synapse with STDP dynamics."""
    pre_id: int
    post_id: int
    weight: float = 0.1
    pre_trace: float = 0.0            # presynaptic eligibility trace
    post_trace: float = 0.0           # postsynaptic eligibility trace
    pre_recent: float = 0.0           # recent presynaptic activity (for STDP)
    post_recent: float = 0.0          # recent postsynaptic activity (for STDP)
    eligibility: float = 0.0          # TD(λ) eligibility trace
    dopamine_trace: float = 0.0       # dopamine-modulated trace
    tag: float = 0.0                  # synaptic tag (Frey & Morris, 1997)
    ltp_history: List[float] = field(default_factory=list)
    ltd_history: List[float] = field(default_factory=list)


@dataclass
class Neuron:
    """A simple spiking neuron model (LIF: Leaky Integrate-and-Fire)."""
    id: int
    membrane_potential: float = -70.0  # mV
    resting_potential: float = -70.0
    threshold: float = -50.0          # spike threshold (mV)
    reset_potential: float = -65.0
    refractory_period: float = 2.0    # ms
    last_spike_time: float = -100.0
    spike_history: List[Spike] = field(default_factory=list)
    input_current: float = 0.0
    adaptation: float = 0.0           # spike-frequency adaptation
    adaptation_increment: float = 0.5
    adaptation_tau: float = 100.0     # ms


# ─── LIF Neuron Dynamics ──────────────────────────────────────────────────────

class LIFNetwork:
    """
    Leaky Integrate-and-Fire network supporting STDP learning.
    Each neuron: τ_m * dV/dt = -(V - V_rest) + R*I + I_syn
    """

    def __init__(self, n_neurons: int, tau_m: float = 20.0,
                 r_m: float = 10.0, dt: float = 1.0, seed: int = 42):
        self.n = n_neurons
        self.tau_m = tau_m         # membrane time constant (ms)
        self.r_m = r_m             # membrane resistance (MΩ)
        self.dt = dt               # simulation timestep (ms)
        self.neurons = [Neuron(id=i) for i in range(n_neurons)]
        self.synapses: Dict[Tuple[int, int], Synapse] = {}
        self.time: float = 0.0
        self._rng = np.random.RandomState(seed)

    def connect(self, pre_id: int, post_id: int, weight: float = 0.1):
        """Create a synapse between two neurons."""
        key = (pre_id, post_id)
        if key not in self.synapses:
            self.synapses[key] = Synapse(pre_id=pre_id, post_id=post_id, weight=weight)

    def connect_all_to_all(self, weight_scale: float = 0.05):
        """Full connectivity with random weights."""
        for i in range(self.n):
            for j in range(self.n):
                if i != j:
                    w = self._rng.randn() * weight_scale + weight_scale
                    self.connect(i, j, max(0.0, w))

    def set_input(self, neuron_id: int, current: float):
        """Set external input current to a neuron."""
        if 0 <= neuron_id < self.n:
            self.neurons[neuron_id].input_current = current

    def step(self, dt: Optional[float] = None) -> List[Spike]:
        """Advance simulation by dt ms, return spikes that occurred."""
        if dt is None:
            dt = self.dt
        self.time += dt
        spikes = []

        for neuron in self.neurons:
            nid = neuron.id

            # Refractory check
            if self.time - neuron.last_spike_time < neuron.refractory_period:
                neuron.membrane_potential = neuron.reset_potential
                continue

            # LIF dynamics: τ dV/dt = -(V - Vrest) + R*I
            dv = (-(neuron.membrane_potential - neuron.resting_potential)
                  + self.r_m * neuron.input_current
                  + neuron.adaptation) * dt / self.tau_m

            # Synaptic input
            syn_current = 0.0
            for (pre_id, post_id), syn in self.synapses.items():
                if post_id == nid:
                    pre_neuron = self.neurons[pre_id]
                    # Recent presynaptic activity contributes current
                    if self.time - pre_neuron.last_spike_time < 10.0:
                        syn_current += syn.weight * syn.pre_recent

            dv += syn_current * dt
            neuron.membrane_potential += dv

            # Adaptation decay
            neuron.adaptation -= neuron.adaptation * dt / neuron.adaptation_tau

            # Spike check
            if neuron.membrane_potential >= neuron.threshold:
                spike = Spike(neuron_id=nid, time=self.time)
                spikes.append(spike)
                neuron.spike_history.append(spike)
                neuron.last_spike_time = self.time
                neuron.membrane_potential = neuron.reset_potential
                neuron.adaptation += neuron.adaptation_increment

        return spikes


# ─── STDP Learning Rule ───────────────────────────────────────────────────────

class STDPRule:
    """
    Spike-Timing-Dependent Plasticity implementation.
    Supports: pair-based STDP, triplet STDP, dopamine modulation.
    """

    def __init__(self,
                 tau_plus: float = 20.0,    # LTP time constant (ms)
                 tau_minus: float = 20.0,   # LTD time constant (ms)
                 a_plus: float = 0.005,     # LTP amplitude
                 a_minus: float = 0.005,    # LTD amplitude
                 w_min: float = 0.0,
                 w_max: float = 1.0,
                 use_triplet: bool = False):
        self.tau_plus = tau_plus
        self.tau_minus = tau_minus
        self.a_plus = a_plus
        self.a_minus = a_minus
        self.w_min = w_min
        self.w_max = w_max
        self.use_triplet = use_triplet

        # Triplet-specific parameters (Pfister & Gerstner, 2006)
        self.tau_x = 15.0           # presynaptic trace (ms)
        self.tau_y = 30.0           # postsynaptic trace for LTP (ms)
        self.tau_y2 = 40.0          # postsynaptic trace for LTD (ms)
        self.a2_plus = 0.00005      # triplet LTP amplitude
        self.a2_minus = 0.00005     # triplet LTD amplitude
        self.a3_plus = 0.00005      # all-to-all LTP

    def compute_pair_delta(self, dt_ms: float) -> float:
        """Pair-based STDP: Δw = f(Δt)."""
        if dt_ms > 0:
            # Pre fired before post: LTP
            return self.a_plus * math.exp(-dt_ms / self.tau_plus)
        elif dt_ms < 0:
            # Post fired before pre: LTD
            return -self.a_minus * math.exp(dt_ms / self.tau_minus)
        return 0.0

    def apply_pair_stdp(self, synapse: Synapse, pre_spikes: List[Spike],
                         post_spikes: List[Spike]) -> float:
        """Apply pair-based STDP to a synapse given spike histories."""
        dw = 0.0
        for pre in pre_spikes:
            for post in post_spikes:
                dt = pre.time - post.time  # pre time - post time
                if abs(dt) > 100.0:  # ignore spikes too far apart
                    continue
                dw += self.compute_pair_delta(dt)

        return dw

    def update_traces(self, synapse: Synapse, dt: float,
                       pre_fired: bool, post_fired: bool):
        """Update eligibility traces with exponential decay."""
        synapse.pre_trace *= math.exp(-dt / self.tau_plus)
        synapse.post_trace *= math.exp(-dt / self.tau_minus)

        if pre_fired:
            synapse.pre_trace += 1.0
            synapse.pre_recent = 1.0

        if post_fired:
            synapse.post_trace += 1.0
            synapse.post_recent = 1.0

        # Decay recent flags faster
        synapse.pre_recent *= math.exp(-dt / 5.0)
        synapse.post_recent *= math.exp(-dt / 5.0)

    def apply_triplet_stdp(self, synapse: Synapse,
                            pre_fired: bool, post_fired: bool,
                            dopamine: float = 0.0) -> float:
        """
        Triplet STDP (Pfister & Gerstner, 2006).
        Accounts for second-order spike interactions.
        Δw = A2+ * x(t) * y2(t) * z(t) for LTP
           - A2- * y(t) * x2(t) * w for LTD
        """
        dw = 0.0

        # Pair-based component
        if post_fired and synapse.pre_trace > 0:
            dw += self.a_plus * synapse.pre_trace
        if pre_fired and synapse.post_trace > 0:
            dw -= self.a_minus * synapse.post_trace

        # Triplet LTP: pre-post-pre triplet
        if post_fired and synapse.pre_trace > 0:
            dw += self.a2_plus * synapse.pre_trace * synapse.post_trace

        # Triplet LTD: post-pre-post triplet
        if pre_fired and synapse.post_trace > 0:
            dw -= self.a2_minus * synapse.post_trace * synapse.pre_trace

        # Dopamine modulation (Reynolds et al., 2001)
        if dopamine > 0:
            dw *= (1.0 + dopamine * 2.0)  # boost plasticity

        return dw


# ─── Eligibility Traces (TD-λ) ────────────────────────────────────────────────

class EligibilityTraceEngine:
    """
    TD(λ) eligibility traces for temporal credit assignment.
    Sutton & Barto (1998): e_t = γλ e_{t-1} + ∇_w V(s_t)

    Supports:
    - Accumulating traces: e = γλ e + ∇V
    - Replacing traces: e = max(γλ e, ∇V)
    - Dutch traces: e = (1 - α) e_old + α ∇V
    """

    def __init__(self, lambda_: float = 0.9, gamma: float = 0.99,
                 trace_type: str = 'accumulating'):
        self.lambda_ = lambda_     # trace decay parameter
        self.gamma = gamma         # discount factor
        self.trace_type = trace_type
        self.traces: Dict[int, float] = {}  # neuron_id → eligibility

    def decay(self, dt: float):
        """Decay all traces by γλ factor."""
        decay_factor = (self.gamma * self.lambda_) ** (dt / 10.0)
        for k in list(self.traces.keys()):
            self.traces[k] *= decay_factor
            if abs(self.traces[k]) < 1e-10:
                del self.traces[k]

    def update(self, gradients: Dict[int, float], td_error: float):
        """
        Update eligibility traces with latest gradients.
        e ← γλ e + ∇V (accumulating) or e ← max(γλ e, ∇V) (replacing)
        """
        for neuron_id, grad in gradients.items():
            old_trace = self.traces.get(neuron_id, 0.0)

            if self.trace_type == 'replacing':
                new_trace = max(self.gamma * self.lambda_ * abs(old_trace), abs(grad))
                new_trace *= (1.0 if grad >= 0 else -1.0)
            elif self.trace_type == 'dutch':
                # Dutch trace: blend old and new
                alpha = 0.3
                new_trace = (1 - alpha) * old_trace + alpha * grad
            else:  # accumulating
                new_trace = self.gamma * self.lambda_ * old_trace + grad

            self.traces[neuron_id] = new_trace

    def get_weight_updates(self, learning_rate: float,
                            td_error: float) -> Dict[int, float]:
        """Compute weight updates: Δw = α * δ * e."""
        updates = {}
        for neuron_id, trace in self.traces.items():
            updates[neuron_id] = learning_rate * td_error * trace
        return updates


# ─── Hebbian Learning ─────────────────────────────────────────────────────────

class HebbianLearner:
    """
    Classic Hebbian and variants: Hebb, Oja, BCM.
    """

    def __init__(self, rule: str = 'hebb', learning_rate: float = 0.01):
        self.rule = rule
        self.lr = learning_rate

    def hebb(self, pre_act: float, post_act: float, weight: float) -> float:
        """Classic Hebb: Δw = η * x * y."""
        return self.lr * pre_act * post_act

    def oja(self, pre_act: float, post_act: float, weight: float) -> float:
        """
        Oja's rule: Δw = η * y * (x - y*w).
        Normalizes weights implicitly. Converges to first PC.
        """
        return self.lr * post_act * (pre_act - post_act * weight)

    def bcm(self, pre_act: float, post_act: float, weight: float,
            theta_m: float = 0.1) -> float:
        """
        BCM rule (Bienenstock, Cooper, Munro, 1982):
        Δw = η * y * (y - θ_M) * x, where θ_M = E[y^2] (sliding threshold).

        LTP when post > θ_M (high activity), LTD when post < θ_M (low activity).
        """
        if post_act > theta_m:
            delta = self.lr * post_act * (post_act - theta_m) * pre_act
        else:
            delta = self.lr * post_act * (post_act - theta_m) * pre_act
        return delta

    def covariance(self, pre_act: float, post_act: float,
                    pre_mean: float = 0.0, post_mean: float = 0.0) -> float:
        """Covariance rule: Δw = η * (x - x̄) * (y - ȳ)."""
        return self.lr * (pre_act - pre_mean) * (post_act - post_mean)

    def compute_delta(self, pre_act: float, post_act: float,
                       weight: float, theta_m: float = 0.1,
                       pre_mean: float = 0.0, post_mean: float = 0.0) -> float:
        """Dispatch to the configured Hebbian rule."""
        if self.rule == 'hebb':
            return self.hebb(pre_act, post_act, weight)
        elif self.rule == 'oja':
            return self.oja(pre_act, post_act, weight)
        elif self.rule == 'bcm':
            return self.bcm(pre_act, post_act, weight, theta_m)
        elif self.rule == 'covariance':
            return self.covariance(pre_act, post_act, pre_mean, post_mean)
        else:
            raise ValueError(f"Unknown Hebbian rule: {self.rule}")


# ─── Main STDP Learner ────────────────────────────────────────────────────────

class STDPLearner:
    """
    Complete STDP-based learning engine.
    Integrates: pair/triplet STDP, eligibility traces, Hebbian variants, dopamine modulation.
    """

    def __init__(self, n_neurons: int = 50,
                 stdp_tau_plus: float = 20.0,
                 stdp_tau_minus: float = 20.0,
                 lambda_: float = 0.9,
                 hebb_rule: str = 'hebb'):
        self.network = LIFNetwork(n_neurons)
        self.stdp = STDPRule(tau_plus=stdp_tau_plus, tau_minus=stdp_tau_minus,
                              use_triplet=True)
        self.eligibility = EligibilityTraceEngine(lambda_=lambda_)
        self.hebbian = HebbianLearner(rule=hebb_rule)
        self.dopamine: float = 0.0
        self.dopamine_tau: float = 50.0  # decay time constant (ms)
        self._time: float = 0.0
        self._activity_log: List[Dict] = []

    def connect_dense(self, weight_scale: float = 0.05):
        """Initialize dense connectivity."""
        self.network.connect_all_to_all(weight_scale)

    def step(self, inputs: Optional[Dict[int, float]] = None,
              dt: float = 1.0) -> Dict:
        """Run one simulation step with learning."""
        self._time += dt

        # Apply inputs
        if inputs:
            for nid, current in inputs.items():
                self.network.set_input(nid, current)

        # Simulate
        spikes = self.network.step(dt)
        spike_ids = {s.neuron_id for s in spikes}

        # STDP learning
        for (pre_id, post_id), synapse in self.network.synapses.items():
            pre_fired = pre_id in spike_ids
            post_fired = post_id in spike_ids

            # Update traces
            self.stdp.update_traces(synapse, dt, pre_fired, post_fired)

            # Apply STDP
            if self.stdp.use_triplet:
                dw = self.stdp.apply_triplet_stdp(synapse, pre_fired, post_fired,
                                                   self.dopamine)
            else:
                pre_spikes = self.network.neurons[pre_id].spike_history[-5:]
                post_spikes = self.network.neurons[post_id].spike_history[-5:]
                dw = self.stdp.apply_pair_stdp(synapse, pre_spikes, post_spikes)

            # Apply dopamine modulation
            dw *= (1.0 + self.dopamine)

            # Clamp weights
            synapse.weight = max(self.stdp.w_min,
                                  min(self.stdp.w_max, synapse.weight + dw))
            synapse.dopamine_trace += self.dopamine * dt / 1.0
            synapse.dopamine_trace *= math.exp(-dt / 100.0)

            if dw > 0:
                synapse.ltp_history.append(dw)
            elif dw < 0:
                synapse.ltd_history.append(-dw)

        # Eligibility trace update (for reinforcement)
        if spike_ids:
            gradients = {nid: 1.0 for nid in spike_ids}
            td_error = self.dopamine  # dopamine ≈ RPE ≈ TD error
            self.eligibility.update(gradients, td_error)
            self.eligibility.decay(dt)

        # Dopamine decay
        self.dopamine *= math.exp(-dt / self.dopamine_tau)

        # Log activity
        self._activity_log.append({
            'time': self._time,
            'n_spikes': len(spikes),
            'spike_ids': list(spike_ids),
            'dopamine': round(self.dopamine, 4),
            'mean_weight': round(self.mean_weight(), 6)
        })

        return {
            'time': self._time,
            'n_spikes': len(spikes),
            'spike_ids': list(spike_ids),
            'dopamine': self.dopamine
        }

    def deliver_reward(self, reward: float):
        """Deliver a reward signal: increases dopamine → modulates plasticity."""
        self.dopamine = max(0.0, self.dopamine + reward)

    def deliver_punishment(self, punishment: float):
        """Deliver a punishment: decreases dopamine → suppresses LTP."""
        self.dopamine = max(-0.5, self.dopamine - punishment)

    def mean_weight(self) -> float:
        """Average synaptic weight across the network."""
        if not self.network.synapses:
            return 0.0
        return float(np.mean([s.weight for s in self.network.synapses.values()]))

    def run_hebbian_epoch(self, input_patterns: List[np.ndarray],
                           epochs: int = 100) -> np.ndarray:
        """
        Run Hebbian learning on input patterns.
        Returns the learned weight matrix.
        """
        n = len(input_patterns[0]) if input_patterns else 0
        if n == 0:
            return np.array([])

        weights = self._rng_hebb.randn(n, n) * 0.01 if hasattr(self, '_rng_hebb') else \
                   np.random.RandomState(42).randn(n, n) * 0.01
        self._rng_hebb = np.random.RandomState(43)

        theta_m = 0.1  # BCM sliding threshold

        for epoch in range(epochs):
            pattern = input_patterns[epoch % len(input_patterns)]
            activity = pattern  # simplified: output = input for auto-association

            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    dw = self.hebbian.compute_delta(
                        pre_act=float(pattern[i]),
                        post_act=float(activity[j]),
                        weight=weights[i, j],
                        theta_m=theta_m,
                        pre_mean=float(np.mean(pattern)),
                        post_mean=float(np.mean(activity))
                    )
                    weights[i, j] += dw

            # BCM threshold update
            theta_m = 0.999 * theta_m + 0.001 * float(np.mean(activity ** 2))

        return weights

    def weight_matrix(self) -> np.ndarray:
        """Return the current synaptic weight matrix."""
        n = self.network.n
        w = np.zeros((n, n))
        for (pre, post), syn in self.network.synapses.items():
            if 0 <= pre < n and 0 <= post < n:
                w[pre, post] = syn.weight
        return w

    def stats(self) -> Dict:
        """Return learning statistics."""
        weights = [s.weight for s in self.network.synapses.values()]
        if not weights:
            return {'n_synapses': 0}

        return {
            'n_synapses': len(weights),
            'mean_weight': float(np.mean(weights)),
            'std_weight': float(np.std(weights)),
            'min_weight': float(np.min(weights)),
            'max_weight': float(np.max(weights)),
            'sparsity': float(np.mean(np.array(weights) < 0.01)),
            'dopamine': round(self.dopamine, 4),
            'time_ms': self._time
        }

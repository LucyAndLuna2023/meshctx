"""
Cerebellar Forward Model — 小脑内部前向模型 (v3.115.16)
基于 Ito(2008) 小脑内部模型 + Wolpert(1998) 前向模型 + Miall(1993) Smith预测器

核心机制:
1. 内部前向模型 (Ito, 2008; Wolpert et al., 1998):
   - 小脑构建感觉运动后果的内部预测
   - 攀缘纤维(Climbing Fibers): 传递误差信号 → 驱动 LTD/LTP
   - 平行纤维(Parallel Fibers): 携带上下文信息

2. Smith Predictor 架构 (Miall et al., 1993):
   - 内反馈回路: 小脑预测输出→立即反馈, 无需等待感觉延迟
   - 外反馈回路: 真实感觉反馈→延迟到达→修正内部模型
   - 延迟补偿: 克服100-200ms的感觉反馈延迟

3. Error-Driven Learning (Ito, 2001):
   - 爬行纤维: 传递"意外"/预测误差 (~1-4 Hz)
   - 平行纤维→浦肯野细胞 LTD: coincidence detection 驱动学习
   - 预测误差下行: 使用MSE梯度更新内部模型权重

4. 运动学习与时间控制:
   - 自适应滤波器: 校正时间序列中的系统误差
   - 小脑皮层微区: 每个微区独立学习特定的感觉运动映射

参考文献:
- Ito M (2008) Control of mental activities by internal models in the cerebellum
- Wolpert DM et al. (1998) Internal models in the cerebellum
- Miall RC et al. (1993) Is the cerebellum a Smith predictor?
- Ito M (2001) Cerebellar long-term depression
- Kawato M, Gomi H (1992) A computational model of four regions of the cerebellum
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Callable
import time
import math


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ForwardPrediction:
    """Output of the cerebellar forward model."""
    predicted_state: np.ndarray
    predicted_sensory: np.ndarray
    confidence: float
    prediction_error: float
    delay_compensation: float
    learning_signal: float  # climbing fiber activity


@dataclass
class SmithPredictorState:
    """State maintained by the Smith predictor architecture."""
    internal_prediction: np.ndarray  # model-based prediction (fast, no delay)
    delayed_prediction: np.ndarray   # delayed version of prediction
    actual_feedback: np.ndarray      # real sensory feedback (delayed)
    error_corrected: np.ndarray      # prediction + delayed error correction
    smith_output: np.ndarray         # final output after Smith compensation
    prediction_error: float
    delay_steps: int


# ─── Granule Cell Layer ──────────────────────────────────────────────────────
# Granule cells: massive expansion (10^11 in humans), sparse recoding of inputs.
# Each granule cell receives ~4 mossy fiber inputs.

class GranuleCellLayer:
    """
    Granule cell layer — sparse expansion recoding.
    Maps low-dim input → high-dim sparse representation via random projections.
    Analogous to cerebellar granule cells: ~4 mossy fiber inputs each.
    """

    def __init__(self, input_dim: int = 16, n_granule_cells: int = 256,
                 sparsity: float = 0.05, seed: int = 42):
        self.input_dim = input_dim
        self.n_granules = n_granule_cells
        self.sparsity = sparsity  # fraction of cells active at once

        # Mossy fiber → Granule cell weights (fixed, sparse random)
        rng = np.random.RandomState(seed)
        self.weights = rng.randn(n_granule_cells, input_dim) * 0.1
        # Sparsify: each granule cell connects to only ~4 mossy fibers
        mask = np.zeros((n_granule_cells, input_dim))
        for i in range(n_granule_cells):
            connections = rng.choice(input_dim, size=min(4, input_dim), replace=False)
            mask[i, connections] = 1.0
        self.weights *= mask

        # Golgi cell inhibition: regulates granule cell activity
        self.golgi_inhibition: float = 0.5
        self._activity_history: deque = deque(maxlen=50)

    def encode(self, mossy_fiber_input: np.ndarray) -> np.ndarray:
        """
        Encode mossy fiber input into sparse granule cell representation.
        Golgi inhibition regulates sparsity.
        """
        if len(mossy_fiber_input) < self.input_dim:
            mossy_fiber_input = np.pad(mossy_fiber_input,
                                       (0, self.input_dim - len(mossy_fiber_input)))
        mf = mossy_fiber_input[:self.input_dim]

        # Granule cell activation
        activations = self.weights @ mf

        # Golgi cell feedback inhibition → sparse coding
        threshold = np.percentile(activations, 100 * (1 - self.sparsity))
        threshold = threshold * (1.0 + self.golgi_inhibition * 0.5)

        # Sparse binary output
        granule_output = (activations > threshold).astype(np.float64)
        self._activity_history.append(float(np.mean(granule_output)))

        # Adjust Golgi inhibition to maintain target sparsity
        actual_sparsity = float(np.mean(granule_output))
        error = actual_sparsity - self.sparsity
        self.golgi_inhibition += 0.1 * error
        self.golgi_inhibition = np.clip(self.golgi_inhibition, 0.1, 0.9)

        return granule_output


# ─── Parallel Fiber → Purkinje Cell Synapses ────────────────────────────────
# Purkinje cells: sole output of cerebellar cortex. ~200K parallel fiber synapses each.
# LTD/LTP at PF→PC synapses is the primary learning mechanism.

class PurkinjeCellLayer:
    """
    Purkinje cell layer — adaptive filter.
    Parallel fiber → Purkinje cell synapses undergo LTD/LTP based on
    climbing fiber error signals (coincidence detection).
    """

    def __init__(self, n_inputs: int = 256, n_purkinje: int = 8,
                 learning_rate: float = 0.01, ltd_threshold: float = 0.3):
        self.n_inputs = n_inputs
        self.n_purkinje = n_purkinje
        self.learning_rate = learning_rate
        self.ltd_threshold = ltd_threshold

        # PF → PC synaptic weights (learnable)
        rng = np.random.RandomState(77)
        self.weights = rng.randn(n_purkinje, n_inputs) * 0.01

        # Eligibility trace for STDP-like learning
        self.eligibility_trace = np.zeros((n_purkinje, n_inputs))
        self.eligibility_decay: float = 0.9

        # Basket/stellate cell lateral inhibition
        self.lateral_inhibition_strength: float = 0.3

    def forward(self, parallel_fibers: np.ndarray) -> np.ndarray:
        """
        Forward pass: PF input → Purkinje cell output.
        Purkinje cells are inhibitory on deep cerebellar nuclei.
        """
        if len(parallel_fibers) < self.n_inputs:
            parallel_fibers = np.pad(parallel_fibers,
                                     (0, self.n_inputs - len(parallel_fibers)))
        pf = parallel_fibers[:self.n_inputs]

        # Linear weighted sum (Purkinje simple spikes)
        outputs = self.weights @ pf

        # Lateral inhibition (basket cells)
        for i in range(self.n_purkinje):
            inhibition = 0.0
            for j in range(self.n_purkinje):
                if i != j:
                    inhibition += np.tanh(outputs[j]) * self.lateral_inhibition_strength
            outputs[i] -= inhibition

        # Update eligibility trace (pre-synaptic activity × recent post-synaptic)
        self.eligibility_trace = self.eligibility_decay * self.eligibility_trace
        pf_reshaped = pf.reshape(1, -1)
        for i in range(self.n_purkinje):
            self.eligibility_trace[i] += np.tanh(outputs[i]) * pf

        # Purkinje output is inhibitory → negative sign in final output
        return -np.tanh(outputs)

    def learn(self, climbing_fiber_error: np.ndarray):
        """
        Climbing fiber-driven LTD/LTP.
        CF error > threshold → LTD (weaken active PF synapses).
        CF error < threshold → LTP (strengthen active PF synapses).
        Coincidence: PF active + CF active = LTD.
        """
        for i in range(self.n_purkinje):
            cf_err = climbing_fiber_error[i] if i < len(climbing_fiber_error) else 0.0

            if abs(cf_err) > self.ltd_threshold:
                # LTD: active PF synapses are weakened (error-driven depression)
                ltd_mask = self.eligibility_trace[i] > 0
                self.weights[i, ltd_mask] -= self.learning_rate * abs(cf_err) * \
                    self.eligibility_trace[i, ltd_mask]
            else:
                # LTP: inactive PF synapses are strengthened (homeostatic)
                ltp_mask = self.eligibility_trace[i] <= 0
                self.weights[i, ltp_mask] += self.learning_rate * 0.1 * \
                    np.abs(self.weights[i, ltp_mask])

        # Weight regularization
        self.weights = np.clip(self.weights, -2.0, 2.0)


# ─── Deep Cerebellar Nuclei ──────────────────────────────────────────────────
# DCN: integrate Purkinje inhibition + mossy/ climbing fiber excitation.
# Final output stage of cerebellum.

class DeepCerebellarNuclei:
    """
    Deep cerebellar nuclei — integrate Purkinje inhibition with excitatory inputs.
    Mossy fibers and climbing fibers send collaterals to DCN providing excitatory drive.
    Purkinje cells provide inhibitory sculpting.
    """

    def __init__(self, n_neurons: int = 8, baseline_rate: float = 40.0):
        self.n_neurons = n_neurons
        self.baseline_rate = baseline_rate  # Hz, typical DCN firing rate
        # DCN has rebound excitation after Purkinje inhibition
        self.rebound_factor: float = 0.3
        self._prev_inhibition = np.zeros(n_neurons)
        # Adaptive output scaling — calibrates DCN magnitude to state space (v3.115.38)
        self.output_scale: float = 0.02
        self.scale_adaptation_rate: float = 0.01
        self.target_activation: float = 0.3

    def integrate(self, purkinje_inhibition: np.ndarray,
                  mossy_excitation: np.ndarray,
                  climbing_excitation: np.ndarray) -> np.ndarray:
        """
        Integrate Purkinje inhibition + excitatory inputs → DCN output.

        Purkinje cells are GABAergic (inhibitory on DCN).
        Mossy/climbing fibers provide glutamatergic excitation.

        Rebound: after strong Purkinje inhibition, DCN cells fire a burst
        (T-type Ca2+ channels de-inactivate during hyperpolarization).
        """
        if len(purkinje_inhibition) < self.n_neurons:
            purkinje_inhibition = np.pad(purkinje_inhibition,
                                         (0, self.n_neurons - len(purkinje_inhibition)))
        if len(mossy_excitation) < self.n_neurons:
            mossy_excitation = np.pad(mossy_excitation,
                                      (0, self.n_neurons - len(mossy_excitation)))

        p_inh = purkinje_inhibition[:self.n_neurons]
        m_exc = mossy_excitation[:self.n_neurons]

        # Net input
        net_input = m_exc * 0.6 - p_inh

        # Rebound excitation: if previous inhibition was strong, add rebound
        rebound = np.maximum(0, -self._prev_inhibition) * self.rebound_factor

        # Firing rate model (sigmoid) + adaptive output scaling
        raw_output = self.baseline_rate * (1.0 + np.tanh(net_input + rebound))
        # Adaptive scaling: drive DCN output mean toward target activation level
        output = raw_output * self.output_scale
        # Adapt scale based on activation deviation
        self.output_scale *= (1.0 + self.scale_adaptation_rate *
            np.clip(self.target_activation - np.mean(np.abs(output)), -0.5, 0.5))
        self.output_scale = float(np.clip(self.output_scale, 0.001, 0.1))

        self._prev_inhibition = p_inh.copy()
        return output


# ─── Internal Forward Model ──────────────────────────────────────────────────
# The core forward model: predicts sensory consequences of motor commands.

class InternalForwardModel:
    """
    Internal forward model (Ito, 2008; Wolpert, 1998).

    Given current state + motor command → predicts next sensory state.
    Learning: minimizes prediction error via climbing fiber-driven LTD.

    This is the core cerebellar computation: predicting consequences.
    """

    def __init__(self, state_dim: int = 8, command_dim: int = 4,
                 hidden_dim: int = 64, learning_rate: float = 0.02):
        self.state_dim = state_dim
        self.command_dim = command_dim
        self.hidden_dim = hidden_dim
        self.input_dim = state_dim + command_dim

        # Neural network as forward model (learning adaptive filter)
        rng = np.random.RandomState(123)
        self.W1 = rng.randn(hidden_dim, self.input_dim) * 0.1 / np.sqrt(self.input_dim)
        self.b1 = np.zeros(hidden_dim)
        self.W2 = rng.randn(state_dim, hidden_dim) * 0.1 / np.sqrt(hidden_dim)
        self.b2 = np.zeros(state_dim)

        # Adam optimizer state (v3.115.38 — replaces plain momentum)
        self.learning_rate = learning_rate * 3.0  # 0.02→0.06 baseline
        self.beta1: float = 0.9
        self.beta2: float = 0.999
        self.eps: float = 1e-8
        self.t: int = 0
        self.m_W1 = np.zeros_like(self.W1)
        self.v_W1 = np.zeros_like(self.W1)
        self.m_W2 = np.zeros_like(self.W2)
        self.v_W2 = np.zeros_like(self.W2)
        self.m_b1 = np.zeros_like(self.b1)
        self.v_b1 = np.zeros_like(self.b1)
        self.m_b2 = np.zeros_like(self.b2)
        self.v_b2 = np.zeros_like(self.b2)

        # Prediction error history
        self.error_history: deque = deque(maxlen=100)
        self.total_updates: int = 0

    def predict(self, state: np.ndarray, command: np.ndarray) -> np.ndarray:
        """
        Predict next sensory state — residual learning (v3.115.38).
        Network learns Δ (change) rather than absolute next state.
        Default prior: state remains unchanged (zero-order hold).
        """
        # Concatenate state + command
        if len(state) < self.state_dim:
            state = np.pad(state, (0, self.state_dim - len(state)))
        if len(command) < self.command_dim:
            command = np.pad(command, (0, self.command_dim - len(command)))

        x = np.concatenate([state[:self.state_dim], command[:self.command_dim]])

        # Forward pass through 2-layer network
        h = np.tanh(self.W1 @ x + self.b1)
        delta = self.W2 @ h + self.b2  # Network predicts change Δ

        # Residual connection: prediction = state*0.5 + Δ (zero-order hold prior)
        prediction = state[:self.state_dim] * 0.5 + delta

        return prediction[:self.state_dim]

    def compute_error(self, prediction: np.ndarray, actual: np.ndarray) -> float:
        """Compute prediction error (MSE)."""
        if len(prediction) != len(actual):
            n = min(len(prediction), len(actual))
            pred = prediction[:n]
            act = actual[:n]
        else:
            pred = prediction
            act = actual
        error = float(np.mean((pred - act) ** 2))
        self.error_history.append(error)
        return error

    def update(self, state: np.ndarray, command: np.ndarray,
               actual_next_state: np.ndarray) -> float:
        """
        Update forward model weights via gradient descent on prediction error.
        This is the climbing fiber-driven learning signal.
        """
        if len(state) < self.state_dim:
            state = np.pad(state, (0, self.state_dim - len(state)))
        if len(command) < self.command_dim:
            command = np.pad(command, (0, self.command_dim - len(command)))
        if len(actual_next_state) < self.state_dim:
            actual_next_state = np.pad(actual_next_state,
                                       (0, self.state_dim - len(actual_next_state)))

        x = np.concatenate([state[:self.state_dim], command[:self.command_dim]])

        # Forward pass
        h = np.tanh(self.W1 @ x + self.b1)
        prediction = self.W2 @ h + self.b2

        target = actual_next_state[:self.state_dim]
        error_signal = prediction - target  # dL/dprediction

        # Backward pass
        dW2 = np.outer(error_signal, h)
        db2 = error_signal
        dh = self.W2.T @ error_signal
        dh_raw = dh * (1 - h**2)  # tanh derivative
        dW1 = np.outer(dh_raw, x)
        db1 = dh_raw

        # Adam update (v3.115.38 — replaces momentum)
        self.t += 1
        # W2 update
        self.m_W2 = self.beta1 * self.m_W2 + (1 - self.beta1) * dW2
        self.v_W2 = self.beta2 * self.v_W2 + (1 - self.beta2) * dW2**2
        m_hat_W2 = self.m_W2 / (1 - self.beta1**self.t)
        v_hat_W2 = self.v_W2 / (1 - self.beta2**self.t)
        self.W2 -= self.learning_rate * m_hat_W2 / (np.sqrt(v_hat_W2) + self.eps)
        self.b2 -= self.learning_rate * db2 / (np.sqrt(self.v_b2 / (1 - self.beta2**self.t)) + self.eps)
        # W1 update
        self.m_W1 = self.beta1 * self.m_W1 + (1 - self.beta1) * dW1
        self.v_W1 = self.beta2 * self.v_W1 + (1 - self.beta2) * dW1**2
        m_hat_W1 = self.m_W1 / (1 - self.beta1**self.t)
        v_hat_W1 = self.v_W1 / (1 - self.beta2**self.t)
        self.W1 -= self.learning_rate * m_hat_W1 / (np.sqrt(v_hat_W1) + self.eps)
        # b1, b2 moment accumulators (simple update for biases)
        self.m_b1 = self.beta1 * self.m_b1 + (1 - self.beta1) * db1
        self.v_b1 = self.beta2 * self.v_b1 + (1 - self.beta2) * db1**2
        self.m_b2 = self.beta1 * self.m_b2 + (1 - self.beta1) * db2
        self.v_b2 = self.beta2 * self.v_b2 + (1 - self.beta2) * db2**2
        self.b1 -= self.learning_rate * self.m_b1 / (1 - self.beta1**self.t) / (np.sqrt(self.v_b1 / (1 - self.beta2**self.t)) + self.eps)

        self.total_updates += 1

        error = float(np.mean(error_signal ** 2))
        self.error_history.append(error)
        return error

    def get_prediction_confidence(self) -> float:
        """Confidence based on recent prediction error history."""
        if len(self.error_history) < 5:
            return 0.5
        recent = list(self.error_history)[-20:]
        mean_err = np.mean(recent)
        # Low error → high confidence
        confidence = np.exp(-mean_err * 5.0)
        return float(confidence)

    def reset_weights(self):
        """Reinitialize weights and Adam state."""
        rng = np.random.RandomState(123)
        self.W1 = rng.randn(self.hidden_dim, self.input_dim) * 0.1 / np.sqrt(self.input_dim)
        self.b1 = np.zeros(self.hidden_dim)
        self.W2 = rng.randn(self.state_dim, self.hidden_dim) * 0.1 / np.sqrt(self.hidden_dim)
        self.b2 = np.zeros(self.state_dim)
        self.m_W1 = np.zeros_like(self.W1)
        self.v_W1 = np.zeros_like(self.W1)
        self.m_W2 = np.zeros_like(self.W2)
        self.v_W2 = np.zeros_like(self.W2)
        self.m_b1 = np.zeros_like(self.b1)
        self.v_b1 = np.zeros_like(self.b1)
        self.m_b2 = np.zeros_like(self.b2)
        self.v_b2 = np.zeros_like(self.b2)
        self.t = 0
        self.error_history.clear()
        self.total_updates = 0


# ─── Smith Predictor ─────────────────────────────────────────────────────────
# Miall et al. (1993): cerebellum implements a Smith predictor for delay compensation.

class SmithPredictor:
    """
    Smith Predictor architecture (Miall et al., 1993).

    Problem: sensory feedback delays (~100-200ms) make real-time control unstable.
    Solution: internal forward model predicts immediate outcome → use prediction
             for fast control; use delayed real feedback to correct the model.

    Architecture:
        Command → [Forward Model] → Fast Prediction → [Controller]
                → [Plant/Delay]    → Delayed Feedback ─┐
                                                         ├→ [Delay Model] → Error
                 Fast Prediction → [Delay Model] ───────┘

    The delay model stores predictions and compares them with delayed feedback.
    """

    def __init__(self, state_dim: int = 8,
                 feedback_delay_steps: int = 3):
        self.state_dim = state_dim
        self.feedback_delay_steps = feedback_delay_steps

        # Ring buffer for delayed predictions
        self._prediction_buffer: deque = deque(maxlen=feedback_delay_steps + 1)
        # Ring buffer for delayed commands
        self._command_buffer: deque = deque(maxlen=feedback_delay_steps + 1)

        # Delay model: learns to match delayed predictions to delayed feedback
        self._delay_correction: float = 0.0
        self._correction_history: deque = deque(maxlen=50)

    def feed_command(self, command: np.ndarray):
        """Record a command for delay modeling."""
        self._command_buffer.append(command.copy() if isinstance(command, np.ndarray)
                                    else np.array(command))

    def predict_and_correct(self, current_state: np.ndarray,
                            forward_model: InternalForwardModel,
                            actual_feedback: Optional[np.ndarray] = None) -> SmithPredictorState:
        """
        Run Smith predictor:
        1. Use forward model to get fast prediction
        2. If actual feedback available, compute delayed error
        3. Correct current prediction with delayed error
        """
        # Fast prediction using internal forward model
        if self._command_buffer:
            command = self._command_buffer[-1]
        else:
            command = np.zeros(self.state_dim)

        fast_prediction = forward_model.predict(current_state, command)
        self._prediction_buffer.append(fast_prediction.copy())

        # Initialize output
        delayed_prediction = np.zeros(self.state_dim)
        error = 0.0
        actual = np.zeros(self.state_dim)

        # If we have enough history, retrieve delayed prediction
        if len(self._prediction_buffer) > self.feedback_delay_steps:
            delayed_prediction = self._prediction_buffer[0]

        # Compare delayed prediction with actual feedback (if available)
        if actual_feedback is not None:
            actual = actual_feedback[:self.state_dim] if len(actual_feedback) > self.state_dim \
                else actual_feedback
            if len(self._prediction_buffer) > self.feedback_delay_steps:
                error = float(np.mean((delayed_prediction - actual) ** 2))
                # Update delay correction (exponential smoothing)
                correction_update = float(np.mean(actual - delayed_prediction))
                self._delay_correction = 0.7 * self._delay_correction + 0.3 * correction_update
                self._correction_history.append(error)

        # Smith output = fast prediction + delayed error correction
        error_corrected = fast_prediction + self._delay_correction * np.ones(self.state_dim) * 0.5
        smith_output = error_corrected.copy()

        return SmithPredictorState(
            internal_prediction=fast_prediction,
            delayed_prediction=delayed_prediction,
            actual_feedback=actual,
            error_corrected=error_corrected,
            smith_output=smith_output,
            prediction_error=error,
            delay_steps=min(self.feedback_delay_steps, len(self._prediction_buffer)),
        )

    def get_delay_compensation_quality(self) -> float:
        """How well the delay compensation is tracking."""
        if len(self._correction_history) < 5:
            return 1.0
        mean_err = np.mean(self._correction_history)
        return max(0.0, 1.0 - mean_err * 3.0)


# ─── Complete CerebellarForwardModel ─────────────────────────────────────────

class CerebellarForwardModel:
    """
    Complete cerebellar internal model system.

    Pipeline:
    Command + State
        → GranuleCellLayer (sparse expansion)
        → PurkinjeCellLayer (adaptive filter, LTD/LTP learning)
        → DeepCerebellarNuclei (integrate + rebound)
        → InternalForwardModel (predict next sensory state)
        → SmithPredictor (delay compensation)

    Key features:
    - ~10-20ms forward prediction latency (matches biology)
    - LTD at PF→PC synapses driven by climbing fiber error
    - Smith predictor compensates for 100-200ms feedback delays
    - Adaptive learning rate modulated by prediction confidence
    """

    def __init__(self, state_dim: int = 8, command_dim: int = 4,
                 feedback_delay: int = 3, learning_rate: float = 0.02):
        self.state_dim = state_dim
        self.command_dim = command_dim

        # Cerebellar cortex layers
        self.granule_layer = GranuleCellLayer(
            input_dim=state_dim + command_dim,
            n_granule_cells=256,
            sparsity=0.05,
        )
        self.purkinje_layer = PurkinjeCellLayer(
            n_inputs=256,
            n_purkinje=8,
            learning_rate=learning_rate,
        )
        self.deep_nuclei = DeepCerebellarNuclei(n_neurons=state_dim)

        # Internal forward model (learnable)
        self.forward_model = InternalForwardModel(
            state_dim=state_dim,
            command_dim=command_dim,
            learning_rate=learning_rate,
        )

        # Smith predictor for delay compensation
        self.smith = SmithPredictor(
            state_dim=state_dim,
            feedback_delay_steps=feedback_delay,
        )

        # Learning state
        self._last_state: Optional[np.ndarray] = None
        self._last_command: Optional[np.ndarray] = None
        self._last_prediction: Optional[np.ndarray] = None
        self.total_predictions: int = 0
        self.total_updates: int = 0

    def predict(self, state: np.ndarray, command: np.ndarray,
                actual_feedback: Optional[np.ndarray] = None) -> ForwardPrediction:
        """
        Generate forward prediction of next sensory state.

        Args:
            state: current state vector
            command: motor/action command vector
            actual_feedback: actual sensory feedback (if available, for correction)
        """
        self.total_predictions += 1

        # 1. Granule cell sparse encoding
        combined_input = np.concatenate([state[:self.state_dim],
                                         command[:self.command_dim]])
        granule_output = self.granule_layer.encode(combined_input)

        # 2. Purkinje cell adaptive filtering
        purkinje_output = self.purkinje_layer.forward(granule_output)

        # 3. Deep cerebellar nuclei integration
        # Mossy fiber excitation = command magnitude
        mossy_exc = np.abs(command[:self.state_dim]) if len(command) >= self.state_dim \
            else np.pad(np.abs(command), (0, self.state_dim - len(command)))
        # Climbing fiber excitation = prediction error magnitude (if available)
        climbing_exc = np.zeros(self.state_dim)
        if actual_feedback is not None:
            climbing_exc = np.abs(state[:self.state_dim] -
                                  actual_feedback[:self.state_dim])

        dcn_output = self.deep_nuclei.integrate(purkinje_output, mossy_exc, climbing_exc)

        # 4. Internal forward model prediction
        raw_prediction = self.forward_model.predict(state, command)

        # 5. Smith predictor delay compensation
        smith_state = self.smith.predict_and_correct(state, self.forward_model,
                                                      actual_feedback)

        # Combine: forward model + DCN modulation + Smith correction
        predicted_sensory = raw_prediction + dcn_output * 0.1 + \
            (smith_state.smith_output - raw_prediction) * 0.5

        # Confidence
        confidence = self.forward_model.get_prediction_confidence()

        # Prediction error
        if actual_feedback is not None:
            pred_error = float(np.mean(
                (predicted_sensory - actual_feedback[:self.state_dim]) ** 2
            ))
        else:
            pred_error = 0.0

        # Climbing fiber learning signal (prediction error)
        learning_signal = pred_error

        # Store for later update
        self._last_state = state.copy()
        self._last_command = command.copy()
        self._last_prediction = predicted_sensory.copy()
        self.smith.feed_command(command)

        return ForwardPrediction(
            predicted_state=predicted_sensory,
            predicted_sensory=predicted_sensory,
            confidence=confidence,
            prediction_error=pred_error,
            delay_compensation=self.smith.get_delay_compensation_quality(),
            learning_signal=learning_signal,
        )

    def update(self, actual_next_state: np.ndarray):
        """
        Update forward model and Purkinje synapses based on observed outcome.
        Climbing fiber carries the prediction error → drives LTD at PF→PC synapses.
        First 10 updates use 3× learning rate (warmup).
        """
        self.total_updates += 1

        if self._last_state is None or self._last_command is None:
            return

        # Warmup: first 10 steps use 3× learning rate for fast initial calibration
        warmup_factor = 3.0 if self.total_updates <= 10 else 1.0
        original_lr = self.forward_model.learning_rate
        self.forward_model.learning_rate = original_lr * warmup_factor

        # Update internal forward model weights
        self.forward_model.update(self._last_state, self._last_command, actual_next_state)

        self.forward_model.learning_rate = original_lr  # restore

        # Compute climbing fiber error for Purkinje layer
        if self._last_prediction is not None:
            climbing_error = self._last_prediction - actual_next_state[:self.state_dim]
        else:
            climbing_error = -actual_next_state[:self.state_dim]

        self.purkinje_layer.learn(climbing_error)

    def get_stats(self) -> dict:
        """Return diagnostic statistics."""
        return {
            "total_predictions": self.total_predictions,
            "total_updates": self.total_updates,
            "recent_prediction_error": round(
                float(np.mean(self.forward_model.error_history))
                if self.forward_model.error_history else 0.0, 6
            ),
            "prediction_confidence": round(self.forward_model.get_prediction_confidence(), 3),
            "delay_compensation_quality": round(self.smith.get_delay_compensation_quality(), 3),
            "granule_sparsity": round(float(np.mean(
                self.granule_layer._activity_history)) if self.granule_layer._activity_history else 0.0, 4
            ),
            "golgi_inhibition": round(self.granule_layer.golgi_inhibition, 3),
            "purkinje_weight_norm": round(float(np.linalg.norm(self.purkinje_layer.weights)), 3),
            "smith_delay_correction": round(self.smith._delay_correction, 4),
        }

    def reset(self):
        """Reset all learning state."""
        self.forward_model.reset_weights()
        self.purkinje_layer = PurkinjeCellLayer(
            n_inputs=256, n_purkinje=8,
            learning_rate=self.purkinje_layer.learning_rate,
        )
        self._last_state = None
        self._last_command = None
        self._last_prediction = None
        self.total_predictions = 0
        self.total_updates = 0

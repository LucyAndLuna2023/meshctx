"""
Insula — Interoception & Anomaly Detection (v3.115.16)
基于 Craig(2002) 内感受理论 + Seth(2013) 预测编码 + Paulus(2007) 岛叶风险处理

核心机制:
1. 内感受 (Craig, 2002, 2009; Critchley et al., 2004):
   - 前岛叶(AIC): 整合内脏感觉→意识情感（"gut feeling"）
   - 后岛叶(PIC): 接受脊髓/脑干内感受传入
   - Lamina I 脊髓神经元→丘脑VMpo→后岛叶→前岛叶 层级处理
   - 心跳感知、呼吸、胃肠、体温、疼痛 等多模态内感受

2. 异常检测 (Seth et al., 2013; Paulus & Stein, 2006):
   - 预测编码: 岛叶生成身体状态预测 → 比较实际传入 → 预测误差(=anomaly)
   - 岛叶作为"显著性网络"核心: 检测意外/异常身体状态
   - 风险感知: 前岛叶激活程度与风险规避正相关

3. 稳态监测 (Craig, 2002; Damasio, 1999):
   - 身体状态再表征: 岛叶是身体状态的"元表征"
   - 稳态偏移检测: 生理参数偏离设定点 → 产生"原始感受"(primordial feeling)
   - 同种(Allostasis): 预测性稳态调节, 不仅反应性

4. 情绪意识整合 (Craig, 2009):
   - 后岛叶→中岛叶→前岛叶: 从客观身体状态→主观情绪感受
   - von Economo神经元(前岛叶特有): 快速、直觉性身体状态意识

参考文献:
- Craig AD (2002) How do you feel? Interoception
- Seth AK et al. (2013) An interoceptive predictive coding model of conscious presence
- Paulus MP, Stein MB (2006) An insular view of anxiety
- Critchley HD et al. (2004) Neural systems supporting interoceptive awareness
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
import time
import math


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class InteroceptiveSignal:
    """A bodily interoceptive signal."""
    modality: str               # "heartbeat", "respiration", "temperature", ...
    raw_value: float
    predicted_value: float
    prediction_error: float
    salience: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class HomeostaticSetpoint:
    """Homeostatic setpoint for a physiological variable."""
    variable_name: str
    setpoint: float
    tolerance_range: float     # acceptable deviation
    error_gain: float          # how strongly deviations are amplified
    allostatic_adaptation: float = 0.0  # learned shift from baseline
    last_reading: float = 0.0
    drift_rate: float = 0.0    # slow drift (circadian, etc.)


@dataclass
class AnomalyReport:
    """Output of insular anomaly detection."""
    is_anomalous: bool
    anomaly_score: float
    affected_modalities: List[str]
    interoceptive_prediction_error: float
    homeostatic_deviation: float
    risk_estimate: float
    gut_feeling: float         # integrated bodily awareness
    recommended_action: str    # "monitor", "alert", "intervene", "normal"


# ─── Posterior Insula — Interoceptive Signal Processing ──────────────────────
# PIC receives laminar I spinal inputs via VMpo thalamus. Maps body state.

class PosteriorInsula:
    """
    Posterior Insula (PIC) — primary interoceptive cortex.

    Receives: lamina I spinal afferents (via VMpo thalamus) carrying:
    - Cardiac signals (heart rate, heart rate variability)
    - Respiratory signals (breath rate, depth, CO2)
    - Gastrointestinal signals
    - Temperature (skin + core)
    - Pain (nociception)
    - Itch, muscle fatigue, etc.

    PIC performs initial sensory mapping: body → neural representation.
    """

    # Normal ranges for key interoceptive modalities
    DEFAULT_RANGES = {
        "heart_rate": (60.0, 80.0),       # bpm
        "hrv": (30.0, 80.0),              # ms (RMSSD)
        "resp_rate": (12.0, 18.0),        # breaths/min
        "temp_core": (36.5, 37.5),        # °C
        "temp_skin": (32.0, 35.0),        # °C
        "blood_pressure_sys": (110.0, 130.0),  # mmHg
        "blood_pressure_dia": (70.0, 85.0),    # mmHg
        "glucose": (70.0, 110.0),         # mg/dL
        "cortisol": (5.0, 20.0),         # μg/dL (morning)
        "oxygen_sat": (95.0, 100.0),      # %
        "galvanic_skin": (2.0, 10.0),     # μS
        "pain": (0.0, 3.0),              # subjective 0-10
    }

    def __init__(self, n_modalities: int = 8):
        self.n_modalities = n_modalities
        self.signal_buffer: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=60)
        )
        # Learned representations (simple running statistics)
        self.running_stats: Dict[str, Dict[str, float]] = {}

    def register_modality(self, name: str, normal_range: Tuple[float, float] = (0.0, 1.0)):
        """Register an interoceptive modality."""
        if name not in self.running_stats:
            self.running_stats[name] = {
                "mean": (normal_range[0] + normal_range[1]) / 2,
                "std": (normal_range[1] - normal_range[0]) / 3,
                "n_samples": 0,
                "lo": normal_range[0],
                "hi": normal_range[1],
            }

    def process_signal(self, modality: str, value: float) -> InteroceptiveSignal:
        """
        Process incoming interoceptive signal.

        Lamina I → VMpo → PIC pathway.
        PIC computes: raw mapping → normalized representation → initial prediction.
        """
        # Register if new
        if modality not in self.running_stats:
            if modality in self.DEFAULT_RANGES:
                self.register_modality(modality, self.DEFAULT_RANGES[modality])
            else:
                self.register_modality(modality)

        stats = self.running_stats[modality]
        self.signal_buffer[modality].append(value)

        # Online update of running statistics (Welford algorithm)
        stats["n_samples"] += 1
        old_mean = stats["mean"]
        stats["mean"] += (value - old_mean) / stats["n_samples"]
        stats["std"] = math.sqrt(
            ((stats["n_samples"] - 2) / (stats["n_samples"] - 1)) * stats["std"]**2 +
            (value - old_mean) * (value - stats["mean"]) / stats["n_samples"]
        ) if stats["n_samples"] > 2 else stats["std"]

        # Simple prediction = running mean (lazy predictive coding baseline)
        predicted_value = stats["mean"]

        # Z-score normalized prediction error
        std = max(stats["std"], 0.001)
        prediction_error = (value - predicted_value) / std

        # Salience = absolute z-score of deviation
        salience = abs((value - stats["mean"]) / std)
        salience = 1.0 - np.exp(-salience / 2.0)

        return InteroceptiveSignal(
            modality=modality,
            raw_value=value,
            predicted_value=predicted_value,
            prediction_error=float(prediction_error),
            salience=float(salience),
        )


# ─── Mid Insula — Integration & Context ──────────────────────────────────────
# Integrates posterior signals + emotional context from amygdala.

class MidInsula:
    """
    Mid Insula — integration hub.
    Combines PIC interoceptive representations with contextual/emotional info.
    Implements re-representation: body state → integrated body schema.
    """

    def __init__(self):
        self.integrated_state: Dict[str, float] = {}
        self._integration_weights: Dict[str, float] = {}
        self._contextual_bias: float = 0.0

    def integrate(self, signals: List[InteroceptiveSignal],
                  emotional_context: float = 0.0) -> Dict[str, float]:
        """
        Integrate multiple interoceptive signals into unified body schema.

        Emotional context (from amygdala) biases integration:
        - Anxiety: amplifies threat-related signals (heart rate, respiration)
        - Calm: dampens all signals equally
        """
        self._contextual_bias = emotional_context
        integrated = {}

        for sig in signals:
            # Learn integration weight (importance of each modality)
            if sig.modality not in self._integration_weights:
                self._integration_weights[sig.modality] = 0.5

            # Update weight based on salience (salient signals get more weight)
            alpha = 0.1
            self._integration_weights[sig.modality] += alpha * (
                sig.salience - self._integration_weights[sig.modality]
            )

            # Emotional amplification
            amplified = sig.prediction_error * (
                1.0 + abs(emotional_context) * self._integration_weights[sig.modality] * 0.5
            )

            integrated[sig.modality] = {
                "value": sig.raw_value,
                "prediction_error": float(amplified),
                "salience": sig.salience,
                "weight": self._integration_weights[sig.modality],
            }

        self.integrated_state = {
            k: v["prediction_error"] if isinstance(v, dict) else v
            for k, v in integrated.items()
        }
        return integrated

    def get_body_percept(self) -> float:
        """Get unified body percept (how the body 'feels' overall)."""
        if not self.integrated_state:
            return 0.0
        # Mean absolute deviation from predictions
        mean_dev = float(np.mean([abs(v) for v in self.integrated_state.values()]))
        return np.tanh(mean_dev)


# ─── Anterior Insula — Conscious Awareness ────────────────────────────────────
# AIC: von Economo neurons → rapid, intuitive awareness of body state.
# "Gut feeling" generator.

class AnteriorInsula:
    """
    Anterior Insula (AIC) — conscious interoceptive awareness.

    Von Economo neurons (VENs): large spindle-shaped neurons unique to AIC/ACC.
    Provide fast, intuitive "gut feeling" about body state.

    AIC activation correlates with:
    - Emotional awareness (Craig, 2009)
    - Risk perception (Paulus & Stein, 2006)
    - Decision-making under uncertainty
    - Empathy for others' pain
    """

    def __init__(self, awareness_threshold: float = 0.3):
        self.awareness_threshold = awareness_threshold
        self._awareness_history: deque = deque(maxlen=50)
        self._gut_feeling_accumulator: float = 0.0
        self._gut_feeling_decay: float = 0.9

        # Risk sensitivity (individual difference)
        self.risk_sensitivity: float = 1.0

    def compute_awareness(self, integrated_state: Dict[str, float],
                          prediction_error_summary: float) -> float:
        """
        Compute conscious awareness of body state.
        AIC activation = integrated interoceptive prediction error.
        """
        if not integrated_state:
            return 0.0

        # Mean absolute prediction error across modalities
        mean_pe = float(np.mean([abs(v) for v in integrated_state.values()]))

        # Sigmoid activation: small deviations → low awareness,
        # large deviations → high awareness ("something feels off")
        awareness = 1.0 - np.exp(-mean_pe * 2.0)

        self._awareness_history.append(awareness)
        return awareness

    def compute_gut_feeling(self, integrated_state: Dict[str, float],
                            update: bool = True) -> float:
        """
        Compute the "gut feeling" — rapidly accessible body-state summary.

        Gut feeling = exponentially-weighted moving average of interoceptive deviations.
        Accumulates over time, decays slowly.
        """
        if integrated_state:
            current_deviation = float(np.mean([
                abs(v) for v in integrated_state.values()
            ]))
        else:
            current_deviation = 0.0

        if update:
            self._gut_feeling_accumulator = (
                self._gut_feeling_decay * self._gut_feeling_accumulator +
                (1.0 - self._gut_feeling_decay) * current_deviation
            )

        return np.tanh(self._gut_feeling_accumulator * 2.0)

    def assess_risk(self, integrated_state: Dict[str, float]) -> float:
        """
        Paulus & Stein (2006): AIC activation reflects risk processing.

        Risk estimate = prediction error * risk sensitivity * modality weights.
        High AIC activation → risk-averse behavior.
        """
        if not integrated_state:
            return 0.0

        risk_score = 0.0
        for modality, value in integrated_state.items():
            pe = abs(value)
            # Core survival modalities have higher inherent risk
            survival_weight = 1.0
            if modality in ["heart_rate", "oxygen_sat", "blood_pressure_sys",
                           "temp_core", "pain"]:
                survival_weight = 1.5
            risk_score += pe * survival_weight

        risk_score = risk_score / max(len(integrated_state), 1)
        return float(np.tanh(risk_score * self.risk_sensitivity))


# ─── Predictive Coding Model ─────────────────────────────────────────────────
# Seth et al. (2013): interoceptive predictive coding.
# Brain generates predictions of body state → compares to actual → prediction error.

class InteroceptivePredictiveCoding:
    """
    Predictive coding model for interoception (Seth et al., 2013).

    Concept:
    - Higher levels generate descending predictions of body state
    - Lower levels (PIC) compare predictions to actual interoceptive signals
    - Prediction errors ascend → update higher-level models
    - Precision-weighted: more precise signals have more influence

    Homeostatic setpoints serve as "prior" predictions.
    """

    def __init__(self, learning_rate: float = 0.05):
        self.learning_rate = learning_rate
        self._predictive_models: Dict[str, Dict[str, float]] = {}
        self._precision_weights: Dict[str, float] = {}  # inverse variance
        self._prediction_history: deque = deque(maxlen=100)

    def set_setpoint(self, modality: str, setpoint: float, precision: float = 1.0):
        """Set homeostatic setpoint (= prior prediction)."""
        self._predictive_models[modality] = {
            "setpoint": setpoint,
            "adaptation": 0.0,
        }
        self._precision_weights[modality] = precision

    def predict(self, modality: str, history: deque) -> float:
        """
        Generate prediction of next interoceptive value.
        Simple model: exponentially-weighted mean of recent history, anchored to setpoint.
        """
        if modality not in self._predictive_models:
            if history:
                return float(np.mean(history))
            return 0.0

        model = self._predictive_models[modality]
        setpoint = model["setpoint"] + model["adaptation"]

        if history and len(history) > 0:
            recent = list(history)[-10:]
            recent_mean = float(np.mean(recent))
            # Blend recent data with setpoint prior
            precision = self._precision_weights.get(modality, 1.0)
            prior_weight = 0.3 * precision
            prediction = prior_weight * setpoint + (1.0 - prior_weight) * recent_mean
        else:
            prediction = setpoint

        return prediction

    def compute_prediction_error(self, modality: str, actual: float,
                                  predicted: float) -> float:
        """Compute precision-weighted prediction error."""
        precision = self._precision_weights.get(modality, 1.0)
        error = (actual - predicted) * precision
        self._prediction_history.append(abs(error))
        return error

    def update_model(self, modality: str, prediction_error: float):
        """
        Update predictive model (allostatic adaptation).

        Persistent prediction errors → shift setpoint adaptation.
        This implements allostasis: predictive regulation, not just reactive.
        """
        if modality in self._predictive_models:
            model = self._predictive_models[modality]
            # Slow adaptation: only sustained errors shift the model
            model["adaptation"] += self.learning_rate * prediction_error * 0.1
            model["adaptation"] = np.clip(model["adaptation"], -2.0, 2.0)


# ─── Anomaly Detection Engine ────────────────────────────────────────────────
# Insula detects anomalies in interoceptive stream.

class InsularAnomalyDetector:
    """
    Insula-based anomaly detection.

    Two detection modes:
    1. Point anomaly: single reading far from expected
    2. Contextual anomaly: reading normal in isolation but abnormal given context
    3. Collective anomaly: sequence of readings shows abnormal pattern
    """

    def __init__(self, z_threshold: float = 2.5, window_size: int = 30):
        self.z_threshold = z_threshold
        self.window_size = window_size
        self._anomaly_history: deque = deque(maxlen=100)
        self._modality_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=window_size)
        )

    def detect_point_anomaly(self, modality: str, value: float,
                             mean: float, std: float) -> Tuple[bool, float]:
        """Detect single-point anomaly via z-score."""
        if std < 0.001:
            return False, 0.0
        z_score = abs(value - mean) / std
        score = 1.0 - np.exp(-z_score / self.z_threshold)
        is_anomaly = z_score > self.z_threshold
        return is_anomaly, float(score)

    def detect_contextual_anomaly(self, modality: str, value: float,
                                   all_modalities: Dict[str, float]) -> Tuple[bool, float]:
        """
        Contextual anomaly: value is normal for this modality alone,
        but unusual given the state of other modalities.
        E.g., high heart rate with low respiration rate is anomalous.
        """
        self._modality_history[modality].append(value)

        if len(self._modality_history[modality]) < 10:
            return False, 0.0

        # Build inter-modality correlation matrix from history
        modalities = list(all_modalities.keys())
        if len(modalities) < 2:
            return False, 0.0

        n = min(30, min(len(self._modality_history[m]) for m in modalities
                         if m in self._modality_history))
        if n < 10:
            return False, 0.0

        # Simple contextual check: is this value anomalous relative to others?
        # Use Mahalanobis-like distance in the interoceptive space
        modality_values = []
        for m in modalities:
            if m in self._modality_history:
                recent = list(self._modality_history[m])[-n:]
                modality_values.append(recent)
            else:
                modality_values.append([0.0] * n)

        # Build covariance matrix
        data = np.array(modality_values).T  # (n_samples, n_modalities)
        if data.shape[1] < 2:
            return False, 0.0

        try:
            mean_vec = np.mean(data, axis=0)
            cov = np.cov(data.T)
            cov += np.eye(cov.shape[0]) * 1e-6
            cov_inv = np.linalg.inv(cov)

            # Current values vector
            current = np.array([all_modalities.get(m, 0.0) for m in modalities])
            diff = current - mean_vec
            mahalanobis = np.sqrt(diff @ cov_inv @ diff)

            score = 1.0 - np.exp(-mahalanobis / 3.0)
            is_anomaly = mahalanobis > self.z_threshold
            return is_anomaly, float(score)
        except np.linalg.LinAlgError:
            return False, 0.0

    def detect_collective_anomaly(self, modality: str) -> Tuple[bool, float]:
        """Detect if recent sequence of readings is anomalous."""
        if modality not in self._modality_history:
            return False, 0.0
        history = list(self._modality_history[modality])
        if len(history) < 10:
            return False, 0.0

        recent = history[-10:]
        older = history[:-10] if len(history) > 10 else history
        if len(older) < 5:
            return False, 0.0

        # Compare recent window statistics to older statistics
        recent_mean = np.mean(recent)
        recent_std = np.std(recent)
        older_mean = np.mean(older)
        older_std = np.std(older)

        # z-test for mean shift
        pooled_std = math.sqrt((recent_std**2 + older_std**2) / 2)
        if pooled_std < 0.001:
            return False, 0.0

        mean_shift = abs(recent_mean - older_mean) / pooled_std
        score = 1.0 - np.exp(-mean_shift / 2.0)
        is_anomaly = mean_shift > 2.0

        return is_anomaly, float(score)


# ─── Complete Insula ─────────────────────────────────────────────────────────

class Insula:
    """
    Complete insular cortex interoception and anomaly detection system.

    Pipeline:
    Interoceptive signals → Posterior Insula (PIC) → Mid Insula (integration)
        → Anterior Insula (awareness) → Anomaly Detection → Output

    Key features:
    - ~50-100ms interoceptive processing latency
    - Predictive coding: body state predictions vs actual signals
    - Multi-level anomaly detection (point, contextual, collective)
    - Homeostatic monitoring with allostatic adaptation
    - Gut feeling / interoceptive awareness output
    """

    def __init__(self, learning_rate: float = 0.05,
                 anomaly_threshold: float = 2.5):
        # Cortical layers
        self.posterior = PosteriorInsula()
        self.mid = MidInsula()
        self.anterior = AnteriorInsula()

        # Predictive coding
        self.predictive_coding = InteroceptivePredictiveCoding(
            learning_rate=learning_rate
        )

        # Anomaly detection
        self.anomaly_detector = InsularAnomalyDetector(
            z_threshold=anomaly_threshold
        )

        # Homeostatic setpoints
        self.setpoints: Dict[str, HomeostaticSetpoint] = {}
        self._init_default_setpoints()

        # State
        self.last_processed: Dict[str, InteroceptiveSignal] = {}
        self.anomaly_count: int = 0
        self.normal_count: int = 0

    def _init_default_setpoints(self):
        """Initialize default homeostatic setpoints."""
        for modality, (lo, hi) in PosteriorInsula.DEFAULT_RANGES.items():
            setpoint = (lo + hi) / 2
            tolerance = (hi - lo) / 2
            self.setpoints[modality] = HomeostaticSetpoint(
                variable_name=modality,
                setpoint=setpoint,
                tolerance_range=tolerance,
                error_gain=1.0,
            )
            self.predictive_coding.set_setpoint(modality, setpoint)

    def add_setpoint(self, variable_name: str, setpoint: float,
                     tolerance: float = 1.0, error_gain: float = 1.0):
        """Add or update a homeostatic setpoint."""
        self.setpoints[variable_name] = HomeostaticSetpoint(
            variable_name=variable_name,
            setpoint=setpoint,
            tolerance_range=tolerance,
            error_gain=error_gain,
        )
        self.predictive_coding.set_setpoint(variable_name, setpoint)

    def process(self, interoceptive_data: Dict[str, float],
                emotional_context: float = 0.0) -> Tuple[AnomalyReport, float]:
        """
        Process a snapshot of interoceptive data.

        Args:
            interoceptive_data: dict of modality → value
            emotional_context: amygdala valence/arousal for mid-insula integration
        Returns:
            (AnomalyReport, gut_feeling)
        """
        # 1. Posterior Insula: process each modality
        signals: List[InteroceptiveSignal] = []
        for modality, value in interoceptive_data.items():
            sig = self.posterior.process_signal(modality, value)

            # Predictive coding: generate prediction, compute error
            history = self.posterior.signal_buffer[modality]
            prediction = self.predictive_coding.predict(modality, history)
            pe = self.predictive_coding.compute_prediction_error(
                modality, value, prediction
            )
            self.predictive_coding.update_model(modality, pe)

            # Enrich signal with predictive info
            sig.predicted_value = prediction
            sig.prediction_error = float(pe)
            signals.append(sig)
            self.last_processed[modality] = sig

        # 2. Mid Insula: integrate across modalities
        integrated = self.mid.integrate(signals, emotional_context)

        # 3. Anterior Insula: compute awareness + gut feeling
        unified_state = self.mid.integrated_state
        awareness = self.anterior.compute_awareness(
            unified_state,
            self.mid.get_body_percept()
        )
        gut_feeling = self.anterior.compute_gut_feeling(unified_state)

        # 4. Anomaly detection
        anomaly_modalities: List[str] = []
        total_anomaly_score = 0.0
        n_anomalies = 0

        for modality, value in interoceptive_data.items():
            stats = self.posterior.running_stats.get(modality, {})
            mean = stats.get("mean", 0.0)
            std = max(stats.get("std", 1.0), 0.001)

            # Point anomaly
            is_point, point_score = self.anomaly_detector.detect_point_anomaly(
                modality, value, mean, std
            )

            # Contextual anomaly
            is_context, context_score = self.anomaly_detector.detect_contextual_anomaly(
                modality, value, interoceptive_data
            )

            # Collective anomaly
            is_collective, collective_score = self.anomaly_detector.detect_collective_anomaly(
                modality
            )

            # Combine anomaly signals
            combined_score = max(point_score, context_score * 0.8,
                                 collective_score * 0.6)
            if is_point or is_context or is_collective:
                anomaly_modalities.append(modality)
                n_anomalies += 1
                total_anomaly_score += combined_score

        # 5. Homeostatic deviation check
        homeo_deviation = 0.0
        for modality, value in interoceptive_data.items():
            if modality in self.setpoints:
                sp = self.setpoints[modality]
                deviation = abs(value - sp.setpoint) / max(sp.tolerance_range, 0.01)
                sp.last_reading = value
                homeo_deviation += deviation * sp.error_gain

        homeo_deviation /= max(len(interoceptive_data), 1)

        # 6. Risk estimate
        risk = self.anterior.assess_risk(unified_state)

        # 7. Determine overall anomaly
        avg_anomaly = total_anomaly_score / max(n_anomalies, 1)
        is_anomalous = n_anomalies > 0 and avg_anomaly > 0.3

        if is_anomalous:
            self.anomaly_count += 1
        else:
            self.normal_count += 1

        # 8. Recommended action based on severity
        if homeo_deviation > 2.0 or avg_anomaly > 0.7:
            action = "intervene"
        elif homeo_deviation > 1.0 or avg_anomaly > 0.5:
            action = "alert"
        elif homeo_deviation > 0.5:
            action = "monitor"
        else:
            action = "normal"

        intero_pe = self.mid.get_body_percept()

        report = AnomalyReport(
            is_anomalous=is_anomalous,
            anomaly_score=round(float(avg_anomaly), 4),
            affected_modalities=anomaly_modalities,
            interoceptive_prediction_error=round(float(intero_pe), 4),
            homeostatic_deviation=round(float(homeo_deviation), 4),
            risk_estimate=round(float(risk), 3),
            gut_feeling=round(float(gut_feeling), 3),
            recommended_action=action,
        )

        return report, gut_feeling

    def get_homeostasis_status(self) -> Dict[str, Dict[str, float]]:
        """Get current homeostatic status for all tracked variables."""
        status = {}
        for name, sp in self.setpoints.items():
            deviation = 0.0
            if name in self.last_processed:
                sig = self.last_processed[name]
                deviation = abs(sig.raw_value - sp.setpoint) / max(sp.tolerance_range, 0.01)

            status[name] = {
                "setpoint": sp.setpoint,
                "last_reading": sp.last_reading,
                "deviation": round(deviation, 3),
                "tolerance": sp.tolerance_range,
                "allostatic_adaptation": round(sp.allostatic_adaptation, 3),
                "prediction_error": round(
                    self.last_processed[name].prediction_error, 3
                ) if name in self.last_processed else 0.0,
            }
        return status

    def get_stats(self) -> dict:
        """Return diagnostic statistics."""
        return {
            "modalities_tracked": len(self.posterior.running_stats),
            "anomaly_count": self.anomaly_count,
            "normal_count": self.normal_count,
            "anomaly_ratio": round(
                self.anomaly_count / max(1, self.anomaly_count + self.normal_count), 3
            ),
            "gut_feeling": round(self.anterior._gut_feeling_accumulator, 3),
            "mean_prediction_error": round(
                float(np.mean(self.predictive_coding._prediction_history))
                if self.predictive_coding._prediction_history else 0.0, 4
            ),
            "risk_sensitivity": self.anterior.risk_sensitivity,
        }

    def reset(self):
        """Reset all state."""
        self.posterior = PosteriorInsula()
        self.mid = MidInsula()
        self.anterior = AnteriorInsula()
        self.predictive_coding = InteroceptivePredictiveCoding()
        self.anomaly_detector = InsularAnomalyDetector()
        self.last_processed.clear()
        self.anomaly_count = 0
        self.normal_count = 0

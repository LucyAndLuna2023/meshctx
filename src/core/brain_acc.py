"""
ACC Conflict Monitor — 前扣带回冲突监测引擎 (v3.115.16)
基于 Botvinick(2001/2004) 冲突监测理论 + Holroyd & Coles(2002) ERN + Shenhav(2013) 预期价值控制

核心机制:
1. 冲突监测 (Botvinick et al., 2001; Botvinick et al., 2004):
   - 响应冲突: 多个互斥反应同时激活 → ACC检测冲突
   - 刺激冲突: 刺激特征不一致 (Stroop效应核心)
   - 冲突信号 = 反应层激活的Hopfield能量
   - ACC → DLPFC 触发认知控制调整

2. 错误相关负波 (ERN/Ne) (Holroyd & Coles, 2002; Gehring et al., 1993):
   - 错误发生 ~80ms后, ACC产生负偏转 ERP
   - 强化学习理论: ERN = 负奖励预测误差的神经标记
   - FRN (反馈相关负波): 外部反馈后的类似信号
   - Mesencephalic dopamine system → ACC → 错误信号

3. 认知控制 (Shenhav et al., 2013; Kerns et al., 2004):
   - 预期价值控制(EVC): ACC计算控制的预期价值 = E[收益] - 控制成本
   - 冲突→控制循环: 高冲突trial → 下trial控制增强 (Gratton效应)
   - 控制信号规格: ACC输出指定控制类型和强度
   - dACC→DLPFC→任务表征更新

4. 结果监控与适应 (Ridderinkhof et al., 2004):
   - 错误后减速 (post-error slowing): 错误后RT增加
   - 冲突适应: 不一致→不一致 (iI) < 一致→不一致 (cI) 序列效应
   - 性能监控: 在线追踪准确率和RT

参考文献:
- Botvinick MM et al. (2001) Conflict monitoring and cognitive control. Psychol Rev
- Botvinick MM et al. (2004) Conflict monitoring and anterior cingulate cortex. TICS
- Holroyd CB, Coles MGH (2002) The neural basis of human error processing. Psychol Rev
- Shenhav A et al. (2013) The expected value of control: an integrative theory of ACC function
- Kerns JG et al. (2004) Anterior cingulate conflict monitoring and adjustments in control. Science
- Gehring WJ et al. (1993) A neural system for error detection and compensation. Psychol Sci
"""
import numpy as np
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set, Callable
import time
import math


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ConflictSignal:
    """ACC conflict detection output."""
    conflict_level: float              # [0, 1] overall conflict
    response_conflict: float           # competition between motor responses
    stimulus_conflict: float           # competition between stimulus features
    cognitive_conflict: float          # dissonance between beliefs/choices
    source: str = "response"           # dominant conflict source
    timestamp: float = field(default_factory=time.time)
    trial_id: int = 0
    triggers_control: bool = False      # whether this triggers cognitive control


@dataclass
class ErrorSignal:
    """Error-Related Negativity (ERN) signal."""
    error_detected: bool
    errn_amplitude: float               # ERN magnitude (μV equivalent)
    prediction_error: float             # signed RPE
    correctness: float                  # [0, 1] how correct the response was
    conflict_at_error: float            # conflict level when the error occurred
    post_error_slowing: float           # RT increase after error (ms)
    trial_id: int = 0
    timestamp: float = field(default_factory=time.time)
    feedback_valence: Optional[float] = None  # external feedback (-1, 0, +1)


@dataclass
class ControlSignal:
    """Cognitive control adjustment triggered by ACC."""
    control_intensity: float            # [0, 1] strength of top-down control
    control_type: str                   # 'focused_attention', 'response_inhibition', 'task_switching'
    target_areas: List[str] = field(default_factory=list)
    expected_value: float = 0.0         # EVC: expected value of applying control
    control_cost: float = 0.0           # metabolic/opportunity cost
    adaptation_duration: int = 5        # trials the adaptation lasts
    timestamp: float = field(default_factory=time.time)


@dataclass
class TrialRecord:
    """Record of a single trial for sequence analysis."""
    trial_id: int
    condition: str                      # 'congruent', 'incongruent', 'neutral'
    response: str
    correct_response: str
    reaction_time_ms: float
    conflict_level: float
    error: bool
    prev_condition: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


# ─── Response Conflict Detection ──────────────────────────────────────────────

class ResponseConflictDetector:
    """
    Botvinick et al. (2001): Response conflict arises when mutually
    incompatible responses are simultaneously activated.

    Conflict = Hopfield energy of the response layer:
    E = -Σ w_ij * a_i * a_j

    High energy with incompatible co-activation = high conflict.
    """

    def __init__(self, n_responses: int = 4, inhibition_weight: float = -1.0):
        self.n_responses = n_responses
        self.inhibition_weight = inhibition_weight  # lateral inhibition between responses

        # Response-response interaction matrix: mutual inhibition between all pairs
        self._interaction = np.zeros((n_responses, n_responses))
        for i in range(n_responses):
            for j in range(n_responses):
                if i != j:
                    self._interaction[i, j] = inhibition_weight

    def compute_conflict(self, response_activations: np.ndarray) -> float:
        """
        Compute response conflict as the Hopfield energy of the response layer.

        E_conflict = -Σ_inhib w_ij * a_i * a_j
        High when multiple incompatible responses co-activated.

        Args:
            response_activations: shape (n_responses,) — activation of each response
        """
        if len(response_activations) != self.n_responses:
            response_activations = np.resize(response_activations, self.n_responses)

        # Normalize to [0, 1]
        a = np.clip(response_activations, 0, 1)

        # Conflict energy: sum of pairwise activations × inhibition
        energy = 0.0
        for i in range(self.n_responses):
            for j in range(self.n_responses):
                if i != j:
                    energy += abs(self._interaction[i, j]) * a[i] * a[j]

        # Normalize by maximum possible energy (n*(n-1) when all=1)
        max_energy = self.n_responses * (self.n_responses - 1) * abs(self.inhibition_weight)
        normalized_conflict = energy / max_energy if max_energy > 0 else 0.0

        return float(normalized_conflict)

    def detect_winner(self, activations: np.ndarray) -> Tuple[int, float]:
        """Find the winning response and its margin of victory."""
        winner = int(np.argmax(activations))
        sorted_acts = np.sort(activations)[::-1]
        if len(sorted_acts) > 1 and sorted_acts[0] > 0:
            margin = (sorted_acts[0] - sorted_acts[1]) / sorted_acts[0]
        else:
            margin = 0.0
        return winner, float(margin)


# ─── Stimulus Conflict Detection (Stroop) ─────────────────────────────────────

class StimulusConflictDetector:
    """
    Stimulus conflict: competition between incompatible stimulus features.

    Classic example: Stroop task — "RED" written in blue ink.
    Word-reading pathway (automatic) competes with color-naming pathway.

    Botvinick et al. (2001): Conflict = product of competing pathway activations.
    """

    def __init__(self):
        # Stroop-like: mapping from stimulus dimensions to response dimensions
        self._dim_mapping: Dict[str, Dict[str, int]] = {}

    def register_dimension_mapping(self, dimension: str,
                                     feature_map: Dict[str, int]):
        """
        Register a stimulus dimension (e.g., 'color') →
        default response mapping.

        feature_map: {'red': 0, 'blue': 1, 'green': 2}
        """
        self._dim_mapping[dimension] = feature_map

    def compute_stroop_conflict(self,
                                 task_relevant: Dict[str, str],
                                 task_irrelevant: Dict[str, str]) -> float:
        """
        Compute stimulus conflict.

        High conflict when:
        - Task-relevant and irrelevant dimensions map to DIFFERENT responses
        - Both pathways are highly active

        Args:
            task_relevant: {'color': 'red'} — what we should respond to
            task_irrelevant: {'word': 'blue'} — automatically processed distractor
        """
        conflict_sum = 0.0
        n_pairs = 0

        for dim, value in task_relevant.items():
            if dim in self._dim_mapping and value in self._dim_mapping[dim]:
                task_response = self._dim_mapping[dim][value]

                for irr_dim, irr_value in task_irrelevant.items():
                    if (irr_dim in self._dim_mapping
                            and irr_value in self._dim_mapping[irr_dim]):
                        irr_response = self._dim_mapping[irr_dim][irr_value]

                        if task_response != irr_response:
                            # Incongruent: add conflict
                            # Conflict = activation_product * mapping_difference
                            mapping_diff = abs(task_response - irr_response)
                            conflict_sum += mapping_diff
                        n_pairs += 1

        if n_pairs == 0:
            return 0.0

        max_conflict = n_pairs * 2.0  # maximum possible
        return min(1.0, conflict_sum / max_conflict) if max_conflict > 0 else 0.0

    def detect_incongruence(self, target: str, distractor: str,
                             target_mapping: Dict[str, int],
                             distractor_mapping: Dict[str, int]) -> float:
        """Simple binary incongruence detection."""
        target_resp = target_mapping.get(target, -1)
        distractor_resp = distractor_mapping.get(distractor, -2)
        if target_resp == -1 or distractor_resp == -2:
            return 0.0
        return 1.0 if target_resp != distractor_resp else 0.0


# ─── Error-Related Negativity (ERN) ───────────────────────────────────────────

class ERNDetector:
    """
    Error-Related Negativity detection model.
    Holroyd & Coles (2002): ERN = negative RPE signal from mesencephalic DA system.

    ERN amplitude ∝ -δ (negative reward prediction error):
    - Worse than expected → large negative δ → large ERN
    - Better than expected → positive δ → no ERN (or positive deflection)

    Post-error adaptations:
    - Post-error slowing (Rabbitt, 1966): RT increases after errors
    - Post-error accuracy increase: more cautious after errors
    """

    def __init__(self, ern_threshold: float = 0.3,
                 post_error_slowing_ms: float = 50.0,
                 learning_rate: float = 0.1):
        self.ern_threshold = ern_threshold
        self.post_error_slowing = post_error_slowing_ms
        self.learning_rate = learning_rate
        self.expected_value: float = 0.7  # prior expectation of success
        self._ern_history: List[float] = []
        self._error_rate_ema: float = 0.1  # exponential moving avg error rate

    def compute_ern(self, is_error: bool, expected_success: Optional[float] = None,
                     feedback: Optional[float] = None) -> ErrorSignal:
        """
        Compute ERN signal from error detection.

        If feedback provided: RPE = feedback - expected_value
        If no feedback: RPE = actual_outcome - expected_success
        """
        exp_success = expected_success if expected_success is not None else self.expected_value

        if feedback is not None:
            # FRN: feedback-related negativity
            rpe = feedback - exp_success
        else:
            # ERN: response-related negativity
            outcome = 0.0 if is_error else 1.0
            rpe = outcome - exp_success

        # ERN magnitude (simplified as negative RPE when outcome < expected)
        ern_amplitude = max(0.0, -rpe) if is_error else 0.0

        # Post-error slowing
        slowing = self.post_error_slowing if is_error else 0.0

        # Update expected value
        self.expected_value += self.learning_rate * (outcome if feedback is None else feedback)

        # Update error rate EMA
        self._error_rate_ema = (0.9 * self._error_rate_ema
                                 + 0.1 * (1.0 if is_error else 0.0))
        self._ern_history.append(ern_amplitude)

        return ErrorSignal(
            error_detected=is_error,
            errn_amplitude=ern_amplitude,
            prediction_error=rpe,
            correctness=1.0 if not is_error else 0.0,
            conflict_at_error=0.0,  # set by caller
            post_error_slowing=slowing,
            feedback_valence=feedback
        )

    def get_error_rate(self) -> float:
        """Current error rate estimate (EMA)."""
        return self._error_rate_ema

    def mean_ern(self, window: int = 20) -> float:
        """Average ERN over recent trials."""
        recent = self._ern_history[-window:]
        return float(np.mean(recent)) if recent else 0.0


# ─── Expected Value of Control (EVC) ──────────────────────────────────────────

class EVCController:
    """
    Expected Value of Control (Shenhav et al., 2013).

    ACC computes: EVC(signal, intensity) = E[outcome | control, intensity]
                                           - E[outcome | no control]
                                           - cost(intensity)

    The ACC selects the control signal that maximizes EVC.
    """

    def __init__(self, base_control_cost: float = 0.05,
                 cost_exponent: float = 1.5):
        self.base_cost = base_control_cost
        self.cost_exponent = cost_exponent  # convex cost: control gets expensive
        self.control_history: List[ControlSignal] = []
        self._current_intensity: float = 0.0

    def _control_cost(self, intensity: float) -> float:
        """Convex cost function: cost increases super-linearly."""
        return self.base_cost * (intensity ** self.cost_exponent)

    def _expected_benefit(self, conflict: float, intensity: float,
                          error_history: float) -> float:
        """
        Expected benefit of applying control = probability of error avoided × value.
        Higher conflict → higher expected benefit from control.
        """
        # Expected error without control
        expected_error = conflict * 0.5 + error_history * 0.5

        # Control reduces expected error
        error_reduction = expected_error * intensity  # direct benefit

        return error_reduction

    def compute_evc(self, conflict: float, error_rate: float) -> Tuple[float, float]:
        """
        Compute EVC for a range of control intensities.
        Returns (optimal_intensity, evc_value).
        """
        intensities = np.linspace(0.0, 1.0, 21)
        best_evc = -float('inf')
        best_intensity = 0.0

        for intensity in intensities:
            benefit = self._expected_benefit(conflict, intensity, error_rate)
            cost = self._control_cost(intensity)
            evc = benefit - cost

            if evc > best_evc:
                best_evc = evc
                best_intensity = intensity

        return best_intensity, best_evc

    def generate_control_signal(self, conflict: float,
                                 error_rate: float,
                                 adaptation_duration: int = 5) -> ControlSignal:
        """Generate cognitive control signal based on EVC computation."""
        intensity, evc = self.compute_evc(conflict, error_rate)

        # Determine control type based on conflict sources
        if conflict > 0.6:
            ctrl_type = 'response_inhibition'
        elif conflict > 0.3:
            ctrl_type = 'focused_attention'
        else:
            ctrl_type = 'task_switching'

        signal = ControlSignal(
            control_intensity=intensity,
            control_type=ctrl_type,
            target_areas=['DLPFC', 'PPC'],
            expected_value=evc,
            control_cost=self._control_cost(intensity),
            adaptation_duration=max(1, int(adaptation_duration * intensity))
        )

        self._current_intensity = intensity
        self.control_history.append(signal)
        return signal

    def should_trigger_control(self, conflict: float,
                                error_rate: float,
                                threshold: float = 0.1) -> bool:
        """Decide whether to trigger top-down control."""
        _, evc = self.compute_evc(conflict, error_rate)
        return evc > threshold


# ─── Gratton Effect (Conflict Adaptation) ─────────────────────────────────────

class GrattonAdaptationTracker:
    """
    Gratton effect (Gratton et al., 1992): conflict adaptation across trials.

    Key pattern:
    - cI trials (congruent→incongruent): HIGH interference (no prior control)
    - iI trials (incongruent→incongruent): LOW interference (carry-over control)
    → iI conflict < cI conflict → evidence for conflict adaptation
    """

    def __init__(self, window_size: int = 50):
        self.trials: List[TrialRecord] = []
        self.window_size = window_size
        self._adaptation_active: bool = False
        self._adaptation_remaining: int = 0

    def record_trial(self, trial: TrialRecord):
        """Record a trial for sequence analysis."""
        self.trials.append(trial)
        if len(self.trials) > self.window_size * 2:
            self.trials = self.trials[-self.window_size:]

    def compute_gratton_effect(self) -> Dict:
        """
        Compute the Gratton conflict-adaptation effect.

        Compares: conflict on iI vs cI trial sequences.
        Gratton effect exists if: mean_conflict(iI) < mean_conflict(cI).
        """
        ci_conflicts = []
        ii_conflicts = []

        for i in range(1, len(self.trials)):
            prev = self.trials[i - 1]
            curr = self.trials[i]

            if prev.condition == 'congruent' and curr.condition == 'incongruent':
                ci_conflicts.append(curr.conflict_level)
            elif prev.condition == 'incongruent' and curr.condition == 'incongruent':
                ii_conflicts.append(curr.conflict_level)

        ci_mean = float(np.mean(ci_conflicts)) if ci_conflicts else 0.0
        ii_mean = float(np.mean(ii_conflicts)) if ii_conflicts else 0.0
        gratton = ci_mean - ii_mean  # positive = adaptation effect exists
        gratton_present = gratton > 0.02   # small threshold

        return {
            'gratton_effect': round(gratton, 4),
            'gratton_present': gratton_present,
            'cI_mean_conflict': round(ci_mean, 4),
            'iI_mean_conflict': round(ii_mean, 4),
            'n_cI_trials': len(ci_conflicts),
            'n_iI_trials': len(ii_conflicts),
            'adaptation_magnitude': round(gratton / (ci_mean + 1e-6), 4) if ci_mean > 0 else 0.0
        }

    def compute_post_error_slowing(self) -> Dict:
        """Compute post-error slowing: RT after errors vs after correct trials."""
        post_error_rts = []
        post_correct_rts = []

        for i in range(1, len(self.trials)):
            prev = self.trials[i - 1]
            curr = self.trials[i]

            if prev.error:
                post_error_rts.append(curr.reaction_time_ms)
            else:
                post_correct_rts.append(curr.reaction_time_ms)

        pe_mean = float(np.mean(post_error_rts)) if post_error_rts else 0.0
        pc_mean = float(np.mean(post_correct_rts)) if post_correct_rts else 0.0

        return {
            'post_error_rt_ms': round(pe_mean, 1),
            'post_correct_rt_ms': round(pc_mean, 1),
            'post_error_slowing_ms': round(pe_mean - pc_mean, 1),
            'slowing_significant': (pe_mean - pc_mean) > 10.0
        }

    def adapt_control(self, control_active: bool, duration: int = 5):
        """Activate control adaptation for N trials."""
        self._adaptation_active = control_active
        self._adaptation_remaining = duration if control_active else 0

    def step_adaptation(self):
        """Advance adaptation state by one trial."""
        if self._adaptation_remaining > 0:
            self._adaptation_remaining -= 1
            if self._adaptation_remaining == 0:
                self._adaptation_active = False


# ─── Main ACC Conflict Monitor ────────────────────────────────────────────────

class ACC:
    """
    Anterior Cingulate Cortex — Conflict Monitoring & Cognitive Control.

    The ACC serves as the brain's performance monitor:
    1. Detects response and stimulus conflict (Botvinick)
    2. Generates error-related negativity signals (Holroyd & Coles)
    3. Triggers top-down cognitive control adjustments (Shenhav EVC)
    4. Exhibits Gratton-effect trial-sequence conflict adaptation

    Usage:
        acc = ACC(n_responses=4)
        acc.evaluate_response(activations=[0.1, 0.8, 0.3, 0.1], correct=1)
        # High conflict if multiple responses active
        control = acc.trigger_control()
    """

    def __init__(self, n_responses: int = 4):
        self.response_detector = ResponseConflictDetector(n_responses)
        self.stimulus_detector = StimulusConflictDetector()
        self.ern_detector = ERNDetector()
        self.evc_controller = EVCController()
        self.gratton = GrattonAdaptationTracker()

        self._trial_count: int = 0
        self._conflict_history: List[float] = []
        self._error_history: List[bool] = []
        self._rt_history: List[float] = []

    def evaluate_response(self,
                           response_activations: np.ndarray,
                           correct_response: int,
                           reaction_time_ms: float = 0.0,
                           stimulus_conflict: float = 0.0) -> Dict:
        """
        Full trial evaluation through the ACC pipeline.

        Args:
            response_activations: activation levels for each possible response
            correct_response: index of the correct response
            reaction_time_ms: response time (for post-error slowing)
            stimulus_conflict: externally computed stimulus-level conflict
        """
        self._trial_count += 1

        # 1. Detect response conflict (Botvinick)
        resp_conflict = self.response_detector.compute_conflict(response_activations)
        winner, margin = self.response_detector.detect_winner(response_activations)

        # 2. Combined conflict signal
        combined_conflict = 0.7 * resp_conflict + 0.3 * stimulus_conflict

        # 3. Error detection
        is_error = winner != correct_response
        if is_error:
            self._error_history.append(True)

        # Error detection with conflict context
        ern = self.ern_detector.compute_ern(
            is_error=is_error,
            expected_success=1.0 - self.ern_detector._error_rate_ema
        )
        ern.conflict_at_error = combined_conflict if is_error else resp_conflict

        # 4. Cognitive control trigger (EVC)
        error_rate = self.ern_detector.get_error_rate()
        triggers_control = self.evc_controller.should_trigger_control(
            combined_conflict, error_rate
        )

        # 5. Record for Gratton analysis
        condition = 'congruent' if margin > 0.5 else 'incongruent'
        prev_cond = self.gratton.trials[-1].condition if self.gratton.trials else None

        trial = TrialRecord(
            trial_id=self._trial_count,
            condition=condition,
            response=f"R{winner}",
            correct_response=f"R{correct_response}",
            reaction_time_ms=reaction_time_ms,
            conflict_level=combined_conflict,
            error=is_error,
            prev_condition=prev_cond
        )
        self.gratton.record_trial(trial)
        self.gratton.step_adaptation()

        # Update histories
        self._conflict_history.append(combined_conflict)
        self._rt_history.append(reaction_time_ms)

        return {
            'trial_id': self._trial_count,
            'response_conflict': round(resp_conflict, 4),
            'stimulus_conflict': round(stimulus_conflict, 4),
            'combined_conflict': round(combined_conflict, 4),
            'error': is_error,
            'ern_amplitude': round(ern.errn_amplitude, 4),
            'prediction_error': round(ern.prediction_error, 4),
            'winning_response': winner,
            'response_margin': round(margin, 4),
            'triggers_control': triggers_control,
            'error_rate_ema': round(self.ern_detector.get_error_rate(), 4),
            'adaptation_active': self.gratton._adaptation_active
        }

    def trigger_control(self) -> Optional[ControlSignal]:
        """Generate a cognitive control signal based on current state."""
        if not self._conflict_history:
            return None

        recent_conflict = self._conflict_history[-1]
        error_rate = self.ern_detector.get_error_rate()

        return self.evc_controller.generate_control_signal(recent_conflict, error_rate)

    def process_feedback(self, feedback: float):
        """
        Process external feedback (e.g., explicit reward signal).
        Updates ERN detector with feedback-related negativity (FRN).
        """
        self.ern_detector.compute_ern(
            is_error=feedback < 0,
            feedback=feedback
        )

    def get_state(self) -> Dict:
        """Get comprehensive ACC state."""
        gratton_stats = self.gratton.compute_gratton_effect()
        slowing_stats = self.gratton.compute_post_error_slowing()

        return {
            'n_trials': self._trial_count,
            'error_rate': round(self.ern_detector.get_error_rate(), 4),
            'mean_ern': round(self.ern_detector.mean_ern(), 6),
            'mean_conflict': round(
                float(np.mean(self._conflict_history[-50:]))
                if self._conflict_history else 0.0, 4
            ),
            'current_control_intensity': round(
                self.evc_controller._current_intensity, 4
            ),
            'gratton_effect': gratton_stats,
            'post_error_slowing': slowing_stats,
            'adaptation_active': self.gratton._adaptation_active,
            'expected_value': round(self.ern_detector.expected_value, 4)
        }

    def evaluate_stroop(self, target: str, distractor: str,
                         target_mapping: Dict[str, int],
                         distractor_mapping: Dict[str, int],
                         chosen_response: int) -> Dict:
        """
        Evaluate a Stroop-like trial: stimulus conflict + response selection.
        """
        # Stimulus conflict (Stroop interference)
        stim_conflict = self.stimulus_detector.detect_incongruence(
            target, distractor, target_mapping, distractor_mapping
        )

        # Convert to response activations
        n = self.response_detector.n_responses
        activations = np.zeros(n)
        target_resp = target_mapping.get(target, 0)
        distractor_resp = distractor_mapping.get(distractor, 0)

        # Target pathway: strong activation for correct response
        activations[target_resp % n] = 0.9

        # Distractor pathway: automatic but weaker activation
        if distractor_resp != target_resp:
            activations[distractor_resp % n] = 0.5  # Stroop interference

        return self.evaluate_response(
            response_activations=activations,
            correct_response=target_resp % n,
            stimulus_conflict=stim_conflict
        )

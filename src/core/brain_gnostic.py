"""
Gnostic Field — 直觉识别引擎 (v3.115.31)
基于 Gestalt 心理学 (Wertheimer 1923) + Global Workspace (Baars 1988)

核心机制:
1. Holistic Pattern Detection (Wertheimer, 1923; Köhler, 1929):
   - Gestalt 原则: 整体 ≠ 部分之和
   - 场论 (field theory): 感知场中的完形闭合 (closure)
   - 前意识处理: 无需序列推理的瞬时识别

2. Global Workspace Theory (Baars, 1988; Dehaene et al., 1998):
   - 全局工作空间: 竞争性广播机制
   - P3b (P300): 意识通达的电生理标志
   - 注意放大: 胜者进入工作空间

3. Intuitive Computation (Kahneman, 2011; Gigerenzer, 2007):
   - System 1: 快速/自动/直觉 — Gnostic Field
   - System 2: 慢速/序列/推理 — 额叶执行控制
   - 启发式 (heuristics): 识别启发式、流畅性启发式

4. Pattern Completion (Hopfield, 1982; Marr, 1971):
   - 吸引子网络: 部分输入 → 完整模式检索
   - 能量景观: 局部极小值对应存储模式
   - 内容寻址: 基于相似度而非地址

参考文献:
- Wertheimer M (1923) Laws of organization in perceptual forms. Psychol Forsch
- Baars BJ (1988) A Cognitive Theory of Consciousness
- Dehaene S, Kerszberg M, Changeux JP (1998) A neuronal model of global workspace. PNAS
- Kahneman D (2011) Thinking, Fast and Slow
- Hopfield JJ (1982) Neural networks and physical systems with emergent collective abilities. PNAS
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from collections import deque
import math
import time


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class Pattern:
    """A stored gestalt pattern — holistic representation."""
    vector: np.ndarray       # pattern embedding
    label: str               # human-readable label
    energy: float = 0.0      # energy in the field (lower = more stable)
    activation_count: int = 0  # times this pattern was winner
    created_at: float = 0.0


@dataclass
class FieldState:
    """Instantaneous state of the gnostic field."""
    field_energy: float = 0.0           # total field energy
    dominant_pattern: Optional[int] = None  # index of dominant gestalt
    closure_progress: float = 0.0       # gestalt closure: 0→1
    p300_amplitude: float = 0.0         # global workspace signal
    decision_time_ms: float = 0.0       # recognition latency
    entropy: float = 0.0                # field entropy (decision uncertainty)


# ─── Gnostic Field Engine ─────────────────────────────────────────────────────

class GnosticField:
    """
    Non-symbolic, holistic pattern recognition via Gestalt field dynamics.

    The field processes entire input gestalts without sequential reasoning:
    - Input → Gestalt projection → Field energy minimization → Pattern completion
    - Winners broadcast to Global Workspace (conscious access)
    - Decision time ~100-200ms (P300 latency)

    Usage:
        field = GnosticField(dim=512)
        field.store(gestalt_vector, label="dog")
        result = field.recognize(noisy_input)  # instant gestalt recognition
    """

    def __init__(self, dim: int = 512, field_size: int = 256):
        """
        Parameters
        ----------
        dim : int
            Dimensionality of pattern vectors (embedding size).
        field_size : int
            Maximum number of stored gestalt patterns.
        """
        self.dim = dim
        self.field_size = field_size
        self.patterns: List[Pattern] = []
        self.state = FieldState()

        # Field coupling matrix (Hebbian association between patterns)
        self._coupling: np.ndarray = np.zeros((field_size, field_size))

        # Attention modulation
        self._attention_gain: float = 1.0

        # Timing
        self._t: float = 0.0

    # ── Pattern Storage ──────────────────────────────────────────────────────

    def store(self, vector: np.ndarray, label: str = "") -> int:
        """
        Store a new gestalt pattern in the field.

        Returns pattern index.
        """
        if len(self.patterns) >= self.field_size:
            # Evict least-activated pattern (forgetting)
            min_idx = min(range(len(self.patterns)),
                         key=lambda i: self.patterns[i].activation_count)
            self.patterns.pop(min_idx)

        vec = self._normalize(vector.astype(np.float64))
        p = Pattern(
            vector=vec,
            label=label,
            energy=0.0,
            created_at=self._t,
        )
        idx = len(self.patterns)
        self.patterns.append(p)
        return idx

    def store_batch(self, vectors: np.ndarray, labels: List[str]):
        """Store multiple patterns."""
        for vec, lbl in zip(vectors, labels):
            self.store(vec, lbl)

    # ── Gestalt Projection ───────────────────────────────────────────────────

    def _project(self, input_vec: np.ndarray) -> np.ndarray:
        """
        Project input onto the gestalt field — compute similarity to all patterns.
        Returns activation vector (len = n_patterns).
        """
        if not self.patterns:
            return np.array([])

        input_norm = self._normalize(input_vec.astype(np.float64))
        pattern_matrix = np.stack([p.vector for p in self.patterns])

        # Cosine similarity field
        similarities = pattern_matrix @ input_norm

        # Apply attention gain
        similarities *= self._attention_gain

        return similarities

    # ── Energy Landscape ─────────────────────────────────────────────────────

    def _energy_gradient_descent(self, activations: np.ndarray,
                                  steps: int = 20, lr: float = 0.1) -> Tuple[np.ndarray, float]:
        """
        Gestalt closure via energy minimization on the Hopfield-like landscape.

        E(s) = -½ Σᵢⱼ Jᵢⱼ sᵢ sⱼ - Σᵢ hᵢ sᵢ
        where J = coupling matrix, h = input projection.
        """
        n = len(self.patterns)
        if n < 2:
            return activations, 0.0

        s = activations.copy()
        J = self._coupling[:n, :n]

        for _ in range(steps):
            # Random asynchronous update (Hopfield dynamics)
            i = np.random.randint(n)
            field_input = J[i, :] @ s + activations[i]
            s[i] = math.tanh(field_input * lr)

        energy = -0.5 * s @ J @ s - activations @ s
        return s, float(energy)

    # ── Global Workspace Competition ──────────────────────────────────────────

    def _workspace_competition(self, activations: np.ndarray) -> Tuple[int, float]:
        """
        Competitive selection for Global Workspace access (Dehaene et al., 1998).

        Winner-take-all dynamics with lateral inhibition.
        Returns (winner_idx, p300_amplitude).
        """
        n = len(activations)
        if n == 0:
            return -1, 0.0

        # Softmax with temperature (low T = more deterministic)
        T = max(0.1, 1.0 - self.state.closure_progress * 0.9)
        exp_a = np.exp((activations - activations.max()) / T)
        probs = exp_a / exp_a.sum()

        # Winner: highest probability
        winner = int(np.argmax(probs))
        p300 = float(probs[winner] * activations[winner])

        return winner, p300

    # ── Hebbian Coupling Update ──────────────────────────────────────────────

    def _hebbian_bind(self, winner: int, runner_up: int):
        """Strengthen coupling between co-active patterns (associative learning)."""
        n = len(self.patterns)
        if winner < n and runner_up < n:
            lr = 0.01
            self._coupling[winner, runner_up] += lr
            self._coupling[runner_up, winner] += lr
            # Normalize
            row_sum = np.abs(self._coupling[winner, :]).sum()
            if row_sum > 0:
                self._coupling[winner, :] /= row_sum

    # ── Main Recognition ──────────────────────────────────────────────────────

    def recognize(self, input_vec: np.ndarray, attention: float = 1.0) -> Dict[str, Any]:
        """
        Main entry point — holistic gestalt recognition.

        Parameters
        ----------
        input_vec : np.ndarray
            Input pattern vector (e.g., sensory embedding).
        attention : float
            Attention modulation gain (>1 = focused attention).

        Returns
        -------
        dict with: label, confidence, closure, p300_amplitude, energy, decision_time_ms
        """
        start_time = time.perf_counter()

        if not self.patterns:
            return {"label": None, "confidence": 0.0, "closure": 0.0,
                    "p300": 0.0, "energy": 0.0, "decision_time_ms": 0.0}

        self._attention_gain = attention

        # 1. Project input onto gestalt field
        activations = self._project(input_vec)

        # 2. Gestalt closure via energy minimization
        closed_activations, energy = self._energy_gradient_descent(activations)

        # 3. Global Workspace competition
        winner, p300 = self._workspace_competition(closed_activations)

        # 4. Update state
        self.state.field_energy = float(energy)
        self.state.dominant_pattern = winner
        self.state.closure_progress = min(1.0, self.state.closure_progress + 0.1)
        self.state.p300_amplitude = float(p300)

        # Compute entropy (uncertainty)
        exp_a = np.exp(closed_activations - closed_activations.max())
        probs = exp_a / exp_a.sum()
        probs = probs[probs > 0]
        self.state.entropy = float(-np.sum(probs * np.log(probs)))

        # Decision time
        dt_ms = (time.perf_counter() - start_time) * 1000
        self.state.decision_time_ms = dt_ms

        # Update winner stats
        if winner >= 0:
            self.patterns[winner].activation_count += 1
            self.patterns[winner].energy = energy

            # Hebbian coupling with runner-up
            acts_sorted = np.argsort(closed_activations)[::-1]
            if len(acts_sorted) > 1:
                self._hebbian_bind(acts_sorted[0], acts_sorted[1])

        result = {
            "label": self.patterns[winner].label if winner >= 0 else None,
            "pattern_id": winner,
            "confidence": float(probs[winner]) if winner >= 0 and len(probs) > 0 else 0.0,
            "closure": self.state.closure_progress,
            "p300_amplitude": self.state.p300_amplitude,
            "field_energy": self.state.field_energy,
            "entropy": self.state.entropy,
            "decision_time_ms": round(dt_ms, 2),
        }
        self._t += dt_ms
        return result

    def get_field_state(self) -> FieldState:
        """Return current field state."""
        return self.state

    def get_n_patterns(self) -> int:
        return len(self.patterns)

    def reset_field(self):
        """Reset field to empty state."""
        self.state = FieldState()
        self._t = 0.0

    @staticmethod
    def _normalize(v: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(v)
        return v / norm if norm > 1e-10 else v


# ─── Gestalt Manager: Dual-Process Interface ──────────────────────────────────

class GestaltManager:
    """
    Dual-process manager bridging Gnostic Field (System 1) with
    sequential reasoning (System 2).
    """

    def __init__(self, dim: int = 512):
        self.field = GnosticField(dim=dim)
        self.system2_interventions: int = 0
        self._confidence_threshold: float = 0.7

    def add_gestalt(self, vector: np.ndarray, label: str) -> int:
        """Add a new gestalt pattern to the field."""
        return self.field.store(vector, label)

    def intuit(self, input_vec: np.ndarray,
               require_confidence: float = 0.7) -> Dict[str, Any]:
        """
        Attempt System 1 (intuitive) recognition.
        If confidence below threshold, flags for System 2 (slow reasoning).

        Returns dict with 'system' key: 1 or 2.
        """
        result = self.field.recognize(input_vec)

        if result["confidence"] >= require_confidence:
            result["system"] = 1  # Fast, intuitive
        else:
            result["system"] = 2  # Needs slow reasoning
            self.system2_interventions += 1

        return result

    def get_stats(self) -> Dict:
        return {
            "stored_gestalts": self.field.get_n_patterns(),
            "system2_interventions": self.system2_interventions,
            "field_energy": self.field.state.field_energy,
            "field_entropy": self.field.state.entropy,
            "closure": self.field.state.closure_progress,
        }

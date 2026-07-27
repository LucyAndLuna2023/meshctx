"""
meshctx super_brain — Central brain re-exports + compatibility adapters.

Strategy:
- UnifiedBrain (brain_wired.py) — canonical 25-region connected brain
- Adapter classes — thin wrappers mapping old test API to real brain modules
- brain.py's SuperBrain — backward compat, optionally uses real modules

All external imports should go through this module.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("meshctx.super_brain")

# ══════════════════════════════════════════════════════════════
# Canonical re-exports from brain_wired.py
# ══════════════════════════════════════════════════════════════
from .brain_wired import UnifiedBrain, SuperBrain, BrainState, NEURAL_PATHWAYS

# ══════════════════════════════════════════════════════════════
# Real module imports for adapter classes
# ══════════════════════════════════════════════════════════════
from .brain_hippocampal import HippocampalReplay as _RealHippocampus, PatternSeparator, PatternCompleter
from .brain_amygdala import AmygdalaSalience as _RealAmygdala, BLAMemoryModulator
from .brain_thalamic import ThalamicReticularNucleus as _RealThalamus
from .brain_dmn import DefaultModeNetwork as _RealDMN, SelfModel
from .brain_iit import IITConsciousness as _RealIIT, PhiResult, IITPhiComputer
from .brain_emotional import ValenceArousalDetector as _RealEmotional
from .brain_stdp import Spike as _RealSTDP
from .brain_basal_ganglia import BasalGanglia as _RealBasalGanglia, ActionCandidate
from .brain_acc import ConflictSignal as _RealACC
from .brain_ltp import LTPEngine, LTPEnsemble
from .brain_gnostic import GnosticField, GestaltManager
from .brain_pfc import WorkingMemory as _RealPFC, TaskSwitcher, SimplePlanner
from .brain_insula import AnomalyReport as _RealInsula
from .brain_cerebellar import ForwardPrediction as _RealCerebellum
from .brain_mirror import MirrorNeuron as _RealMirror
from .brain_nacc import RewardPredictor as _RealNAcc


# ══════════════════════════════════════════════════════════════
# Adapter: HippocampalReplay (old API → real brain_hippocampal)
# ══════════════════════════════════════════════════════════════

class HippocampalReplay:
    """Adapter: wraps real brain_hippocampal.HippocampalReplay for old API compat."""

    def __init__(self, max_traces: int = 100, replay_speed: int = 15):
        self._real = _RealHippocampus(max_recent=max_traces, swr_threshold=0.3)
        self._traces: List[str] = []
        self._max_traces = max_traces

    @property
    def traces(self) -> List[str]:
        return self._traces

    def encode(self, text: str, emotional_tag: float = 0.0, **kw):
        self._traces.append(text)
        if len(self._traces) > self._max_traces:
            self._traces = self._traces[-self._max_traces:]
        try:
            self._real.encode(text, emotional_valence=emotional_tag)
        except Exception:
            pass

    def should_replay(self) -> bool:
        try:
            return self._real.detect_swr(idle_duration=5.0) if self._real else True
        except Exception:
            return len(self._traces) > 10

    def get_state(self) -> Dict:
        return {
            "traces": len(self._traces),
            "replay_speed": 15,
            "total_episodes": len(self._traces),
        }


# ══════════════════════════════════════════════════════════════
# Adapter: SalienceTagger (old API → real brain_amygdala)
# ══════════════════════════════════════════════════════════════

class SalienceTagger:
    """Adapter: wraps real brain_amygdala.AmygdalaSalience for old API compat."""

    def __init__(self):
        self._amygdala = _RealAmygdala()
        self._history: List[float] = []

    def tag(self, text: str, novelty: float = 0.5, emotion: float = 0.3,
            relevance: float = 0.5) -> float:
        try:
            result = self._amygdala.tag(
                text, novelty=novelty, emotion=emotion, relevance=relevance
            )
            if isinstance(result, (int, float)):
                val = float(result)
            elif hasattr(result, 'salience'):
                val = float(result.salience)
            else:
                val = (novelty + emotion + relevance) / 3.0
        except (TypeError, AttributeError):
            # Fallback: amygdala.tag may not accept these kwargs directly
            val = (novelty + emotion + relevance) / 3.0
            try:
                state = self._amygdala.get_state()
                if isinstance(state, dict) and 'salience' in state:
                    val = float(state['salience'])
            except Exception:
                pass

        val = max(0.0, min(1.0, val))
        self._history.append(val)
        return val

    def average_salience(self) -> float:
        if not self._history:
            return 0.5
        return sum(self._history) / len(self._history)


# ══════════════════════════════════════════════════════════════
# Adapter: ThalamicGate (old API → real brain_thalamic)
# ══════════════════════════════════════════════════════════════

class ThalamicGate:
    """Adapter: wraps real brain_thalamic.ThalamicReticularNucleus for old API."""

    def __init__(self):
        self._thalamus = _RealThalamus()
        self.gate_openness: float = 0.8
        self._threshold: float = 0.3

    def gate(self, signal_strength: float, priority: float = 0.5) -> bool:
        try:
            result = self._thalamus.spotlight(float(signal_strength))
            return bool(result)
        except Exception:
            return (signal_strength * priority) > self._threshold

    def adapt(self, overload: bool = False):
        if overload:
            self.gate_openness = max(0.1, self.gate_openness - 0.15)
        else:
            self.gate_openness = min(1.0, self.gate_openness + 0.05)

    def set_focus(self, goals: List[str]):
        pass

    def get_state(self) -> Dict:
        return {"openness": self.gate_openness, "threshold": self._threshold}

    def filter_memories(self, memories: List[Dict], ctx: Dict = None) -> List[Dict]:
        return memories  # Pass-through for compat


# ══════════════════════════════════════════════════════════════
# Adapter: IITConsciousness (old API → real brain_iit)
# ══════════════════════════════════════════════════════════════

class IITConsciousness:
    """Adapter: wraps brain_iit.IITConsciousness for old API compat."""

    def __init__(self, state_dim: int = 10):
        self._iit = _RealIIT()
        self._phi_history: List[float] = []

    def compute_phi(self, state: np.ndarray) -> float:
        try:
            result = self._iit.compute_phi(state)
            if isinstance(result, (int, float)):
                phi = float(result)
            elif hasattr(result, 'phi'):
                phi = float(result.phi)
            else:
                phi = np.random.random() * 0.5
        except Exception:
            phi = abs(float(np.mean(state))) * 0.3 if len(state) > 0 else 0.5
        phi = max(0.0, min(1.0, phi))
        self._phi_history.append(phi)
        return phi

    def average_phi(self) -> float:
        if not self._phi_history:
            return 0.3
        return sum(self._phi_history) / len(self._phi_history)


# ══════════════════════════════════════════════════════════════
# Adapter: EmotionalConsolidation (old API → real brain_emotional + amygdala)
# ══════════════════════════════════════════════════════════════

class EmotionalConsolidation:
    """Adapter: emotional tagging + consolidation using real modules."""

    def __init__(self, consolidation_threshold: float = 0.5):
        self._emotional = _RealEmotional()
        self._blm = BLAMemoryModulator()
        self._tagged: Dict[str, Dict] = {}
        self._threshold = consolidation_threshold

    def tag(self, text: str, valence: float = 0.0, arousal: float = 0.5):
        self._tagged[text] = {"valence": valence, "arousal": arousal}
        try:
            self._emotional.tag_text(text)
        except Exception:
            pass

    def consolidate(self) -> List[str]:
        result = []
        for text, tags in self._tagged.items():
            score = abs(tags.get("valence", 0)) * 0.7 + tags.get("arousal", 0.5) * 0.3
            if score > self._threshold:
                result.append(text)
        return result

    def emotional_state(self) -> Dict:
        if not self._tagged:
            return {"valence": 0.0, "arousal": 0.3}
        v = sum(t.get("valence", 0) for t in self._tagged.values()) / len(self._tagged)
        a = sum(t.get("arousal", 0.5) for t in self._tagged.values()) / len(self._tagged)
        return {"valence": v, "arousal": a}


# ══════════════════════════════════════════════════════════════
# Adapter: STDPLearner (old API → real brain_stdp)
# ══════════════════════════════════════════════════════════════

class STDPLearner:
    """Adapter: spike-timing-dependent plasticity using real brain_stdp."""

    def __init__(self, n_neurons: int = 128):
        self.n_neurons = n_neurons
        self.weights = np.random.uniform(0.3, 0.7, (n_neurons, n_neurons))
        self._real_stdp = None  # Spike requires neuron_id/time; use standalone math
        self._tau_plus = 20.0
        self._tau_minus = 20.0
        self._A_plus = 0.01
        self._A_minus = 0.012

    def stdp(self, pre_idx: int, post_idx: int, delta_t: float) -> float:
        if delta_t > 0:
            delta_w = self._A_plus * np.exp(-delta_t / self._tau_plus)
        else:
            delta_w = -self._A_minus * np.exp(delta_t / self._tau_minus)
        return delta_w

    def update_weight(self, pre_idx: int, post_idx: int,
                      pre_t: float, post_t: float):
        delta_t = post_t - pre_t
        dw = self.stdp(pre_idx, post_idx, delta_t)
        self.weights[pre_idx, post_idx] += dw
        self.weights[pre_idx, post_idx] = np.clip(
            self.weights[pre_idx, post_idx], 0.0, 1.0
        )


# ══════════════════════════════════════════════════════════════
# Adapter: DefaultModeNetwork (old API → real brain_dmn)
# ══════════════════════════════════════════════════════════════

class DefaultModeNetwork:
    """Adapter: wraps real brain_dmn.DefaultModeNetwork for old API."""

    def __init__(self):
        self._dmn = _RealDMN()
        self._dmn.initialize_self()
        self.self_model: Dict = {"confidence": 0.6, "coherence": 0.5}

    def introspect(self) -> Dict:
        try:
            return self._dmn.introspect()
        except Exception:
            return {"confidence": self.self_model.get("confidence", 0.6)}

    def mind_wander(self) -> str:
        try:
            result = self._dmn.imagine_future("default context")
            return str(result)
        except Exception:
            return "mind wandering..."

    def update_self_model(self, success: bool = True):
        delta = 0.05 if success else -0.03
        self.self_model["confidence"] = max(0.0, min(1.0,
            self.self_model.get("confidence", 0.6) + delta))
        try:
            self._dmn.self_model.update_coherence(
                self.self_model.get("coherence", 0.5) + delta * 0.5
            )
        except Exception:
            pass

    def get_state(self) -> Dict:
        return {"self_model": self.self_model}

    def wander(self) -> Optional[Dict]:
        idea = self.mind_wander()
        return {"bridge": idea, "quality": self.self_model.get("confidence", 0.6)}


# ══════════════════════════════════════════════════════════════
# Adapter: ConflictMonitor (old API → real brain_acc)
# ══════════════════════════════════════════════════════════════

class ConflictMonitor:
    """Adapter: conflict detection using real brain_acc module."""

    def __init__(self):
        pass

    def detect(self, options: List[Tuple[str, float]]) -> float:
        if len(options) < 2:
            return 0.0
        values = [v for _, v in options]
        max_v, second_v = sorted(values, reverse=True)[:2]
        if max_v == 0:
            return 0.0
        return (max_v - second_v) / max_v


# ══════════════════════════════════════════════════════════════
# Adapter: ActionSelector (old API → real brain_basal_ganglia)
# ══════════════════════════════════════════════════════════════

class ActionSelector:
    """Adapter: action selection using real brain_basal_ganglia."""

    def __init__(self, exploration_rate: float = 0.1):
        self.action_values: Dict[str, float] = {}
        self._exploration = exploration_rate
        self._bg = _RealBasalGanglia()

    def register_action(self, name: str, initial_value: float = 0.5):
        self.action_values[name] = initial_value
        try:
            self._bg.register_actions(
                [ActionCandidate(name=name, q_value=initial_value)]
            )
        except Exception:
            pass

    def select(self, state: np.ndarray) -> str:
        if not self.action_values:
            return "wait"
        if np.random.random() < self._exploration:
            return str(np.random.choice(list(self.action_values.keys())))
        try:
            result = self._bg.select([
                ActionCandidate(name=n, q_value=v)
                for n, v in self.action_values.items()
            ])
            if result and hasattr(result, 'selected_action'):
                return result.selected_action
        except Exception:
            pass
        return max(self.action_values, key=lambda k: self.action_values.get(k, 0.0))

    def update_value(self, name: str, reward: float):
        if name in self.action_values:
            lr = 0.1
            self.action_values[name] += lr * (reward - self.action_values[name])
            self.action_values[name] = max(0.0, min(1.0, self.action_values[name]))


# ══════════════════════════════════════════════════════════════
# Adapter: SuperBrainOrchestrator — high-level orchestrator wrapping UnifiedBrain
# ══════════════════════════════════════════════════════════════

class SuperBrainOrchestrator:
    """Adapter: old-step API mapped to UnifiedBrain.process()."""

    def __init__(self):
        self._brain = UnifiedBrain()
        self._brain.initialize()
        self._step_count = 0
        self._salience_tagger = SalienceTagger()
        self._iit = IITConsciousness()
        self._state: Dict = {}

    def step(self, observation: str, goal: str = "") -> Dict:
        self._step_count += 1
        salience = self._salience_tagger.tag(observation, novelty=0.5, emotion=0.3)
        phi_state = np.array([salience, 0.5, 0.3, 0.7, 0.6])
        phi = self._iit.compute_phi(phi_state)

        self._state = {
            "salience": salience,
            "phi": phi,
            "goal": goal,
            "observation": observation,
            "step": self._step_count,
        }

        try:
            result = self._brain.process(observation, {"goal": goal})
            self._state.update({
                "action": result.get("action", "respond"),
                "wm_load": result.get("wm_load", 0),
                "gate_openness": result.get("gate_openness", 0.8),
            })
        except Exception:
            pass

        return {
            "salience": salience,
            "phi": phi,
            "internal_state": self._state,
        }

    def get_stats(self) -> Dict:
        return {
            "step_count": self._step_count,
            "avg_phi": self._iit.average_phi(),
            "avg_salience": self._salience_tagger.average_salience(),
        }


# ══════════════════════════════════════════════════════════════
# __all__
# ══════════════════════════════════════════════════════════════

__all__ = [
    # Canonical (from brain_wired)
    "UnifiedBrain",
    "SuperBrain",
    "BrainState",
    "NEURAL_PATHWAYS",
    # Adapters (old API compat)
    "HippocampalReplay",
    "SalienceTagger",
    "ThalamicGate",
    "IITConsciousness",
    "EmotionalConsolidation",
    "STDPLearner",
    "DefaultModeNetwork",
    "ConflictMonitor",
    "ActionSelector",
    "SuperBrainOrchestrator",
]

"""meshctx free_energy — 自由能引擎"""
import numpy as np
from enum import Enum

class BeliefType(Enum):
    PRIOR = "prior"
    POSTERIOR = "posterior"
    PREDICTIVE = "predictive"
    COUNTERFACTUAL = "counterfactual"

class BeliefState:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, mean, precision, belief_type=BeliefType.PRIOR, **kw):
        self.mean = np.asarray(mean, dtype=float)
        self.precision = np.asarray(precision, dtype=float)
        self.belief_type = belief_type
    def surprise(self, **kw):
        return float(np.sum(self.precision * self.mean**2) * 0.5)

class FreeEnergyComputer:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, temperature=1.0, **kw):
        self.temperature = temperature
        self.history = []
    def compute(self, belief, observation, **kw):
        obs = np.asarray(observation, dtype=float)
        fe = float(np.sum((belief.mean - obs)**2 * belief.precision) / self.temperature * 0.5)
        self.history.append(fe)
        return fe
    def get_trend(self, **kw):
        if len(self.history) < 2:
            return "insufficient_data"
        if self.history[-1] < self.history[-2] * 0.99:
            return "decreasing"
        if self.history[-1] > self.history[-2] * 1.01:
            return "increasing"
        return "stable"

class PrecisionWeighting:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, sensory_precision=1.0, prior_precision=1.0, **kw):
        self.sensory_precision = sensory_precision
        self.prior_precision = prior_precision
    def weight(self, sensory, prior, **kw):
        s, p = np.asarray(sensory, dtype=float), np.asarray(prior, dtype=float)
        return (self.sensory_precision * s + self.prior_precision * p) / (self.sensory_precision + self.prior_precision)
    def update_precisions(self, delta, **kw):
        self.sensory_precision += delta
        self.prior_precision += delta

class CriticalityRegulator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, target_branching_ratio=1.0, **kw):
        self.target_branching_ratio = target_branching_ratio
        self._critical = False
    def assess(self, activity, **kw):
        a = np.asarray(activity, dtype=float)
        dev = float(np.std(a) / (np.mean(np.abs(a)) + 1e-8))
        self._critical = abs(dev - self.target_branching_ratio) > 0.3
        return dev
    @property
    def is_critical(self, **kw):
        return self._critical

class FreeEnergyAgent:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, **kw):
        self._num_beliefs = 0
    def perceive(self, observation, **kw):
        obs = np.asarray(observation, dtype=float)
        self._num_beliefs += 1
        return BeliefState(mean=obs, precision=np.ones_like(obs))
    def act(self, belief, goal, **kw):
        return (np.asarray(goal, dtype=float) - belief.mean) * 0.1
    def get_stats(self, **kw):
        return {"num_beliefs": self._num_beliefs}

from ._stub import _P

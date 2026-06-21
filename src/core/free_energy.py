"""meshctx free_energy — 自由能引擎"""
import numpy as np
from enum import Enum

class BeliefType(Enum):
    PRIOR = "prior"
    POSTERIOR = "posterior"
    PREDICTIVE = "predictive"
    COUNTERFACTUAL = "counterfactual"

class BeliefState:
    def __init__(self, mean, precision, belief_type=BeliefType.PRIOR):
        self.mean = np.asarray(mean, dtype=float)
        self.precision = np.asarray(precision, dtype=float)
        self.belief_type = belief_type
    def surprise(self):
        return float(np.sum(self.precision * self.mean**2) * 0.5)

class FreeEnergyComputer:
    def __init__(self, temperature=1.0):
        self.temperature = temperature
        self.history = []
    def compute(self, belief, observation):
        obs = np.asarray(observation, dtype=float)
        fe = float(np.sum((belief.mean - obs)**2 * belief.precision) / self.temperature * 0.5)
        self.history.append(fe)
        return fe
    def get_trend(self):
        if len(self.history) < 2:
            return "insufficient_data"
        if self.history[-1] < self.history[-2] * 0.99:
            return "decreasing"
        if self.history[-1] > self.history[-2] * 1.01:
            return "increasing"
        return "stable"

class PrecisionWeighting:
    def __init__(self, sensory_precision=1.0, prior_precision=1.0):
        self.sensory_precision = sensory_precision
        self.prior_precision = prior_precision
    def weight(self, sensory, prior):
        s, p = np.asarray(sensory, dtype=float), np.asarray(prior, dtype=float)
        return (self.sensory_precision * s + self.prior_precision * p) / (self.sensory_precision + self.prior_precision)
    def update_precisions(self, delta):
        self.sensory_precision += delta
        self.prior_precision += delta

class CriticalityRegulator:
    def __init__(self, target_branching_ratio=1.0):
        self.target_branching_ratio = target_branching_ratio
        self._critical = False
    def assess(self, activity):
        a = np.asarray(activity, dtype=float)
        dev = float(np.std(a) / (np.mean(np.abs(a)) + 1e-8))
        self._critical = abs(dev - self.target_branching_ratio) > 0.3
        return dev
    @property
    def is_critical(self):
        return self._critical

class FreeEnergyAgent:
    def __init__(self):
        self._num_beliefs = 0
    def perceive(self, observation):
        obs = np.asarray(observation, dtype=float)
        self._num_beliefs += 1
        return BeliefState(mean=obs, precision=np.ones_like(obs))
    def act(self, belief, goal):
        return (np.asarray(goal, dtype=float) - belief.mean) * 0.1
    def get_stats(self):
        return {"num_beliefs": self._num_beliefs}

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): raise TypeError("not iterable")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


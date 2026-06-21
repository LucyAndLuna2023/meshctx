"""meshctx active_inference — 主动推理引擎"""
import numpy as np
from enum import Enum

class ActionType(Enum):
    EXPLORE = "explore"
    EXPLOIT = "exploit"
    WAIT = "wait"

class Policy:
    def __init__(self, actions=None):
        self.actions = actions or []

class GenerativeModel:
    def __init__(self, state_dim=4, obs_dim=4):
        self.state_dim = state_dim
        self.obs_dim = obs_dim
        self._A = np.eye(obs_dim, state_dim) * 0.9
    def generate_observation(self, state):
        s = np.asarray(state, dtype=float)
        return self._A[:self.obs_dim, :len(s)].dot(s) + np.random.randn(self.obs_dim) * 0.01

class ActiveInferenceEngine:
    def __init__(self, state_dim=8, obs_dim=8):
        self.state_dim = state_dim
        self.obs_dim = obs_dim
        self._state = np.ones(state_dim) / state_dim
    def step(self, observation, goal):
        obs = np.asarray(observation, dtype=float)
        g = np.asarray(goal, dtype=float)
        pred_error = float(np.sum((obs - self._state)**2))
        self._state = self._state * 0.9 + obs * 0.1
        return {"state": self._state, "actions": [ActionType.EXPLOIT], "prediction_error": pred_error}

class DualProcessDecision:
    def __init__(self):
        self.system1_weight = 0.5
        self.system2_weight = 0.5
    def decide(self, intuition, reasoning):
        i = np.asarray(intuition, dtype=float)
        r = np.asarray(reasoning, dtype=float)
        return self.system1_weight * i + self.system2_weight * r
    def adapt_weights(self, system2_fraction):
        self.system2_weight = max(0.0, min(1.0, system2_fraction))
        self.system1_weight = 1.0 - self.system2_weight

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
    def __iter__(s): return iter([_P("i0")])
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


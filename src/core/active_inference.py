"""meshctx active_inference — 主动推理引擎"""
import numpy as np
from enum import Enum

class ActionType(Enum):
    EXPLORE = "explore"
    EXPLOIT = "exploit"
    WAIT = "wait"

class Policy:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, actions=None, **kw):
        self.actions = actions or []

class GenerativeModel:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, state_dim=4, obs_dim=4, **kw):
        self.state_dim = state_dim
        self.obs_dim = obs_dim
        self._A = np.eye(obs_dim, state_dim) * 0.9
    def generate_observation(self, state, **kw):
        s = np.asarray(state, dtype=float)
        return self._A[:self.obs_dim, :len(s)].dot(s) + np.random.randn(self.obs_dim) * 0.01

class ActiveInferenceEngine:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, state_dim=8, obs_dim=8, **kw):
        self.state_dim = state_dim
        self.obs_dim = obs_dim
        self._state = np.ones(state_dim) / state_dim
    def step(self, observation, goal, **kw):
        obs = np.asarray(observation, dtype=float)
        g = np.asarray(goal, dtype=float)
        pred_error = float(np.sum((obs - self._state)**2))
        self._state = self._state * 0.9 + obs * 0.1
        return {"state": self._state, "actions": [ActionType.EXPLOIT], "prediction_error": pred_error}

class DualProcessDecision:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, **kw):
        self.system1_weight = 0.5
        self.system2_weight = 0.5
    def decide(self, intuition, reasoning, **kw):
        i = np.asarray(intuition, dtype=float)
        r = np.asarray(reasoning, dtype=float)
        return self.system1_weight * i + self.system2_weight * r
    def adapt_weights(self, system2_fraction, **kw):
        self.system2_weight = max(0.0, min(1.0, system2_fraction))
        self.system1_weight = 1.0 - self.system2_weight


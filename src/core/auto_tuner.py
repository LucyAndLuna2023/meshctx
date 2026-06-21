"""meshctx auto_tuner"""
import time, math, random
from dataclasses import dataclass
from enum import Enum

@dataclass
class PIDParams:
    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.05

class PIDController:
    def __init__(self, kp=1.0, ki=0.1, kd=0.05, setpoint=0.0):
        self.params = PIDParams(kp=kp, ki=ki, kd=kd)
        self.setpoint = setpoint
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = time.time()
    def compute(self, current_value):
        now = time.time()
        dt = max(now - self._last_time, 0.001)
        self._last_time = now
        error = self.setpoint - current_value
        self._integral += error * dt
        derivative = (error - self._prev_error) / dt
        self._prev_error = error
        return self.params.kp * error + self.params.ki * self._integral + self.params.kd * derivative
    def reset(self):
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = time.time()

class ABTest:
    def __init__(self, name="", variants=None):
        self.name = name
        self.variants = variants or []
        self.results = {}
    def add_variant(self, name, config=None):
        self.variants.append({"name": name, "config": config or {}})
    def record(self, variant_name, metric, value):
        if variant_name not in self.results:
            self.results[variant_name] = {}
        self.results[variant_name][metric] = value
    def get_winner(self):
        if not self.results: return None
        best = max(self.results.items(), key=lambda x: x[1].get("score", 0))
        return best[0]

class PerformanceAutoTuner:
    def __init__(self):
        self._tuners = {}
        self._pid = PIDController()
    def get_pid(self): return self._pid

_auto_tuner = None
def get_auto_tuner():
    global _auto_tuner
    if _auto_tuner is None: _auto_tuner = PerformanceAutoTuner()
    return _auto_tuner

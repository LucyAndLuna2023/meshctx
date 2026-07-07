"""meshctx auto_tuner — PID-based auto-tuning with performance monitoring."""
import time
import math
import random
from dataclasses import dataclass
from enum import Enum


@dataclass
class PIDParams:
    setpoint: float = 0.0
    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.05


class PIDController:
    def __init__(self, *args, setpoint=0.0, kp=1.0, ki=0.1, kd=0.05, **kw):
        if args and isinstance(args[0], PIDParams):
            p = args[0]
            kp, ki, kd = p.kp, p.ki, p.kd
            setpoint = p.setpoint
        self.params = PIDParams(kp=kp, ki=ki, kd=kd, setpoint=setpoint)
        self.setpoint = setpoint
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = time.time()

    def compute(self, current_value, **kw):
        now = time.time()
        dt = max(now - self._last_time, 0.001)
        self._last_time = now
        error = self.setpoint - current_value
        self._integral += error * dt
        derivative = (error - self._prev_error) / dt
        self._prev_error = error
        return self.params.kp * error + self.params.ki * self._integral + self.params.kd * derivative

    def reset(self, **kw):
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = time.time()


class ABTest:
    def __init__(self, name="", variants=None, **kw):
        self.name = name
        self.variants = variants or []
        self.results = {}

    def add_variant(self, name, config=None, **kw):
        self.variants.append({"name": name, "config": config or {}})

    def record(self, variant_name, metric, value, **kw):
        if variant_name not in self.results:
            self.results[variant_name] = {}
        self.results[variant_name][metric] = value

    def get_winner(self, **kw):
        if not self.results:
            return None
        best = max(self.results.items(), key=lambda x: x[1].get("score", 0))
        return best[0]


class AutoTuner:
    def __init__(self, window_size: int = 100, tune_interval: int = 60, **kw):
        self._tuners: dict[str, PIDController] = {}
        self._pid = PIDController()
        self._window_size = window_size
        self._tune_interval = tune_interval
        self._history: dict[str, list[float]] = {}
        self._ab_tests: dict[str, ABTest] = {}
        self._configs: dict[str, dict] = {}
        self._current_config: str = ""

    def get_pid(self):
        return self._pid

    def _get_tuner(self, name: str) -> PIDController:
        if name not in self._tuners:
            self._tuners[name] = PIDController()
        return self._tuners[name]

    def record_metric(self, name: str, value: float, setpoint: float, **kw) -> float:
        tuner = self._get_tuner(name)
        tuner.setpoint = setpoint
        if name not in self._history:
            self._history[name] = []
        self._history[name].append(value)
        while len(self._history[name]) > self._window_size:
            self._history[name].pop(0)
        return tuner.compute(value)

    def auto_tune(self, name: str, value: float, setpoint: float, **kw):
        adj = self.record_metric(name, value, setpoint)
        return adj, self._get_tuner(name).params

    def get_trend(self, **kw) -> str:
        all_vals = []
        for vals in self._history.values():
            all_vals.extend(vals)
        if len(all_vals) < 2:
            return "insufficient_data"
        if all_vals[-1] < all_vals[-2]:
            return "improving"
        elif all_vals[-1] > all_vals[-2]:
            return "degrading"
        return "stable"

    def create_ab_test(self, name: str, config_a: dict, config_b: dict, **kw):
        test = ABTest(name=name)
        test.add_variant("a", config_a)
        test.add_variant("b", config_b)
        self._ab_tests[name] = test

    def record_ab_result(self, test_name: str, variant: str, score: float, **kw):
        if test_name in self._ab_tests:
            self._ab_tests[test_name].record(variant, "score", score)

    def get_ab_winner(self, test_name: str, **kw):
        if test_name not in self._ab_tests:
            return None
        from dataclasses import dataclass

        @dataclass
        class AbWinner:
            winner: str

        test = self._ab_tests[test_name]
        winner = test.get_winner()
        if winner:
            return AbWinner(winner=winner)
        return None

    def save_config(self, name: str, **kw):
        self._configs[name] = {"pid": self._pid.params, "name": name}

    def switch_config(self, name: str, **kw) -> bool:
        if name in self._configs:
            self._current_config = name
            return True
        return False


@dataclass
class SnapShot:
    latency_ms: float = 0.0
    memory_mb: float = 0.0
    error_count: int = 0


@dataclass
class ParamConfig:
    name: str = ""
    current_value: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0


class PerformanceAutoTuner(AutoTuner):
    """High-level performance auto-tuner with snapshot-based monitoring."""

    def __init__(self, window_size=100, tune_interval=60):
        super().__init__(window_size=int(window_size), tune_interval=int(tune_interval))
        self._history: list[SnapShot] = []
        self._stats: dict = {"total_snapshots": 0}
        self._params: dict = {
            "cache_size_mb": ParamConfig(name="cache_size_mb", current_value=128, min_value=32, max_value=512),
            "batch_size": ParamConfig(name="batch_size", current_value=32, min_value=1, max_value=64),
        }

    def snapshot(self, latency_ms=0.0, memory_mb=0.0, error_count=0):
        snap = SnapShot(latency_ms=latency_ms, memory_mb=memory_mb, error_count=error_count)
        self._history.append(snap)
        while len(self._history) > self._window_size:
            self._history.pop(0)
        self._stats["total_snapshots"] += 1
        return snap

    def auto_tune(self):
        if len(self._history) < 5:
            return {"status": "insufficient_data"}
        avg_latency = sum(s.latency_ms for s in self._history) / len(self._history)
        avg_errors = sum(s.error_count for s in self._history) / len(self._history)
        avg_memory = sum(s.memory_mb for s in self._history) / len(self._history)
        adjustments = {}
        if avg_latency > 300:
            adjustments["timeout_ms"] = max(100, int(avg_latency * 1.5))
        if avg_latency > 100:
            adjustments["timeout_budget"] = max(100, int(avg_latency * 1.2))
        if avg_errors > 1:
            adjustments["retry_count"] = min(5, int(avg_errors * 2))
        if avg_memory > 200:
            adjustments["cache_size_mb"] = max(32, int(avg_memory * 0.5))
        return {"status": "tuned", "adjustments": adjustments}

    def get_params(self):
        return {k: v.current_value for k, v in self._params.items()}

    def set_param(self, name, value):
        if name not in self._params:
            return False
        p = self._params[name]
        clamped = max(p.min_value, min(p.max_value, value))
        p.current_value = clamped
        return True

    def _get_current_metrics(self):
        if not self._history:
            return {"avg_latency_ms": 0, "memory_mb": 0}
        avg_latency = sum(s.latency_ms for s in self._history) / len(self._history)
        avg_memory = sum(s.memory_mb for s in self._history) / len(self._history)
        return {"avg_latency_ms": avg_latency, "memory_mb": avg_memory}

    def get_stats(self):
        return {
            "total_snapshots": self._stats["total_snapshots"],
            "current_metrics": self._get_current_metrics(),
            "params": {k: v.current_value for k, v in self._params.items()},
        }


_auto_tuner = None
_engine = None


def get_auto_tuner():
    global _engine
    if _engine is None:
        _engine = PerformanceAutoTuner()
    return _engine

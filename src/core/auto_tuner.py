"""meshctx auto_tuner"""
import time, math, random
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


class PerformanceAutoTuner(AutoTuner):
    """Legacy alias — renamed to AutoTuner."""
    pass


_auto_tuner = None


def get_auto_tuner():
    global _auto_tuner
    if _auto_tuner is None:
        _auto_tuner = AutoTuner()
    return _auto_tuner

"""
meshctx v3.95 — Auto-Tuner (PID自优化引擎)

PID控制参数自动调优 + 性能监控 + A/B测试
"""
import time, logging, statistics, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import deque

logger = logging.getLogger("meshctx.auto_tuner")

@dataclass
class PIDParams:
    kp: float = 1.0; ki: float = 0.1; kd: float = 0.05
    setpoint: float = 100.0; sample_time: float = 1.0

@dataclass 
class TuningMetric:
    name: str; value: float; target: float; timestamp: float = field(default_factory=time.time)

@dataclass
class ABTest:
    name: str; variant_a: Dict; variant_b: Dict
    results_a: List[float] = field(default_factory=list)
    results_b: List[float] = field(default_factory=list)
    winner: Optional[str] = None; confidence: float = 0.0

class PIDController:
    def __init__(self, params: PIDParams = None):
        self.p = params or PIDParams()
        self._integral = 0.0; self._prev_error = 0.0; self._last_time = time.time()
    
    def compute(self, current: float) -> float:
        error = self.p.setpoint - current
        dt = time.time() - self._last_time
        if dt <= 0: dt = 1.0
        self._integral += error * dt
        derivative = (error - self._prev_error) / dt
        output = self.p.kp * error + self.p.ki * self._integral + self.p.kd * derivative
        self._prev_error = error; self._last_time = time.time()
        return max(0, output)

class AutoTuner:
    """v3.95 PID自优化+性能监控+A/B测试"""
    
    def __init__(self):
        self._pid = PIDController()
        self._metrics: List[TuningMetric] = []
        self._history: deque = deque(maxlen=100)
        self._ab_tests: Dict[str, ABTest] = {}
        self._configs: Dict[str, Tuple[float, float, float]] = {}
    
    def record_metric(self, name: str, value: float, target: float = 100):
        m = TuningMetric(name=name, value=value, target=target)
        self._metrics.append(m)
        self._history.append((value, time.time()))
        return self._pid.compute(value)
    
    def auto_tune(self, metric: str, current: float, target: float) -> Tuple[float, PIDParams]:
        adjustment = self.record_metric(metric, current, target)
        return adjustment, self._pid.p
    
    def get_trend(self) -> str:
        if len(self._history) < 5: return "insufficient_data"
        recent = [h[0] for h in list(self._history)[-5:]]
        # Check if last value is closer to target than first
        last_metric = self._metrics[-1] if self._metrics else None
        first_metric = self._metrics[-5] if len(self._metrics) >= 5 else None
        if last_metric and first_metric:
            last_dist = abs(last_metric.value - last_metric.target)
            first_dist = abs(first_metric.value - first_metric.target)
            if last_dist < first_dist: return "improving"
            if last_dist > first_dist: return "degrading"
        return "stable"
    
    def create_ab_test(self, name: str, config_a: Dict, config_b: Dict) -> ABTest:
        test = ABTest(name=name, variant_a=config_a, variant_b=config_b)
        self._ab_tests[name] = test
        return test
    
    def record_ab_result(self, test_name: str, variant: str, result: float):
        test = self._ab_tests.get(test_name)
        if not test: return
        if variant == 'a': test.results_a.append(result)
        else: test.results_b.append(result)
        if len(test.results_a) >= 10 and len(test.results_b) >= 10:
            avg_a = statistics.mean(test.results_a)
            avg_b = statistics.mean(test.results_b)
            test.winner = 'a' if avg_a > avg_b else 'b'
            test.confidence = min(0.99, abs(avg_a - avg_b) / max(avg_a, avg_b, 1))
    
    def get_ab_winner(self, name: str) -> Optional[ABTest]:
        return self._ab_tests.get(name)
    
    def save_config(self, name: str):
        self._configs[name] = (self._pid.p.kp, self._pid.p.ki, self._pid.p.kd)
    
    def switch_config(self, name: str) -> bool:
        if name not in self._configs: return False
        kp, ki, kd = self._configs[name]
        self._pid.p.kp = kp; self._pid.p.ki = ki; self._pid.p.kd = kd
        return True
    
    def get_stats(self) -> Dict:
        return {"metrics": len(self._metrics), "ab_tests": len(self._ab_tests),
                "configs": len(self._configs), "trend": self.get_trend()}

def get_auto_tuner():
    global _tuner
    if _tuner is None: _tuner = AutoTuner()
    return _tuner

@dataclass
class PerfSnapshot:
    latency_ms: float = 0; memory_mb: float = 0; error_count: int = 0

class PerformanceAutoTuner(AutoTuner):
    """v2.56兼容 — 性能自动调优器 (向后兼容)"""
    
    def __init__(self, window_size: int = 20, tune_interval: float = 1.0):
        super().__init__()
        self._stats = {"total_snapshots": 0, "tunes_performed": 0}
        self._params = {
            "cache_size_mb": _ParamDef(64, 8, 256),
            "batch_size": _ParamDef(8, 1, 64),
            "timeout_ms": _ParamDef(5000, 1000, 30000),
            "workers": _ParamDef(4, 1, 16),
        }
        self._window_size = window_size
        self._history: deque = deque(maxlen=window_size)
    
    def snapshot(self, latency_ms: float = 0, memory_mb: float = 0, error_count: int = 0):
        self._history.append(latency_ms)
        self._stats["total_snapshots"] += 1
        return PerfSnapshot(latency_ms=latency_ms, memory_mb=memory_mb, error_count=error_count)
    
    def auto_tune(self) -> Dict:
        if self._stats["total_snapshots"] < 5:
            return {"status": "insufficient_data", "adjustments": {}}
        
        adjustments = {}
        recent = list(self._history)
        avg_lat = sum(recent) / len(recent)
        
        if avg_lat > 500:
            self._params["timeout_ms"].current_value = min(30000, self._params["timeout_ms"].current_value + 2000)
            adjustments["timeout_ms"] = self._params["timeout_ms"].current_value
        
        self._stats["tunes_performed"] += 1
        return {"status": "tuned", "adjustments": adjustments}
    
    def get_params(self) -> Dict:
        return {k: v.current_value for k, v in self._params.items()}
    
    def set_param(self, name: str, value: int) -> bool:
        if name not in self._params: return False
        p = self._params[name]
        p.current_value = max(p.min_val, min(p.max_val, value))
        return True
    
    def _get_current_metrics(self) -> Dict:
        recent = list(self._history)
        if not recent:
            return {"avg_latency_ms": 0, "memory_mb": 0}
        return {"avg_latency_ms": sum(recent) / len(recent), "memory_mb": 200}
    
    def get_stats(self) -> Dict:
        return {"total_snapshots": self._stats["total_snapshots"],
                "current_metrics": self._get_current_metrics(),
                "params": self.get_params()}

class _ParamDef:
    def __init__(self, current: int, min_val: int, max_val: int):
        self.current_value = current; self.min_val = min_val; self.max_val = max_val

_engine = None
_tuner = None

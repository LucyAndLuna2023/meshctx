"""meshctx Performance Monitor — real implementation (v3.115.16)"""
import time
import threading
from collections import defaultdict
from typing import Dict, List

class PerformanceMonitor:
    """Track function call latency, throughput, and error rates."""
    
    def __init__(self):
        self._metrics: Dict[str, List[float]] = defaultdict(list)
        self._errors: Dict[str, int] = defaultdict(int)
        self._calls: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._started = time.time()
    
    def record(self, name: str, duration_ms: float, error: bool = False):
        with self._lock:
            self._metrics[name].append(duration_ms)
            self._calls[name] += 1
            if error:
                self._errors[name] += 1
            if len(self._metrics[name]) > 1000:
                self._metrics[name] = self._metrics[name][-500:]
    
    def stats(self, name: str = None) -> dict:
        with self._lock:
            result = {"uptime_sec": time.time() - self._started}
            names = [name] if name else list(self._metrics.keys())
            for n in names:
                latencies = self._metrics.get(n, [])
                calls = self._calls.get(n, 0)
                errors = self._errors.get(n, 0)
                result[n] = {
                    "calls": calls,
                    "errors": errors,
                    "error_rate": errors / max(1, calls),
                    "avg_ms": sum(latencies) / max(1, len(latencies)),
                    "p50_ms": sorted(latencies)[len(latencies)//2] if latencies else 0,
                    "p99_ms": sorted(latencies)[int(len(latencies)*0.99)] if len(latencies) > 1 else 0,
                }
            return result

_perf: PerformanceMonitor = None
def get_perf_monitor() -> PerformanceMonitor:
    global _perf
    if _perf is None:
        _perf = PerformanceMonitor()
    return _perf

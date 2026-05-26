"""Metrics Collector — v3.26"""
import logging, time, psutil
from collections import defaultdict, deque
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class MetricsCollector:
    def __init__(self, window_size: int = 60):
        self.window_size = window_size
        self._cpu: deque = deque(maxlen=window_size)
        self._mem: deque = deque(maxlen=window_size)
        self._disk: deque = deque(maxlen=window_size)
    
    def collect(self) -> Dict:
        t = time.time()
        try:
            self._cpu.append((t, psutil.cpu_percent()))
            mem = psutil.virtual_memory()
            self._mem.append((t, mem.percent))
            disk = psutil.disk_usage("/")
            self._disk.append((t, disk.percent))
        except: pass
        
        def avg(d): return round(sum(v for _,v in d)/max(1,len(d)),1) if d else 0
        
        return {
            "cpu_current": self._cpu[-1][1] if self._cpu else 0,
            "cpu_avg_60s": avg(self._cpu),
            "mem_current": self._mem[-1][1] if self._mem else 0,
            "mem_avg_60s": avg(self._mem),
            "disk_current": self._disk[-1][1] if self._disk else 0,
            "disk_avg_60s": avg(self._disk),
            "data_points": len(self._cpu),
        }
    
    def get_stats(self) -> Dict: return self.collect()

_collector: Optional[MetricsCollector] = None
def get_metrics_collector() -> MetricsCollector:
    global _collector
    if _collector is None: _collector = MetricsCollector()
    return _collector

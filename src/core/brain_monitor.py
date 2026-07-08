"""meshctx Brain Monitor — real implementation (v3.115.16)"""
import time, threading
from typing import Dict, List

class BrainMonitor:
    """Monitor brain module health, activity, and resource usage."""
    
    def __init__(self):
        self._regions: Dict[str, dict] = {}
        self._events: List[dict] = []
        self._lock = threading.Lock()
    
    def register_region(self, name: str, module: str):
        with self._lock:
            self._regions[name] = {
                "module": module, "status": "active",
                "last_pulse": time.time(), "pulse_count": 0,
                "errors": 0
            }
    
    def pulse(self, name: str):
        with self._lock:
            if name in self._regions:
                self._regions[name]["last_pulse"] = time.time()
                self._regions[name]["pulse_count"] += 1
    
    def record_error(self, name: str, error: str):
        with self._lock:
            if name in self._regions:
                self._regions[name]["errors"] += 1
            self._events.append({"region": name, "error": error, "time": time.time()})
            if len(self._events) > 500:
                self._events = self._events[-200:]
    
    def health_report(self) -> dict:
        with self._lock:
            now = time.time()
            regions = {}
            for name, r in self._regions.items():
                idle = now - r["last_pulse"]
                status = "dead" if idle > 300 else ("idle" if idle > 60 else "active")
                regions[name] = {**r, "idle_sec": round(idle, 1), "status": status}
            return {
                "regions": len(self._regions),
                "active": sum(1 for r in regions.values() if r["status"] == "active"),
                "details": regions,
                "recent_errors": self._events[-5:],
            }

_monitor = BrainMonitor()
def get_brain_monitor() -> BrainMonitor:
    return _monitor

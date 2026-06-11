"""Health Monitor — 开源版 (stub)"""
class _HealthMonitor:
    def check(self, *a, **kw) -> bool: return True
    def stats(self): return {"status": "healthy"}

_monitor = _HealthMonitor()
def get_health_monitor(): return _monitor

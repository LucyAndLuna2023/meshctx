"""Attention Decay — 开源版 (stub)"""
class _Monitor:
    def check(self, *a, **kw): return 0.0
    def stats(self): return {}

_monitor = _Monitor()
def get_monitor(): return _monitor

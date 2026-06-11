"""Unified Loop — 开源版 (stub)"""
class _UnifiedLoop:
    def start(self, *a, **kw): pass
    def stop(self): pass
    def stats(self): return {}

_loop = _UnifiedLoop()
def get_unified_loop(): return _loop

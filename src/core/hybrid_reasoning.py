"""Hybrid Reasoning — 开源版 (stub)"""
class HybridReasoningScheduler:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, *a, **kw): pass
    def schedule(self, *a, **kw): return None
    def stats(self): return {}

from ._stub import _P

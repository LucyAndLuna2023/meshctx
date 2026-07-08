"""Performance — 开源版 (stub)"""
class CacheStats:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self): self.hits = 0; self.misses = 0
class StreamStats:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self): self.total = 0

class PerformancePlugin:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    info = type('Info', (), {'name': 'performance', 'version': '0.1', 'dependencies': [], 'category': 'perf', 'description': 'Performance stub'})()
    state = "active"
    async def on_load(self, kernel): return True
    def generate_report(self): return {"hits": 0, "misses": 0}

from ._stub import _P

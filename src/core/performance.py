"""Performance — 开源版 (stub)"""
class CacheStats:
    def __init__(self): self.hits = 0; self.misses = 0
class StreamStats:
    def __init__(self): self.total = 0

class PerformancePlugin:
    info = type('Info', (), {'name': 'performance', 'version': '0.1', 'dependencies': [], 'category': 'perf', 'description': 'Performance stub'})()
    state = "active"
    async def on_load(self, kernel): return True
    def generate_report(self): return {"hits": 0, "misses": 0}

class _P:
    __slots__ = ('_n',)
    def __init__(s, n=""): object.__setattr__(s, '_n', n)
    def __getattr__(s, n):
        if n.startswith('_'): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


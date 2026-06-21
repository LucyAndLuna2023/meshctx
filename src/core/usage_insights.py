"""Usage Insights — 开源版 (stub)"""
class UsageInsights:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def get_today(self): return {"calls": 0, "tokens": 0, "models": []}
    def record_call(self, *a, **kw): return {"recorded": True}
    def __init__(self, *a, **kw): pass
    def track(self, *a, **kw): pass
    def report(self) -> dict: return {"total_tokens": 0, "total_calls": 0}
    def stats(self): return {}
    def get_provider_stats(self): return {}
    def get_model_stats(self): return {}
    def record_session_start(self): pass
    def get_weekly(self): return {"period": "weekly", "calls": 0, "tokens": 0}
    def get_monthly(self): return {"period": "monthly", "calls": 0, "tokens": 0}
    def get_summary(self, days=30): return {"period": f"{days}d", "calls": 0, "tokens": 0, "models": []}

def get_usage_insights(): return UsageInsights()

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


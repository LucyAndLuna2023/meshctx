"""Action Gate — 开源版 (stub)"""
TOOL_PRINCIPLE_MAP = {}

class _ActionGate:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def check(self, *a, **kw) -> bool: return True
    def stats(self): return {}
    def get_stats(self): return self.stats()
    def get_recent_events(self, limit=10): return []

_gate = _ActionGate()
def get_gate(): return _gate
get_action_gate = get_gate

"""Action Gate — 开源版 (stub)"""
TOOL_PRINCIPLE_MAP = {}

class _ActionGate:
    def check(self, *a, **kw) -> bool: return True
    def stats(self): return {}

_gate = _ActionGate()
def get_gate(): return _gate
get_action_gate = get_gate

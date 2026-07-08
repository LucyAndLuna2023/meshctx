"""Windows Admin — 开源版 (stub)"""

from ._stub import _P

class _WinAdmin:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def elevate(self, *a, **kw): return False
    def is_admin(self) -> bool: return False
    def stats(self): return {}

_admin = _WinAdmin()
def get_win_admin(): return _admin

"""Windows Admin — 开源版 (stub)"""
class _WinAdmin:
    def elevate(self, *a, **kw): return False
    def is_admin(self) -> bool: return False
    def stats(self): return {}

_admin = _WinAdmin()
def get_win_admin(): return _admin

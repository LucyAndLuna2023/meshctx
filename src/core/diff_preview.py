"""Diff Preview — 开源版 (stub)"""
class _DiffEngine:
    def diff(self, *a, **kw) -> str: return ""
    def preview(self, *a, **kw) -> str: return ""
    def stats(self): return {}

_engine = _DiffEngine()
def get_diff_engine(): return _engine

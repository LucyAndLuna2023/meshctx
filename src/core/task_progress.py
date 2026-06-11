"""Task Progress — 开源版 (stub)"""
class _ProgressEngine:
    def update(self, *a, **kw): pass
    def get(self, *a, **kw): return {"progress": 0}
    def stats(self): return {}

_engine = _ProgressEngine()
def get_progress_engine(): return _engine

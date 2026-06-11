"""SDB Framework — 开源版 (stub)"""
class _SDBEngine:
    def execute(self, *a, **kw): return None
    def stats(self): return {}

_engine = _SDBEngine()
def get_sdb_engine(): return _engine

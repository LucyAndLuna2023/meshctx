"""Gateway Connectors — 开源版 (stub)"""
class _Gateway:
    def start(self, *a, **kw): pass
    def stop(self): pass
    def stats(self): return {"connections": 0}

_gateway = _Gateway()
def get_gateway(): return _gateway

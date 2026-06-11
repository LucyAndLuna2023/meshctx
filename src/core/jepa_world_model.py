"""JEPA World Model — 开源版 (stub)"""
class _WorldModel:
    def predict(self, *a, **kw): return None
    def stats(self): return {}

_wm = _WorldModel()
def get_world_model(): return _wm
def get_non_generative_router(): return _wm

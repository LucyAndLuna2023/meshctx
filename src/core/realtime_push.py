"""实时推送 — 开源版"""
class _Hub:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def broadcast(self, *a, **kw): pass
    def subscribe(self, *a, **kw): pass
    async def start(self): pass
    def stats(self): return {"connections": 0}

_hub = _Hub()
def get_hub(): return _hub

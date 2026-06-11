"""实时推送 — 开源版"""
class _Hub:
    def broadcast(self, *a, **kw): pass
    def subscribe(self, *a, **kw): pass
    async def start(self): pass
    def stats(self): return {"connections": 0}

_hub = _Hub()
def get_hub(): return _hub

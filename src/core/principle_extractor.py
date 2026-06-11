"""Principle Extractor — 开源版 (stub)"""
class _Extractor:
    def extract(self, *a, **kw) -> dict: return {"principles": []}
    def stats(self): return {}

_extractor = _Extractor()
def get_extractor(): return _extractor

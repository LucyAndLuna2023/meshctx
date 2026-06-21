"""Principle Extractor — 开源版 (stub)"""
class _Extractor:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def extract(self, *a, **kw) -> dict: return {"principles": []}
    def stats(self): return {}
    def list_all(self): return self.extract().get("principles", [])

_extractor = _Extractor()
def get_extractor(): return _extractor
list_all = _Extractor.extract

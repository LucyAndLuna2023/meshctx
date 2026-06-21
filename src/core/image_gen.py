"""Image Generator — 开源版 (stub)"""
class ImageGenerator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, *a, **kw): pass
    def generate(self, prompt: str, *a, **kw) -> dict:
        return {"url": "", "error": "Image generation requires meshctx-core"}
    def stats(self): return {}

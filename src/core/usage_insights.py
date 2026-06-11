"""Usage Insights — 开源版 (stub)"""
class UsageInsights:
    def __init__(self, *a, **kw): pass
    def track(self, *a, **kw): pass
    def report(self) -> dict: return {"total_tokens": 0, "total_calls": 0}
    def stats(self): return {}

def get_usage_insights(): return UsageInsights()

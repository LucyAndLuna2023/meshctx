"""Dashboard — 开源版 (stub)"""
class UnifiedDashboard:
    def __init__(self, *a, **kw): pass
    def start(self, *a, **kw): pass
    def render(self) -> str: return "<html><body>meshctx Dashboard (stub)</body></html>"
    def stats(self): return {}
    def get_full_dashboard(self): return self.stats()

def get_dashboard(): return UnifiedDashboard()
get_full_dashboard = UnifiedDashboard.stats

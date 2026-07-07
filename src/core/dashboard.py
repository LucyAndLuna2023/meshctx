"""Dashboard — 开源版 (stub)"""
class UnifiedDashboard:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, *a, **kw):
        object.__setattr__(self, '_running', False)
    def start(self, host: str = "0.0.0.0", port: int = 3001, **kw):
        self._running = True
        self._host = host
        self._port = port
        return True
    def render(self) -> str: return "<html><body>meshctx Dashboard (stub)</body></html>"
    def stats(self): return {}
    def get_full_dashboard(self): return self.stats()

def get_dashboard(): return UnifiedDashboard()
get_full_dashboard = UnifiedDashboard.stats

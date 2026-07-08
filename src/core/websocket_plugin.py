"""WebSocket Plugin — 开源版 (stub)"""
class WebSocketPlugin:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    info = type('Info', (), {'name': 'websocket', 'version': '0.1', 'dependencies': [], 'category': 'network', 'description': 'WebSocket stub'})()
    state = "active"
    async def on_load(self, kernel): return True

def create_ws_routes(*a, **kw):
    return []


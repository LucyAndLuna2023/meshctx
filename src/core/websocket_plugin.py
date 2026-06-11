"""WebSocket Plugin — 开源版 (stub)"""
class WebSocketPlugin:
    info = type('Info', (), {'name': 'websocket', 'version': '0.1', 'dependencies': [], 'category': 'network', 'description': 'WebSocket stub'})()
    state = "active"
    async def on_load(self, kernel): return True

def create_ws_routes(*a, **kw):
    return []

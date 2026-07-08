"""meshctx WebSocket Plugin — real implementation (v3.115.16)"""
import asyncio, logging, json
logger = logging.getLogger("meshctx.ws")

class WebSocketPlugin:
    """WebSocket server plugin for real-time communication."""
    def __init__(self):
        self.clients = set()
        self._running = False
    
    async def connect(self, websocket):
        self.clients.add(websocket)
        logger.info(f"WS client connected (total: {len(self.clients)})")
    
    async def disconnect(self, websocket):
        self.clients.discard(websocket)
    
    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.clients -= dead
    
    async def start(self): self._running = True
    async def stop(self): self._running = False; self.clients.clear()
    def stats(self) -> dict: return {"clients": len(self.clients), "running": self._running}

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


def create_ws_routes(app=None, plugin: WebSocketPlugin = None):
    """创建 WebSocket 路由 (2026-08-25 004meshctx 审计补齐 — main.py import 契约)。

    返回 (plugin, router); 若传入 FastAPI app 则挂载 /ws 端点。
    保持与 _known 映射兼容: from src.core import create_ws_routes 可用。
    """
    if plugin is None:
        plugin = WebSocketPlugin()
    if app is not None:
        try:
            from fastapi import WebSocket, WebSocketDisconnect

            @app.websocket("/ws")
            async def ws_endpoint(websocket: WebSocket):
                await websocket.accept()
                await plugin.connect(websocket)
                try:
                    while True:
                        await websocket.receive_text()
                except (WebSocketDisconnect, Exception):
                    await plugin.disconnect(websocket)
        except Exception as e:
            logger.warning(f"create_ws_routes: cannot mount /ws ({e})")
    return plugin

<<<<<<< Updated upstream
"""
meshctx realtime_push — WebSocket 实时推送服务

用法:
    from src.core.realtime_push import RealtimePush, create_realtime_router
    app.include_router(create_realtime_router())

前端:
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = (e) => { const msg = JSON.parse(e.data); ... };

消息类型:
    - agent.status: {type, status: 'idle'|'thinking'|'online'}
    - chat.message: {type, role, content, timestamp}
    - system.event: {type, event, data}
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("meshctx.realtime")

# ═══════════════════════════════════════════════════════════════
# WebSocket 连接管理器
# ═══════════════════════════════════════════════════════════════


class ConnectionManager:
    """管理所有活跃 WebSocket 连接，支持广播和按频道推送。"""

    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._global: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket, channel: str = "global"):
        """接受新连接并注册到频道。"""
        await ws.accept()
        self._global.add(ws)
        self._connections.setdefault(channel, set()).add(ws)
        logger.debug(f"WS connected channel={channel} total={len(self._global)}")

    def disconnect(self, ws: WebSocket, channel: str = "global"):
        """移除断开的连接。"""
        self._global.discard(ws)
        if channel in self._connections:
            self._connections[channel].discard(ws)
        logger.debug(f"WS disconnected channel={channel} total={len(self._global)}")

    async def broadcast(self, message: Dict[str, Any], channel: str = "global"):
        """向指定频道广播消息。"""
        payload = json.dumps(message, ensure_ascii=False)
        targets = self._connections.get(channel, set()).copy()

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections[channel].discard(ws)

    async def broadcast_all(self, message: Dict[str, Any]):
        """向所有连接广播消息。"""
        payload = json.dumps(message, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self._global.copy():
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._global.discard(ws)

    @property
    def active_count(self) -> int:
        return len(self._global)


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

_realtime_instance: "RealtimePush | None" = None


class RealtimePush:
    """实时推送服务 — 简化的工作线程 API。

    用法:
        rtp = RealtimePush()
        await rtp.push_status("thinking")
        await rtp.push_message("assistant", "Hello!")
        await rtp.push_event("file.changed", {"path": "test.py"})
    """

    def __init__(self):
        self.manager = ConnectionManager()

    async def push_status(self, status: str):
        """推送 Agent 状态变更。"""
        await self.manager.broadcast({
            "type": "agent.status",
            "status": status,
        })

    async def push_message(self, role: str, content: str, tool_result: Optional[str] = None, **kwargs):
        """推送聊天消息。"""
        await self.manager.broadcast({
            "type": "chat.message",
            "role": role,
            "content": content,
            "tool_result": tool_result,
            **kwargs,
        })

    async def push_event(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """推送系统事件。"""
        await self.manager.broadcast_all({
            "type": "system.event",
            "event": event_type,
            "data": data or {},
        })

    async def push_hybrid_info(self, info: Dict[str, Any]):
        """推送混合推理状态。"""
        await self.manager.broadcast({
            "type": "hybrid.info",
            **info,
        })


def get_realtime() -> RealtimePush:
    """获取全局 RealtimePush 单例。"""
    global _realtime_instance
    if _realtime_instance is None:
        _realtime_instance = RealtimePush()
    return _realtime_instance


# ═══════════════════════════════════════════════════════════════
# FastAPI 路由
# ═══════════════════════════════════════════════════════════════


def create_realtime_router() -> APIRouter:
    """创建 WebSocket 路由，挂载到 FastAPI app。

    用法:
        from src.core.realtime_push import create_realtime_router
        app.include_router(create_realtime_router())
    """
    router = APIRouter(tags=["realtime"])
    rtp = get_realtime()

    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        """WebSocket 端点 — 默认 global 频道。"""
        await rtp.manager.connect(websocket)
        try:
            # 发送初始连接确认
            await websocket.send_text(json.dumps({
                "type": "system.connected",
                "active_connections": rtp.manager.active_count,
            }))
            # 保持连接，接收客户端消息（心跳/订阅切换）
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            rtp.manager.disconnect(websocket)
        except Exception:
            rtp.manager.disconnect(websocket)

    @router.websocket("/ws/{channel}")
    async def ws_channel_endpoint(websocket: WebSocket, channel: str):
        """WebSocket 端点 — 指定频道。"""
        await rtp.manager.connect(websocket, channel)
        try:
            await websocket.send_text(json.dumps({
                "type": "system.connected",
                "channel": channel,
                "active_connections": rtp.manager.active_count,
            }))
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            rtp.manager.disconnect(websocket, channel)
        except Exception:
            rtp.manager.disconnect(websocket, channel)

    return router
=======
"""实时推送 — 开源版"""
class _Hub:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def broadcast(self, *a, **kw): pass
    def subscribe(self, *a, **kw): pass
    async def start(self): pass
    def stats(self): return {"connections": 0}

_hub = _Hub()
def get_hub(): return _hub
>>>>>>> Stashed changes

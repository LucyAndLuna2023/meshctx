"""
meshctx v1.0 WebSocket 实时通信

支持:
- 实时事件推送 (内核事件→前端)
- Agent对话流 (双向实时)
- 系统状态推送 (heartbeat)
- 多频道订阅
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from .kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.ws")


# ═══════════════════════════════════════════════════════════
# WebSocket 连接管理器
# ═══════════════════════════════════════════════════════════

@dataclass
class WSClient:
    """WebSocket客户端"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ws: WebSocket = None
    channels: Set[str] = field(default_factory=set)
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)


class WSManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self._clients: Dict[str, WSClient] = {}
        self._channels: Dict[str, Set[str]] = {}  # channel → client_ids
        
    async def connect(self, ws: WebSocket, metadata: Dict = None) -> str:
        """建立连接"""
        await ws.accept()
        client = WSClient(ws=ws, metadata=metadata or {})
        self._clients[client.id] = client
        
        # 默认订阅全局频道
        client.channels.add("global")
        self._add_to_channel("global", client.id)
        
        logger.debug(f"WS客户端连接: {client.id[:8]}")
        
        # 发送欢迎消息
        await self._send(client, {
            "type": "connected",
            "client_id": client.id,
            "timestamp": time.time(),
        })
        
        return client.id
    
    async def disconnect(self, client_id: str):
        """断开连接"""
        client = self._clients.pop(client_id, None)
        if client:
            for channel in client.channels:
                self._remove_from_channel(channel, client_id)
            try:
                await client.ws.close()
            except:
                pass
            logger.debug(f"WS客户端断开: {client_id[:8]}")
    
    def subscribe(self, client_id: str, channel: str):
        """订阅频道"""
        client = self._clients.get(client_id)
        if client:
            client.channels.add(channel)
            self._add_to_channel(channel, client_id)
    
    def unsubscribe(self, client_id: str, channel: str):
        """取消订阅"""
        client = self._clients.get(client_id)
        if client:
            client.channels.discard(channel)
            self._remove_from_channel(channel, client_id)
    
    def _add_to_channel(self, channel: str, client_id: str):
        if channel not in self._channels:
            self._channels[channel] = set()
        self._channels[channel].add(client_id)
    
    def _remove_from_channel(self, channel: str, client_id: str):
        if channel in self._channels:
            self._channels[channel].discard(client_id)
            if not self._channels[channel]:
                del self._channels[channel]
    
    async def broadcast(self, channel: str, data: Dict, exclude: str = None):
        """向频道广播"""
        client_ids = self._channels.get(channel, set())
        
        dead_clients = []
        for cid in client_ids:
            if cid == exclude:
                continue
            client = self._clients.get(cid)
            if client:
                try:
                    await self._send(client, data)
                    client.last_activity = time.time()
                except:
                    dead_clients.append(cid)
        
        # 清理断开的客户端
        for cid in dead_clients:
            await self.disconnect(cid)
    
    async def send_to(self, client_id: str, data: Dict):
        """发送给特定客户端"""
        client = self._clients.get(client_id)
        if client:
            try:
                await self._send(client, data)
            except:
                await self.disconnect(client_id)
    
    async def _send(self, client: WSClient, data: Dict):
        """发送数据"""
        data["_ts"] = time.time()
        await client.ws.send_json(data)
    
    def stats(self) -> Dict:
        return {
            "clients": len(self._clients),
            "channels": len(self._channels),
            "channel_details": {
                ch: len(clients) for ch, clients in self._channels.items()
            },
        }


# ═══════════════════════════════════════════════════════════
# WebSocket 插件
# ═══════════════════════════════════════════════════════════

class WebSocketPlugin(Plugin):
    """
    WebSocket实时通信插件
    
    频道:
    - global: 全局事件
    - kernel: 内核事件
    - memory: 记忆更新
    - agent: Agent状态
    - predictor: 预测结果
    - health: 健康状态
    """
    
    info = PluginInfo(
        name="websocket",
        version="1.0.0",
        description="WebSocket实时通信 — 事件推送+双向对话",
        author="meshctx",
    )
    
    def __init__(self):
        self.manager = WSManager()
        self._broadcast_task: Optional[asyncio.Task] = None
        
        # 事件→频道映射
        self._event_channels = {
            "kernel.*": "kernel",
            "memory.*": "memory",
            "agent.*": "agent",
            "predictor.*": "predictor",
            "healer.*": "health",
            "task.*": "agent",
            "plugin.*": "kernel",
            "system.*": "global",
        }
    
    async def on_load(self):
        bus = self.kernel.bus
        
        # 订阅所有事件用于广播
        bus.subscribe("*", self._on_any_event, plugin_name="websocket")
        bus.subscribe("ws.stats", self._on_stats_request, plugin_name="websocket")
        
        logger.info("WebSocket插件已加载 (实时事件推送)")
    
    async def on_unload(self):
        # 断开所有客户端
        for cid in list(self.manager._clients.keys()):
            await self.manager.disconnect(cid)
        logger.info("WebSocket插件已卸载")
    
    async def _on_any_event(self, event: Event):
        """所有内核事件→广播到对应频道"""
        # 找到匹配频道
        channels = set()
        for pattern, channel in self._event_channels.items():
            if pattern == "*" or (
                "*" in pattern and event.type.startswith(pattern.replace("*", ""))
            ) or event.type == pattern:
                channels.add(channel)
        
        if not channels:
            channels.add("global")
        
        # 广播
        payload = {
            "type": "event",
            "event_type": event.type,
            "source": event.source,
            "data": event.data,
            "timestamp": event.timestamp,
        }
        
        for channel in channels:
            await self.manager.broadcast(channel, payload)
    
    async def _on_stats_request(self, event: Event):
        stats = self.manager.stats()
        await self.kernel.bus.publish(Event(
            type="ws.stats_result",
            source="websocket",
            correlation_id=event.id,
            data=stats,
        ))
    
    # ── 公开方法 ────────────────────────────────────────────
    
    async def handle_ws(self, ws: WebSocket, channels: List[str] = None):
        """处理WebSocket连接 (由FastAPI路由调用)"""
        client_id = await self.manager.connect(ws)
        
        # 订阅指定频道
        if channels:
            for ch in channels:
                self.manager.subscribe(client_id, ch)
        
        try:
            # 发送初始状态
            await self.manager.send_to(client_id, {
                "type": "ready",
                "channels": list(self.manager._clients[client_id].channels),
            })
            
            # 接收客户端消息
            while True:
                data = await ws.receive_json()
                
                msg_type = data.get("type", "")
                
                if msg_type == "ping":
                    await self.manager.send_to(client_id, {"type": "pong"})
                
                elif msg_type == "subscribe":
                    channel = data.get("channel", "")
                    if channel:
                        self.manager.subscribe(client_id, channel)
                        await self.manager.send_to(client_id, {
                            "type": "subscribed", "channel": channel,
                        })
                
                elif msg_type == "unsubscribe":
                    channel = data.get("channel", "")
                    if channel:
                        self.manager.unsubscribe(client_id, channel)
                
                elif msg_type == "message":
                    # 用户消息→发布到内核
                    await self.kernel.bus.publish(Event(
                        type="user.message",
                        source="websocket",
                        data={
                            "content": data.get("content", ""),
                            "client_id": client_id,
                            "context": data.get("context", {}),
                        },
                    ))
                
                elif msg_type == "predict":
                    await self.kernel.bus.publish(Event(
                        type="predictor.predict",
                        source="websocket",
                        data={"client_id": client_id},
                    ))
                
                self.manager._clients[client_id].last_activity = time.time()
                
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WS错误 [{client_id[:8]}]: {e}")
        finally:
            await self.manager.disconnect(client_id)
    
    def generate_report(self) -> Dict:
        return {
            "stats": self.manager.stats(),
        }


# ═══════════════════════════════════════════════════════════
# FastAPI WebSocket 路由 (供 main.py 使用)
# ═══════════════════════════════════════════════════════════

def create_ws_routes(app, ws_plugin: WebSocketPlugin):
    """创建WebSocket路由"""
    
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await ws_plugin.handle_ws(websocket)
    
    @app.websocket("/ws/{channel}")
    async def ws_channel_endpoint(websocket: WebSocket, channel: str):
        await ws_plugin.handle_ws(websocket, channels=[channel])
    
    @app.get("/ws/stats")
    async def ws_stats():
        return ws_plugin.manager.stats()

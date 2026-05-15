"""
MeshCtx Realtime Push — WebSocket Dashboard Updates
=====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Pushes metrics via WebSocket so dashboard updates in real-time.
"""
import asyncio
import json
import time
import logging
from typing import Set, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class RealtimeHub:
    """WebSocket hub for real-time metric broadcasting."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._running = False
        self._task = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        logger.info(f"WebSocket connected ({len(self._connections)} total)")
        try:
            while True:
                await ws.receive_text()  # Keep alive, ignore messages
        except WebSocketDisconnect:
            self._connections.remove(ws)
            logger.info(f"WebSocket disconnected ({len(self._connections)} total)")

    async def broadcast(self, data: Dict[str, Any]):
        """Push data to all connected clients."""
        if not self._connections:
            return
        message = json.dumps(data, ensure_ascii=False)
        dead = set()
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    async def start_broadcast_loop(self, interval: float = 2.0):
        """Start periodic metric broadcasting."""
        self._running = True
        while self._running:
            try:
                from src.core.agent_monitor import get_monitor
                metrics = get_monitor().get_snapshot()
                metrics["type"] = "agent_metrics"
                metrics["timestamp"] = time.time()
                await self.broadcast(metrics)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False


# Global hub
_hub = RealtimeHub()


def get_hub() -> RealtimeHub:
    return _hub

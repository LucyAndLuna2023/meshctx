"""
meshctx Reliable WebSocket (v3.115.16)
Auto-reconnecting WebSocket with exponential backoff and heartbeat.
"""
import asyncio
import logging
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("meshctx.ws")

class ReliableWebSocket:
    """WebSocket wrapper with auto-reconnect and heartbeat."""
    
    def __init__(self, url: str, on_message: Callable[[str], Awaitable[None]] = None,
                 ping_interval: float = 30, reconnect_base: float = 1.0,
                 reconnect_max: float = 60.0, max_retries: int = 0):
        self.url = url
        self.on_message = on_message
        self.ping_interval = ping_interval
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self.max_retries = max_retries  # 0 = infinite
        self._ws = None
        self._running = False
        self._retry_count = 0
    
    async def connect(self):
        """Connect and start message loop."""
        self._running = True
        self._retry_count = 0
        await self._connect_loop()
    
    async def _connect_loop(self):
        """Main connection loop with auto-reconnect."""
        import websockets
        
        while self._running:
            if self.max_retries > 0 and self._retry_count >= self.max_retries:
                logger.warning(f"Max retries ({self.max_retries}) reached for {self.url}")
                break
            
            try:
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    self._retry_count = 0
                    logger.info(f"WebSocket connected: {self.url}")
                    
                    # Start heartbeat
                    heartbeat_task = asyncio.ensure_future(self._heartbeat())
                    
                    # Message loop
                    async for message in ws:
                        if self.on_message:
                            try:
                                await self.on_message(message)
                            except Exception as e:
                                logger.error(f"Message handler error: {e}")
                    
                    heartbeat_task.cancel()
                    
            except Exception as e:
                self._retry_count += 1
                delay = min(self.reconnect_base * (2 ** (self._retry_count - 1)), self.reconnect_max)
                logger.warning(f"WebSocket disconnected ({e}), retry {self._retry_count} in {delay:.1f}s")
                await asyncio.sleep(delay)
    
    async def _heartbeat(self):
        """Send periodic pings to keep connection alive."""
        while self._running and self._ws:
            try:
                await asyncio.sleep(self.ping_interval)
                if self._ws:
                    pong = await self._ws.ping()
                    await asyncio.wait_for(pong, timeout=5)
            except Exception:
                break
    
    async def send(self, message: str):
        """Send a message through the websocket."""
        if self._ws and self._ws.open:
            await self._ws.send(message)
    
    async def close(self):
        """Gracefully close the connection."""
        self._running = False
        if self._ws:
            await self._ws.close()

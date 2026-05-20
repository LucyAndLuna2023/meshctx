"""
MeshCtx Gateway Connectors — Interactive Bot Framework
========================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Pluggable interactive bot connectors for messaging platforms.
Each connector handles:
- Incoming messages → dispatch to agent
- Outgoing responses → format + send to platform
- Platform-specific auth + retry logic

Supported platforms:
- Slack (Socket Mode + Web API)
- Discord (Gateway + REST)
- WhatsApp (Cloud API)
- Extensible via Connector base class

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import json
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
import os

logger = logging.getLogger(__name__)

# ── Data Model ──────────────────────────────────────────────


@dataclass
class GatewayMessage:
    """Normalized incoming message from any platform."""
    platform: str          # slack, discord, whatsapp, telegram
    channel_id: str        # platform-specific channel/chat ID
    user_id: str           # sender ID
    user_name: str         # sender display name
    text: str              # message content
    thread_id: str = ""    # reply thread (if any)
    raw_payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConnectorStatus:
    platform: str
    connected: bool = False
    last_message_ts: float = 0
    messages_received: int = 0
    messages_sent: int = 0
    errors: int = 0
    last_error: str = ""


# ── Base Connector ──────────────────────────────────────────


class BaseConnector(ABC):
    """Abstract base for all platform connectors."""

    platform: str = "unknown"

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.status = ConnectorStatus(platform=self.platform)
        self._handler: Optional[Callable] = None

    def on_message(self, handler: Callable[[GatewayMessage], Any]):
        """Register message handler."""
        self._handler = handler

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to platform."""
        ...

    @abstractmethod
    async def disconnect(self):
        """Close connection."""
        ...

    @abstractmethod
    async def send_message(self, channel_id: str, text: str,
                           thread_id: str = "") -> bool:
        """Send a message to a channel."""
        ...

    def _record_message(self, msg: GatewayMessage):
        """Record incoming message stats."""
        self.status.messages_received += 1
        self.status.last_message_ts = msg.timestamp

    def _record_sent(self):
        self.status.messages_sent += 1

    def _record_error(self, error: str):
        self.status.errors += 1
        self.status.last_error = error


# ── Slack Connector ─────────────────────────────────────────


class SlackConnector(BaseConnector):
    """Slack Bot — Socket Mode + Web API.

    Requires:
    - SLACK_BOT_TOKEN (xoxb-...)
    - SLACK_APP_TOKEN (xapp-...)
    """

    platform = "slack"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN", "")
        self.app_token = self.config.get("app_token") or os.environ.get("SLACK_APP_TOKEN", "")
        self._socket_client = None
        self._web_client = None
        self._connected = False

    async def connect(self) -> bool:
        """Connect to Slack via Socket Mode."""
        if not self.bot_token or not self.app_token:
            self._record_error("Missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN")
            return False

        try:
            # Use slack_sdk if available, otherwise use HTTP fallback
            try:
                from slack_sdk import WebClient
                from slack_sdk.socket_mode import SocketModeClient
                self._web_client = WebClient(token=self.bot_token)
                self._socket_client = SocketModeClient(
                    app_token=self.app_token,
                    web_client=self._web_client,
                )
                self._socket_client.socket_mode_request_listeners.append(
                    self._handle_slack_event
                )
                # Start in background
                import threading
                t = threading.Thread(target=self._socket_client.connect, daemon=True)
                t.start()
                self._connected = True
                self.status.connected = True
                logger.info("Slack connector connected via Socket Mode")
                return True
            except ImportError:
                logger.warning("slack_sdk not installed, using webhook-only mode")
                self._connected = self.bot_token != ""
                self.status.connected = self._connected
                return self._connected
        except Exception as e:
            self._record_error(str(e))
            return False

    async def disconnect(self):
        if self._socket_client:
            self._socket_client.close()
        self._connected = False
        self.status.connected = False

    def _handle_slack_event(self, client, req):
        """Handle incoming Slack events."""
        if req.type == "events_api":
            event = req.payload.get("event", {})
            if event.get("type") == "message" and not event.get("bot_id"):
                msg = GatewayMessage(
                    platform="slack",
                    channel_id=event.get("channel", ""),
                    user_id=event.get("user", ""),
                    user_name=event.get("user", ""),
                    text=event.get("text", ""),
                    thread_id=event.get("thread_ts", ""),
                    raw_payload=event,
                )
                self._record_message(msg)
                if self._handler:
                    asyncio.run(self._handler(msg))

    async def send_message(self, channel_id: str, text: str,
                           thread_id: str = "") -> bool:
        """Send message via Slack Web API or webhook."""
        if self._web_client:
            try:
                kwargs = {"channel": channel_id, "text": text}
                if thread_id:
                    kwargs["thread_ts"] = thread_id
                self._web_client.chat_postMessage(**kwargs)
                self._record_sent()
                return True
            except Exception as e:
                self._record_error(str(e))
                return False

        # Fallback: webhook
        webhook = self.config.get("webhook_url", "")
        if webhook:
            return await self._send_webhook(webhook, text)
        return False

    async def _send_webhook(self, url: str, text: str) -> bool:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"text": text}) as resp:
                    ok = resp.status == 200
                    if ok:
                        self._record_sent()
                    else:
                        self._record_error(f"HTTP {resp.status}")
                    return ok
        except Exception as e:
            self._record_error(str(e))
            return False


# ── Discord Connector ───────────────────────────────────────


class DiscordConnector(BaseConnector):
    """Discord Bot — Gateway + REST API.

    Requires:
    - DISCORD_BOT_TOKEN
    """

    platform = "discord"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN", "")
        self._client = None
        self._connected = False

    async def connect(self) -> bool:
        if not self.bot_token:
            self._record_error("Missing DISCORD_BOT_TOKEN")
            return False
        try:
            try:
                import discord
                intents = discord.Intents.default()
                intents.message_content = True
                self._client = discord.Client(intents=intents)

                @self._client.event
                async def on_ready():
                    logger.info(f"Discord bot connected as {self._client.user}")
                    self._connected = True
                    self.status.connected = True

                @self._client.event
                async def on_message(message):
                    if message.author.bot:
                        return
                    msg = GatewayMessage(
                        platform="discord",
                        channel_id=str(message.channel.id),
                        user_id=str(message.author.id),
                        user_name=message.author.name,
                        text=message.content,
                        raw_payload={"guild_id": str(message.guild.id) if message.guild else ""},
                    )
                    self._record_message(msg)
                    if self._handler:
                        await self._handler(msg)

                import threading
                t = threading.Thread(
                    target=lambda: asyncio.run(self._client.start(self.bot_token)),
                    daemon=True
                )
                t.start()
                return True
            except ImportError:
                logger.warning("discord.py not installed, using webhook-only mode")
                self._connected = True
                self.status.connected = True
                return True
        except Exception as e:
            self._record_error(str(e))
            return False

    async def disconnect(self):
        if self._client:
            await self._client.close()
        self._connected = False
        self.status.connected = False

    async def send_message(self, channel_id: str, text: str,
                           thread_id: str = "") -> bool:
        if self._client and self._connected:
            try:
                channel = self._client.get_channel(int(channel_id))
                if channel:
                    await channel.send(text[:2000])
                    self._record_sent()
                    return True
            except Exception as e:
                self._record_error(str(e))

        # Fallback: webhook
        webhook = self.config.get("webhook_url", "")
        if webhook:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    payload = {"content": text[:2000]}
                    async with session.post(webhook, json=payload) as resp:
                        ok = resp.status in (200, 204)
                        if ok:
                            self._record_sent()
                        return ok
            except Exception as e:
                self._record_error(str(e))
        return False


# ── WhatsApp Connector ──────────────────────────────────────


class WhatsAppConnector(BaseConnector):
    """WhatsApp Cloud API connector.

    Requires:
    - WHATSAPP_TOKEN
    - WHATSAPP_PHONE_ID
    - WHATSAPP_VERIFY_TOKEN (for webhook verification)
    """

    platform = "whatsapp"
    API_BASE = "https://graph.facebook.com/v18.0"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.token = self.config.get("token") or os.environ.get("WHATSAPP_TOKEN", "")
        self.phone_id = self.config.get("phone_id") or os.environ.get("WHATSAPP_PHONE_ID", "")
        self.verify_token = self.config.get("verify_token") or os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
        self._webhook_handler = None

    async def connect(self) -> bool:
        if not self.token or not self.phone_id:
            self._record_error("Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_ID")
            return False
        self._connected = True
        self.status.connected = True
        return True

    async def disconnect(self):
        self._connected = False
        self.status.connected = False

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verify WhatsApp webhook subscription."""
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None

    def handle_webhook(self, body: dict) -> List[GatewayMessage]:
        """Parse incoming WhatsApp webhook payload."""
        messages = []
        try:
            entries = body.get("entry", [])
            for entry in entries:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        gm = GatewayMessage(
                            platform="whatsapp",
                            channel_id=msg.get("from", ""),
                            user_id=msg.get("from", ""),
                            user_name=value.get("contacts", [{}])[0].get("profile", {}).get("name", ""),
                            text=msg.get("text", {}).get("body", ""),
                            raw_payload=msg,
                        )
                        messages.append(gm)
                        self._record_message(gm)
                        if self._handler:
                            asyncio.create_task(self._handler(gm))
        except Exception as e:
            self._record_error(str(e))
        return messages

    async def send_message(self, channel_id: str, text: str,
                           thread_id: str = "") -> bool:
        """Send WhatsApp message via Cloud API."""
        if not self._connected:
            return False
        try:
            import aiohttp
            url = f"{self.API_BASE}/{self.phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": channel_id,
                "type": "text",
                "text": {"body": text[:4096]},
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    ok = resp.status in (200, 201)
                    if ok:
                        self._record_sent()
                    else:
                        body = await resp.text()
                        self._record_error(f"WhatsApp {resp.status}: {body[:200]}")
                    return ok
        except Exception as e:
            self._record_error(str(e))
            return False


# ── Gateway Manager ─────────────────────────────────────────


class GatewayManager:
    """Central manager for all platform connectors."""

    def __init__(self):
        self.connectors: Dict[str, BaseConnector] = {}
        self._agent_handler: Optional[Callable] = None

    def on_agent_message(self, handler: Callable[[GatewayMessage], Any]):
        """Set the handler that processes messages through the AI agent."""
        self._agent_handler = handler
        for conn in self.connectors.values():
            conn.on_message(handler)

    def add_connector(self, connector: BaseConnector) -> bool:
        """Add and connect a platform connector."""
        platform = connector.platform
        if platform in self.connectors:
            logger.warning(f"Connector {platform} already exists, replacing")
        self.connectors[platform] = connector
        if self._agent_handler:
            connector.on_message(self._agent_handler)
        return True

    async def start_all(self) -> Dict[str, bool]:
        """Connect all registered connectors."""
        results = {}
        for platform, conn in self.connectors.items():
            results[platform] = await conn.connect()
        return results

    async def stop_all(self):
        """Disconnect all connectors."""
        for conn in self.connectors.values():
            await conn.disconnect()

    def get_status(self) -> List[Dict]:
        """Get status of all connectors."""
        return [
            {
                "platform": c.platform,
                "connected": c.status.connected,
                "messages_received": c.status.messages_received,
                "messages_sent": c.status.messages_sent,
                "errors": c.status.errors,
                "last_error": c.status.last_error,
            }
            for c in self.connectors.values()
        ]

    async def send_to_platform(self, platform: str, channel_id: str,
                               text: str) -> bool:
        """Send message to a specific platform."""
        conn = self.connectors.get(platform)
        if not conn:
            return False
        return await conn.send_message(channel_id, text)

    async def broadcast(self, text: str, platforms: List[str] = None):
        """Broadcast message to multiple platforms."""
        results = {}
        targets = platforms or list(self.connectors.keys())
        for platform in targets:
            conn = self.connectors.get(platform)
            if conn and conn.status.connected:
                # Broadcast to a default channel if configured
                channel = conn.config.get("default_channel", "")
                if channel:
                    results[platform] = await conn.send_message(channel, text)
        return results

    async def handle_whatsapp_webhook(self, query_params: dict, body: dict) -> dict:
        """Handle WhatsApp webhook verification + messages."""
        wa = self.connectors.get("whatsapp")
        if not wa or not isinstance(wa, WhatsAppConnector):
            return {"status": "error", "message": "WhatsApp not configured"}

        # Webhook verification
        mode = query_params.get("hub.mode", "")
        token = query_params.get("hub.verify_token", "")
        challenge = query_params.get("hub.challenge", "")
        if mode and token and challenge:
            result = wa.verify_webhook(mode, token, challenge)
            return {"challenge": result} if result else {"status": "verification_failed"}

        # Message handling
        messages = wa.handle_webhook(body)
        return {"status": "ok", "messages_processed": len(messages)}


# ── Singleton ───────────────────────────────────────────────

_global_gateway: Optional[GatewayManager] = None


def get_gateway() -> GatewayManager:
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = GatewayManager()
    return _global_gateway

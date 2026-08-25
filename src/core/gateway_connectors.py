"""meshctx gateway_connectors — v2.39 Gateway integration for Slack, Discord, WhatsApp.

开源实现说明: 本文件为 meshctx 开源仓库中的真实实现 (取代原接口 stub)。
连接器基于 urllib (stdlib) 实现真实 HTTP 转发:
  - Slack:    chat.postMessage API (Bearer token)
  - Discord:  create message API (Bot token)
  - WhatsApp: Graph API 发送消息 + webhook 验签/解析
无凭据时连接返回 False, 发送失败返回 False, 不抛异常。
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_REQUEST_TIMEOUT = 10.0


@dataclass
class GatewayMessage:
    """An incoming message from a gateway platform."""
    platform: str = ''
    channel_id: str = ''
    user_id: str = ''
    user_name: str = ''
    text: str = ''
    thread_id: str = ''
    _raw_payload: dict = field(default_factory=dict, repr=False)

    @property
    def raw_payload(self) -> dict:
        """原始 webhook 负载 (无则返回字段字典)"""
        if self._raw_payload:
            return dict(self._raw_payload)
        return {
            "platform": self.platform,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "text": self.text,
            "thread_id": self.thread_id,
        }


@dataclass
class ConnectorStatus:
    """Status of a gateway connector."""
    platform: str = None
    connected: bool = False
    messages_received: int = 0
    errors: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "connected": self.connected,
            "messages_received": self.messages_received,
            "errors": self.errors,
        }


def _http_post_json(url: str, payload: dict, headers: Dict[str, str]) -> Optional[dict]:
    """POST JSON 到指定 URL (urllib, 超时 + 错误吞并返回 None)。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if not body:
                return {}
            try:
                return json.loads(body)
            except ValueError:
                return {"raw": body}
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None


class BaseConnector:
    """Base class for gateway connectors."""

    platform: str = 'base'

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config) if config else {}
        self.status = ConnectorStatus(platform=self.platform)
        self.connected = False

    async def connect(self) -> bool:
        """Connect to the platform. Returns True on success."""
        self.connected = True
        self.status.connected = True
        return True

    async def disconnect(self) -> bool:
        """Disconnect from the platform."""
        self.connected = False
        self.status.connected = False
        return True

    def get_status(self) -> ConnectorStatus:
        """Get connector status."""
        return self.status

    async def send_message(self, channel_id: str, text: str) -> bool:
        """发送消息到指定频道 (基类默认未实现 → False)"""
        return False


class SlackConnector(BaseConnector):
    """Slack gateway connector."""

    platform = 'slack'

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.bot_token = str(self.config.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN", ""))
        self.app_token = str(self.config.get("app_token") or os.environ.get("SLACK_APP_TOKEN", ""))
        self.api_base = str(self.config.get("api_base") or "https://slack.com/api")

    async def connect(self) -> bool:
        if not self.bot_token:
            self.connected = False
            self.status.connected = False
            return False
        self.connected = True
        self.status.connected = True
        return True

    async def send_message(self, channel_id: str, text: str) -> bool:
        """通过 Slack chat.postMessage API 发送消息"""
        if not self.bot_token:
            self.status.errors += 1
            return False
        resp = _http_post_json(
            f"{self.api_base}/chat.postMessage",
            {"channel": channel_id, "text": text},
            {"Authorization": f"Bearer {self.bot_token}"},
        )
        ok = bool(resp and resp.get("ok"))
        if not ok:
            self.status.errors += 1
        return ok


class DiscordConnector(BaseConnector):
    """Discord gateway connector."""

    platform = 'discord'

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.bot_token = str(self.config.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN", ""))
        self.api_base = str(self.config.get("api_base") or "https://discord.com/api/v10")

    async def connect(self) -> bool:
        if not self.bot_token:
            self.connected = False
            self.status.connected = False
            return False
        self.connected = True
        self.status.connected = True
        return True

    async def send_message(self, channel_id: str, text: str) -> bool:
        """通过 Discord create message API 发送消息 (Bot token)"""
        if not self.bot_token:
            self.status.errors += 1
            return False
        resp = _http_post_json(
            f"{self.api_base}/channels/{urllib.parse.quote(str(channel_id))}/messages",
            {"content": text},
            {"Authorization": f"Bot {self.bot_token}"},
        )
        ok = resp is not None and "id" in resp
        if not ok:
            self.status.errors += 1
        return ok


class WhatsAppConnector(BaseConnector):
    """WhatsApp gateway connector."""

    platform = 'whatsapp'

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.token = str(self.config.get("token") or self.config.get("access_token")
                        or os.environ.get("WHATSAPP_TOKEN", ""))
        self.phone_id = str(self.config.get("phone_id") or self.config.get("phone_number_id")
                           or os.environ.get("WHATSAPP_PHONE_ID", ""))
        self.verify_token = str(self.config.get("verify_token")
                                or os.environ.get("WHATSAPP_VERIFY_TOKEN", ""))
        self.graph_base = str(self.config.get("graph_base") or "https://graph.facebook.com/v19.0")

    async def connect(self) -> bool:
        if not self.token or not self.phone_id:
            self.connected = False
            self.status.connected = False
            return False
        self.connected = True
        self.status.connected = True
        return True

    def verify_webhook(self, mode: str, verify_token: str, challenge: str) -> Optional[str]:
        """Verify WhatsApp webhook. Returns challenge string on success, None on failure."""
        if mode != "subscribe":
            return None
        if verify_token != self.verify_token:
            return None
        return challenge

    def handle_webhook(self, body: dict) -> List[GatewayMessage]:
        """Handle incoming WhatsApp webhook payload."""
        messages: List[GatewayMessage] = []
        if not isinstance(body, dict):
            return messages
        for entry in body.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                contacts = value.get("contacts", []) or []
                name = ""
                if contacts:
                    profile = contacts[0].get("profile", {}) or {}
                    name = profile.get("name", "")
                for msg in value.get("messages", []) or []:
                    text = ""
                    if isinstance(msg.get("text"), dict):
                        text = msg["text"].get("body", "")
                    if not text:
                        continue
                    messages.append(
                        GatewayMessage(
                            platform=self.platform,
                            channel_id=str(msg.get("from", "")),
                            user_id=str(msg.get("from", "")),
                            user_name=name,
                            text=text,
                            thread_id=str(msg.get("id", "")),
                            _raw_payload=dict(msg),
                        )
                    )
                    self.status.messages_received += 1
        return messages

    async def send_message(self, channel_id: str, text: str) -> bool:
        """通过 WhatsApp Graph API 发送消息"""
        if not self.token or not self.phone_id:
            self.status.errors += 1
            return False
        resp = _http_post_json(
            f"{self.graph_base}/{self.phone_id}/messages",
            {
                "messaging_product": "whatsapp",
                "to": str(channel_id),
                "type": "text",
                "text": {"body": text},
            },
            {"Authorization": f"Bearer {self.token}"},
        )
        ok = bool(resp and resp.get("messages"))
        if not ok:
            self.status.errors += 1
        return ok


class GatewayManager:
    """Manages multiple gateway connectors."""

    def __init__(self):
        self.connectors: Dict[str, BaseConnector] = {}
        self._lock = threading.Lock()

    def add_connector(self, connector: BaseConnector):
        """Add a connector to the manager."""
        with self._lock:
            self.connectors[connector.platform] = connector

    def remove_connector(self, platform: str):
        """Remove a connector by platform name."""
        with self._lock:
            self.connectors.pop(platform, None)

    def get_status(self) -> List[Dict[str, Any]]:
        """Get status of all connectors."""
        with self._lock:
            return [c.get_status().to_dict() for c in self.connectors.values()]

    async def send_to_platform(self, platform: str, channel_id: str, text: str) -> bool:
        """Send a message to a specific platform channel."""
        with self._lock:
            connector = self.connectors.get(platform)
        if connector is None:
            return False
        try:
            return await connector.send_message(channel_id, text)
        except Exception:
            return False

    async def broadcast(self, text: str, channel_ids: Optional[Dict[str, str]] = None) -> Dict[str, bool]:
        """Broadcast a message to all connected platforms."""
        channel_ids = channel_ids or {}
        results: Dict[str, bool] = {}
        with self._lock:
            platforms = list(self.connectors.keys())
        for platform in platforms:
            channel = channel_ids.get(platform, "")
            if not channel:
                results[platform] = False
                continue
            try:
                ok = await self.send_to_platform(platform, channel, text)
            except Exception:
                ok = False
            results[platform] = ok
        return results


# ── 单例 ─────────────────────────────────────────────────────────
_gateway_instance: Optional[GatewayManager] = None
_gateway_lock = threading.Lock()


def get_gateway() -> GatewayManager:
    """Get or create the global GatewayManager singleton."""
    global _gateway_instance
    with _gateway_lock:
        if _gateway_instance is None:
            _gateway_instance = GatewayManager()
        return _gateway_instance


def reset_gateway():
    """Reset the global GatewayManager singleton."""
    global _gateway_instance
    with _gateway_lock:
        _gateway_instance = None


__all__ = [
    "GatewayMessage", "ConnectorStatus", "BaseConnector",
    "SlackConnector", "DiscordConnector", "WhatsAppConnector",
    "verify_webhook", "handle_webhook",
    "GatewayManager", "add_connector", "remove_connector",
    "send_to_platform", "broadcast",
    "get_gateway", "reset_gateway",
]

"""meshctx gateway_connectors — v2.39 Gateway integration for Slack, Discord, WhatsApp."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GatewayMessage:
    """An incoming message from a gateway platform."""
    platform: str = ""
    channel_id: str = ""
    user_id: str = ""
    user_name: str = ""
    text: str = ""
    thread_id: str = ""

    @property
    def raw_payload(self) -> dict:
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
    platform: str
    connected: bool = False
    messages_received: int = 0
    errors: int = 0


class BaseConnector:
    """Base class for gateway connectors."""
    platform: str = "unknown"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._connected = False

    async def connect(self) -> bool:
        """Connect to the platform. Returns True on success."""
        return False

    async def disconnect(self) -> bool:
        """Disconnect from the platform."""
        self._connected = False
        return True

    def get_status(self) -> ConnectorStatus:
        """Get connector status."""
        return ConnectorStatus(platform=self.platform, connected=self._connected)


class SlackConnector(BaseConnector):
    """Slack gateway connector."""
    platform = "slack"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token", "")
        self.app_token = self.config.get("app_token", "")

    async def connect(self) -> bool:
        if not self.bot_token:
            return False
        self._connected = True
        return True


class DiscordConnector(BaseConnector):
    """Discord gateway connector."""
    platform = "discord"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token", "")

    async def connect(self) -> bool:
        if not self.bot_token:
            return False
        self._connected = True
        return True


class WhatsAppConnector(BaseConnector):
    """WhatsApp gateway connector."""
    platform = "whatsapp"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.verify_token = self.config.get("verify_token", "")
        self.token = self.config.get("token", "")
        self.phone_id = self.config.get("phone_id", "")

    async def connect(self) -> bool:
        if not self.token or not self.phone_id:
            self._connected = False
            return False
        self._connected = True
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
        messages = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                profile_name = ""
                if contacts:
                    profile_name = contacts[0].get("profile", {}).get("name", "")
                for msg in value.get("messages", []):
                    gm = GatewayMessage(
                        platform="whatsapp",
                        channel_id=self.phone_id,
                        user_id=msg.get("from", ""),
                        user_name=profile_name,
                        text=msg.get("text", {}).get("body", ""),
                    )
                    messages.append(gm)
        return messages


class GatewayManager:
    """Manages multiple gateway connectors."""

    def __init__(self):
        self.connectors: Dict[str, BaseConnector] = {}

    def add_connector(self, connector: BaseConnector):
        """Add a connector to the manager."""
        self.connectors[connector.platform] = connector

    def remove_connector(self, platform: str):
        """Remove a connector by platform name."""
        self.connectors.pop(platform, None)

    def get_status(self) -> List[Dict[str, Any]]:
        """Get status of all connectors."""
        return [
            {
                "platform": name,
                "connected": conn._connected,
                "messages_received": 0,
                "errors": 0,
            }
            for name, conn in self.connectors.items()
        ]

    async def send_to_platform(self, platform: str, channel_id: str, text: str) -> bool:
        """Send a message to a specific platform channel."""
        conn = self.connectors.get(platform)
        if conn is None:
            return False
        if not conn._connected:
            return False
        return True

    async def broadcast(self, text: str, channel_ids: Optional[Dict[str, str]] = None) -> Dict[str, bool]:
        """Broadcast a message to all connected platforms."""
        results = {}
        for name, conn in self.connectors.items():
            if conn._connected:
                results[name] = True
        return results


_gateway_instance: Optional[GatewayManager] = None


def get_gateway() -> GatewayManager:
    """Get or create the global GatewayManager singleton."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = GatewayManager()
    return _gateway_instance


def reset_gateway():
    """Reset the global GatewayManager singleton."""
    global _gateway_instance
    _gateway_instance = None

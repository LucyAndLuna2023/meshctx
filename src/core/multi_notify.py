"""
MeshCtx Multi-Channel Notifier — Telegram/Discord/Slack
=========================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Send notifications to multiple platforms via webhook.
"""
import json
import urllib.request
import urllib.error
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send messages via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str):
        self.token = bot_token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{bot_token}"

    def send(self, text: str) -> bool:
        try:
            url = f"{self.base}/sendMessage"
            data = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }).encode()
            req = urllib.request.Request(url, data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("ok", False)
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False


class DiscordNotifier:
    """Send messages via Discord Webhook."""

    def __init__(self, webhook_url: str):
        self.url = webhook_url

    def send(self, text: str, username: str = "MeshCtx") -> bool:
        try:
            data = json.dumps({
                "content": text,
                "username": username,
            }).encode()
            req = urllib.request.Request(self.url, data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception as e:
            logger.error(f"Discord send failed: {e}")
            return False

    def send_embed(self, title: str, description: str, color: int = 0x8b5cf6) -> bool:
        try:
            data = json.dumps({
                "embeds": [{"title": title, "description": description, "color": color}],
            }).encode()
            req = urllib.request.Request(self.url, data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception as e:
            logger.error(f"Discord embed failed: {e}")
            return False


class SlackNotifier:
    """Send messages via Slack Webhook."""

    def __init__(self, webhook_url: str):
        self.url = webhook_url

    def send(self, text: str) -> bool:
        try:
            data = json.dumps({"text": text}).encode()
            req = urllib.request.Request(self.url, data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False


class MultiNotifier:
    """Send to all configured notification channels at once."""

    def __init__(self):
        self.telegram: Optional[TelegramNotifier] = None
        self.discord: Optional[DiscordNotifier] = None
        self.slack: Optional[SlackNotifier] = None

    def configure(self, channel: str, **kwargs):
        if channel == "telegram":
            self.telegram = TelegramNotifier(kwargs.get("token", ""), kwargs.get("chat_id", ""))
        elif channel == "discord":
            self.discord = DiscordNotifier(kwargs.get("webhook_url", ""))
        elif channel == "slack":
            self.slack = SlackNotifier(kwargs.get("webhook_url", ""))

    def broadcast(self, text: str) -> Dict[str, bool]:
        results = {}
        if self.telegram:
            results["telegram"] = self.telegram.send(text)
        if self.discord:
            results["discord"] = self.discord.send(text)
        if self.slack:
            results["slack"] = self.slack.send(text)
        return results


_multi = MultiNotifier()


def get_multi_notifier() -> MultiNotifier:
    return _multi

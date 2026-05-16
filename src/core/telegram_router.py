"""
MeshCtx Telegram Bot Router — Learn from OpenWork
====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Telegram Bot integration with multi-bot support per workspace.
Inspired by OpenWork's opencode-router.json Telegram channels.
"""
import json
import urllib.request
import urllib.error
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


@dataclass
class TgBot:
    """Telegram Bot configuration."""
    id: str = ""
    token: str = ""
    name: str = "MeshCtxBot"
    enabled: bool = True
    workspace: str = "default"
    access: str = "private"  # private, group, public
    last_poll: float = 0
    update_offset: int = 0
    commands: List[str] = field(default_factory=lambda: ["/stats", "/help", "/chat"])

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name,
            "enabled": self.enabled, "workspace": self.workspace,
            "access": self.access, "commands": self.commands,
        }


class TelegramRouter:
    """Multi-bot Telegram router (learned from OpenWork)."""

    def __init__(self):
        self.bots: Dict[str, TgBot] = {}

    def add_bot(self, bot_id: str, token: str, name: str = "MeshCtxBot",
                workspace: str = "default") -> TgBot:
        bot = TgBot(id=bot_id, token=token, name=name, workspace=workspace)
        self.bots[bot_id] = bot
        return bot

    def remove_bot(self, bot_id: str):
        self.bots.pop(bot_id, None)

    def get_bot(self, bot_id: str) -> Optional[TgBot]:
        return self.bots.get(bot_id)

    def list_bots(self) -> List[Dict]:
        return [b.to_dict() for b in self.bots.values()]

    def send_message(self, bot_id: str, chat_id: str, text: str,
                     parse_mode: str = "Markdown") -> bool:
        """Send message via a specific bot."""
        bot = self.bots.get(bot_id)
        if not bot or not bot.enabled:
            return False

        try:
            url = f"{TELEGRAM_API}/bot{bot.token}/sendMessage"
            data = json.dumps({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }).encode()
            req = urllib.request.Request(url, data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
                return result.get("ok", False)
        except Exception as e:
            logger.error(f"Telegram send via {bot_id}: {e}")
            return False

    def poll_updates(self, bot_id: str) -> List[Dict]:
        """Poll for new messages from a bot."""
        bot = self.bots.get(bot_id)
        if not bot or not bot.enabled:
            return []

        try:
            url = f"{TELEGRAM_API}/bot{bot.token}/getUpdates"
            params = f"?offset={bot.update_offset + 1}&timeout=10"
            req = urllib.request.Request(url + params)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())

            updates = []
            for upd in data.get("result", []):
                upd_id = upd.get("update_id", 0)
                if upd_id > bot.update_offset:
                    bot.update_offset = upd_id
                msg = upd.get("message", {})
                if msg:
                    updates.append({
                        "chat_id": str(msg.get("chat", {}).get("id", "")),
                        "text": msg.get("text", ""),
                        "from": msg.get("from", {}).get("first_name", ""),
                        "date": msg.get("date", 0),
                    })

            bot.last_poll = time.time()
            return updates
        except Exception as e:
            logger.debug(f"Telegram poll {bot_id}: {e}")
            return []

    def broadcast(self, text: str, chat_ids: List[str] = None) -> Dict[str, bool]:
        """Broadcast message to all enabled bots."""
        results = {}
        for bot_id, bot in self.bots.items():
            if bot.enabled:
                targets = chat_ids or []
                if not targets:
                    continue
                for cid in targets:
                    key = f"{bot_id}:{cid}"
                    results[key] = self.send_message(bot_id, cid, text)
        return results


# Global
_router = TelegramRouter()


def get_telegram_router() -> TelegramRouter:
    return _router

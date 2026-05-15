"""
MeshCtx Feishu Notification — Lark/Feishu Webhook Integration
===============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Push real-time notifications to Feishu (Lark) groups via webhook.
Supports: Card messages, text messages, event-driven notifications.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Optional, Dict, Any, List
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────
FEISHU_WEBHOOK_BASE = "https://open.feishu.cn/open-apis/bot/v2/hook"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
RATE_LIMIT_INTERVAL = 1.0  # minimum seconds between sends


class FeishuNotifier:
    """Feishu/Lark webhook notification sender."""

    def __init__(self, webhook_url: str, secret: str = ""):
        """
        Args:
            webhook_url: Full webhook URL from Feishu bot (https://open.feishu.cn/open-apis/bot/v2/hook/xxx)
            secret: Optional signing secret for security verification
        """
        self.webhook_url = webhook_url
        self.secret = secret
        self._last_send = 0.0

    def _sign(self, timestamp: int) -> str:
        """Generate HMAC-SHA256 signature if secret is configured."""
        if not self.secret:
            return ""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        )
        return hmac_code.digest().hex()

    async def send_text(self, text: str) -> bool:
        """
        Send a text message to Feishu.

        Args:
            text: Plain text content (supports Markdown-like formatting)

        Returns:
            True if successful
        """
        payload = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        return await self._send(payload)

    async def send_card(self, title: str, content: str,
                        color: str = "blue", buttons: Optional[List[Dict]] = None) -> bool:
        """
        Send an interactive card message.

        Args:
            title: Card title
            content: Card body (supports Feishu markdown)
            color: Card color (blue, green, red, yellow, purple)
            buttons: Optional list of {title, url} button dicts

        Returns:
            True if successful
        """
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color
            },
            "elements": [
                {"tag": "markdown", "content": content}
            ]
        }

        if buttons:
            actions = []
            for btn in buttons:
                actions.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": btn.get("title", "Open")},
                    "type": "primary" if btn.get("primary") else "default",
                    "url": btn.get("url", ""),
                })
            card["elements"].append({"tag": "action", "actions": actions})

        payload = {
            "msg_type": "interactive",
            "card": card
        }
        return await self._send(payload)

    async def send_deploy_notification(self, version: str, status: str,
                                        details: str = "", test_count: int = 0) -> bool:
        """Send a structured deploy notification card."""
        status_emoji = {"success": "✅", "failed": "❌", "building": "🔄", "deploying": "🚀"}
        status_color = {"success": "green", "failed": "red", "building": "blue", "deploying": "purple"}
        emoji = status_emoji.get(status, "📋")
        clr = status_color.get(status, "blue")

        content = f"**MeshCtx {version}**\n\n"
        content += f"{emoji} 状态: **{status.upper()}**\n"
        if test_count:
            content += f"🧪 测试: {test_count} passed\n"
        if details:
            content += f"\n{details}\n"

        content += f"\n🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"

        buttons = [
            {"title": "GitHub", "url": "https://github.com/LucyAndLuna2023/meshctx", "primary": True},
            {"title": "官网", "url": "https://meshctx.com"},
        ]

        return await self.send_card(
            title=f"MeshCtx {version} {emoji}",
            content=content,
            color=clr,
            buttons=buttons,
        )

    async def send_health_report(self, metrics: Dict[str, Any]) -> bool:
        """Send a health monitoring report."""
        content = "**🫀 系统健康报告**\n\n"
        for key, value in metrics.items():
            content += f"- **{key}**: {value}\n"
        content += f"\n🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"

        return await self.send_card(
            title="🫀 MeshCtx 健康报告",
            content=content,
            color="blue",
        )

    async def _send(self, payload: Dict[str, Any]) -> bool:
        """Send payload to Feishu webhook with retry logic."""
        # Rate limiting
        elapsed = time.time() - self._last_send
        if elapsed < RATE_LIMIT_INTERVAL:
            await asyncio.sleep(RATE_LIMIT_INTERVAL - elapsed)

        # Add signature if configured
        if self.secret:
            timestamp = int(time.time())
            sign = self._sign(timestamp)
            payload["timestamp"] = str(timestamp)
            payload["sign"] = sign

        data = json.dumps(payload).encode("utf-8")

        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    self.webhook_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    code = result.get("code", -1)
                    msg = result.get("msg", "")

                    if code == 0:
                        self._last_send = time.time()
                        logger.info(f"Feishu通知已发送: {msg}")
                        return True
                    else:
                        logger.error(f"Feishu发送失败 (attempt {attempt+1}): code={code} msg={msg}")
                        if code == 19001:  # Invalid token
                            return False  # Don't retry on auth errors

            except urllib.error.HTTPError as e:
                logger.error(f"Feishu HTTP错误 (attempt {attempt+1}): {e.code} {e.reason}")
            except Exception as e:
                logger.error(f"Feishu发送异常 (attempt {attempt+1}): {e}")

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        return False


# ─── Synchronous helpers (for non-async contexts) ─────────

def send_text_sync(webhook_url: str, text: str, secret: str = "") -> bool:
    """Synchronous text send (for cron/background tasks)."""
    notifier = FeishuNotifier(webhook_url, secret)
    return asyncio.get_event_loop().run_until_complete(notifier.send_text(text)) if asyncio.get_event_loop().is_running() else False


# ─── Integration with MeshCtx event system ────────────────

class FeishuPlugin:
    """MeshCtx plugin for Feishu integration."""

    def __init__(self, webhook_url: str = "", secret: str = ""):
        self.notifier = FeishuNotifier(webhook_url, secret) if webhook_url else None

    def on_deploy(self, version: str, status: str, test_count: int = 0):
        """Called after deploy/version bump."""
        if self.notifier:
            asyncio.create_task(
                self.notifier.send_deploy_notification(version, status,
                                                       test_count=test_count)
            )

    def on_health_report(self, metrics: Dict[str, Any]):
        """Called for periodic health reports."""
        if self.notifier:
            asyncio.create_task(self.notifier.send_health_report(metrics))

    def on_error(self, error_msg: str, module: str = ""):
        """Called on critical errors."""
        if self.notifier:
            text = f"⚠️ **MeshCtx Error**\n模块: {module}\n{error_msg}\n\n🕐 {time.strftime('%H:%M:%S')}"
            asyncio.create_task(self.notifier.send_text(text))

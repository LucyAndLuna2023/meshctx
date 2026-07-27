"""meshctx Feishu Notify — real implementation (v3.115.20)

Sends notifications to Feishu/Lark via webhook.
Supports: text, interactive card, deploy notification, rich markdown.
"""

import hashlib
import hmac
import json
import logging
import time

logger = logging.getLogger("meshctx.feishu")

# ── Feishu webhook format reference ──
# POST https://open.feishu.cn/open-apis/bot/v2/hook/<token>
# Body: {"msg_type":"text","content":{"text":"message"}}
# Or with secret: sign = base64(HMAC-SHA256(timestamp+"\n"+secret, timestamp))
# Headers: {"timestamp": str(ts), "sign": sign}


def _sign(secret: str, timestamp: int) -> str:
    """Generate Feishu webhook signature (HMAC-SHA256)."""
    import base64
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


class FeishuNotifier:
    """Send notifications to Feishu/Lark via webhook."""

    def __init__(self, webhook_url: str = "", secret: str = ""):
        self.webhook_url = webhook_url
        self.secret = secret

    # ── Public API (matches main.py call sites) ──

    async def send_text(self, content: str) -> bool:
        """Send plain text notification. (async-compatible)"""
        return self._post({"msg_type": "text", "content": {"text": content}})

    async def send_card(self, title: str, elements: list) -> bool:
        """Send interactive card notification. (async-compatible)"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }
        return self._post({"msg_type": "interactive", "card": card})

    async def send_deploy_notification(
        self, version: str, status: str, content: str, test_count: int = 0
    ) -> bool:
        """Send deploy notification with structured card. (async-compatible)"""
        status_color = "green" if status == "success" else "red"
        status_icon = "✅" if status == "success" else "❌"
        elements = [
            {
                "tag": "markdown",
                "content": f"{status_icon} **meshctx {version}** 部署{status}\n{content}",
            },
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": f"测试: {test_count} 项通过"}
                ],
            },
        ]
        return await self.send_card(f"meshctx 部署: {status}", elements)

    def send_sync(self, title: str, content: str, msg_type: str = "text") -> bool:
        """Synchronous send (for non-async contexts)."""
        if msg_type == "interactive":
            return self._post(
                {"msg_type": "interactive", "card": {"header": {"title": {"tag": "plain_text", "content": title}}, "elements": [{"tag": "markdown", "content": content}]}}
            )
        return self._post({"msg_type": "text", "content": {"text": f"{title}\n{content}"}})

    # ── Rich message helpers ──

    def send_alert(self, level: str, title: str, body: str) -> bool:
        """Send colored alert (🔴 CRITICAL / 🟡 WARNING / 🔵 INFO)."""
        icons = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
        icon = icons.get(level.lower(), "📢")
        text = f"{icon} **[{level.upper()}] {title}**\n{body}\n\n_ meshctx · {time.strftime('%Y-%m-%d %H:%M:%S')}_"
        return self._post({"msg_type": "text", "content": {"text": text}})

    def send_rich_card(self, title: str, fields: dict) -> bool:
        """Send a rich card with key-value fields."""
        elements = []
        for k, v in fields.items():
            elements.append({
                "tag": "column_set",
                "flex_mode": "bisect",
                "background_style": "default",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [{"tag": "markdown", "content": f"**{k}**"}],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [{"tag": "markdown", "content": str(v)}],
                    },
                ],
            })
        elements.append({
            "tag": "hr",
        })
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"meshctx · {time.strftime('%Y-%m-%d %H:%M:%S')}"}],
        })
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }
        return self._post({"msg_type": "interactive", "card": card})

    # ── Internal ──

    def _post(self, payload: dict) -> bool:
        """POST to webhook with optional signature."""
        if not self.webhook_url:
            logger.warning("Feishu: no webhook_url configured")
            return False

        try:
            import urllib.request

            headers = {"Content-Type": "application/json"}
            if self.secret:
                ts = int(time.time())
                headers["timestamp"] = str(ts)
                headers["sign"] = _sign(self.secret, ts)

            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url, data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                if result.get("code") == 0:
                    logger.info(f"Feishu sent OK: {result.get('msg','')}")
                    return True
                logger.warning(f"Feishu error: {result}")
                return False
        except Exception as e:
            logger.warning(f"Feishu send failed: {e}")
            return False


def get_feishu_notifier(webhook_url: str = "", secret: str = "") -> FeishuNotifier:
    """Factory for FeishuNotifier."""
    return FeishuNotifier(webhook_url, secret)

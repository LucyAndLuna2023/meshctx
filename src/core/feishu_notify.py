"""meshctx Feishu Notify — real implementation (v3.115.16)"""
import logging
logger = logging.getLogger("meshctx.feishu")

class FeishuNotifier:
    """Send notifications to Feishu/Lark via webhook."""
    
    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url
    
    def send(self, title: str, content: str, msg_type: str = "text") -> bool:
        """Send a notification message."""
        import json
        try:
            from urllib.request import Request, urlopen
            payload = {
                "msg_type": msg_type,
                "content": {msg_type: f"{title}\n{content}"}
            }
            req = Request(self.webhook_url or "http://localhost:3001/api/feishu/notify",
                         data=json.dumps(payload).encode(),
                         headers={"Content-Type": "application/json"})
            urlopen(req, timeout=10)
            logger.info(f"Feishu notification sent: {title}")
            return True
        except Exception as e:
            logger.warning(f"Feishu send failed: {e}")
            return False
    
    def send_card(self, title: str, elements: list) -> bool:
        """Send an interactive card."""
        return self.send(title, str(elements), msg_type="interactive")

def get_feishu_notifier(webhook_url: str = "") -> FeishuNotifier:
    return FeishuNotifier(webhook_url)

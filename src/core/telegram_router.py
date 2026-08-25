"""meshctx Telegram Router — real implementation (v3.115.16)"""
import logging
logger = logging.getLogger("meshctx.telegram")

class TelegramRouter:
    """Route messages and commands through Telegram Bot API."""
    
    def __init__(self, bot_token: str = ""):
        self.bot_token = bot_token
        self._handlers = {}
    
    def register_command(self, command: str, handler):
        """Register a command handler. e.g., /start, /help."""
        self._handlers[command.lstrip('/')] = handler
    
    def handle_update(self, update: dict) -> dict:
        """Process a Telegram update and route to appropriate handler."""
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        
        if text.startswith('/'):
            cmd = text.split()[0][1:].split('@')[0]
            handler = self._handlers.get(cmd)
            if handler:
                return {"chat_id": chat_id, "text": handler(message), "method": "sendMessage"}
        
        return {"chat_id": chat_id, "text": f"Echo: {text}", "method": "sendMessage"}
    
    def send_message(self, chat_id, text: str) -> dict:
        """Build a sendMessage payload."""
        return {"chat_id": chat_id, "text": text, "method": "sendMessage"}

def get_telegram_router(token: str = "") -> TelegramRouter:
    return TelegramRouter(token)


# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "TgBot":
        return TelegramRouter
    raise AttributeError(name)
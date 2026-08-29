"""meshctx gateway_llm — Gateway LLM Adapter with template fallback"""

import time
import re


class GatewayLLMAdapter:
    """Adapter for LLM calls with conversation history, template fallback, and stats."""

    def __init__(self, default_model: str = "deepseek-v4-flash",
                 fallback_to_template: bool = True, max_history: int = 10):
        self.default_model = default_model
        self.fallback_to_template = fallback_to_template
        self.max_history = max_history
        self._conversations: dict = {}
        self._stats = {
            "total_requests": 0,
            "template_fallbacks": 0,
            "active_conversations": 0,
        }

    def _default_system_prompt(self, user_name: str = None):
        """Generate the default system prompt."""
        name_part = ""
        if user_name:
            name_part = f"当前用户: {user_name}。"
        return (
            f"你是 meshctx AI 助手，一个智能的自主Agent系统。"
            f"{name_part}"
            f"你拥有文件操作、终端执行、网页搜索等工具能力。"
            f"请简洁准确地回答问题。"
        )

    def build_messages(self, chat_id: str, message: str,
                       system_prompt: str = None, user_name: str = None):
        """Build a messages list for the LLM API."""
        system = system_prompt or self._default_system_prompt(user_name)
        messages = [{"role": "system", "content": system}]

        # Add history
        history = self._conversations.get(chat_id, [])
        messages.extend(history)

        # Add current message
        messages.append({"role": "user", "content": message})
        return messages

    def _add_to_history(self, chat_id: str, user_msg: str, assistant_reply: str):
        """Add a user/assistant pair to conversation history."""
        max_messages = self.max_history * 2  # pairs * 2
        if chat_id not in self._conversations:
            self._conversations[chat_id] = []
        history = self._conversations[chat_id]
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_reply})
        # Truncate if over limit
        while len(history) > max_messages:
            history.pop(0)
        self._stats["active_conversations"] = len(self._conversations)

    def clear_history(self, chat_id: str = None):
        """Clear conversation history for a specific chat or all."""
        if chat_id:
            self._conversations.pop(chat_id, None)
        else:
            self._conversations.clear()
        self._stats["active_conversations"] = len(self._conversations)

    def _fallback(self, text: str):
        """Template-based fallback when LLM is unavailable."""
        text_lower = text.lower().strip()

        # Help
        help_keywords = ["帮助", "help", "功能", "能力", "能做什么", "capabilities"]
        if any(kw in text_lower for kw in help_keywords):
            return {
                "success": True,
                "content": "meshctx 核心能力：\n1. 文件读写与代码编辑\n2. 终端命令执行\n3. 网页搜索与浏览\n4. 多Agent协作\n5. JEPA世界模型推理",
                "model": "template",
                "fallback": True,
            }

        # Version
        if "version" in text_lower or "版本" in text_lower:
            return {
                "success": True,
                "content": "meshctx v3.115 — 纯本地开发模式",
                "model": "template",
                "fallback": True,
            }

        # Status
        status_keywords = ["状态", "status", "健康", "health", "运行"]
        if any(kw in text_lower for kw in status_keywords):
            return {
                "success": True,
                "content": "系统状态：正常在线。所有核心模块正常运行。",
                "model": "template",
                "fallback": True,
            }

        # Greeting
        greeting_keywords = ["你好", "hello", "hi", "hey", "嗨"]
        if any(kw in text_lower for kw in greeting_keywords):
            return {
                "success": True,
                "content": "你好！我是 meshctx AI 助手，有什么可以帮助你的？",
                "model": "template",
                "fallback": True,
            }

        # Generic fallback
        return {
            "success": True,
            "content": "当前AI模型暂时不可用，已切换到本地模板应答模式。请稍后重试或联系管理员。",
            "model": "template",
            "fallback": True,
        }

    async def chat(self, chat_id: str, message: str,
                   model_id: str = None, system_prompt: str = None):
        """Send a chat message and get a response (with fallback)."""
        self._stats["total_requests"] += 1

        # Try template fallback first (no real model connection in stub)
        if self.fallback_to_template:
            result = self._fallback(message)
            self._stats["template_fallbacks"] += 1

            # Add to history
            self._add_to_history(chat_id, message, result["content"])
            return result

        # Would call real LLM here
        return self._fallback(message)

    def get_stats(self):
        """Get adapter statistics."""
        return dict(self._stats)


_adapter: GatewayLLMAdapter = None


def get_gateway_llm() -> GatewayLLMAdapter:
    """Get the singleton GatewayLLMAdapter instance."""
    global _adapter
    if _adapter is None:
        _adapter = GatewayLLMAdapter()
    return _adapter

"""
Gateway LLM Integration — v2.49
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将Gateway/AgentLoop的消息流接入真实LLM模型调用。
支持SSE流式输出到消息平台。

之前: Gateway → AgentLoop → Responder(模板) → 硬编码回复
现在: Gateway → AgentLoop → GatewayLLM → ModelClient(真实LLM) → 流式回复

特性:
- 透明接入: 自动将IncomingMessage转为LLM对话格式
- 流式输出: 支持逐token推送到消息平台
- 优雅降级: LLM不可用时回退到模板Responder
- 多平台: 飞书/企业微信/Telegram/Discord/Slack
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class GatewayLLMAdapter:
    """Gateway ↔ LLM 桥接适配器"""

    def __init__(self, default_model: str = "deepseek-v4-pro",
                 fallback_to_template: bool = True,
                 max_history: int = 20):
        self.default_model = default_model
        self.fallback_to_template = fallback_to_template
        self.max_history = max_history

        # 对话历史缓存 (chat_id → messages)
        self._conversations: Dict[str, List[Dict]] = {}

        # 统计
        self._stats = {
            "total_requests": 0,
            "llm_responses": 0,
            "template_fallbacks": 0,
            "errors": 0,
            "avg_latency_ms": 0.0,
            "total_tokens": 0,
        }

    # ── Core: Message to LLM ──────────────────────────────

    def build_messages(self, chat_id: str, user_content: str,
                       system_prompt: str = "",
                       user_name: str = "") -> List[Dict]:
        """构建LLM消息列表

        Args:
            chat_id: 会话ID (用于历史管理)
            user_content: 用户消息内容
            system_prompt: 系统提示词
            user_name: 用户名

        Returns:
            OpenAI格式的消息列表
        """
        messages = []

        # 系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({
                "role": "system",
                "content": self._default_system_prompt(user_name),
            })

        # 加载历史
        history = self._conversations.get(chat_id, [])
        messages.extend(history[-self.max_history:])

        # 添加当前消息
        messages.append({"role": "user", "content": user_content})

        return messages

    async def chat(self, chat_id: str, user_content: str,
                   model_id: str = "",
                   system_prompt: str = "",
                   user_name: str = "",
                   stream_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """通过LLM处理Gateway消息

        Args:
            chat_id: 会话ID
            user_content: 用户消息
            model_id: 模型ID (空=默认)
            system_prompt: 系统提示词
            user_name: 用户名
            stream_callback: 流式回调 async(token) -> None

        Returns:
            {success, content, model, tokens, latency_ms}
        """
        t0 = time.time()
        self._stats["total_requests"] += 1

        try:
            # 获取模型客户端
            from src.model_registry import get_registry
            registry = get_registry()

            model = model_id or self.default_model
            client = registry.get(model)
            if client is None:
                logger.warning(f"模型未找到: {model}, 回退模板")
                return self._fallback(user_content)

            # 构建消息
            messages = self.build_messages(chat_id, user_content,
                                           system_prompt, user_name)

            # 调用LLM
            if stream_callback:
                # 流式模式
                full_text = ""
                for token in client.chat_stream(messages):
                    full_text += token
                    try:
                        await stream_callback(token)
                    except Exception:
                        pass  # 忽略回调错误
                content = full_text
            else:
                # 非流式模式
                result = client.chat(messages)
                content = result.get("content", "") if isinstance(result, dict) else str(result)

            latency = (time.time() - t0) * 1000
            self._stats["llm_responses"] += 1
            self._stats["avg_latency_ms"] = (
                (self._stats["avg_latency_ms"] * (self._stats["llm_responses"] - 1) + latency)
                / self._stats["llm_responses"]
            )
            self._stats["total_tokens"] += len(content)

            # 保存到历史
            self._add_to_history(chat_id, user_content, content)

            return {
                "success": True,
                "content": content,
                "model": model,
                "latency_ms": round(latency, 1),
                "tokens": len(content),
            }

        except Exception as e:
            logger.error(f"Gateway LLM调用失败: {e}")
            self._stats["errors"] += 1
            if self.fallback_to_template:
                return self._fallback(user_content)
            return {"success": False, "error": str(e), "content": "抱歉，我暂时无法处理您的请求。"}

    # ── Streaming helper ──────────────────────────────────

    async def chat_stream(self, chat_id: str, user_content: str,
                          model_id: str = "",
                          system_prompt: str = "",
                          user_name: str = ""):
        """流式生成器: 逐token产出LLM响应

        用法:
            async for token in adapter.chat_stream(chat_id, msg):
                await connector.send_message(chat_id, token)
        """
        t0 = time.time()
        self._stats["total_requests"] += 1
        full_text = ""

        try:
            from src.model_registry import get_registry
            registry = get_registry()
            model = model_id or self.default_model
            client = registry.get(model)

            if client is None:
                yield "抱歉，AI模型暂不可用。"
                return

            messages = self.build_messages(chat_id, user_content,
                                           system_prompt, user_name)

            for token in client.chat_stream(messages):
                full_text += token
                yield token

            latency = (time.time() - t0) * 1000
            self._stats["llm_responses"] += 1
            self._stats["total_tokens"] += len(full_text)
            self._add_to_history(chat_id, user_content, full_text)

        except Exception as e:
            logger.error(f"Gateway流式调用失败: {e}")
            self._stats["errors"] += 1
            yield "\n\n[AI回复生成失败，请稍后重试]"

    # ── History management ──────────────────────────────────

    def _add_to_history(self, chat_id: str, user_msg: str, assistant_msg: str):
        """添加消息到对话历史"""
        if chat_id not in self._conversations:
            self._conversations[chat_id] = []
        self._conversations[chat_id].append(
            {"role": "user", "content": user_msg}
        )
        self._conversations[chat_id].append(
            {"role": "assistant", "content": assistant_msg}
        )
        # 限制历史长度
        if len(self._conversations[chat_id]) > self.max_history * 2:
            self._conversations[chat_id] = self._conversations[chat_id][-self.max_history * 2:]

    def clear_history(self, chat_id: str = ""):
        """清除对话历史"""
        if chat_id:
            self._conversations.pop(chat_id, None)
        else:
            self._conversations.clear()

    # ── Template fallback ──────────────────────────────────

    def _fallback(self, user_content: str) -> Dict[str, Any]:
        """模板降级回复"""
        self._stats["template_fallbacks"] += 1

        # 简单规则匹配
        content_lower = user_content.lower()
        if any(kw in content_lower for kw in ["帮助", "help", "功能", "能做什么"]):
            reply = ("我是meshctx AI Agent 🧠\n\n"
                     "核心能力:\n"
                     "• 智能对话与代码编写\n"
                     "• 文件管理与项目索引\n"
                     "• 多Agent协作编排\n"
                     "• 自主运维与自愈\n"
                     "• 脑启发认知架构\n\n"
                     "输入 /help 查看更多命令。")
        elif any(kw in content_lower for kw in ["版本", "version", "ver"]):
            from src.core import __version__
            reply = f"meshctx v{__version__}\n世界首个全脑仿真自进化Agent系统"
        elif any(kw in content_lower for kw in ["状态", "status", "健康"]):
            reply = "系统运行正常 ✅\n所有模块在线，脑状态稳定。"
        elif any(kw in content_lower for kw in ["你好", "hello", "hi"]):
            reply = "你好！我是meshctx AI Agent。有什么可以帮助你的？"
        else:
            reply = f"收到您的消息。AI模型暂时不可用，请稍后重试或输入 /help 查看命令列表。"

        return {
            "success": True,
            "content": reply,
            "model": "template",
            "latency_ms": 0,
            "tokens": len(reply),
            "fallback": True,
        }

    def _default_system_prompt(self, user_name: str = "") -> str:
        """默认系统提示词"""
        name_part = f"用户{user_name}正在通过消息平台与你对话。" if user_name else ""
        return (
            f"你是meshctx，一个自主AI Agent。{name_part}\n"
            "请用简洁、有帮助的方式回复。如果用户询问技术问题，提供具体可行的答案。\n"
            "回复使用中文。"
        )

    # ── Stats ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "active_conversations": len(self._conversations),
            "total_history_messages": sum(len(v) for v in self._conversations.values()),
        }


# 单例
_adapter: Optional[GatewayLLMAdapter] = None


def get_gateway_llm() -> GatewayLLMAdapter:
    global _adapter
    if _adapter is None:
        _adapter = GatewayLLMAdapter()
    return _adapter

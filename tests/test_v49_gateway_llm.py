"""v2.49 Gateway LLM Integration — 测试套件"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.gateway_llm import GatewayLLMAdapter, get_gateway_llm


@pytest.fixture
def adapter():
    return GatewayLLMAdapter(default_model="deepseek-v4-pro",
                              fallback_to_template=True,
                              max_history=10)


class TestBuildMessages:
    """消息构建"""

    def test_build_messages_with_system(self, adapter):
        msgs = adapter.build_messages("chat1", "你好", system_prompt="你是助手")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "你是助手"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "你好"

    def test_build_messages_default_system(self, adapter):
        msgs = adapter.build_messages("chat2", "Hello")
        assert msgs[0]["role"] == "system"
        assert "meshctx" in msgs[0]["content"]

    def test_build_messages_with_history(self, adapter):
        # 先添加历史
        adapter._add_to_history("chat3", "之前的问题", "之前的回答")
        msgs = adapter.build_messages("chat3", "新问题")
        # 应包含历史 + 当前消息
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert len(msgs) >= 2

    def test_build_messages_username(self, adapter):
        msgs = adapter.build_messages("chat4", "Hi", user_name="张三")
        assert "张三" in msgs[0]["content"]


class TestFallback:
    """模板降级"""

    def test_fallback_help(self, adapter):
        result = adapter._fallback("帮助")
        assert result["success"]
        assert "核心能力" in result["content"] or "meshctx" in result["content"]
        assert result["model"] == "template"
        assert result["fallback"]

    def test_fallback_version(self, adapter):
        result = adapter._fallback("version")
        assert result["success"]
        assert "meshctx" in result["content"]

    def test_fallback_status(self, adapter):
        result = adapter._fallback("状态")
        assert result["success"]
        assert "正常" in result["content"] or "在线" in result["content"]

    def test_fallback_greeting(self, adapter):
        result = adapter._fallback("你好")
        assert result["success"]
        assert len(result["content"]) > 5

    def test_fallback_generic(self, adapter):
        result = adapter._fallback("随机文本xyzabc")
        assert result["success"]
        assert "AI模型" in result["content"] or "暂时不可用" in result["content"]


class TestHistoryManagement:
    """历史管理"""

    def test_add_to_history(self, adapter):
        adapter._add_to_history("h1", "user msg", "assistant reply")
        history = adapter._conversations.get("h1", [])
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_history_limit(self, adapter):
        """历史应被截断"""
        for i in range(30):  # max_history=10, 所以最多20条消息
            adapter._add_to_history("h2", f"q{i}", f"a{i}")
        history = adapter._conversations["h2"]
        assert len(history) <= 20  # 10对 * 2

    def test_clear_specific_history(self, adapter):
        adapter._add_to_history("h3", "q", "a")
        adapter.clear_history("h3")
        assert "h3" not in adapter._conversations

    def test_clear_all_history(self, adapter):
        adapter._add_to_history("h4", "q", "a")
        adapter._add_to_history("h5", "q", "a")
        adapter.clear_history()
        assert len(adapter._conversations) == 0


class TestChatWithFallback:
    """LLM调用(实际没有真实模型时走降级)"""

    @pytest.mark.asyncio
    async def test_chat_falls_back_when_no_model(self, adapter):
        """没有模型时回退模板"""
        result = await adapter.chat("test_chat", "Hello",
                                     model_id="nonexistent_model")
        assert result["success"]
        assert len(result["content"]) > 0

    @pytest.mark.asyncio
    async def test_chat_tracks_stats(self, adapter):
        await adapter.chat("chat_stats", "test msg")
        assert adapter._stats["total_requests"] >= 1

    @pytest.mark.asyncio
    async def test_chat_default_system_prompt(self, adapter):
        """默认系统提示词应包含meshctx"""
        prompt = adapter._default_system_prompt()
        assert "meshctx" in prompt

    @pytest.mark.asyncio
    async def test_chat_with_username(self, adapter):
        prompt = adapter._default_system_prompt("李四")
        assert "李四" in prompt


class TestStats:
    """统计"""

    @pytest.mark.asyncio
    async def test_stats_tracks_requests(self, adapter):
        for _ in range(3):
            await adapter.chat("stats", "test")
        stats = adapter.get_stats()
        assert stats["total_requests"] == 3
        assert "active_conversations" in stats

    @pytest.mark.asyncio
    async def test_stats_template_fallbacks(self, adapter):
        await adapter.chat("fallback_stats", "帮助")
        stats = adapter.get_stats()
        assert stats["template_fallbacks"] >= 1


class TestEdgeCases:
    """边界条件"""

    def test_empty_message(self, adapter):
        msgs = adapter.build_messages("empty", "")
        assert msgs[-1]["content"] == ""

    def test_long_message(self, adapter):
        long_text = "测试" * 500
        msgs = adapter.build_messages("long", long_text)
        assert len(msgs[-1]["content"]) > 100

    def test_special_characters(self, adapter):
        special = "Hello 👋 世界\n换行\t制表符 <script>alert(1)</script>"
        msgs = adapter.build_messages("special", special)
        assert len(msgs) > 0

    def test_conversation_isolation(self, adapter):
        """不同chat_id的对话应隔离"""
        adapter._add_to_history("isolated_1", "q1", "a1")
        adapter._add_to_history("isolated_2", "q2", "a2")
        assert len(adapter._conversations["isolated_1"]) == 2
        assert len(adapter._conversations["isolated_2"]) == 2


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import gateway_llm
        gateway_llm._adapter = None
        a1 = get_gateway_llm()
        a2 = get_gateway_llm()
        assert a1 is a2

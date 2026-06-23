"""
LLM质量监控 + ACP IDE测试
"""
import pytest
import time


class TestLLMQualityMonitor:
    """LLM调用质量实时监控"""

    def test_record_call_updates_stats(self):
        from src.core.llm_quality import LLMQualityMonitor
        mon = LLMQualityMonitor()
        mon.record_call(
            model="deepseek:v4-pro",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=1200,
            success=True,
        )
        stats = mon.get_stats()
        assert stats["total_calls"] == 1
        assert stats["total_prompt_tokens"] == 100
        assert stats["avg_latency_ms"] > 0

    def test_token_waste_ratio(self):
        """重复输出检测 — 浪费率"""
        from src.core.llm_quality import LLMQualityMonitor
        mon = LLMQualityMonitor()

        # 正常输出
        mon.record_call(prompt_tokens=100, completion_tokens=50, latency_ms=800, success=True)
        # 重复输出 (completion远大于prompt)
        mon.record_call(prompt_tokens=50, completion_tokens=500, latency_ms=3000, success=True)
        mon.record_call(prompt_tokens=50, completion_tokens=450, latency_ms=2900, success=True)

        waste = mon.get_token_waste_ratio()
        assert waste > 0.5  # 大量completion相对prompt是浪费

    def test_error_rate(self):
        from src.core.llm_quality import LLMQualityMonitor
        mon = LLMQualityMonitor()

        for _ in range(7):
            mon.record_call(prompt_tokens=10, completion_tokens=5, latency_ms=100, success=True)
        for _ in range(3):
            mon.record_call(prompt_tokens=10, completion_tokens=0, latency_ms=5000, success=False)

        rate = mon.get_error_rate()
        assert rate == 0.3

    def test_latency_trend(self):
        """延迟趋势检测"""
        from src.core.llm_quality import LLMQualityMonitor
        mon = LLMQualityMonitor(max_history=10)

        # 延迟逐步上升
        for lat in [500, 600, 700, 800, 900, 1000, 1200, 1500, 1800, 2000]:
            mon.record_call(prompt_tokens=10, completion_tokens=5, latency_ms=lat, success=True)

        trend = mon.get_latency_trend()
        assert trend > 0  # 上升趋势


class TestACPProtocol:
    """ACP IDE集成协议"""

    def test_acp_server_initializes(self):
        from src.core.acp_server import ACPServer
        server = ACPServer()
        assert server.protocol_version == "2025-01-01"

    def test_acp_handle_initialize(self):
        from src.core.acp_server import ACPServer
        server = ACPServer()
        result = server.handle_request("initialize", {
            "clientName": "vscode",
            "clientVersion": "1.90.0",
        })
        assert result["serverInfo"]["name"] == "meshctx"

    def test_acp_list_tools(self):
        from src.core.acp_server import ACPServer
        server = ACPServer()
        result = server.handle_request("tools/list", {})
        assert "tools" in result
        tool_names = [t["name"] for t in result["tools"]]
        assert "read_file" in tool_names
        assert "write_file" in tool_names

    def test_acp_ping(self):
        from src.core.acp_server import ACPServer
        server = ACPServer()
        result = server.handle_request("ping", {})
        assert result == {"status": "ok"}

    def test_acp_handle_unknown_method(self):
        from src.core.acp_server import ACPServer
        server = ACPServer()
        result = server.handle_request("unknown/method", {})
        assert "error" in result

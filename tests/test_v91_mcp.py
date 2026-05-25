"""v2.91 MCP Integrator — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mcp():
    from src.core.mcp_integrator import MCPIntegrator
    return MCPIntegrator()


class TestServerRegistration:
    def test_register_server(self, mcp):
        server = mcp.register_server("test-server", "echo", ["hello"])
        assert server.name == "test-server"
        assert server.command == "echo"
        assert "test-server" in mcp._servers

    def test_register_builtin(self, mcp):
        mcp.register_builtin_mcp_servers()
        assert "filesystem" in mcp._servers
        assert "github" in mcp._servers


class TestToolManagement:
    @pytest.mark.asyncio
    async def test_list_tools(self, mcp):
        from src.core.mcp_integrator import MCPTool
        # Add tools directly for testing
        mcp.register_server("test", "echo", ["test"])
        tools = [
            MCPTool(name="read_file", description="Read a file", server_name="test"),
            MCPTool(name="write_file", description="Write a file", server_name="test"),
        ]
        for t in tools:
            mcp._tools[f"test/{t.name}"] = t
        mcp._servers["test"].tools = tools

        result = await mcp.list_tools("test")
        assert len(result) >= 2


class TestCallTool:
    @pytest.mark.asyncio
    async def test_call_tool(self, mcp):
        from src.core.mcp_integrator import MCPTool
        mcp.register_server("test", "echo", ["test"])
        tool = MCPTool(name="read_file", description="Read", server_name="test")
        mcp._tools["test/read_file"] = tool
        mcp._servers["test"].tools = [tool]

        # Should not crash even without real process
        result = await mcp.call_tool("test/read_file", {"path": "/tmp/test"})
        assert result is not None


class TestDiscovery:
    def test_discover_from_nonexistent(self, mcp):
        loaded = mcp.discover_from_config(Path("/nonexistent/mcp.json"))
        assert loaded == 0


class TestStats:
    def test_stats(self, mcp):
        mcp.register_builtin_mcp_servers()
        stats = mcp.get_stats()
        assert stats["mcp_servers"] >= 2
        assert stats["claude_compatible"] is True
        assert stats["cursor_compatible"] is True
        assert stats["protocol"] == "JSON-RPC 2.0"

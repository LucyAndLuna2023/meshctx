"""v3.82 MCP Protocol Standardizer — tests"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.mcp_standardizer import (
    MCPStandardizer,
    MCPToolDef,
    MCPToolResult,
    generate_json_schema_from_func,
    generate_schema_from_dict,
    discover_functions_in_module,
    _py_type_to_json_schema,
    get_mcp_standardizer,
    reset_mcp_standardizer,
)


class TestJSONSchemaGeneration:
    """JSON Schema自动生成测试"""

    def test_py_type_to_json_schema_basic(self):
        assert _py_type_to_json_schema(str) == {"type": "string"}
        assert _py_type_to_json_schema(int) == {"type": "integer"}
        assert _py_type_to_json_schema(float) == {"type": "number"}
        assert _py_type_to_json_schema(bool) == {"type": "boolean"}
        assert _py_type_to_json_schema(list) == {"type": "array", "items": {}}
        assert _py_type_to_json_schema(dict) == {"type": "object"}

    def test_schema_from_simple_func(self):
        def my_tool(query: str, limit: int = 10) -> dict:
            """Search for items"""
            return {"results": []}

        result = generate_json_schema_from_func(my_tool)
        assert result["input_schema"]["type"] == "object"
        assert "query" in result["input_schema"]["properties"]
        assert "limit" in result["input_schema"]["properties"]
        assert result["input_schema"]["required"] == ["query"]
        assert result["input_schema"]["properties"]["query"]["type"] == "string"
        assert result["input_schema"]["properties"]["limit"]["type"] == "integer"
        assert result["input_schema"]["properties"]["limit"]["default"] == 10
        assert result["output_schema"]["type"] == "object"

    def test_schema_from_func_with_descriptions(self):
        def calc(a: int, b: int) -> int:
            """Add two numbers
            :param a: First number
            :param b: Second number
            """
            return a + b

        result = generate_json_schema_from_func(calc)
        assert result["input_schema"]["required"] == ["a", "b"]
        schema_input = result["input_schema"]
        assert "a" in schema_input["properties"]
        assert "b" in schema_input["properties"]

    def test_schema_from_func_no_params(self):
        def ping() -> dict:
            return {"status": "ok"}

        result = generate_json_schema_from_func(ping)
        assert result["input_schema"]["type"] == "object"
        assert result["output_schema"]["type"] == "object"

    def test_schema_from_optional_param(self):
        def read_file(path: str, encoding: str = "utf-8") -> str:
            """Read a file"""
            return ""

        result = generate_json_schema_from_func(read_file)
        assert result["input_schema"]["required"] == ["path"]
        assert "encoding" in result["input_schema"]["properties"]
        assert result["input_schema"]["properties"]["encoding"]["default"] == "utf-8"

    def test_generate_schema_from_dict(self):
        tool_dict = {
            "name": "search",
            "description": "Search files",
            "parameters": {
                "query": {"type": "string", "description": "Search query", "required": True},
                "max_results": {"type": "integer", "default": 10},
                "case_sensitive": {"type": "boolean", "optional": True},
            },
        }
        schema = generate_schema_from_dict(tool_dict)
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["properties"]["query"]["type"] == "string"
        assert "query" in schema["required"]
        assert "case_sensitive" not in schema.get("required", [])

    def test_generate_schema_from_simple_dict(self):
        tool_dict = {
            "name": "echo",
            "parameters": {"msg": "string", "repeat": "integer"},
        }
        schema = generate_schema_from_dict(tool_dict)
        assert schema["properties"]["msg"]["type"] == "string"
        assert schema["properties"]["repeat"]["type"] == "integer"


class TestFunctionDiscovery:
    """函数发现测试"""

    def test_discover_functions_in_module(self):
        path = Path(__file__).parent.parent / "src" / "core" / "sandbox.py"
        if not path.exists():
            pytest.skip("sandbox.py not found")
        funcs = discover_functions_in_module(str(path))
        assert len(funcs) > 0
        names = [f["name"] for f in funcs]
        assert "get_sandbox" in names or "run_python" in names or any("sandbox" in n.lower() for n in names)

    def test_discover_this_module(self):
        # Discover functions in this test file
        # discover_functions_in_module only finds top-level functions (not class methods)
        funcs = discover_functions_in_module(__file__)
        names = [f["name"] for f in funcs]
        assert "test_discover_this_module" not in names  # class methods aren't top-level
        # The discovery should still work without error
        assert isinstance(funcs, list)

    def test_discover_skips_private(self):
        funcs = discover_functions_in_module(__file__)
        names = [f["name"] for f in funcs]
        # Private functions should be skipped
        for name in names:
            assert not name.startswith("_"), f"Private function {name} should be skipped"


class TestMCPStandardizer:
    """MCPStandardizer核心测试"""

    def setup_method(self):
        reset_mcp_standardizer()

    def test_init(self):
        std = MCPStandardizer()
        assert std.SERVER_NAME == "meshctx-mcp-standardizer"
        assert std.SERVER_VERSION == "3.82.0"
        assert std.PROTOCOL_VERSION == "2024-11-05"
        assert len(std._tools) == 0

    def test_register_tool(self):
        std = MCPStandardizer()

        def echo(msg: str) -> str:
            """Echo the message"""
            return msg

        tool = std.register_tool("echo", echo, "Echo tool")
        assert tool.name == "echo"
        assert tool.func is not None
        assert "input_schema" in tool.input_schema or tool.input_schema["type"] == "object"
        assert len(std._tools) == 1

    def test_register_tool_auto_schema(self):
        std = MCPStandardizer()

        def add(a: int, b: int) -> int:
            """Add two integers"""
            return a + b

        tool = std.register_tool("add", add)
        assert tool.input_schema["type"] == "object"
        assert "a" in tool.input_schema["properties"]
        assert "b" in tool.input_schema["properties"]
        assert tool.input_schema["properties"]["a"]["type"] == "integer"
        assert tool.input_schema["required"] == ["a", "b"]

    def test_register_tool_custom_schema(self):
        std = MCPStandardizer()
        custom_input = {
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        }

        def double(x): return x * 2

        tool = std.register_tool("double", double, input_schema=custom_input)
        assert tool.input_schema == custom_input
        assert tool.input_schema["required"] == ["x"]

    def test_register_from_dict(self):
        std = MCPStandardizer()
        tool_dict = {
            "name": "search",
            "description": "Search files",
            "parameters": {
                "query": {"type": "string", "description": "Query string", "required": True},
                "limit": {"type": "integer", "default": 10},
            },
            "category": "filesystem",
            "tags": ["search", "files"],
        }
        tool = std.register_from_dict(tool_dict)
        assert tool.name == "search"
        assert tool.description == "Search files"
        assert tool.category == "filesystem"
        assert tool.tags == ["search", "files"]
        assert tool.input_schema["type"] == "object"
        assert "query" in tool.input_schema["properties"]
        assert tool.func is None  # Dict-based has no callable

    def test_unregister_tool(self):
        std = MCPStandardizer()

        def test(): return True

        std.register_tool("test", test)
        assert len(std._tools) == 1
        assert std.unregister_tool("test") is True
        assert len(std._tools) == 0
        assert std.unregister_tool("nonexistent") is False

    def test_list_tools(self):
        std = MCPStandardizer()

        def tool1(): return 1
        def tool2(): return 2

        std.register_tool("tool1", tool1, category="cat_a")
        std.register_tool("tool2", tool2, category="cat_b")

        tools = std.list_tools()
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "tool1" in names
        assert "tool2" in names

    def test_call_tool_success(self):
        std = MCPStandardizer()

        def greet(name: str = "World") -> str:
            """Greet someone"""
            return f"Hello, {name}!"

        std.register_tool("greet", greet)
        result = std.call_tool("greet", {"name": "Alice"})
        assert result.is_error is False
        assert result.content == "Hello, Alice!"
        assert result.duration_ms >= 0
        assert result.tool_name == "greet"

    def test_call_tool_default_args(self):
        std = MCPStandardizer()

        def greet(name: str = "World") -> str:
            return f"Hello, {name}!"

        std.register_tool("greet", greet)
        result = std.call_tool("greet", {})
        assert result.content == "Hello, World!"

    def test_call_tool_not_found(self):
        std = MCPStandardizer()
        result = std.call_tool("nonexistent", {})
        assert result.is_error is True
        assert "not found" in result.error_message.lower()

    def test_call_tool_no_callable(self):
        std = MCPStandardizer()
        std.register_from_dict({
            "name": "dict_only",
            "description": "Tool without function",
            "parameters": {},
        })
        result = std.call_tool("dict_only", {})
        assert result.is_error is True
        assert "no callable" in result.error_message.lower()

    def test_call_tool_execution_error(self):
        std = MCPStandardizer()

        def failing():
            raise ValueError("Something broke")

        std.register_tool("failing", failing)
        result = std.call_tool("failing", {})
        assert result.is_error is True
        assert "Something broke" in result.error_message

    def test_call_tool_input_validation(self):
        std = MCPStandardizer()

        def require_x(x: int) -> int:
            return x * 2

        std.register_tool("require_x", require_x)
        result = std.call_tool("require_x", {})
        assert result.is_error is True
        assert "Missing required parameter" in result.error_message or "validation" in result.error_message.lower()

    def test_call_tool_type_validation(self):
        std = MCPStandardizer()

        def add(a: int, b: int) -> int:
            return a + b

        std.register_tool("add", add)
        result = std.call_tool("add", {"a": "not_a_number", "b": 1})
        # String for int will fail validation
        assert result.is_error is True

    # ── MCP Protocol Interface ─────────────────────────

    def test_handle_initialize(self):
        std = MCPStandardizer()
        response = std.handle_request("initialize", {
            "clientInfo": {"name": "test-client", "version": "1.0"}
        })
        assert response["protocolVersion"] == "2024-11-05"
        assert response["serverInfo"]["name"] == "meshctx-mcp-standardizer"
        assert "tools" in response["capabilities"]

    def test_handle_list_tools(self):
        std = MCPStandardizer()

        def t1(): return 1
        std.register_tool("t1", t1, "Tool 1")

        response = std.handle_request("tools/list", {})
        assert "tools" in response
        assert len(response["tools"]) == 1
        assert response["tools"][0]["name"] == "t1"
        assert "inputSchema" in response["tools"][0]

    def test_handle_call_tool(self):
        std = MCPStandardizer()

        def echo(msg: str) -> str:
            return msg

        std.register_tool("echo", echo)
        response = std.handle_request("tools/call", {
            "name": "echo",
            "arguments": {"msg": "hello"},
        })
        assert "content" in response
        assert len(response["content"]) == 1
        assert response["content"][0]["text"] == "hello"

    def test_handle_call_tool_error(self):
        std = MCPStandardizer()
        response = std.handle_request("tools/call", {"name": "nonexistent"})
        assert response.get("isError") is True
        assert "not found" in response["content"][0]["text"].lower()

    def test_handle_ping(self):
        std = MCPStandardizer()
        response = std.handle_request("ping", {})
        assert response["status"] == "ok"
        assert "timestamp" in response

    def test_handle_server_info(self):
        std = MCPStandardizer()
        response = std.handle_request("server/info", {})
        assert response["name"] == "meshctx-mcp-standardizer"
        assert response["version"] == "3.82.0"
        assert response["protocol_version"] == "2024-11-05"

    def test_handle_unknown_method(self):
        std = MCPStandardizer()
        response = std.handle_request("unknown/method", {})
        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_handle_notification(self):
        std = MCPStandardizer()
        response = std.handle_request("notifications/initialized", {})
        assert response == {}

    # ── Tool Discovery ──────────────────────────────────

    def test_discover_tools_sandbox_module(self):
        std = MCPStandardizer()
        path = Path(__file__).parent.parent / "src" / "core" / "sandbox.py"
        if not path.exists():
            pytest.skip("sandbox.py not found")
        count = std.discover_tools(str(path))
        assert count > 0
        assert len(std._tools) >= count

    def test_auto_discover_src_core(self):
        std = MCPStandardizer()
        result = std.auto_discover_src_core()
        assert result["discovered_count"] > 0
        assert result["total_tools"] > 0
        assert result["module_count"] > 0
        assert "tools_by_module" in result

    def test_discover_tools_skips_duplicates(self):
        std = MCPStandardizer()
        path = Path(__file__).parent.parent / "src" / "core" / "sandbox.py"
        if not path.exists():
            pytest.skip("sandbox.py not found")
        count1 = std.discover_tools(str(path))
        count2 = std.discover_tools(str(path))
        # Second discovery should not register duplicates
        assert std._stats["tools_registered"] == count1
        assert count2 == 0

    # ── Schema Helpers ─────────────────────────────────

    def test_generate_schema_for_func(self):
        std = MCPStandardizer()

        def process(data: dict, timeout: int = 30) -> dict:
            return {}

        schema = std.generate_schema_for_func(process)
        assert schema["input_schema"]["type"] == "object"
        assert "data" in schema["input_schema"]["properties"]
        assert "timeout" in schema["input_schema"]["properties"]

    def test_get_tool_schema(self):
        std = MCPStandardizer()

        def calc(x: int) -> int:
            return x

        std.register_tool("calc", calc)
        schema = std.get_tool_schema("calc")
        assert schema is not None
        assert schema["name"] == "calc"
        assert "inputSchema" in schema

    def test_get_tool_schema_not_found(self):
        std = MCPStandardizer()
        assert std.get_tool_schema("nonexistent") is None

    # ── Export ─────────────────────────────────────────

    def test_export_tools_as_mcp_config(self):
        std = MCPStandardizer()

        def test_tool(): return True
        std.register_tool("test_tool", test_tool)

        config = std.export_tools_as_mcp_config()
        assert "mcpServers" in config
        assert "meshctx-mcp-standardizer" in config["mcpServers"]
        server_cfg = config["mcpServers"]["meshctx-mcp-standardizer"]
        assert server_cfg["command"] == "python"
        assert "--serve" in server_cfg["args"]

    def test_export_tools_to_file(self, tmp_path):
        std = MCPStandardizer()

        def test_tool(): return True
        std.register_tool("test_tool", test_tool)

        out_path = tmp_path / "mcp_config.json"
        config = std.export_tools_as_mcp_config(str(out_path))
        assert out_path.exists()

        loaded = json.loads(out_path.read_text())
        assert "mcpServers" in loaded

    # ── Stats ──────────────────────────────────────────

    def test_get_stats(self):
        std = MCPStandardizer()

        def t1(): return 1
        std.register_tool("t1", t1, category="cat_a")
        std.register_tool("t2", t1, category="cat_b")

        stats = std.get_stats()
        assert stats["total_tools"] >= 2
        assert "cat_a" in stats["categories"] or stats["total_tools"] >= 2
        assert stats["server_name"] == "meshctx-mcp-standardizer"
        assert stats["protocol"] == "MCP 2024-11-05"

    def test_get_call_history(self):
        std = MCPStandardizer()

        def echo(msg: str) -> str:
            return msg

        std.register_tool("echo", echo)
        std.call_tool("echo", {"msg": "test"})

        history = std.get_call_history()
        assert len(history) >= 1
        assert history[0]["tool"] == "echo"
        assert history[0]["arguments"] == {"msg": "test"}

    def test_get_tool(self):
        std = MCPStandardizer()

        def mytool(): return True
        std.register_tool("mytool", mytool)

        tool = std.get_tool("mytool")
        assert tool is not None
        assert tool.name == "mytool"
        assert std.get_tool("nonexistent") is None

    def test_reset(self):
        std = MCPStandardizer()

        def t(): return True
        std.register_tool("t", t)
        std.call_tool("t", {})

        assert len(std._tools) == 1
        assert std._stats["calls_made"] == 1

        std.reset()
        assert len(std._tools) == 0
        assert std._stats["calls_made"] == 0
        assert std._stats["tools_registered"] == 0
        assert std._stats["schemas_generated"] == 0

    # ── Singleton ──────────────────────────────────────

    def test_singleton(self):
        reset_mcp_standardizer()
        s1 = get_mcp_standardizer()
        s2 = get_mcp_standardizer()
        assert s1 is s2
        reset_mcp_standardizer()

    def test_singleton_reset(self):
        s1 = get_mcp_standardizer()
        reset_mcp_standardizer()
        s2 = get_mcp_standardizer()
        assert s1 is not s2
        reset_mcp_standardizer()

    # ── MCPToolResult ──────────────────────────────────

    def test_tool_result_success(self):
        result = MCPToolResult(content={"data": 42}, tool_name="test")
        assert result.is_error is False
        assert result.content == {"data": 42}

    def test_tool_result_error(self):
        result = MCPToolResult(is_error=True, error_message="Failed")
        assert result.is_error is True
        assert result.error_message == "Failed"


class TestMCPStandardizerIntegration:
    """集成测试 — 模拟MCP客户端交互"""

    def test_full_mcp_interaction(self):
        """模拟完整的MCP客户端交互流程"""
        reset_mcp_standardizer()
        std = MCPStandardizer()

        # Register some tools
        def read_file(path: str) -> str:
            return f"content of {path}"

        def list_dir(path: str = ".") -> list:
            return ["file1.txt", "file2.py"]

        def search(query: str, limit: int = 10) -> list:
            return [f"result for '{query}'"] * min(limit, 5)

        std.register_tool("read_file", read_file, "Read file contents")
        std.register_tool("list_dir", list_dir, "List directory")
        std.register_tool("search", search, "Search files")

        # Step 1: Initialize
        init_resp = std.handle_request("initialize", {
            "clientInfo": {"name": "Claude", "version": "2.0"}
        })
        assert init_resp["protocolVersion"] == "2024-11-05"
        assert init_resp["capabilities"]["tools"]["listChanged"] is True

        # Step 2: List tools
        list_resp = std.handle_request("tools/list", {})
        assert len(list_resp["tools"]) == 3
        tool_names = [t["name"] for t in list_resp["tools"]]
        assert "read_file" in tool_names
        assert "list_dir" in tool_names
        assert "search" in tool_names

        # Step 3: Call a tool
        call_resp = std.handle_request("tools/call", {
            "name": "search",
            "arguments": {"query": "test", "limit": 3},
        })
        assert "content" in call_resp
        assert "result for 'test'" in call_resp["content"][0]["text"]

        # Step 4: Error case
        err_resp = std.handle_request("tools/call", {
            "name": "nonexistent_tool",
            "arguments": {},
        })
        assert err_resp.get("isError") is True

        # Step 5: Ping
        ping_resp = std.handle_request("ping", {})
        assert ping_resp["status"] == "ok"

        # Verify stats
        stats = std.get_stats()
        assert stats["total_tools"] == 3
        assert stats["calls_made"] == 2  # search call + nonexistent_tool call

        reset_mcp_standardizer()

    def test_discovery_and_registration_chain(self):
        """测试发现→注册→调用的完整链路"""
        reset_mcp_standardizer()
        std = MCPStandardizer()

        # Auto-discover src/core tools
        result = std.auto_discover_src_core()
        assert result["discovered_count"] > 0

        # Verify tools are registrable and callable as dict-based
        stats = std.get_stats()
        assert stats["total_tools"] > 0

        # Try calling a dict-based tool (should error gracefully)
        tool_names = stats["tool_names"]
        if tool_names:
            res = std.call_tool(tool_names[0], {})
            # Dict-based tools have no callable — should error cleanly
            assert isinstance(res, MCPToolResult)

        reset_mcp_standardizer()

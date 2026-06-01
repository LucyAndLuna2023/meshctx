"""
meshctx v3.82 — MCP Protocol Standardizer (MCP协议标准化器)

功能:
  1. MCP工具注册: 接受现有工具定义→转换为MCP兼容格式
  2. MCP Server接口: 模拟MCP Server的tools/list、tools/call端点
  3. 工具发现: 自动扫描src/core/下所有工具函数
  4. JSON Schema生成: 为每个工具自动生成输入/输出schema
  5. 兼容层: 现有meshctx工具可无缝对接MCP客户端

协议: JSON-RPC 2.0 (MCP 2024-11-05规范)
"""
import ast
import importlib
import inspect
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union, get_type_hints

logger = logging.getLogger("meshctx.mcp_standardizer")

# ── Data Classes ────────────────────────────────────────────────────

@dataclass
class MCPToolDef:
    """MCP工具定义 (符合MCP 2024-11-05规范)"""
    name: str
    description: str = ""
    input_schema: Dict = field(default_factory=dict)
    output_schema: Optional[Dict] = None
    func: Optional[Callable] = None
    module: str = ""
    source_file: str = ""
    category: str = "general"
    version_added: str = "3.82"
    tags: List[str] = field(default_factory=list)


@dataclass
class MCPToolResult:
    """MCP工具调用结果"""
    content: Any = None
    is_error: bool = False
    error_message: str = ""
    duration_ms: float = 0
    tool_name: str = ""


@dataclass
class MCPServerInfo:
    """MCP Server元信息"""
    name: str = "meshctx-mcp-server"
    version: str = "3.82.0"
    protocol_version: str = "2024-11-05"
    capabilities: Dict = field(default_factory=lambda: {
        "tools": {},
        "resources": {},
        "prompts": {},
    })


# ── JSON Schema Generation ──────────────────────────────────────────

# Python type → JSON Schema type mapping
_TYPE_MAP: Dict[type, str] = {
    str: "string", int: "integer", float: "number",
    bool: "boolean", list: "array", dict: "object",
    type(None): "null",
}


def _py_type_to_json_schema(py_type: Any) -> Dict:
    """Convert Python type annotation to JSON Schema"""
    origin = getattr(py_type, "__origin__", None)
    args = getattr(py_type, "__args__", ())

    if py_type in _TYPE_MAP:
        return {"type": _TYPE_MAP[py_type]}

    if origin is list or origin is List:
        item_schema = {}
        if args:
            item_schema = _py_type_to_json_schema(args[0])
        return {"type": "array", "items": item_schema or {}}

    if origin is dict or origin is Dict:
        return {"type": "object"}

    if origin is Union:
        types = []
        has_none = False
        for a in args:
            if a is type(None):
                has_none = True
            else:
                types.append(_py_type_to_json_schema(a))
        if has_none and len(types) == 1:
            result = types[0].copy()
            result["nullable"] = True
            return result
        if types:
            return {"type": [t.get("type", "string") for t in types] if not has_none else
                    types[0] if len(types) == 1 else {"type": "string"}}

    if origin is Optional:
        if args and args[0] is not type(None):
            result = _py_type_to_json_schema(args[0])
            result["nullable"] = True
            return result

    return {"type": "string"}


def _infer_description_from_docstring(docstring: str, param_name: str = "") -> str:
    """Extract parameter description from docstring"""
    if not docstring or not param_name:
        return ""
    lines = docstring.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f":param {param_name}:") or stripped.startswith(f"{param_name}:"):
            parts = stripped.split(":", 1)
            return parts[1].strip() if len(parts) > 1 else ""
    return ""


def generate_json_schema_from_func(func: Callable) -> Dict:
    """Auto-generate JSON Schema from a Python function's type hints + docstring

    Returns a dict with 'input_schema' and 'output_schema' keys,
    both conforming to JSON Schema draft-07 + MCP conventions.
    """
    input_schema: Dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    output_schema: Dict = {
        "type": "object",
        "properties": {},
    }

    try:
        sig = inspect.signature(func)
        hints = {}
        try:
            hints = get_type_hints(func)
        except Exception:
            pass

        doc = inspect.getdoc(func) or ""

        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue

            prop: Dict = {}
            # Type
            if name in hints:
                prop.update(_py_type_to_json_schema(hints[name]))
            else:
                if param.default is not inspect.Parameter.empty:
                    prop["type"] = _TYPE_MAP.get(type(param.default), "string")
                else:
                    prop["type"] = "string"

            # Description
            desc = _infer_description_from_docstring(doc, name)
            if desc:
                prop["description"] = desc

            # Default
            if param.default is not inspect.Parameter.empty:
                prop["default"] = param.default

            input_schema["properties"][name] = prop

            # Required
            if param.default is inspect.Parameter.empty and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                input_schema["required"].append(name)

        # Output schema
        if "return" in hints and hints["return"] is not type(None):
            return_type = hints["return"]
            if hasattr(return_type, "__origin__") and return_type.__origin__ is dict:
                output_schema = {"type": "object", "properties": {}}
            else:
                output_schema = _py_type_to_json_schema(return_type)
        else:
            output_schema = {"type": "object"}

    except Exception as e:
        logger.debug(f"Schema generation fallback for {func.__name__}: {e}")
        input_schema = {"type": "object", "properties": {}}
        output_schema = {"type": "object"}

    if not input_schema["required"]:
        del input_schema["required"]

    return {
        "input_schema": input_schema,
        "output_schema": output_schema,
    }


def generate_schema_from_dict(tool_def: Dict) -> Dict:
    """Generate JSON Schema from a dict-based tool definition

    Accepts both dict-format parameters:
        {"param_name": {"type": "string", "required": True}, ...}
    And list-format (from AST discovery):
        [{"name": "param_name", "type": "string"}, ...]
    """
    params = tool_def.get("parameters", tool_def.get("params", {}))
    props = {}
    required = []

    # Handle list-format parameters (from AST-based discovery)
    if isinstance(params, list):
        for item in params:
            if isinstance(item, dict):
                name = item.get("name", "")
                if not name:
                    continue
                prop = {"type": item.get("type", "string")}
                if "description" in item:
                    prop["description"] = item["description"]
                if "default" in item:
                    prop["default"] = item["default"]
                if item.get("required", not item.get("optional", False)):
                    required.append(name)
                props[name] = prop
    else:
        for name, info in params.items():
            if isinstance(info, dict):
                prop = {
                    "type": info.get("type", "string"),
                }
                if "description" in info:
                    prop["description"] = info["description"]
                if "default" in info:
                    prop["default"] = info["default"]
                if info.get("required", not info.get("optional", False)):
                    required.append(name)
                props[name] = prop
            elif isinstance(info, str):
                props[name] = {"type": info}
            else:
                props[name] = {"type": "string"}

    schema = {
        "type": "object",
        "properties": props,
    }
    if required:
        schema["required"] = required

    return schema


# ── Tool Discovery ──────────────────────────────────────────────────


def discover_functions_in_module(module_path: str) -> List[Dict]:
    """Scan a Python module file for public functions with type hints

    Returns list of dicts: {name, description, params, module, source_file}
    """
    discovered = []
    try:
        with open(module_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, OSError) as e:
        logger.debug(f"Skip {module_path}: {e}")
        return discovered

    module_name = Path(module_path).stem

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            # Skip private/dunder functions
            if node.name.startswith("_") and not node.name.startswith("__init"):
                continue

            params = []
            for arg in node.args.args:
                param_info = {"name": arg.arg, "type": "string"}
                if arg.annotation:
                    param_info["type"] = ast.unparse(arg.annotation)
                # Check for defaults
                defaults_offset = len(node.args.args) - len(node.args.defaults)
                arg_index = node.args.args.index(arg)
                if arg_index >= defaults_offset:
                    default_node = node.args.defaults[arg_index - defaults_offset]
                    try:
                        param_info["default"] = ast.literal_eval(default_node)
                    except Exception:
                        param_info["default"] = ast.unparse(default_node)
                params.append(param_info)

            docstring = ast.get_docstring(node) or ""

            discovered.append({
                "name": node.name,
                "description": docstring.split("\n")[0] if docstring else "",
                "full_description": docstring,
                "parameters": params,
                "module": module_name,
                "source_file": module_path,
                "line_number": node.lineno,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })

    return discovered


def discover_tools_in_package(
    package_path: str, exclude_patterns: Optional[List[str]] = None
) -> List[Dict]:
    """Scan all .py files in a package directory for discoverable tool functions

    Args:
        package_path: Path to the package directory (e.g., src/core/)
        exclude_patterns: File name patterns to exclude
    """
    if exclude_patterns is None:
        exclude_patterns = ["__init__", "test_", "_test", "setup"]

    all_tools = []
    pkg = Path(package_path)

    if not pkg.is_dir():
        return all_tools

    for py_file in sorted(pkg.glob("*.py")):
        name = py_file.stem
        if any(name.startswith(pat) or name.endswith(pat) for pat in exclude_patterns):
            continue

        tools = discover_functions_in_module(str(py_file))
        all_tools.extend(tools)

    return all_tools


# ── MCP Standardizer ────────────────────────────────────────────────


class MCPStandardizer:
    """v3.82 MCP Protocol Standardizer

    将现有meshctx工具转换为MCP兼容格式，提供JSON-RPC 2.0端点
    并自动生成JSON Schema。

    Usage:
        std = MCPStandardizer()
        std.register_tool("my_tool", my_func, "Does something")
        std.auto_discover_src_core()
        result = std.handle_request("tools/list", {})
        call_result = std.call_tool("my_tool", {"arg": "val"})
    """

    # MCP protocol version we implement
    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "meshctx-mcp-standardizer"
    SERVER_VERSION = "3.82.0"

    def __init__(self, project_root: Optional[str] = None):
        """Initialize MCPStandardizer

        Args:
            project_root: Root directory of meshctx project.
                          Defaults to auto-detection from this file's location.
        """
        self._tools: Dict[str, MCPToolDef] = {}
        self._call_history: List[Dict] = []
        self._stats: Dict[str, int] = {
            "tools_registered": 0,
            "tools_discovered": 0,
            "calls_made": 0,
            "schemas_generated": 0,
        }

        # Determine project root
        if project_root:
            self._project_root = Path(project_root)
        else:
            self._project_root = Path(__file__).resolve().parent.parent.parent

        self._core_path = self._project_root / "src" / "core"

        # Server metadata
        self._server_info = MCPServerInfo()

    # ── 1. Tool Registration ────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str = "",
        input_schema: Optional[Dict] = None,
        output_schema: Optional[Dict] = None,
        category: str = "general",
        tags: Optional[List[str]] = None,
    ) -> MCPToolDef:
        """注册一个Python函数为MCP工具

        Args:
            name: MCP工具名称 (唯一标识)
            func: Python可调用对象
            description: 工具描述
            input_schema: 手动指定的输入schema (不指定则自动生成)
            output_schema: 手动指定的输出schema (不指定则自动生成)
            category: 工具分类
            tags: 标签列表
        """
        # Auto-generate schemas if not provided
        if input_schema is None or output_schema is None:
            gen = generate_json_schema_from_func(func)
            if input_schema is None:
                input_schema = gen["input_schema"]
            if output_schema is None:
                output_schema = gen["output_schema"]
            self._stats["schemas_generated"] += 1

        # Extract module info
        module = getattr(func, "__module__", "unknown")
        try:
            source_file = inspect.getfile(func)
        except TypeError:
            source_file = ""

        if not description:
            description = (inspect.getdoc(func) or "").split("\n")[0]

        tool = MCPToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            func=func,
            module=module,
            source_file=source_file,
            category=category,
            tags=tags or [],
        )
        self._tools[name] = tool
        self._stats["tools_registered"] += 1

        logger.debug(f"Registered MCP tool: {name} (category={category})")
        return tool

    def register_from_dict(self, tool_dict: Dict) -> MCPToolDef:
        """从字典定义注册MCP工具 (适用于无Python函数源的情况)

        Args:
            tool_dict: 包含 name, description, parameters 等字段的定义字典
        """
        name = tool_dict.get("name", "")
        description = tool_dict.get("description", "")

        input_schema = tool_dict.get("inputSchema", tool_dict.get("input_schema"))
        if not input_schema:
            input_schema = generate_schema_from_dict(tool_dict)

        tool = MCPToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=tool_dict.get("outputSchema") or tool_dict.get("output_schema"),
            category=tool_dict.get("category", "general"),
            tags=tool_dict.get("tags", []),
            version_added=tool_dict.get("version_added", "3.82"),
        )
        self._tools[name] = tool
        self._stats["tools_registered"] += 1

        logger.debug(f"Registered MCP tool from dict: {name}")
        return tool

    def unregister_tool(self, name: str) -> bool:
        """注销一个MCP工具"""
        if name in self._tools:
            del self._tools[name]
            self._stats["tools_registered"] -= 1
            return True
        return False

    # ── 2. MCP Server Interface ─────────────────────────────────────

    def handle_request(self, method: str, params: Optional[Dict] = None) -> Dict:
        """MCP JSON-RPC 2.0 请求分发器

        支持的方法:
        - initialize      → 返回server信息
        - tools/list       → 列出所有注册工具
        - tools/call       → 调用指定工具
        - ping             → 健康检查
        - server/info      → 返回server元信息
        - notifications/initialized → 无操作确认

        Args:
            method: JSON-RPC方法名
            params: 方法参数
        """
        params = params or {}

        if method == "initialize":
            return self._handle_initialize(params)
        elif method == "tools/list":
            return self._handle_list_tools(params)
        elif method == "tools/call":
            return self._handle_call_tool(params)
        elif method == "ping":
            return {"status": "ok", "timestamp": time.time()}
        elif method == "server/info":
            return {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
                "protocol_version": self.PROTOCOL_VERSION,
                "tools_count": len(self._tools),
            }
        elif method == "notifications/initialized":
            return {}  # No response needed for notifications
        else:
            return {"error": {"code": -32601, "message": f"Unknown method: {method}"}}

    def _handle_initialize(self, params: Dict) -> Dict:
        """Handle MCP initialize request"""
        client_info = params.get("clientInfo", {})
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "serverInfo": {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
            },
            "capabilities": {
                "tools": {"listChanged": True},
            },
            "instructions": (
                "meshctx MCP Standardizer v3.82 — "
                f"{len(self._tools)} tools available. "
                "Use tools/list to discover tools, tools/call to invoke them."
            ),
        }

    def _handle_list_tools(self, params: Dict) -> Dict:
        """Handle MCP tools/list request"""
        tools_list = []
        for name, tool in self._tools.items():
            tools_list.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            })
        return {"tools": tools_list}

    def _handle_call_tool(self, params: Dict) -> Dict:
        """Handle MCP tools/call request"""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        result = self.call_tool(tool_name, arguments)

        if result.is_error:
            return {
                "content": [{"type": "text", "text": result.error_message}],
                "isError": True,
            }

        content_text = result.content
        if not isinstance(content_text, str):
            try:
                content_text = json.dumps(content_text, ensure_ascii=False, default=str)
            except Exception:
                content_text = str(content_text)

        return {
            "content": [{"type": "text", "text": content_text}],
        }

    def list_tools(self) -> List[Dict]:
        """列出所有已注册的MCP工具 (非JSON-RPC包装, 直接返回)"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "output_schema": t.output_schema,
                "category": t.category,
                "tags": t.tags,
                "module": t.module,
            }
            for t in self._tools.values()
        ]

    def call_tool(self, name: str, arguments: Optional[Dict] = None) -> MCPToolResult:
        """直接调用已注册的MCP工具 (非JSON-RPC包装)

        Args:
            name: 工具名称
            arguments: 调用参数字典
        """
        arguments = arguments or {}
        t0 = time.perf_counter()

        tool = self._tools.get(name)
        if not tool:
            self._stats["calls_made"] += 1
            self._call_history.append({
                "tool": name, "arguments": arguments,
                "error": "Tool not found", "timestamp": time.time(),
            })
            return MCPToolResult(
                is_error=True,
                error_message=f"Tool not found: {name}",
                tool_name=name,
            )

        if tool.func is None:
            self._stats["calls_made"] += 1
            self._call_history.append({
                "tool": name, "arguments": arguments,
                "error": "No callable function", "timestamp": time.time(),
            })
            return MCPToolResult(
                is_error=True,
                error_message=f"Tool '{name}' has no callable function (registered from dict)",
                tool_name=name,
            )

        try:
            # Validate input against schema
            validation_error = self._validate_arguments(name, arguments, tool.input_schema)
            if validation_error:
                return MCPToolResult(
                    is_error=True,
                    error_message=f"Input validation failed: {validation_error}",
                    tool_name=name,
                )

            result = tool.func(**arguments)
            duration = (time.perf_counter() - t0) * 1000

            self._call_history.append({
                "tool": name, "arguments": arguments,
                "result": str(result)[:200], "duration_ms": round(duration, 2),
                "timestamp": time.time(),
            })
            self._stats["calls_made"] += 1

            return MCPToolResult(
                content=result,
                duration_ms=round(duration, 2),
                tool_name=name,
            )
        except Exception as e:
            duration = (time.perf_counter() - t0) * 1000
            self._call_history.append({
                "tool": name, "arguments": arguments,
                "error": str(e), "duration_ms": round(duration, 2),
                "timestamp": time.time(),
            })
            self._stats["calls_made"] += 1
            logger.warning(f"Tool call '{name}' failed: {e}")

            return MCPToolResult(
                is_error=True,
                error_message=f"Tool execution error: {e}",
                duration_ms=round(duration, 2),
                tool_name=name,
            )

    def _validate_arguments(self, name: str, arguments: Dict, schema: Dict) -> Optional[str]:
        """Lightweight input validation against JSON Schema"""
        if not schema or schema.get("type") != "object":
            return None

        required = schema.get("required", [])

        # Check required fields
        for field in required:
            if field not in arguments:
                return f"Missing required parameter: '{field}'"

        # Check types (basic validation)
        props = schema.get("properties", {})
        for key, value in arguments.items():
            if key not in props:
                continue  # Skip extra params silently
            expected_type = props[key].get("type", "string")
            if isinstance(expected_type, list):
                # Union type — accept any
                continue
            type_check = self._check_type(value, expected_type)
            if not type_check:
                return (
                    f"Parameter '{key}': expected {expected_type}, "
                    f"got {type(value).__name__}"
                )

        return None

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        """Check if value matches expected JSON Schema type"""
        type_map = {
            "string": str, "integer": int, "number": (int, float),
            "boolean": bool, "array": list, "object": dict,
            "null": type(None),
        }
        expected_types = type_map.get(expected)
        if expected_types is None:
            return True  # Unknown type, accept
        if isinstance(expected_types, tuple):
            return isinstance(value, expected_types)
        return isinstance(value, expected_types)

    # ── 3. Tool Discovery ───────────────────────────────────────────

    def discover_tools(self, module_path: Optional[str] = None) -> int:
        """扫描指定路径或默认src/core/目录, 发现可注册的工具函数

        Args:
            module_path: 要扫描的路径 (文件或目录). 默认: src/core/

        Returns:
            发现并成功注册的工具数量
        """
        if module_path is None:
            module_path = str(self._core_path)

        target = Path(module_path)
        if not target.exists():
            logger.warning(f"Discovery path not found: {module_path}")
            return 0

        discovered = []
        if target.is_file() and target.suffix == ".py":
            discovered = discover_functions_in_module(str(target))
        elif target.is_dir():
            discovered = discover_tools_in_package(
                str(target),
                exclude_patterns=["__init__", "test_", "_test", "mcp_standardizer"],
            )

        count = 0
        for tool_info in discovered:
            func_name = tool_info["name"]
            # Skip if already registered
            if func_name in self._tools:
                continue

            # Build tool dict
            tool_dict = {
                "name": func_name,
                "description": tool_info.get("description", ""),
                "parameters": tool_info["parameters"],
                "category": tool_info.get("module", "discovered"),
                "tags": ["auto-discovered"],
                "source_file": tool_info.get("source_file", ""),
            }

            self.register_from_dict(tool_dict)
            self._stats["tools_discovered"] += 1
            count += 1

        return count

    def auto_discover_src_core(self) -> Dict[str, Any]:
        """自动扫描src/core/下所有模块, 发现工具函数并注册

        Returns:
            {discovered_count, total_tools, module_count, tools_by_module}
        """
        # Step 1: Discover functions from source files
        all_tools_raw = discover_tools_in_package(str(self._core_path))

        # Step 2: Register each discovered tool
        registered = 0
        tools_by_module: Dict[str, List[str]] = {}

        for tool_info in all_tools_raw:
            func_name = tool_info["name"]
            module = tool_info.get("module", "unknown")

            # Skip functions that start with underscore
            if func_name.startswith("_"):
                continue

            # Skip if already registered
            if func_name in self._tools:
                continue

            # Try to import and register with full schema generation
            registered_func = self._import_function(func_name, module)
            if registered_func:
                self.register_tool(
                    name=func_name,
                    func=registered_func,
                    description=tool_info.get("full_description", tool_info.get("description", "")),
                    category=module,
                    tags=["auto-discovered", module],
                )
            else:
                # Fallback: register from dict
                self.register_from_dict({
                    "name": func_name,
                    "description": tool_info.get("description", ""),
                    "parameters": tool_info["parameters"],
                    "category": module,
                    "tags": ["auto-discovered", module],
                })

            if module not in tools_by_module:
                tools_by_module[module] = []
            tools_by_module[module].append(func_name)
            registered += 1

        self._stats["tools_discovered"] += registered

        return {
            "discovered_count": registered,
            "total_tools": len(self._tools),
            "module_count": len(tools_by_module),
            "tools_by_module": tools_by_module,
        }

    def _import_function(self, func_name: str, module_name: str) -> Optional[Callable]:
        """Try to import a function from a meshctx core module"""
        try:
            # Try importing from src.core.<module>
            full_module = f"src.core.{module_name}"
            if full_module in sys.modules:
                mod = sys.modules[full_module]
            else:
                mod = importlib.import_module(full_module)
            return getattr(mod, func_name, None)
        except Exception as e:
            logger.debug(f"Cannot import {func_name} from {module_name}: {e}")
            return None

    # ── 4. Schema Helpers ───────────────────────────────────────────

    def generate_schema_for_func(self, func: Callable) -> Dict:
        """为给定函数生成完整的MCP schema"""
        self._stats["schemas_generated"] += 1
        return generate_json_schema_from_func(func)

    def get_tool_schema(self, name: str) -> Optional[Dict]:
        """获取指定工具的schema"""
        tool = self._tools.get(name)
        if not tool:
            return None
        return {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
            "outputSchema": tool.output_schema,
        }

    def export_tools_as_mcp_config(self, output_path: Optional[str] = None) -> Dict:
        """导出所有工具为MCP配置文件格式 (mcp.json兼容)

        Args:
            output_path: 如果指定, 将配置写入此文件
        """
        config = {
            "mcpServers": {
                self.SERVER_NAME: {
                    "command": "python",
                    "args": ["-m", "src.core.mcp_standardizer", "--serve"],
                    "description": f"meshctx MCP Server v{self.SERVER_VERSION} — {len(self._tools)} tools",
                }
            }
        }

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(config, indent=2, ensure_ascii=False))
            logger.info(f"MCP config exported to {output_path}")

        return config

    # ── 5. Stats & Utilities ────────────────────────────────────────

    def get_stats(self) -> Dict:
        """获取standardizer统计信息"""
        categories = {}
        for t in self._tools.values():
            cat = t.category
            categories[cat] = categories.get(cat, 0) + 1

        return {
            **self._stats,
            "total_tools": len(self._tools),
            "tool_names": sorted(self._tools.keys()),
            "categories": categories,
            "protocol": f"MCP {self.PROTOCOL_VERSION}",
            "server_name": self.SERVER_NAME,
            "server_version": self.SERVER_VERSION,
            "call_history_size": len(self._call_history),
            "core_modules_scanned": (
                len(list(self._core_path.glob("*.py")))
                if self._core_path.exists()
                else 0
            ),
        }

    def get_tool(self, name: str) -> Optional[MCPToolDef]:
        """获取单个工具定义"""
        return self._tools.get(name)

    def get_call_history(self, limit: int = 50) -> List[Dict]:
        """获取最近的工具调用历史"""
        return list(reversed(self._call_history))[:limit]

    def reset(self):
        """重置所有注册的工具和统计"""
        self._tools.clear()
        self._call_history.clear()
        for key in self._stats:
            self._stats[key] = 0


# ── Singleton & Convenience ─────────────────────────────────────────

_standardizer: Optional[MCPStandardizer] = None


def get_mcp_standardizer(project_root: Optional[str] = None) -> MCPStandardizer:
    """获取MCPStandardizer单例"""
    global _standardizer
    if _standardizer is None:
        _standardizer = MCPStandardizer(project_root=project_root)
    return _standardizer


def reset_mcp_standardizer():
    """重置单例 (用于测试)"""
    global _standardizer
    _standardizer = None


# ── CLI Entry Point ─────────────────────────────────────────────────

def serve_stdin(standardizer: Optional[MCPStandardizer] = None):
    """Run MCP Standardizer in stdio mode (MCP JSON-RPC over stdin/stdout)

    This is the standard MCP transport for launching as a subprocess
    from MCP clients like Claude Desktop, Cursor, etc.
    """
    std = standardizer or get_mcp_standardizer()
    logger.info(f"MCPStandardizer v{std.SERVER_VERSION} serving on stdio")
    sys.stderr.write(f"MCPStandardizer v{std.SERVER_VERSION} ready\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            req_id = request.get("id")
            method = request.get("method", "")
            params = request.get("params", {})

            result = std.handle_request(method, params)

            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            sys.stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="meshctx MCP Standardizer v3.82")
    parser.add_argument("--serve", action="store_true", help="Run as MCP stdio server")
    parser.add_argument("--discover", action="store_true", help="Discover tools in src/core/")
    parser.add_argument("--list", action="store_true", help="List all registered tools")
    parser.add_argument("--export", type=str, metavar="PATH", help="Export MCP config JSON")
    parser.add_argument("--stats", action="store_true", help="Show statistics")

    args = parser.parse_args()

    std = get_mcp_standardizer()

    if args.serve:
        std.auto_discover_src_core()
        serve_stdin(std)
    elif args.discover:
        result = std.auto_discover_src_core()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.list:
        std.auto_discover_src_core()
        tools = std.list_tools()
        for t in tools:
            print(f"  {t['name']:30s} [{t['category']:20s}] {t['description'][:60]}")
        print(f"\n{len(tools)} tools total")
    elif args.export:
        std.auto_discover_src_core()
        cfg = std.export_tools_as_mcp_config(args.export)
        print(f"Exported to {args.export}")
        print(f"Server: {cfg['mcpServers'][std.SERVER_NAME]['command']}")
    elif args.stats:
        std.auto_discover_src_core()
        stats = std.get_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        parser.print_help()

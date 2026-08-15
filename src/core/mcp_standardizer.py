"""meshctx mcp_standardizer"""
import inspect, json, uuid, time, os
from dataclasses import dataclass, field
from typing import Any

@dataclass
class MCPToolDef:
    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    func: Any = None
    category: str = ""
    tags: list = field(default_factory=list)

@dataclass
class MCPToolResult:
    is_error: bool = False
    content: Any = None
    error_message: str = ""
    tool_name: str = ""
    duration_ms: float = 0.0

class MCPStandardizer:
    SERVER_NAME = "meshctx-mcp-standardizer"
    SERVER_VERSION = "3.82.0"
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, **kw):
        self._tools = {}
        self._stats = {"tools_registered": 0, "calls_made": 0, "schemas_generated": 0}
        self._call_history = []
        self._migration_history = []

    def register_tool(self, name, func, description="", input_schema=None, output_schema=None, category=None, tags=None, **kw):
        if input_schema is None:
            generated = generate_json_schema_from_func(func)
            input_schema = generated["input_schema"]
        if output_schema is None:
            generated = generate_json_schema_from_func(func)
            output_schema = generated["output_schema"]
        tool = MCPToolDef(
            name=name,
            description=description or (func.__doc__ or ""),
            input_schema=input_schema,
            output_schema=output_schema,
            func=func,
            category=category or "",
            tags=tags or [],
        )
        self._tools[name] = tool
        self._stats["tools_registered"] += 1
        return tool

    def register_from_dict(self, tool_dict):
        name = tool_dict.get("name", "")
        description = tool_dict.get("description", "")
        category = tool_dict.get("category", "")
        tags = tool_dict.get("tags", [])
        params = tool_dict.get("parameters", {})
        input_schema = generate_schema_from_dict({"parameters": params})
        tool = MCPToolDef(
            name=name,
            description=description,
            input_schema=input_schema,
            func=None,
            category=category,
            tags=tags,
        )
        self._tools[name] = tool
        self._stats["tools_registered"] += 1
        return tool

    def unregister_tool(self, name):
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def list_tools(self):
        tools = []
        for t in self._tools.values():
            tools.append({
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
                "outputSchema": t.output_schema,
                "category": t.category,
                "tags": t.tags,
            })
        return tools

    def call_tool(self, name, arguments, **kw):
        start = time.time()
        self._stats["calls_made"] += 1
        tool = self._tools.get(name)
        if tool is None:
            duration = (time.time() - start) * 1000
            result = MCPToolResult(is_error=True, error_message=f"Tool '{name}' not found", tool_name=name, duration_ms=duration)
            self._call_history.append({"tool": name, "arguments": arguments, "success": False})
            return result
        if tool.func is None:
            duration = (time.time() - start) * 1000
            result = MCPToolResult(is_error=True, error_message="no callable for dict-based tool", tool_name=name, duration_ms=duration)
            self._call_history.append({"tool": name, "arguments": arguments, "success": False})
            return result
        schema = tool.input_schema
        required = schema.get("required", [])
        for req in required:
            if req not in arguments:
                duration = (time.time() - start) * 1000
                result = MCPToolResult(is_error=True, error_message=f"Missing required parameter: {req}", tool_name=name, duration_ms=duration)
                self._call_history.append({"tool": name, "arguments": arguments, "success": False})
                return result
        properties = schema.get("properties", {})
        for pname, pval in arguments.items():
            if pname in properties:
                expected_type = properties[pname].get("type", "")
                type_ok = True
                if expected_type == "integer" and not isinstance(pval, int):
                    type_ok = False
                elif expected_type == "number" and not isinstance(pval, (int, float)):
                    type_ok = False
                elif expected_type == "string" and not isinstance(pval, str):
                    type_ok = False
                elif expected_type == "boolean" and not isinstance(pval, bool):
                    type_ok = False
                if not type_ok:
                    duration = (time.time() - start) * 1000
                    result = MCPToolResult(is_error=True, error_message=f"validation error for parameter: {pname}", tool_name=name, duration_ms=duration)
                    self._call_history.append({"tool": name, "arguments": arguments, "success": False})
                    return result
        try:
            output = tool.func(**arguments)
            duration = (time.time() - start) * 1000
            result = MCPToolResult(is_error=False, content=output, tool_name=name, duration_ms=duration)
            self._call_history.append({"tool": name, "arguments": arguments, "success": True, "result": str(output)[:200]})
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            result = MCPToolResult(is_error=True, error_message=str(e), tool_name=name, duration_ms=duration)
            self._call_history.append({"tool": name, "arguments": arguments, "success": False, "error": str(e)})
            return result

    def handle_request(self, method, params=None):
        params = params or {}
        if method == "initialize":
            return {
                "protocolVersion": self.PROTOCOL_VERSION,
                "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
                "capabilities": {"tools": {"listChanged": True}},
            }
        elif method == "tools/list":
            tools_list = []
            for t in self._tools.values():
                tools_list.append({
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                })
            return {"tools": tools_list}
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = self.call_tool(tool_name, arguments)
            if result.is_error:
                return {"isError": True, "content": [{"type": "text", "text": result.error_message}]}
            content_text = str(result.content)
            return {"content": [{"type": "text", "text": content_text}]}
        elif method == "ping":
            return {"status": "ok", "timestamp": time.time()}
        elif method == "server/info":
            return {"name": self.SERVER_NAME, "version": self.SERVER_VERSION, "protocol_version": self.PROTOCOL_VERSION}
        elif method.startswith("notifications/"):
            return {}
        else:
            return {"error": {"code": -32601, "message": f"Unknown method: {method}"}}

    def discover_tools(self, module_path):
        try:
            import importlib.util
            mod_name = os.path.splitext(os.path.basename(module_path))[0]
            spec = importlib.util.spec_from_file_location(mod_name, module_path)
            if spec is None or spec.loader is None:
                return 0
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            count = 0
            for fname in dir(module):
                if fname.startswith("_"):
                    continue
                obj = getattr(module, fname)
                if inspect.isfunction(obj):
                    if fname in self._tools:
                        continue
                    try:
                        self.register_tool(fname, obj)
                        count += 1
                    except Exception:
                        pass
            return count
        except Exception:
            return 0

    def auto_discover_src_core(self):
        discovered = 0
        module_count = 0
        tools_by_module = {}
        candidates = []
        src_core = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
        if os.path.isdir(src_core):
            candidates.append(src_core)
        cwd_core = os.path.join(os.getcwd(), "src", "core")
        if os.path.isdir(cwd_core) and cwd_core not in candidates:
            candidates.append(cwd_core)
        for core_dir in candidates:
            for fname in sorted(os.listdir(core_dir)):
                if not fname.endswith(".py") or fname.startswith("_"):
                    continue
                fpath = os.path.join(core_dir, fname)
                count = self.discover_tools(fpath)
                if count > 0:
                    module_count += 1
                    discovered += count
                    tools_by_module[os.path.splitext(fname)[0]] = count
        return {
            "discovered_count": discovered,
            "total_tools": len(self._tools),
            "module_count": module_count,
            "tools_by_module": tools_by_module,
        }

    def generate_schema_for_func(self, func):
        self._stats["schemas_generated"] += 1
        return generate_json_schema_from_func(func)

    def get_tool_schema(self, name):
        tool = self._tools.get(name)
        if tool is None:
            return None
        return {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }

    def export_tools_as_mcp_config(self, output_path=None):
        config = {
            "mcpServers": {
                "meshctx-mcp-standardizer": {
                    "command": "python",
                    "args": ["-m", "src.core.mcp_standardizer", "--serve"],
                }
            }
        }
        if output_path:
            with open(output_path, "w") as f:
                json.dump(config, f)
        return config

    def get_tool(self, name, **kw):
        return self._tools.get(name)

    def get_stats(self):
        categories = list({t.category for t in self._tools.values() if t.category})
        return {
            "total_tools": len(self._tools),
            "categories": categories,
            "calls_made": self._stats["calls_made"],
            "tools_registered": self._stats["tools_registered"],
            "schemas_generated": self._stats["schemas_generated"],
            "server_name": self.SERVER_NAME,
            "protocol": "MCP 2024-11-05",
            "tool_names": list(self._tools.keys()),
        }

    def get_call_history(self):
        return list(self._call_history)

    def reset(self):
        self._tools = {}
        self._stats = {"tools_registered": 0, "calls_made": 0, "schemas_generated": 0}
        self._call_history = []


def _py_type_to_json_schema(py_type):
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
    schema = {"type": mapping.get(py_type, "string")}
    if py_type == list:
        schema["items"] = {}
    return schema


def generate_json_schema_from_func(func):
    sig = inspect.signature(func)
    props = {}
    required = []
    for pname, param in sig.parameters.items():
        pt = param.annotation if param.annotation != inspect.Parameter.empty else str
        props[pname] = _py_type_to_json_schema(pt)
        if param.default != inspect.Parameter.empty:
            props[pname]["default"] = param.default
        if param.default == inspect.Parameter.empty:
            required.append(pname)
    input_schema = {"type": "object", "properties": props}
    if required:
        input_schema["required"] = required
    ret_annotation = sig.return_annotation
    if ret_annotation != inspect.Signature.empty:
        output_schema = _py_type_to_json_schema(ret_annotation)
    else:
        output_schema = {"type": "object"}
    return {"input_schema": input_schema, "output_schema": output_schema}


def generate_schema_from_dict(data, name="root"):
    if isinstance(data, dict) and "parameters" in data:
        params = data["parameters"]
        if isinstance(params, dict):
            props = {}
            required = []
            for pname, pval in params.items():
                if isinstance(pval, dict):
                    ptype = pval.get("type", "string")
                    props[pname] = {"type": ptype}
                    if "description" in pval:
                        props[pname]["description"] = pval["description"]
                    if "default" in pval:
                        props[pname]["default"] = pval["default"]
                    if pval.get("required") is True:
                        required.append(pname)
                elif isinstance(pval, str):
                    props[pname] = {"type": pval}
                else:
                    props[pname] = {"type": "string"}
            result = {"type": "object", "properties": props}
            if required:
                result["required"] = required
            return result
    if isinstance(data, dict):
        props = {k: generate_schema_from_dict(v, k) for k, v in data.items()}
        return {"type": "object", "properties": props}
    elif isinstance(data, list) and data:
        return {"type": "array", "items": generate_schema_from_dict(data[0], "item")}
    elif isinstance(data, bool):
        return {"type": "boolean"}
    elif isinstance(data, int):
        return {"type": "integer"}
    elif isinstance(data, float):
        return {"type": "number"}
    return {"type": "string"}


def discover_functions_in_module(module_path):
    import importlib.util
    import sys
    mod_name = os.path.splitext(os.path.basename(module_path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    # 先注册到 sys.modules: dataclass 等装饰器在 exec_module 期间
    # 会通过 sys.modules[cls.__module__] 查找模块上下文。
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(mod_name, None)
    funcs = []
    for fname, obj in inspect.getmembers(module):
        if inspect.isfunction(obj) and not fname.startswith("_"):
            funcs.append({"name": fname, "func": obj})
    return funcs


_mcp = None
def get_mcp_standardizer():
    global _mcp
    if _mcp is None:
        _mcp = MCPStandardizer()
    return _mcp


def reset_mcp_standardizer():
    global _mcp
    _mcp = None

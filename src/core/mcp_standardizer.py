"""meshctx mcp_standardizer"""
import inspect, json, uuid, time
from dataclasses import dataclass, field
from typing import Any

@dataclass
class MCPToolDef:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    name: str = ""
    description: str = ""
    parameters: dict = field(default_factory=dict)
    returns: dict = field(default_factory=dict)

@dataclass
class MCPToolResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    tool_name: str = ""
    success: bool = True
    output: Any = None
    error: str = ""

class MCPStandardizer:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, **kw):
        self._tools = {}
    def register_function(self, func, name=None, description=None, **kw):
        name = name or func.__name__
        params = {}
        sig = inspect.signature(func)
        for pname, param in sig.parameters.items():
            pt = param.annotation if param.annotation != inspect.Parameter.empty else Any
            default = param.default if param.default != inspect.Parameter.empty else None
            params[pname] = {"type": str(pt), "default": default, "required": param.default == inspect.Parameter.empty}
        ret = str(sig.return_annotation) if sig.return_annotation != inspect.Signature.empty else "Any"
        tool = MCPToolDef(name=name, description=description or func.__doc__ or "", parameters=params, returns={"type": ret})
        self._tools[name] = tool
        return tool
    def list_tools(self, **kw):
        return list(self._tools.values())
    def get_tool(self, name, **kw):
        return self._tools.get(name)

def _py_type_to_json_schema(py_type):
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
    return {"type": mapping.get(py_type, "string")}

def generate_json_schema_from_func(func):
    sig = inspect.signature(func)
    props = {}
    required = []
    for pname, param in sig.parameters.items():
        pt = param.annotation if param.annotation != inspect.Parameter.empty else str
        props[pname] = _py_type_to_json_schema(pt)
        if param.default == inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}

def generate_schema_from_dict(data, name="root"):
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

def discover_functions_in_module(module):
    funcs = []
    for name, obj in inspect.getmembers(module):
        if inspect.isfunction(obj) and not name.startswith("_"):
            funcs.append(obj)
    return funcs

_mcp = None
def get_mcp_standardizer():
    global _mcp
    if _mcp is None: _mcp = MCPStandardizer()
    return _mcp

def reset_mcp_standardizer():
    global _mcp
    _mcp = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


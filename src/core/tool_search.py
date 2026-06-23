"""
meshctx ToolSearch — 工具搜索/动态加载
对标: Claude Code ToolSearch + OpenClaw ToolSearch
"""
import importlib, pkgutil, inspect, sys
from pathlib import Path
from typing import Any

_TOOL_REGISTRY: dict[str, dict] = {}
_SEARCH_INDEX: dict[str, list[str]] = {}

def tool_register(name: str, fn: callable = None, description: str = "",
                  category: str = "general", parameters: dict = None,
                  module: str = None) -> str:
    """注册工具到搜索索引"""
    _TOOL_REGISTRY[name] = {
        "name": name, "fn": fn, "description": description,
        "category": category, "parameters": parameters or {},
        "module": module
    }
    # 索引关键词
    words = set((name + " " + description + " " + category).lower().split())
    for w in words:
        _SEARCH_INDEX.setdefault(w, []).append(name)
    return f"Tool({name}) registered"

def tool_search(query: str, category: str = None, top_k: int = 10) -> list:
    """搜索工具：按名称/描述/类别/关键词匹配"""
    query_lower = query.lower()
    query_words = set(query_lower.split())
    scored = []
    
    for name, tool in _TOOL_REGISTRY.items():
        if category and tool.get("category") != category:
            continue
        score = 0
        # 名称精确匹配
        if query_lower == name.lower():
            score += 100
        elif query_lower in name.lower():
            score += 50
        # 描述匹配
        desc = tool.get("description", "").lower()
        for w in query_words:
            if w in desc:
                score += 5
            if w in name.lower():
                score += 10
        # 类别匹配
        if query_lower in tool.get("category", "").lower():
            score += 20
        if score > 0:
            scored.append({"name": name, "category": tool["category"],
                          "description": tool["description"], "score": score})
    
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def tool_discover(path: str = None) -> list:
    """动态发现工具模块"""
    discovered = []
    scan_dirs = [path] if path else [
        str(Path(__file__).parent),
        str(Path.home() / ".meshctx/tools")
    ]
    
    for scan_dir in scan_dirs:
        p = Path(scan_dir)
        if not p.is_dir():
            continue
        sys.path.insert(0, str(p.parent))
        for f in sorted(p.glob("*_tool.py")):
            mod_name = f.stem
            try:
                mod = importlib.import_module(mod_name)
                funcs = inspect.getmembers(mod, inspect.isfunction)
                for fname, fn in funcs:
                    if not fname.startswith("_") and hasattr(fn, '__doc__'):
                        doc = (fn.__doc__ or "").strip().split("\n")[0]
                        cat = "general"
                        if any(k in fn.__module__ for k in 
                               ["browser","web","file","terminal","git","notify","lsp",
                                "team","workflow","monitor","message","schedule"]):
                            cat = fn.__module__.split("_")[0]
                        discovered.append({"module": mod_name, "function": fname, 
                                          "description": doc, "category": cat})
            except Exception:
                pass
    return discovered

def tool_categories() -> list:
    """列出所有工具类别"""
    cats = set(t["category"] for t in _TOOL_REGISTRY.values())
    return sorted(cats)

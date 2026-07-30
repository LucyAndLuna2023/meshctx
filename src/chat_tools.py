"""
meshctx Chat 工具引擎 v2 — 原生 OpenAI function calling 格式
对标 Hermes: read_file, write_file, search_files, terminal, web_search, list_dir
"""
import os, re, json, shlex, subprocess, urllib.request, urllib.parse
from pathlib import Path
from typing import Dict, Optional, List

# ═══════════════════════════════════════════════════
# 工具执行函数
# ═══════════════════════════════════════════════════

def _read_file(path: str, limit: int = 100) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"文件不存在: {path}"
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > limit:
            return "".join(lines[:limit]) + f"\n... (共{len(lines)}行, 显示前{limit}行)"
        return "".join(lines)
    except Exception as e:
        return f"读取失败: {e}"

def _write_file(path: str, content: str) -> str:
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入: {path} ({len(content)}字符)"
    except Exception as e:
        return f"写入失败: {e}"

def _list_dir(path: str) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"目录不存在: {path}"
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for item in items[:50]:
            t = "📁" if item.is_dir() else "📄"
            size = ""
            if item.is_file():
                s = item.stat().st_size
                size = f" ({s:,}B)" if s < 1024 else f" ({s/1024:.1f}KB)"
            lines.append(f"  {t} {item.name}{size}")
        return "\n".join(lines) if lines else "(空目录)"
    except Exception as e:
        return f"列出失败: {e}"

def _run_cmd(cmd: str) -> str:
    try:
        env = os.environ.copy()
        env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:' + env.get('PATH', '')
        r = subprocess.run(shlex.split(cmd), shell=False, capture_output=True, text=True, timeout=30, cwd=os.getcwd(), env=env)
        out = r.stdout[:3000]
        if r.stderr:
            out += "\n[stderr]\n" + r.stderr[:500]
        return out or f"(exit={r.returncode})"
    except subprocess.TimeoutExpired:
        return "命令超时(30秒)"
    except Exception as e:
        return f"执行失败: {e}"

def _search_files(pattern: str, path: str = ".", glob: str = "*") -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"目录不存在: {path}"
        matches = []
        for f in p.rglob(glob):
            if f.is_file() and f.stat().st_size < 1024*1024:
                try:
                    content = f.read_text(errors="replace")
                    if pattern.lower() in content.lower():
                        matches.append(str(f))
                except Exception:
                    logger.debug("chat_tools error", exc_info=True)
                    pass
        if not matches:
            return f"未找到包含 '{pattern}' 的文件"
        return "\n".join(matches[:20])
    except Exception as e:
        return f"搜索失败: {e}"

def _web_search(query: str) -> str:
    date_keywords = ['今天', '今日', '最新', '实时', '当前', '目前']
    if any(k in query for k in date_keywords):
        from datetime import datetime
        today = datetime.now().strftime('%Y年%m月%d日')
        if today not in query:
            query = f"{query} {today}"
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "meshctx/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode()
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)<', html, re.DOTALL)
        results = [re.sub(r'<[^>]+>', '', s).strip()[:200] for s in snippets[:5]]
        if results:
            return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results))
    except Exception:
        logger.debug("chat_tools error", exc_info=True)
        pass
    try:
        url = f"https://cn.bing.com/search?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode()
        snippets = re.findall(r'<p[^>]* class="b_lineclamp[^\"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'<div class="b_caption"[^>]*>.*?<p>(.*?)</p>', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'<span class="c-abstract"[^>]*>(.*?)</span>', html, re.DOTALL)
        results = [re.sub(r'<[^>]+>', '', s).strip()[:200] for s in snippets[:5] if s.strip()]
        return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results)) if results else "无搜索结果"
    except Exception as e:
        return f"搜索失败: {e}"

# ═══════════════════════════════════════════════════
# OpenAI Function Calling 工具定义
# ═══════════════════════════════════════════════════

TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容。用于查看代码、配置、日志等文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径（绝对路径或相对路径）"},
                    "limit": {"type": "integer", "description": "最多显示行数，默认100", "default": 100}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件。会自动创建父目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录中的文件和子目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认当前目录", "default": "."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_cmd",
            "description": "执行终端命令。用于编译、安装包、git操作等。命令在30秒超时内运行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "要执行的shell命令"}
                },
                "required": ["cmd"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "在文件中搜索指定内容。用于查找函数定义、错误信息等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索文本（不区分大小写）"},
                    "path": {"type": "string", "description": "搜索起始目录，默认当前目录", "default": "."},
                    "glob": {"type": "string", "description": "文件名过滤，如 *.py 只搜索Python文件", "default": "*"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索网页信息。查股票、新闻、天气、文档等实时数据时优先使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        }
    },
]

# 工具执行器映射
TOOL_EXECUTORS = {
    "read_file": lambda args: _read_file(args.get("path", ""), args.get("limit", 100)),
    "write_file": lambda args: _write_file(args.get("path", ""), args.get("content", "")),
    "list_dir": lambda args: _list_dir(args.get("path", ".")),
    "run_cmd": lambda args: _run_cmd(args.get("cmd", "")),
    "search_files": lambda args: _search_files(args.get("pattern", ""), args.get("path", "."), args.get("glob", "*")),
    "web_search": lambda args: _web_search(args.get("query", "")),
}

TOOL_ICONS = {
    "read_file": "📖", "write_file": "📝", "list_dir": "📂",
    "run_cmd": "⚡", "search_files": "🔍", "web_search": "🌐",
}

def execute_tool(tool_name: str, arguments: Dict) -> str:
    """执行工具并返回结果"""
    fn = TOOL_EXECUTORS.get(tool_name)
    if not fn:
        return f"未知工具: {tool_name}"
    try:
        return fn(arguments)
    except Exception as e:
        return f"工具执行错误: {e}"

def get_tools_prompt() -> str:
    """生成简洁的工具列表文本（用于系统提示中的快速参考）"""
    return """可用工具: read_file, write_file, list_dir, run_cmd, search_files, web_search
你运行在用户本地机器上，有完整的文件系统访问权限。
看到需要读文件/执行命令/搜索代码时，直接用工具！不要说"我无法访问"。
回复简洁有用，中文优先。"""

# 兼容旧代码
TOOLS = TOOL_EXECUTORS
has_tool_call = lambda text: bool(re.search(r'\{["\']tool["\']\s*:', text))

"""
meshctx Chat 工具执行引擎
让 AI 不只是聊天，能真正读文件、跑命令、搜索代码

工具集对标 Hermes: read_file, write_file, search_files, terminal, web
"""
import os, re, json, shlex, subprocess, urllib.request, urllib.parse
from pathlib import Path
from typing import Dict, Optional

# ═══════════════════════════════════════════════════
# 工具定义
# ═══════════════════════════════════════════════════

TOOLS = {
    "read_file": {
        "desc": "读取文件内容。参数: path(文件路径), limit(行数,默认100)",
        "fn": lambda args: _read_file(args.get("path",""), args.get("limit",100)),
        "openai": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "读取文件内容。用于查看代码、配置、日志等文本文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径(绝对或相对)"},
                        "limit": {"type": "integer", "description": "最大显示行数, 默认100", "default": 100},
                    },
                    "required": ["path"],
                },
            },
        },
        "icon": "📖",
    },
    "write_file": {
        "desc": "写入文件。参数: path(文件路径), content(内容)",
        "fn": lambda args: _write_file(args.get("path",""), args.get("content","")),
        "openai": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "写入文件内容。创建或覆盖文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "content": {"type": "string", "description": "要写入的内容"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "icon": "✏️",
    },
    "list_dir": {
        "desc": "列出目录。参数: path(目录路径)",
        "fn": lambda args: _list_dir(args.get("path",".")),
        "openai": {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "列出目录中的文件和子目录",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "目录路径, 默认当前目录", "default": "."},
                    },
                    "required": [],
                },
            },
        },
        "icon": "📁",
    },
    "run_cmd": {
        "desc": "执行终端命令。参数: cmd(命令)",
        "fn": lambda args: _run_cmd(args.get("cmd","")),
        "openai": {
            "type": "function",
            "function": {
                "name": "run_cmd",
                "description": "执行 Shell 终端命令。用于安装依赖、git 操作、构建、运行脚本等",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "要执行的命令"},
                    },
                    "required": ["cmd"],
                },
            },
        },
        "icon": "💻",
    },
    "search_files": {
        "desc": "搜索文件内容。参数: pattern(搜索词), path(目录,默认.), glob(文件过滤,如*.py)",
        "fn": lambda args: _search_files(args.get("pattern",""), args.get("path","."), args.get("glob","*")),
        "openai": {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "搜索文件内容(使用 ripgrep)。按正则模式搜索，支持文件过滤",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "搜索关键词或正则表达式"},
                        "path": {"type": "string", "description": "搜索目录, 默认当前目录", "default": "."},
                        "glob": {"type": "string", "description": "文件过滤, 如 *.py, 默认 *", "default": "*"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        "icon": "🔍",
    },
    "web_search": {
        "desc": "联网搜索网页信息(股票、新闻、天气等实时数据优先用此工具)。参数: query(搜索词)",
        "fn": lambda args: _web_search(args.get("query","")),
        "openai": {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索网页信息。用于查股票、新闻、天气、实时数据等",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                    },
                    "required": ["query"],
                },
            },
        },
        "icon": "🌐",
    },
}

# ── OpenAI 格式工具列表 (供 cli.py 的 _chat_loop 使用) ──
TOOLS_OPENAI = [v["openai"] for v in TOOLS.values()]

# ── 工具图标映射 ──
TOOL_ICONS = {name: info["icon"] for name, info in TOOLS.items()}

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
        # 确保PATH包含基本工具路径(WSL/Docker/最小环境)
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

def _search_files(pattern: str, path: str, glob: str) -> str:
    try:
        p = Path(path).expanduser()
        matches = []
        for f in p.rglob(glob):
            if f.is_file() and f.stat().st_size < 1024*1024:  # 跳过>1MB文件
                try:
                    content = f.read_text(errors="replace")
                    if pattern.lower() in content.lower():
                        matches.append(str(f))
                except Exception:
                    pass
        if not matches:
            return f"未找到包含 '{pattern}' 的文件"
        return "\n".join(matches[:20])
    except Exception as e:
        return f"搜索失败: {e}"

def _web_search(query: str) -> str:
    # 自动追加日期: 含"今天/今日/最新/实时"时加当天日期
    date_keywords = ['今天', '今日', '最新', '实时', '当前', '目前']
    if any(k in query for k in date_keywords):
        from datetime import datetime
        today = datetime.now().strftime('%Y年%m月%d日')
        if today not in query:
            query = f"{query} {today}"
    # 尝试DuckDuckGo，失败则回退到百度
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
        pass
    # 回退: Bing搜索
    try:
        url = f"https://cn.bing.com/search?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode()
        # 提取Bing搜索结果摘要
        snippets = re.findall(r'<p[^>]* class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'<div class="b_caption"[^>]*>.*?<p>(.*?)</p>', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'<span class="c-abstract"[^>]*>(.*?)</span>', html, re.DOTALL)
        results = [re.sub(r'<[^>]+>', '', s).strip()[:200] for s in snippets[:5] if s.strip()]
        return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results)) if results else "无搜索结果"
    except Exception as e:
        return f"搜索失败: {e}"


# ═══════════════════════════════════════════════════
# 工具执行循环
# ═══════════════════════════════════════════════════

def execute_tool(response_text: str) -> Optional[str]:
    """从AI回复中提取工具调用并执行 (旧版兼容)"""
    # 匹配格式: {"tool": "xxx", "path": "yyy", ...}
    match = re.search(r'\{["\']tool["\']\s*:\s*["\'](\w+)["\'](.*?)\}', response_text, re.DOTALL)
    if not match:
        return None
    
    tool_name = match.group(1)
    args_str = match.group(2)
    
    if tool_name not in TOOLS:
        return f"未知工具: {tool_name}"
    
    # 解析参数
    args = {}
    for k in re.findall(r'["\'](\w+)["\']\s*:\s*["\']([^"\']*?)["\']', args_str):
        args[k[0]] = k[1]
    
    result = TOOLS[tool_name]["fn"](args)
    return f"[工具: {tool_name}]\n{result}"


def exec_tool(name: str, args: dict) -> str:
    """直接执行工具 (供 cli.py _chat_loop 调用)"""
    if name not in TOOLS:
        return f"未知工具: {name}"
    return TOOLS[name]["fn"](args)


def get_tools_prompt() -> str:
    """生成工具提示"""
    tools_desc = []
    for name, info in TOOLS.items():
        tools_desc.append(f"  {name}: {info['desc']}")
    
    return f"""你可以使用以下工具来完成任务。调用格式：在回复中包含 JSON:
{{"tool": "工具名", "参数名": "参数值", ...}}

可用工具:
{chr(10).join(tools_desc)}

重要:
1. 如果用户要求读文件、搜代码、执行命令等操作，不要说你做不到——直接使用工具！
2. 联网搜索、查股票、查新闻、查天气等实时数据，必须用 web_search 工具，不要用 run_cmd+curl！
3. 用工具执行后根据结果回复用户。"""


def has_tool_call(text: str) -> bool:
    return bool(re.search(r'\{["\']tool["\']\s*:', text))

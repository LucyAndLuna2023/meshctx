"""
meshctx Chat 工具引擎 v2 — 原生 OpenAI function calling 格式
对标 Hermes: read_file, write_file, search_files, terminal, web_search, list_dir
"""
import logging
import os, re, json, shlex, subprocess, urllib.request, urllib.parse
from pathlib import Path
from typing import Dict, Optional, List

logger = logging.getLogger("meshctx.chat_tools")

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
        # 安全: shell=False + shlex.split，避免命令注入（模型输入不直接进 shell）
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

def _get_proxy() -> str:
    """读取搜索代理配置: meshctx.yaml > env > None"""
    import yaml
    config_paths = [
        Path(__file__).parent.parent / "meshctx.yaml",
        Path.home() / ".meshctx" / "config.yaml",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                cfg = yaml.safe_load(cp.read_text())
                proxy = cfg.get("search", {}).get("proxy", "")
                if proxy:
                    return proxy
            except Exception:
                pass
    # 环境变量回退
    for env_var in ["ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"]:
        val = os.environ.get(env_var, "")
        if val:
            return val
    return ""


def _web_search(query: str) -> str:
    """多引擎网页搜索: ddgs(代理翻墙) → cn.bing.com(直连兜底)"""
    date_keywords = ['今天', '今日', '最新', '实时', '当前', '目前']
    if any(k in query for k in date_keywords):
        from datetime import datetime
        today = datetime.now().strftime('%Y年%m月%d日')
        if today not in query:
            query = f"{query} {today}"

    proxy = _get_proxy()

    # 引擎1: ddgs 库 (DuckDuckGo API, 质量最高, 需代理翻墙)
    if proxy:
        try:
            result = _search_ddgs_api(query, proxy)
            if result:
                return result
        except Exception:
            logger.debug("chat_tools ddgs error", exc_info=True)

    # 引擎2: cn.bing.com 直连 (中文/兜底)
    try:
        result = _search_bing_cn(query)
        if result:
            return result
    except Exception:
        logger.debug("chat_tools bing cn error", exc_info=True)

    return "搜索失败: 所有搜索引擎均不可用"


def _search_ddgs_api(query: str, proxy: str) -> str:
    """DuckDuckGo API — 通过 ddgs 库, 质量最高"""
    # 环境变量仅在函数内临时设置（finally 恢复），避免污染全局 env（004 隐患#6 同款问题）
    import os as _os
    _saved = {k: _os.environ.get(k) for k in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY")}
    for _k in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        _os.environ[_k] = proxy
    try:
        try:
            from ddgs import DDGS
            with DDGS(timeout=15) as ddgs:
                results = list(ddgs.text(query, max_results=6))
            if not results:
                return ""
            lines = []
            for i, r in enumerate(results):
                title = r.get("title", "")
                body = r.get("body", "")[:200]
                href = r.get("href", "")
                if title:
                    lines.append(f"{i+1}. {title}\n   {body}\n   {href}")
            return "\n".join(lines) if lines else ""
        except ImportError:
            return ""
        except Exception as e:
            return ""
    finally:
        # 恢复环境变量，避免污染全局
        for _k, _v in _saved.items():
            if _v is None:
                _os.environ.pop(_k, None)
            else:
                _os.environ[_k] = _v



def _search_bing_cn(query: str) -> str:
    """cn.bing.com 直连 — 中文内容"""
    url = f"https://cn.bing.com/search?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode(errors='replace')
    return _parse_bing_html(raw)


def _parse_bing_html(raw: str) -> str:
    """解析 Bing HTML 搜索结果"""
    import html as _html
    html_text = _html.unescape(raw)
    algos = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html_text, re.DOTALL)
    if not algos:
        return ""
    results = []
    for algo in algos[:8]:
        title_m = re.search(r'<h2[^>]*><a[^>]*>(.*?)</a>', algo, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
        url_m = re.search(r'<a[^>]*href="(https?://[^"]+)"', algo)
        url_text = url_m.group(1) if url_m else ""
        cap_m = re.search(r'<div class="b_caption"[^>]*>(.*?)</div>', algo, re.DOTALL)
        snippet = ""
        if cap_m:
            raw_text = re.sub(r'<[^>]+>', ' ', cap_m.group(1))
            snippet = re.sub(r'\\s+', ' ', raw_text).strip()[:250]
        if title and snippet:
            results.append(f"{len(results)+1}. {title}\n   {snippet}\n   {url_text}")
        elif title:
            results.append(f"{len(results)+1}. {title}\n   {url_text}")
    return "\n".join(results[:6]) if results else ""

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


def trim_messages(messages: List[Dict], max_len: int = 40, keep: int = 30) -> List[Dict]:
    """公共消息清理：截断 + 保证 assistant(tool_calls)↔tool 配对完整。

    CLI 与 UI 统一后端共用，防止长对话/多轮工具调用后消息无限膨胀
    导致 token 超限。保留 system 在首位，剔除孤立的 tool 消息。
    """
    if len(messages) <= max_len:
        return messages
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    recent = messages[-keep:] if keep else messages[-max_len:]
    # 去掉开头的孤立 tool 消息（缺少前置 assistant+tool_calls）
    while recent and recent[0].get("role") == "tool":
        recent.pop(0)
    # 收集所有 assistant 声明的 tool_call_id，过滤无匹配的孤立 tool 消息
    known_tool_call_ids = set()
    for m in recent:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                known_tool_call_ids.add(tc.get("id", ""))
    filtered = [m for m in recent
                if not (m.get("role") == "tool"
                        and m.get("tool_call_id") not in known_tool_call_ids)]
    out = []
    if system:
        out.append(system)
    out.extend(filtered)
    return out

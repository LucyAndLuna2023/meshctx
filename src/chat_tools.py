"""
meshctx Chat 工具执行引擎
让 AI 不只是聊天，能真正读文件、跑命令、搜索代码

工具集对标 Hermes: read_file, write_file, search_files, terminal, web
"""
import os, re, json, subprocess, urllib.request
from pathlib import Path
from typing import Dict, Optional

# ═══════════════════════════════════════════════════
# 工具定义
# ═══════════════════════════════════════════════════

TOOLS = {
    "read_file": {
        "desc": "读取文件内容。参数: path(文件路径), limit(行数,默认100)",
        "fn": lambda args: _read_file(args.get("path",""), args.get("limit",100)),
    },
    "write_file": {
        "desc": "写入文件。参数: path(文件路径), content(内容)",
        "fn": lambda args: _write_file(args.get("path",""), args.get("content","")),
    },
    "list_dir": {
        "desc": "列出目录。参数: path(目录路径)",
        "fn": lambda args: _list_dir(args.get("path",".")),
    },
    "run_cmd": {
        "desc": "执行终端命令。参数: cmd(命令)",
        "fn": lambda args: _run_cmd(args.get("cmd","")),
    },
    "search_files": {
        "desc": "搜索文件内容。参数: pattern(搜索词), path(目录,默认.), glob(文件过滤,如*.py)",
        "fn": lambda args: _search_files(args.get("pattern",""), args.get("path","."), args.get("glob","*")),
    },
    "web_search": {
        "desc": "搜索网页(需要联网)。参数: query(搜索词)",
        "fn": lambda args: _web_search(args.get("query","")),
    },
}

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
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
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
                except:
                    pass
        if not matches:
            return f"未找到包含 '{pattern}' 的文件"
        return "\n".join(matches[:20])
    except Exception as e:
        return f"搜索失败: {e}"

def _web_search(query: str) -> str:
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.request.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "meshctx/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode()
        # 提取摘要
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)<', html, re.DOTALL)
        results = [re.sub(r'<[^>]+>', '', s).strip()[:200] for s in snippets[:5]]
        return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results)) if results else "无搜索结果"
    except Exception as e:
        return f"搜索失败: {e}"


# ═══════════════════════════════════════════════════
# 工具执行循环
# ═══════════════════════════════════════════════════

def execute_tool(response_text: str) -> Optional[str]:
    """从AI回复中提取工具调用并执行"""
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


def get_tools_prompt() -> str:
    """生成工具提示"""
    tools_desc = []
    for name, info in TOOLS.items():
        tools_desc.append(f"  {name}: {info['desc']}")
    
    return f"""你可以使用以下工具来完成任务。调用格式：在回复中包含 JSON:
{{"tool": "工具名", "参数名": "参数值", ...}}

可用工具:
{chr(10).join(tools_desc)}

重要: 如果用户要求读文件、搜代码、执行命令等操作，
不要说你做不到——直接使用工具！用工具执行后根据结果回复用户。"""


def has_tool_call(text: str) -> bool:
    return bool(re.search(r'\{["\']tool["\']\s*:', text))

"""
meshctx Chat 工具引擎 v3 — 11工具 · 对标 Codex / Claude Code
新增: patch, edit_file, git_diff, git_log, git_show, web_extract, lint_check
"""
import os, re, json, shlex, subprocess, urllib.request, urllib.parse, hashlib
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
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=os.getcwd(), env=env,
                           executable='/bin/bash')
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
                except:
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
    except:
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
# v3 新增工具 — 对标 Codex / Claude Code
# ═══════════════════════════════════════════════════

def _patch(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """应用 find-and-replace 补丁到文件 — 对标 Hermes patch 工具"""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"文件不存在: {path}"
        content = p.read_text(encoding="utf-8")
        count = content.count(old_string)
        if count == 0:
            return f"❌ 未找到匹配文本: {old_string[:60]}..."
        if not replace_all and count > 1:
            return f"❌ 匹配到 {count} 处，请缩小范围。唯一匹配或设置 replace_all=true"
        new_content = content.replace(old_string, new_string)
        p.write_text(new_content, encoding="utf-8")
        changes = count if replace_all else 1
        return f"✅ 已修补: {path} ({changes}处替换)"
    except Exception as e:
        return f"补丁失败: {e}"

def _edit_file(path: str, old_string: str, new_string: str) -> str:
    """精确行编辑 — 替换文件中的唯一匹配文本。比 patch 更安全。"""
    return _patch(path, old_string, new_string, replace_all=False)

def _git_diff(path: str = ".", staged: bool = False) -> str:
    """获取 git diff"""
    try:
        cmd = f"git diff{' --staged' if staged else ''} -- {shlex.quote(path)}"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, executable='/bin/bash')
        out = r.stdout[:5000]
        return out or "(无变更)"
    except subprocess.TimeoutExpired:
        return "git diff 超时"
    except Exception as e:
        return f"git diff 失败: {e}"

def _git_log(path: str = ".", limit: int = 10) -> str:
    """获取 git log"""
    try:
        cmd = f"git log --oneline -{limit} -- {shlex.quote(path)}"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, executable='/bin/bash')
        return r.stdout[:3000] or "(无提交)"
    except Exception as e:
        return f"git log 失败: {e}"

def _git_show(commit: str = "HEAD", path: str = "") -> str:
    """查看某次 commit 的详情"""
    try:
        target = f"{commit} -- {shlex.quote(path)}" if path else commit
        cmd = f"git show --stat {target}"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, executable='/bin/bash')
        return r.stdout[:3000] or "(无内容)"
    except Exception as e:
        return f"git show 失败: {e}"

def _web_extract(url: str) -> str:
    """提取网页内容为纯文本"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "meshctx/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode(errors="replace")
        # 简单提取文本：去标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:4000] if text else "(空页面)"
    except Exception as e:
        return f"网页提取失败: {e}"

def _lint_check(path: str, linter: str = "auto") -> str:
    """对文件运行 linter"""
    p = Path(path).expanduser()
    if not p.exists():
        return f"文件不存在: {path}"
    suffix = p.suffix.lower()
    if linter == "auto":
        if suffix == ".py":
            linter = "pylint"
        elif suffix in (".js", ".jsx"):
            linter = "eslint"
        elif suffix == ".sh":
            linter = "shellcheck"
        elif suffix in (".go",):
            linter = "gofmt"
        else:
            return f"无法自动检测 linter: {suffix}"
    try:
        if linter == "pylint":
            cmd = f"python3 -m pylint --exit-zero '{path}' 2>&1 | tail -20"
        elif linter == "flake8":
            cmd = f"python3 -m flake8 '{path}' 2>&1 | tail -20"
        elif linter == "shellcheck":
            cmd = f"shellcheck '{path}' 2>&1 | tail -20"
        else:
            cmd = f"{linter} '{path}' 2>&1 | tail -20"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, executable='/bin/bash')
        return r.stdout[:3000] or "(无诊断)"
    except Exception as e:
        return f"Lint 失败: {e}"

# ═══════════════════════════════════════════════════
# OpenAI Function Calling 工具定义（11工具）
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
            "description": "写入文件（覆盖）。会自动创建父目录。",
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
            "name": "patch",
            "description": "安全的结构化编辑：在文件中查找并替换唯一文本。用于精确修改代码片段。比 write_file 更安全。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原文本（必须唯一）"},
                    "new_string": {"type": "string", "description": "替换后的新文本"},
                    "replace_all": {"type": "boolean", "description": "替换所有匹配（默认false=必须唯一）", "default": False}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "精确行编辑：替换文件中的唯一匹配文本。比 patch 更好理解的别名。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原文本"},
                    "new_string": {"type": "string", "description": "替换后的新文本"}
                },
                "required": ["path", "old_string", "new_string"]
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
    {
        "type": "function",
        "function": {
            "name": "web_extract",
            "description": "提取网页内容为纯文本。用于获取文档、API参考、论文等网页正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页URL"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "显示文件的 git diff 变更。用于查看未提交的改动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件或目录路径，默认当前目录", "default": "."},
                    "staged": {"type": "boolean", "description": "是否查看暂存区变更", "default": False}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "查看 git 提交历史。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件或目录路径，默认当前目录", "default": "."},
                    "limit": {"type": "integer", "description": "最多显示条数，默认10", "default": 10}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_show",
            "description": "查看某次 commit 的详细内容和文件变更。",
            "parameters": {
                "type": "object",
                "properties": {
                    "commit": {"type": "string", "description": "commit hash，默认HEAD", "default": "HEAD"},
                    "path": {"type": "string", "description": "限定文件路径", "default": ""}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lint_check",
            "description": "对代码文件运行 linter 诊断。自动检测语言并选择合适工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "linter": {"type": "string", "description": "linter名称: pylint/flake8/eslint/shellcheck/gofmt，默认auto自动检测", "default": "auto"}
                },
                "required": ["path"]
            }
        }
    },
]

# 工具执行器映射
TOOL_EXECUTORS = {
    "read_file": lambda args: _read_file(args.get("path", ""), args.get("limit", 100)),
    "write_file": lambda args: _write_file(args.get("path", ""), args.get("content", "")),
    "patch": lambda args: _patch(args.get("path", ""), args.get("old_string", ""), args.get("new_string", ""), args.get("replace_all", False)),
    "edit_file": lambda args: _edit_file(args.get("path", ""), args.get("old_string", ""), args.get("new_string", "")),
    "list_dir": lambda args: _list_dir(args.get("path", ".")),
    "run_cmd": lambda args: _run_cmd(args.get("cmd", "")),
    "search_files": lambda args: _search_files(args.get("pattern", ""), args.get("path", "."), args.get("glob", "*")),
    "web_search": lambda args: _web_search(args.get("query", "")),
    "web_extract": lambda args: _web_extract(args.get("url", "")),
    "git_diff": lambda args: _git_diff(args.get("path", "."), args.get("staged", False)),
    "git_log": lambda args: _git_log(args.get("path", "."), args.get("limit", 10)),
    "git_show": lambda args: _git_show(args.get("commit", "HEAD"), args.get("path", "")),
    "lint_check": lambda args: _lint_check(args.get("path", ""), args.get("linter", "auto")),
}

TOOL_ICONS = {
    "read_file": "📖", "write_file": "📝", "patch": "🩹", "edit_file": "✏️",
    "list_dir": "📂", "run_cmd": "⚡", "search_files": "🔍",
    "web_search": "🌐", "web_extract": "📥",
    "git_diff": "📊", "git_log": "📜", "git_show": "🔎",
    "lint_check": "🧹",
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
    return """可用工具(11个):
  文件: read_file, write_file, patch, edit_file, list_dir, search_files
  终端: run_cmd
  网络: web_search, web_extract
  Git:  git_diff, git_log, git_show
  诊断: lint_check

你运行在用户本地机器上，有完整的文件系统访问权限。
编辑代码优先用 patch/edit_file（安全的结构化编辑），不要用 write_file 覆盖全文件！
看到需要读文件/执行命令/搜索代码时，直接用工具！不要说"我无法访问"。
回复简洁有用，中文优先。"""

# 兼容旧代码
TOOLS = TOOL_EXECUTORS
has_tool_call = lambda text: bool(re.search(r'\{["\']tool["\']\s*:', text))

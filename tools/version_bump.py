#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 版本 bump 工具 — 原子两阶段 (v3.133.4 起).

用法: python3 tools/version_bump.py <旧版本> <新版本>

阶段 1 (内存): 全部替换在内存中计算, 不落盘
阶段 2 (扫描): 对"变更文件的新文本 + 未变更文件的磁盘文本"做残留扫描
  · 功能性残留非零 → 打印清单并 exit 1, **一个文件都不写** (002codex round63:
    旧版"先改 21 文件再 exit 1"的非原子缺陷根除)
  · 豁免: 行首注释 (#, //, <!--) + AST 识别的 docstring 行 (round61 P2-3b)
阶段 3 (落盘): 扫描全绿后才统一写入

保护:
  · meshctx_desktop.py 不做全局 replace (HOST IP 曾被版本号污染, I-8 同族)
    → 仅精确替换 DESKTOP_VERSION 常量行 (含 v 前缀, round61 P2-3a)
  · 版本线唯一化: 3.133.x (002zcode tag 对位裁定)
"""
import ast
import pathlib
import re
import sys

OLD, NEW = sys.argv[1], sys.argv[2]

FILES = ["pyproject.toml", "src/__init__.py", "src/core/__init__.py", "package.json",
         "version_info.txt", "build.bat", "meshctx_setup.nsi", "meshctx_desktop.spec",
         "docs/llms.txt", "tools/meshctx_support_bot.py",
         "install.sh", "docs/install.sh", "install-mac.sh", "docs/install-mac.sh",
         "install-edition.sh", "docs/install-edition.sh",
         "install.bat", "docs/install.bat", "install-edition.bat", "docs/install-edition.bat"]


def tuple_of(v):
    p = v.split(".")
    p += ["0"] * (4 - len(p))  # 补齐四段, 不再额外加 ", 0" (双零 bug: 五段永失配)
    return "(" + ", ".join(p) + ")"


def docstring_lines(text):
    """AST 识别 module/class/func 首语句 docstring 的行号集合 (解析失败=空集)."""
    lines = set()
    try:
        tree = ast.parse(text)
    except Exception:
        return lines
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                lines.update(range(body[0].lineno,
                                   (body[0].end_lineno or body[0].lineno) + 1))
    return lines


# ── 阶段 1: 内存计算 ─────────────────────────────────────
pending = {}          # path -> new_text (仅内容有变者)
for f in FILES:
    p = pathlib.Path(f)
    if not p.is_file():
        continue
    t = p.read_text(encoding="utf-8", errors="replace")
    nt = t.replace(f"v{OLD}", f"v{NEW}").replace(OLD, NEW)
    nt = nt.replace(tuple_of(OLD), tuple_of(NEW))
    if nt != t:
        pending[f] = nt

dp = pathlib.Path("meshctx_desktop.py")
t = dp.read_text(encoding="utf-8", errors="replace")
m = re.search(r'DESKTOP_VERSION = "(v[^"]+)"', t)
if m:
    nt = t.replace(f'DESKTOP_VERSION = "{m.group(1)}"',
                   f'DESKTOP_VERSION = "v{NEW}"')
    if nt != t:
        pending[str(dp)] = nt
else:
    print("⚠ DESKTOP_VERSION 常量未找到 — desktop 版本未 bump (人工检查)")

# ── 阶段 2: 残留扫描 (内存文本优先, 不写盘) ───────────────
scan_paths = (list(pathlib.Path("src").rglob("*.py"))
              + list(pathlib.Path("tools").glob("*.py"))
              + list(pathlib.Path(".").glob("*.py"))
              + list(pathlib.Path("templates").glob("*.html"))
              + list(pathlib.Path(".").glob("*.md")))
left = []
for p in scan_paths:
    sp = str(p)
    if "CHANGELOG" in sp or "INCIDENTS" in sp:
        continue
    if sp in pending:
        t = pending[sp]                    # 扫描"将要写入"的新文本
    else:
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
    doc_lines = docstring_lines(t)
    hits = [ln.strip() for i, ln in enumerate(t.splitlines(), 1)
            if OLD in ln and i not in doc_lines
            and not ln.strip().startswith(("#", "//", "<!--"))]
    if hits:
        left.append(f"{sp}: {hits[0][:80]}")

if left:
    print(f"⚠ 旧版本号功能性残留 — 原子中止, 未写任何文件:")
    for x in left:
        print(f"  {x}")
    sys.exit(1)

# ── 阶段 3: 落盘 ────────────────────────────────────────
for sp, nt in pending.items():
    pathlib.Path(sp).write_text(nt, encoding="utf-8")
print(f"bump {OLD} → {NEW}: {len(pending)} 文件, 功能性残留 0 ✅ (原子两阶段)")

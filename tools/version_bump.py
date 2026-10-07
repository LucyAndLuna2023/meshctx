#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 版本 bump 工具 — 带保护清单 (v3.133.2 起).

用法: python3 tools/version_bump.py 3.133.2 3.134.0
保护:
  · meshctx_desktop.py 不做全局 replace (HOST IP 曾被版本号污染致 bind 失败, I-8 同族)
    → 仅精确替换 DESKTOP_VERSION 常量行
  · 版本残留扫描: bump 后全仓 grep 旧版本号, 残留非零即 exit 1
"""
import pathlib
import re
import sys

OLD, NEW = sys.argv[1], sys.argv[2]

FILES = ["pyproject.toml","src/__init__.py","src/core/__init__.py","package.json","version_info.txt",
         "build.bat","meshctx_setup.nsi","meshctx_desktop.spec","docs/llms.txt",
         "tools/meshctx_support_bot.py","install.sh","docs/install.sh","install-mac.sh","docs/install-mac.sh",
         "install-edition.sh","docs/install-edition.sh","install.bat","docs/install.bat",
         "install-edition.bat","docs/install-edition.bat"]

def tuple_of(v):
    p = v.split(".")
    return "(" + ", ".join(p + ["0"] * (4 - len(p))) + ", 0)"

n = 0
for f in FILES:
    p = pathlib.Path(f)
    if not p.is_file():
        continue
    t = p.read_text(encoding="utf-8", errors="replace")
    nt = t.replace(f"v{OLD}", f"v{NEW}").replace(OLD, NEW)
    nt = nt.replace(tuple_of(OLD), tuple_of(NEW))  # filevers 等 tuple 形态
    if nt != t:
        p.write_text(nt, encoding="utf-8")
        n += 1

# desktop.py: 仅精确替换 DESKTOP_VERSION 常量 (永不全局 replace — HOST IP 保护)
# 002meshctx round61 P2-3a 修复: 捕获组含 v 前缀, replace 目标带 v (原失配永不生效)
dp = pathlib.Path("meshctx_desktop.py")
t = dp.read_text(encoding="utf-8", errors="replace")
m = re.search(r'DESKTOP_VERSION = "(v[^"]+)"', t)
if m:
    t = t.replace(f'DESKTOP_VERSION = "{m.group(1)}"',
                  f'DESKTOP_VERSION = "v{NEW}"')
    dp.write_text(t, encoding="utf-8")
    n += 1
else:
    print("⚠ DESKTOP_VERSION 常量未找到 — desktop 版本未 bump (人工检查)")

# 残留扫描 (002meshctx P2-3b/c 修复):
#  · 只报非注释行 (功能性版本串), 注释行豁免 — 修复"扫描自锁" (自身注释含旧版本号致 bump 必 exit1)
#  · 范围: src/**/*.py + tools/*.py + 根 *.py + *.md + templates/*.html
left = []
scan_paths = (list(pathlib.Path("src").rglob("*.py"))
              + list(pathlib.Path("tools").glob("*.py"))
              + list(pathlib.Path(".").glob("*.py"))
              + list(pathlib.Path("templates").glob("*.html"))
              + list(pathlib.Path(".").glob("*.md")))
for p in scan_paths:
    sp = str(p)
    if "CHANGELOG" in sp or "INCIDENTS" in sp:
        continue
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    hits = [ln.strip() for ln in t.splitlines()
            if OLD in ln and not ln.strip().startswith(("#", "//", "<!--"))]
    if hits:
        left.append(f"{sp}: {hits[0][:80]}")
if left:
    print("⚠ 旧版本号功能性残留 (非注释行):")
    for x in left:
        print(f"  {x}")
    sys.exit(1)
print(f"bump {OLD} → {NEW}: {n} 文件, 功能性残留 0 ✅")

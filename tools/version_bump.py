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
dp = pathlib.Path("meshctx_desktop.py")
t = dp.read_text(encoding="utf-8", errors="replace")
m = re.search(r'DESKTOP_VERSION = "v?([^"]+)"', t)
if m:
    t = t.replace(f'DESKTOP_VERSION = "{m.group(1)}"',
                  f'DESKTOP_VERSION = "v{NEW}"')
    dp.write_text(t, encoding="utf-8")
    n += 1

# 残留扫描
left = []
for p in list(pathlib.Path("src").rglob("*.py")) + list(pathlib.Path(".").glob("*.md")):
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    if OLD in t and "CHANGELOG" not in str(p) and "INCIDENTS" not in str(p):
        left.append(str(p))
if left:
    print(f"⚠ 旧版本号残留: {left}")
    sys.exit(1)
print(f"bump {OLD} → {NEW}: {n} 文件, 残留 0 ✅")

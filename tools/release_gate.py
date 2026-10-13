#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 发版门禁 (release gate) — v3.135.5 落地, 002meshctx round71-74 催办 (应验 8 次).

pre-tag 四检 (任何一项失败 exit 1, 阻断 tag/push):
  1. 版本对位: 六资产逐文件含当前版本号 (bump 原子中止/tag 错位九犯根治)
  2. CHANGELOG: 头部含当前版本条目 (七/八/九犯根治)
  3. 测试绿: 定向守门跑通 (task_cards+G10+cascade)
  4. KNOWN_ISSUES: 新挂账须在仓内台账 (002codex 阻断②根治)

用法: python3 tools/release_gate.py 3.135.5   (tag 前跑)
"""
import pathlib
import re
import subprocess
import sys

VER = sys.argv[1] if len(sys.argv) > 1 else ""
if not re.fullmatch(r"\d+\.\d+\.\d+", VER or ""):
    print("用法: release_gate.py X.Y.Z"); sys.exit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
fail = []

# 1. 版本对位 (六资产)
assets = {
    "pyproject.toml": f'version = "{VER}"',
    "package.json": f'"version": "{VER}"',
    "src/__init__.py": f'__version__ = "{VER}"',
    "install.sh": f'VERSION="{VER}"',
    "install-mac.sh": f'VERSION="{VER}"',
    "meshctx_desktop.py": f'DESKTOP_VERSION = "v{VER}"',
}
for f, needle in assets.items():
    t = (ROOT / f).read_text(encoding="utf-8", errors="replace")
    ok = needle in t
    print(f"  [{'✓' if ok else '✗'}] 版本对位 {f}: {needle}")
    if not ok:
        fail.append(f"版本错位: {f}")

# 2. CHANGELOG 条目
ch = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
ok = f"## [v{VER}]" in ch
print(f"  [{'✓' if ok else '✗'}] CHANGELOG [v{VER}] 条目")
if not ok:
    fail.append(f"CHANGELOG 缺 [v{VER}] 条目 (九犯线)")

# 3. 定向守门
r = subprocess.run([sys.executable, "-m", "pytest",
                    "tests/test_task_cards.py", "tests/test_project_integrity.py",
                    "tests/test_cascade_router.py", "-q", "-o", "addopts="],
                   cwd=ROOT, capture_output=True, text=True, timeout=600)
ok = r.returncode == 0
tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else "(无输出)"
print(f"  [{'✓' if ok else '✗'}] 定向守门: {tail[:70]}")
if not ok:
    fail.append(f"定向守门红: {tail[:80]}")

# 4. KNOWN_ISSUES 在位 (仓内台账载体)
ki = ROOT / "KNOWN_ISSUES.md"
ok = ki.exists() and len(ki.read_text(encoding="utf-8", errors="replace")) > 100
print(f"  [{'✓' if ok else '✗'}] KNOWN_ISSUES.md 台账在位")
if not ok:
    fail.append("KNOWN_ISSUES.md 缺失")

# post-tag 提醒
print("\n⚠ post-tag 第五检 (发版后): release body 非空且含完整 40 位 SHA — curl PATCH 后必须验证返回值")

if fail:
    print(f"\n🔴 发版门禁拦截 ({len(fail)} 项):")
    for x in fail:
        print(f"  - {x}")
    sys.exit(1)
print(f"\n🟢 发版门禁全过 — {VER} 可 tag")

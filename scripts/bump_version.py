#!/usr/bin/env python3
"""meshctx 版本发布脚本 — 统一修改所有版本引用位置

用法:
  python3 scripts/bump_version.py 3.115.19
  python3 scripts/bump_version.py 3.115.19 --dry-run

需要修改的位置:
  1. src/__init__.py          — __version__ (Python 导入)
  2. src/core/__init__.py     — __version__ (health 端点读取)
  3. src/main.py              — FastAPI app.version
  4. docs/index.html          — 主页标题
  5. docs/docs.html           — 文档页
"""

import re, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES = [
    ("src/__init__.py",      r'^__version__\s*=\s*"[^"]*"', '__version__ = "{}"'),
    ("src/core/__init__.py", r'^__version__\s*=\s*"[^"]*"', '__version__ = "{}"'),
    ("src/main.py",          r'version\s*=\s*"[^"]*"',       'version="{}"'),
    ("docs/index.html",      r'v\d+\.\d+\.\d+',             'v{}'),
    ("docs/docs.html",       r'MeshCtx\s+v\d+\.\d+\.\d+',   'MeshCtx v{}'),
]


def get_current_version():
    """从 src/__init__.py 读取当前版本（唯一权威源）"""
    init = ROOT / "src/__init__.py"
    text = init.read_text()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def bump(ver: str, dry_run: bool = False):
    """修改所有文件中的版本号"""
    current = get_current_version()
    if not current:
        print("❌ 无法读取当前版本")
        return 1
    print(f"📦 当前版本: {current} → 目标: {ver}")

    for relpath, pattern, template in VERSION_FILES:
        path = ROOT / relpath
        text = path.read_text()

        # 查找所有匹配
        matches = list(re.finditer(pattern, text, re.MULTILINE))
        if not matches:
            print(f"  ⚠️  {relpath}: 未找到版本号")
            continue

        new_text = text
        for m in reversed(matches):
            old_str = m.group(0)
            new_str = template.format(ver)
            # 只在模板是完整替换时用模板，否则用 v{ver} 替换
            if template == 'v{}':
                new_str = f'v{ver}'
            elif template == 'MeshCtx v{}':
                new_str = f'MeshCtx v{ver}'
            new_text = new_text[:m.start()] + new_str + new_text[m.end():]

        if new_text == text:
            print(f"  ✅ {relpath}: 已是 {ver}")
        else:
            old_val = matches[0].group(0)
            new_val = template.format(ver)
            if template == 'v{}':
                new_val = f'v{ver}'
            elif template == 'MeshCtx v{}':
                new_val = f'MeshCtx v{ver}'
            if dry_run:
                print(f"  🔍 {relpath}: {old_val} → {new_val}")
            else:
                path.write_text(new_text)
                print(f"  ✅ {relpath}: 已更新 {old_val} → {new_val}")

    if dry_run:
        print("\n🔍 --dry-run 模式，未实际修改")
    else:
        print(f"\n✅ 版本更新完成: {current} → {ver}")
        print("   请 git diff 确认后 commit")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <新版本号> [--dry-run]")
        print(f"当前版本: {get_current_version()}")
        sys.exit(1)

    new_ver = sys.argv[1]
    dry = "--dry-run" in sys.argv
    sys.exit(bump(new_ver, dry))

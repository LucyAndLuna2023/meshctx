#!/usr/bin/env python3
"""版本号一键同步 — 本地+服务器+文档全覆盖，缺失文件自动跳过"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def sync_version(new_ver: str):
    major, minor, patch = new_ver.split(".")
    files = {
        # Python 包版本
        "src/__init__.py": [
            (r'__version__\s*=\s*"[^"]*"', f'__version__ = "{new_ver}"'),
        ],
        "src/core/__init__.py": [
            (r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new_ver}"'),
        ],
        # 桌面应用
        "meshctx_desktop.py": [
            (r'TITLE = "meshctx Desktop v[\d.]+"', f'TITLE = "meshctx Desktop v{new_ver}"'),
            (r'meshctx Desktop v[\d.]+ 启动中', f'meshctx Desktop v{new_ver} 启动中'),
        ],
        "package.json": [
            (r'"version":\s*"[^"]+"', f'"version": "{new_ver}"'),
        ],
        # NSIS 安装包 (4处: define + VIProductVersion + 2x VIAddVersionKey)
        "meshctx_setup.nsi": [
            (r'!define VERSION "[^"]+"', f'!define VERSION "{new_ver}"'),
            (r'VIProductVersion "[\d.]+"', f'VIProductVersion "{major}.{minor}.{patch}.0"'),
            (r'VIAddVersionKey "FileVersion" "[^"]+"', f'VIAddVersionKey "FileVersion" "{new_ver}"'),
            (r'VIAddVersionKey "ProductVersion" "[^"]+"', f'VIAddVersionKey "ProductVersion" "{new_ver}"'),
        ],
        # PyInstaller spec (macOS)
        "meshctx_desktop.spec": [
            (r"'CFBundleShortVersionString': '[^']+'", f"'CFBundleShortVersionString': '{new_ver}'"),
            (r"'CFBundleVersion': '[^']+'", f"'CFBundleVersion': '{new_ver}'"),
        ],
        # Windows 版本信息
        "version_info.txt": [
            (r"filevers=\(\d+,\s*\d+,\s*\d+", f"filevers=({major}, {minor}, {patch}"),
            (r"prodvers=\(\d+,\s*\d+,\s*\d+", f"prodvers=({major}, {minor}, {patch}"),
            (r"u'FileVersion', u'[^']+'", f"u'FileVersion', u'{new_ver}'"),
            (r"u'ProductVersion', u'[^']+'", f"u'ProductVersion', u'{new_ver}'"),
        ],
        # 安装脚本
        "install.sh": [
            (r'VERSION="[^"]+"', f'VERSION="{new_ver}"'),
        ],
        "docs/install.sh": [
            (r'VERSION="[^"]+"', f'VERSION="{new_ver}"'),
        ],
        # 文档
        "docs/index.html": [
            (r'(v)\d+\.\d+\.\d+', fr'\g<1>{new_ver}'),
        ],
    }
    ok, skip = 0, 0
    for fpath, patterns in files.items():
        path = ROOT / fpath
        if not path.exists():
            print(f"SKIP: {fpath}")
            skip += 1
            continue
        content = path.read_text()
        for pattern, replacement in patterns:
            content = re.sub(pattern, replacement, content)
        path.write_text(content)
        print(f"OK: {fpath}")
        ok += 1
    print(f"\n→ {ok} synced, {skip} skipped (missing files)")

if __name__ == "__main__":
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    if not ver:
        # Auto-detect: prefer package.json (most reliable across envs)
        for src in ["package.json", "src/core/__init__.py"]:
            p = ROOT / src
            if p.exists():
                m = re.search(r'(\d+\.\d+\.\d+)', p.read_text())
                if m:
                    ver = m.group(1)
                    break
        if not ver:
            ver = "3.115.2"
        print(f"→ Auto-detected: {ver}")
    sync_version(ver)
    print(f"\n✓ 版本已同步到 {ver}")

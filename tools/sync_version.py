#!/usr/bin/env python3
"""版本号一键同步 — 防止手动更新遗漏"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def sync_version(new_ver: str):
    major, minor, patch = new_ver.split(".")
    files = {
        "src/__init__.py": [
            (r'__version__\s*=\s*"[^"]*"', f'__version__ = "{new_ver}"'),
        ],
        "src/core/__init__.py": [
            (r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new_ver}"'),
        ],
        "version_info.txt": [
            (r"filevers=\(\d+,\s*\d+,\s*\d+", f"filevers=({major}, {minor}, {patch}"),
            (r"prodvers=\(\d+,\s*\d+,\s*\d+", f"prodvers=({major}, {minor}, {patch}"),
            (r"u'FileVersion', u'[^']+'", f"u'FileVersion', u'{new_ver}'"),
            (r"u'ProductVersion', u'[^']+'", f"u'ProductVersion', u'{new_ver}'"),
        ],
        "meshctx_setup.nsi": [
            (r'!define VERSION "[^"]+"', f'!define VERSION "{new_ver}"'),
        ],
        "docs/index.html": [
            (r'(v)\d+\.\d+\.\d+', fr'\g<1>{new_ver}', 1),
        ],
        "meshctx_desktop.spec": [
            (r"'CFBundleShortVersionString': '[^']+'", f"'CFBundleShortVersionString': '{new_ver}'"),
            (r"'CFBundleVersion': '[^']+'", f"'CFBundleVersion': '{new_ver}'"),
        ],
    }
    for fpath, patterns in files.items():
        path = ROOT / fpath
        if not path.exists():
            print(f"SKIP: {fpath} not found")
            continue
        content = path.read_text()
        for pattern, replacement in patterns:
            content = re.sub(pattern, replacement, content)
        path.write_text(content)
        print(f"OK: {fpath}")

if __name__ == "__main__":
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    if not ver:
        # Read current version
        init = (ROOT / "src/core/__init__.py").read_text()
        m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
        ver = m.group(1) if m else "3.33.4"
    sync_version(ver)
    print(f"\n版本已同步到 {ver}")

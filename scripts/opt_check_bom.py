# -*- coding: utf-8 -*-
"""检查目标文件的 BOM / 编码完整性。字节安全版工具链的配套体检。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = [
    "src/__init__.py",
    "src/core/__init__.py",
    "src/main.py",
    "package.json",
    "version_info.txt",
    "src/web_ui.py",
    "src/cli.py",
    "src/model_registry.py",
    "src/work_engine.py",
]

for rel in CHECK:
    p = ROOT / rel
    raw = p.read_bytes()
    bom = raw[:3] == b"\xef\xbb\xbf"
    try:
        raw.decode("utf-8")
        ok = "utf8-ok"
    except UnicodeDecodeError:
        ok = "NOT-UTF8"
    print(f"{rel:32s} BOM={bom!s:5s} {ok} bytes={len(raw)}")

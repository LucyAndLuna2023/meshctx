# -*- coding: utf-8 -*-
"""找 subprocess.* 调用中硬编码 encoding='utf-8' 的位置
(Windows 原生命令输出 GBK → 读取线程 UnicodeDecodeError)。只报告。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr); node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))

for py in sorted(SRC.rglob("*.py")):
    if "__pycache__" in str(py):
        continue
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if dotted(node.func) not in {"subprocess.run", "subprocess.Popen",
                                     "subprocess.check_output", "subprocess.call",
                                     "subprocess.check_call"}:
            continue
        for kw in node.keywords:
            if kw.arg == "encoding" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value in ("utf-8", "utf8"):
                print(f"{py.relative_to(SRC)}:{node.lineno}: {dotted(node.func)}(encoding='utf-8')")

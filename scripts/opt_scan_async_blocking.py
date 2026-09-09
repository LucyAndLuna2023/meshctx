# -*- coding: utf-8 -*-
"""扫描 async def 函数内的阻塞调用 (open/time.sleep/subprocess.run):
阻塞事件循环是 FastAPI 服务最常见的性能问题。只报告, 不修改。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

BLOCKERS = {"open", "time.sleep", "subprocess.run", "subprocess.check_output",
            "subprocess.call", "requests.get", "requests.post", "input"}

def dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))

hits = {}
for py in sorted(SRC.rglob("*.py")):
    if "__pycache__" in str(py):
        continue
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except Exception:
        continue
    for func in ast.walk(tree):
        if not isinstance(func, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                name = dotted_name(node.func)
                if name in BLOCKERS or name.endswith(".sleep") and name.startswith("time"):
                    key = (str(py.relative_to(SRC)), func.name)
                    hits.setdefault(key, set()).add(name)

for (f, fn), names in sorted(hits.items()):
    print(f"{f} :: async {fn} -> {sorted(names)}")
print("TOTAL_ASYNC_FUNC_WITH_BLOCKERS:", len(hits))

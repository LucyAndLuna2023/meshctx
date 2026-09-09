# -*- coding: utf-8 -*-
"""校验 src/core/__init__.py 的 _known 符号映射与真实模块的一致性。

找出: ① 重复键 ② 映射中声明但模块中不存在的符号 (会误降级为 stub)。
用法: python scripts/opt_validate_known_map.py
"""
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

src = (ROOT / "src/core/__init__.py").read_text(encoding="utf-8")
m = re.search(r"_known = \{(.*?)\n\}\n", src, re.S)
ns = {}
exec("_known = {" + m.group(1) + "\n}", ns)
known = ns["_known"]

# 重复键检测: 字面量中每个键名出现次数 > 1 即为重复 (dict 字面量后者覆盖前者)
keys_in_literal = re.findall(r"'([a-z0-9_]+)':\s*\[", m.group(1))
dups = sorted({k for k in keys_in_literal if keys_in_literal.count(k) > 1})
print("DUP_KEYS:", dups)

missing = []
for mod, syms in known.items():
    try:
        mod_obj = importlib.import_module("src.core." + mod)
    except Exception:
        continue  # 模块本身不存在 → 走 stub 属正常降级路径
    for s in syms:
        if not hasattr(mod_obj, s):
            missing.append((mod, s))

print("MISSING_SYMBOLS:")
for mod, s in missing:
    print(f"  {mod} -> {s}")
print("TOTAL_MISSING:", len(missing))

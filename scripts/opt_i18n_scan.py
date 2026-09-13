# -*- coding: utf-8 -*-
"""11 语言 i18n 完整性扫描: 找服务端/前端漏翻 key。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载服务端 i18n
tr = json.loads((ROOT / "src" / "i18n_translations.json").read_text(encoding="utf-8"))
LANGS = list(tr.keys())
REF = tr.get("en", {})
ref_keys = set(REF.keys())
print(f"服务端 i18n: {len(LANGS)} 语言, 参照(en) {len(ref_keys)} 键\n")

missing = {}
for lang in LANGS:
    if lang == "en":
        continue
    cur = set(tr.get(lang, {}).keys())
    miss = ref_keys - cur
    if miss:
        missing[lang] = sorted(miss)[:5]
        print(f"  {lang}: 缺 {len(miss)} 键 (示例: {sorted(miss)[:3]})")

if not missing:
    print("  所有语言完整 ✓")

# 检查 templates 里 T() 调用但 i18n 无 key 的
import re
tpl_dir = ROOT / "templates"
used_keys = set()
for p in tpl_dir.glob("*.html"):
    for m in re.finditer(r"t\('([a-zA-Z_][a-zA-Z0-9_]*)'\)", p.read_text(encoding="utf-8", errors="replace")):
        used_keys.add(m.group(1))

unresolved = used_keys - ref_keys
if unresolved:
    print(f"\n模板 T() 引用但 en 无 key: {len(unresolved)} (前 10)")
    for k in sorted(unresolved)[:10]:
        print(f"  {k}")
else:
    print("\n模板 T() 引用全部在 en 有 key ✓")

print("\ni18n_SCAN_DONE")

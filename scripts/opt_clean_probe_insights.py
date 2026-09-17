# -*- coding: utf-8 -*-
"""清理 E2E 探针写入真实用户目录的测试洞见 (自进化数据卫生)。"""
import json
from pathlib import Path

p = Path.home() / ".meshctx" / "self_evolution" / "insights.json"
if not p.exists():
    print("no insights file:", p)
    sys.exit(0)
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception as e:
    print("parse err:", e)
    sys.exit(1)
before = len(data)
data = {k: v for k, v in data.items() if "e2e_probe" not in k}
p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"cleaned: {before} -> {len(data)} insights")
for k in data:
    print("  kept:", k)

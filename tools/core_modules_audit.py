#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""src/core 模块实体/stub 审计 — README "313 = 311 实体 + 2 stub" 口径的可复现依据.

判定口径 (透明可复核):
- 对每个 src/core/*.py: 计总行数、去注释/空行后的有效行、return 语句数、
  NotImplementedError 出现数
- STUB 判定: 总行数 < 120 且 (NotImplementedError 存在 或 有效行占比 < 40%)
- 其余一律计入"实体实现" (含测试/胶水代码 — 它们是可运行代码, 非接口签名)

运行: python3 tools/core_modules_audit.py [--list]
"""
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "src" / "core"


def classify(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    total = len(lines)
    code = [l for l in lines
            if l.strip() and not l.strip().startswith(("#", '"""', "'''"))]
    effective = len(code)
    nimpl = raw.count("NotImplementedError")
    returns = sum(1 for l in code if l.strip().startswith("return "))
    is_stub = total < 120 and (nimpl > 0 or effective / max(total, 1) < 0.4)
    return {"file": path.name, "lines": total, "effective": effective,
            "returns": returns, "NotImplementedError": nimpl, "stub": is_stub}


def main():
    rows = [classify(p) for p in sorted(CORE.glob("*.py"))]
    stubs = [r for r in rows if r["stub"]]
    real = [r for r in rows if not r["stub"]]
    print(f"src/core 模块总数: {len(rows)} = 实体 {len(real)} + stub {len(stubs)}")
    print("stub 明细:", [r["file"] for r in stubs])
    fat = sorted(real, key=lambda r: -r["lines"])[:5]
    print("实体 TOP5 (行数):", [(r["file"], r["lines"]) for r in fat])
    if "--list" in sys.argv:
        for r in rows:
            tag = "STUB" if r["stub"] else "real"
            print(f'{tag:5} {r["file"]:40} {r["lines"]:5}行 returns={r["returns"]}')
    sys.exit(0 if len(rows) == 313 and len(stubs) == 2 else 1)


if __name__ == "__main__":
    main()

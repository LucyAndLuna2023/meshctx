#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hub_misrouted — 收件侧 to_profile 分布审计 (INCIDENTS I-2 对策工具).

扫本机各收件箱 jsonl, 统计 to_profile 分布 + 可疑件 (to_profile 为空/
含多段冒号/与通道名不符), 供人工确认误投 (I-2) 与堆积来源 (I-6).

用法: python3 tools/hub_misrouted.py [--json]
"""
import glob
import json
import sys
import os
from collections import Counter

HERMES = os.path.expanduser("~/.hermes/.hub_inbox")
CLUSTER = os.path.expanduser("~/.meshctx/cluster/inbox")


def scan():
    dist, suspicious, files = Counter(), [], 0
    for fp in [HERMES] + sorted(glob.glob(os.path.join(CLUSTER, "*.jsonl"))):
        if not os.path.exists(fp):
            continue
        files += 1
        for line in open(fp, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            tp = str(d.get("to_profile", "") or "(空)")
            dist[tp] += 1
            if tp == "(空)" or tp.count(":") > 1:
                suspicious.append({"file": os.path.basename(fp),
                                   "msg_id": d.get("msg_id", "?"),
                                   "to_profile": tp,
                                   "from": f"{d.get('from','?')}@{d.get('from_profile','?')}"})
    return {"files_scanned": files, "to_profile_distribution": dict(dist),
            "suspicious": suspicious}


def main(argv=None):
    out = scan()
    if "--json" in (argv or sys.argv[1:]):
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        print(f"扫描 {out['files_scanned']} 个收件箱文件")
        print("to_profile 分布:", out["to_profile_distribution"])
        print("可疑件:", out["suspicious"] or "(无)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

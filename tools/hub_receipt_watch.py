#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 集群回执监控 v1 — hub_receipt_watch (INCIDENTS I-3 根治件, TODO 第一项)

问题 (I-3): 送审/派活消息发出后无回执跟踪 — 002zcode 送审 4 天无回执才发现审计链停摆。
本工具: 扫 journal 发出件中带 expect_reply 标记 (或审计/送审标记) 的消息,
检查超时阈值内是否收到来自目标节点的**回执证据** (回执消息文本引用原 msg_id,
或 reply 通道出现 msg_id), 超时输出告警清单。

用法:
  python3 tools/hub_receipt_watch.py [--hours 6] [--json]
  # cron 建议: 每 30 分钟一次, 输出非空即告警 (接入通知)

判定口径 (诚实边界):
  · "已回执" = 后续 journal recv/send 记录的 message 文本中出现原 msg_id
    (集群惯例: 回执引用原 msg_id; 宽松但零误报)
  · expect_reply 判定 = 发出 payload.message 含 "[送审" / "审计请求" /
    "expect_reply" / "请回执" 之一
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MESHCTX_HOME = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
JOURNAL_DIR = MESHCTX_HOME / "web3_journal"
REPLY_MARKS = ("[送审", "审计请求", "expect_reply", "请回执", "送审请求")


def load_journal_entries():
    """读全部 journal jsonl (跨项目实例), 按 ts 升序。"""
    entries = []
    if not JOURNAL_DIR.exists():
        return entries
    for fp in sorted(JOURNAL_DIR.glob("*.jsonl")):
        for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    entries.sort(key=lambda e: e.get("ts", ""))
    return entries


def ts_to_epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def watch(hours: float = 6.0) -> Dict[str, Any]:
    now = time.time()
    entries = load_journal_entries()
    # 发出件: kind=send/message 且 expect_reply 标记
    awaiting = []
    for e in entries:
        if ">send" not in str(e.get("sender", "")):
            continue
        payload = e.get("payload") or {}
        text = str(payload.get("message", ""))
        if not any(m in text for m in REPLY_MARKS):
            continue
        awaiting.append(e)

    # 回执证据: 任何后续记录的文本引用原 msg_id (排除原发送记录自身)
    alerted = []
    for e in awaiting:
        mid = str(e.get("msg_id", ""))
        ts = e.get("ts", "")
        age_h = (now - ts_to_epoch(ts)) / 3600.0 if ts else -1
        acked = any(
            mid in json.dumps(x.get("payload", {}), ensure_ascii=False)
            and x is not e and x.get("ts", "") > ts
            for x in entries
        )
        if not acked and age_h >= hours:
            alerted.append({
                "msg_id": mid, "sent_at": ts,
                "age_hours": round(age_h, 1),
                "to_profile": (e.get("payload") or {}).get("to_profile", "?"),
                "excerpt": str((e.get("payload") or {}).get("message", ""))[:80],
            })
    return {
        "checked": len(awaiting),
        "threshold_hours": hours,
        "unacked_overdue": alerted,
        "verdict": "ALERT" if alerted else "OK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    hours = 6.0
    if "--hours" in args:
        hours = float(args[args.index("--hours") + 1])
    out = watch(hours)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 1 if out["verdict"] == "ALERT" else 0


if __name__ == "__main__":
    sys.exit(main())

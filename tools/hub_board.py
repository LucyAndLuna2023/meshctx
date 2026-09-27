#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meshctx 集群看板 — 心跳/任务/误投 状态一览 (INCIDENTS TODO: I-5 看板 + misrouted 计数).

只读工具, 零副作用:
  python3 tools/hub_board.py [--json]
输出:
  · 节点心跳: hub:workers 各实例最后心跳距今 (阈值: >5min=失联⚠)
  · 任务队列: hub:tasks pending/done 计数 + 最老 pending (堆积告警 >24h, I-6 铁律)
  · 收件箱: 本机各 hub:inbox:* LLEN (堆积告警)
"""
import json
import os
import sys
import time

try:
    from cluster_comm_v6 import get_redis, MACHINE_ID  # type: ignore
except ImportError:
    _c = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cluster")
    sys.path.insert(0, _c)
    from cluster_comm_v6 import get_redis, MACHINE_ID  # type: ignore

HEARTBEAT_STALE_SEC = 300
TASK_STALE_SEC = 86400


def _to_epoch(v) -> float:
    """created_at 兼容 epoch float 与 ISO 字符串两种形态 (实机 002admin 数据是 ISO)."""
    if not v:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            from datetime import datetime
            return datetime.fromisoformat(str(v)).timestamp()
        except Exception:
            return 0.0


def board() -> Dict[str, Any]:
    r = get_redis()
    now = time.time()
    # 心跳
    workers = []
    for field, val in (r.hgetall("hub:workers") or {}).items():
        try:
            d = json.loads(val)
            hb = _to_epoch(d.get("timestamp") or d.get("ts") or d.get("time")
                           or d.get("heartbeat", 0))
        except Exception:
            hb, d = 0, {}
        age = now - hb if hb else None
        workers.append({"instance": field, "age_sec": round(age) if age is not None else None,
                        "stale": age is None or age > HEARTBEAT_STALE_SEC,
                        "label": d.get("label", ""), "hostname": d.get("hostname", "")})
    # 任务
    tasks = {"total": 0, "pending": 0, "done": 0, "oldest_pending_sec": None,
             "zombie_empty": 0}
    for _f, raw in (r.hgetall("hub:tasks") or {}).items():
        tasks["total"] += 1
        try:
            t = json.loads(raw)
        except Exception:
            tasks["zombie_empty"] += 1
            continue
        status = str(t.get("status", "")).lower()
        if status == "done":
            tasks["done"] += 1
        else:
            tasks["pending"] += 1
            created = _to_epoch(t.get("created_at", t.get("ts", 0)))
            if created:
                age = now - created
                if tasks["oldest_pending_sec"] is None or age > tasks["oldest_pending_sec"]:
                    tasks["oldest_pending_sec"] = round(age)
    # 收件箱堆积扫描 (I-6 铁律: LLEN>0 超 24h=事故; 此处先报 >0 阈值可见)
    alerts = []
    inboxes = []
    for k in r.keys("hub:inbox:*"):
        try:
            n = r.llen(k)
            if n and int(n) > 0:
                inboxes.append({"channel": k, "llen": int(n)})
        except Exception:
            continue
    for ib in inboxes:
        alerts.append(f"⚠ 收件箱堆积: {ib['channel']} LLEN={ib['llen']}")

    for w in workers:
        if w["stale"]:
            alerts.append(f"⚠ 节点失联: {w['instance']} ({w['age_sec']}s 无心跳)")
    if tasks["oldest_pending_sec"] and tasks["oldest_pending_sec"] > TASK_STALE_SEC:
        alerts.append(f"⚠ 任务堆积: 最老 pending {tasks['oldest_pending_sec']}s (>24h, I-6 铁律)")
    if tasks["zombie_empty"]:
        alerts.append(f"⚠ 空 payload 僵尸 {tasks['zombie_empty']} 条 (可清理)")
    return {"workers": sorted(workers, key=lambda x: x["instance"]),
            "tasks": tasks, "inboxes": inboxes, "alerts": alerts,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def main(argv=None):
    out = board()
    if "--json" in (argv or sys.argv[1:]):
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        print("═ 集群心跳 ═")
        for w in out["workers"]:
            flag = "⚠失联" if w["stale"] else "✓"
            print(f"  {flag} {w['instance']}  ({w['age_sec']}s 前)")
        print("═ 任务队列 ═")
        t = out["tasks"]
        print(f"  总 {t['total']} | pending {t['pending']} | done {t['done']}"
              f" | 僵尸 {t['zombie_empty']} | 最老 pending {t['oldest_pending_sec']}s")
        print("═ 告警 ═")
        for a in out["alerts"] or ["(无)"]:
            print(f"  {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

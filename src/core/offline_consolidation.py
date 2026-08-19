"""第三阶段：睡眠期离线巩固 + 主动遗忘修剪（ARCHIVAL 层）。

对标 002 审计第三阶段实施指南：
1. 睡眠巩固：空闲时（无对话 5min 或定时）跑 consolidate() + FSRS 到期条目
   重排（到期项由 retrieve 的 review_urgency 天然优先，无需额外动作）。
2. 主动遗忘修剪：低 importance(<0.2) 且 retention 极低(<0.1) 且 lapses≥3
   的条目 → 移入 ARCHIVAL 层（不删除，可恢复），控制注入规模。

设计约束：
- 纯函数优先（可回滚、可测试）；修改 store 状态的操作由调用方显式执行。
- 修剪只改 level（LONG_TERM → ARCHIVAL），不删数据；恢复即改回。
- retrieve 默认过滤 ARCHIVAL（见 memory_hierarchy.retrieve include_archived）。
"""
from __future__ import annotations

import time
from pathlib import Path

from .memory_hierarchy import MemoryLevel

# 修剪阈值（002 指南：importance<0.2 且 retention<0.1 且 lapses>2）
PRUNE_IMPORTANCE_MAX = 0.2
PRUNE_RETENTION_MAX = 0.1
PRUNE_LAPSES_MIN = 3
# 睡眠巩固最小间隔（秒）：距上次 <1h 跳过（与 P3-1 节流一致）
CONSOLIDATE_MIN_GAP = 3600


def prune_to_archival(
    store,
    importance_max: float = PRUNE_IMPORTANCE_MAX,
    retention_max: float = PRUNE_RETENTION_MAX,
    lapses_min: int = PRUNE_LAPSES_MIN,
) -> list:
    """找出应移入 ARCHIVAL 层的记忆条目（纯函数，不修改 store）。

    条件：importance < importance_max 且 current_retention() < retention_max
          且 lapses >= lapses_min 且当前 level 为 LONG_TERM。
    返回候选 MemoryItem 列表（调用方可据此 archive_candidates() 落盘）。
    """
    candidates = []
    for _item_id, item in store._all_items():
        if getattr(item, "level", None) != MemoryLevel.LONG_TERM:
            continue
        if float(getattr(item, "importance", 0.5) or 0.5) >= importance_max:
            continue
        retention = item.current_retention() if hasattr(item, "current_retention") else 0.0
        if retention >= retention_max:
            continue
        if int(getattr(item, "lapses", 0) or 0) < lapses_min:
            continue
        candidates.append(item)
    return candidates


def archive_candidates(store, candidates) -> list:
    """把候选条目移入 ARCHIVAL 层（不删除，可恢复）。

    返回实际归档的 item id 列表。调用方需自行持久化（如 cli 写回）。
    """
    archived = []
    for item in candidates:
        if getattr(item, "level", None) == MemoryLevel.LONG_TERM:
            item.level = MemoryLevel.ARCHIVAL
            archived.append(item.id)
    return archived


def restore_from_archival(store, item_ids) -> int:
    """从 ARCHIVAL 层恢复为 LONG_TERM（可回滚操作的逆操作）。"""
    restored = 0
    by_id = {getattr(i, "id", None): i for _iid, i in store._all_items()}
    for _id in item_ids:
        item = by_id.get(_id)
        if item is not None and getattr(item, "level", None) == MemoryLevel.ARCHIVAL:
            item.level = MemoryLevel.LONG_TERM
            restored += 1
    return restored


def offline_consolidate(
    store,
    mem_dir: str | Path | None = None,
    min_gap: float = CONSOLIDATE_MIN_GAP,
) -> dict:
    """睡眠期离线巩固：节流 consolidate() + 到期条目统计。

    触发条件：距上次巩固 >= min_gap（默认 1h，防高频调用开销）。
    - consolidate(): 图式化三层收敛（情景→语义→核心）
    - 到期重排：retrieve 已按 review_urgency（importance×(1-R)）排序，
      到期项天然优先，无需额外动作；这里仅统计到期数供观测。
    返回统计 dict（可作观测/日志），失败零阻塞（返回错误标记）。

    mem_dir 提供时在 <mem_dir>/.last_offline_consolidate 记节流时间戳；
    否则用 store 内部标记（memory_hierarchy 无此字段 → 每次触发）。
    """
    marker = None
    if mem_dir is not None:
        marker = Path(mem_dir) / ".last_offline_consolidate"
        try:
            if marker.exists():
                last = float(marker.read_text().strip() or 0.0)
                if time.time() - last < min_gap:
                    return {"triggered": False, "reason": "throttled"}
        except (OSError, ValueError):
            pass
    try:
        stats = store.consolidate(**{"min_group_size": 3})
    except TypeError:
        stats = store.consolidate()
    except Exception as exc:  # 失败零阻塞
        return {"triggered": False, "reason": f"error:{exc}"}
    # 到期统计（观测用）
    due = 0
    for _item_id, item in store._all_items():
        if hasattr(item, "is_due") and item.is_due():
            due += 1
    if marker is not None:
        try:
            marker.write_text(str(time.time()))
        except OSError:
            pass
    return {"triggered": True, "consolidate": stats, "due_items": due}


__all__ = [
    "PRUNE_IMPORTANCE_MAX", "PRUNE_RETENTION_MAX", "PRUNE_LAPSES_MIN",
    "CONSOLIDATE_MIN_GAP",
    "prune_to_archival", "archive_candidates", "restore_from_archival",
    "offline_consolidate",
]

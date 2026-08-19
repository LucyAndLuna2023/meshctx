"""第三阶段：睡眠期离线巩固 + 主动遗忘修剪（ARCHIVAL 层）测试。

覆盖（对标 002 第三阶段实施指南）：
1. prune_to_archival：importance<0.2 且 retention<0.1 且 lapses≥3 → 候选
2. archive_candidates：LONG_TERM → ARCHIVAL（不删除，可恢复）
3. restore_from_archival：ARCHIVAL → LONG_TERM 逆操作
4. retrieve 默认过滤 ARCHIVAL（include_archived=True 可查）
5. offline_consolidate 节流（<1h 跳过）+ 失败零阻塞
"""
import time
from pathlib import Path

import pytest

from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel
from src.core.offline_consolidation import (
    archive_candidates,
    offline_consolidate,
    prune_to_archival,
    restore_from_archival,
)


def _low_importance_item(key="旧梗", value="过时笑话", importance=0.1, lapses=3,
                         stability=1.0, last_reviewed=None):
    """构造低价值高遗忘记忆（应被修剪）。"""
    return MemoryItem(
        key=key, value=value, importance=importance,
        level=MemoryLevel.LONG_TERM, lapses=lapses,
        stability=stability,
        last_reviewed=last_reviewed if last_reviewed is not None else time.time() - 86400 * 30,
    )


class TestPruneToArchival:
    def test_candidate_selected(self):
        store = HierarchicalMemoryStore()
        store.store(_low_importance_item())
        store.store(MemoryItem(key="重要", value="核心原则", importance=0.9))
        cands = prune_to_archival(store)
        assert len(cands) == 1
        assert cands[0].key == "旧梗"

    def test_high_importance_kept(self):
        store = HierarchicalMemoryStore()
        store.store(_low_importance_item(importance=0.5))
        assert prune_to_archival(store) == []

    def test_few_lapses_kept(self):
        store = HierarchicalMemoryStore()
        store.store(_low_importance_item(lapses=1))
        assert prune_to_archival(store) == []

    def test_high_retention_kept(self):
        """stability 大 → retention 高 → 不修剪。"""
        store = HierarchicalMemoryStore()
        store.store(_low_importance_item(stability=5000.0, last_reviewed=time.time()))
        assert prune_to_archival(store) == []

    def test_non_longterm_ignored(self):
        store = HierarchicalMemoryStore()
        it = _low_importance_item()
        it.level = MemoryLevel.SHORT_TERM
        store.store(it)
        assert prune_to_archival(store) == []


class TestArchiveRestore:
    def test_archive_then_restore_roundtrip(self):
        store = HierarchicalMemoryStore()
        it = _low_importance_item()
        store.store(it)
        cands = prune_to_archival(store)
        archived = archive_candidates(store, cands)
        assert archived == [it.id]
        assert store._items[it.id].level == MemoryLevel.ARCHIVAL
        # 恢复（可回滚）
        assert restore_from_archival(store, [it.id]) == 1
        assert store._items[it.id].level == MemoryLevel.LONG_TERM

    def test_restore_unknown_id_returns_zero(self):
        store = HierarchicalMemoryStore()
        assert restore_from_archival(store, ["nonexistent"]) == 0


class TestRetrieveFiltersArchived:
    def test_default_excludes_archived(self):
        store = HierarchicalMemoryStore()
        it = _low_importance_item(key="过时", value="旧数据")
        store.store(it)
        store.store(MemoryItem(key="活跃", value="新数据", importance=0.8))
        # 归档
        archive_candidates(store, prune_to_archival(store))
        hits = store.retrieve("旧数据", top_k=0)
        assert all(h.key != "过时" for h in hits)
        # 显式包含 → 可查（可恢复性保障）
        hits = store.retrieve("旧数据", top_k=0, include_archived=True)
        assert any(h.key == "过时" for h in hits)

    def test_archived_not_in_empty_query(self):
        store = HierarchicalMemoryStore()
        store.store(_low_importance_item())
        archive_candidates(store, prune_to_archival(store))
        assert all(getattr(h, "level", None) != MemoryLevel.ARCHIVAL
                   for h in store.retrieve("", top_k=0))


class TestOfflineConsolidate:
    def test_first_run_triggers(self, tmp_path):
        store = HierarchicalMemoryStore()
        for i in range(3):
            store.store(MemoryItem(key=f"会议{i}", value=f"会议点{i}", importance=0.5))
        res = offline_consolidate(store, mem_dir=tmp_path)
        assert res["triggered"] is True
        assert (tmp_path / ".last_offline_consolidate").exists()

    def test_throttled_within_gap(self, tmp_path):
        store = HierarchicalMemoryStore()
        (tmp_path / ".last_offline_consolidate").write_text(str(time.time() - 600))
        res = offline_consolidate(store, mem_dir=tmp_path)
        assert res["triggered"] is False
        assert res["reason"] == "throttled"

    def test_no_mem_dir_always_runs(self):
        store = HierarchicalMemoryStore()
        res = offline_consolidate(store, mem_dir=None)
        assert res["triggered"] is True

    def test_error_zero_blocking(self, tmp_path):
        class BoomStore:
            def consolidate(self, **kw):
                raise RuntimeError("boom")

            def _all_items(self):
                return []

        res = offline_consolidate(BoomStore(), mem_dir=tmp_path)
        assert res["triggered"] is False
        assert "error" in res["reason"]

# -*- coding: utf-8 -*-
"""FSRS 间隔重复闭环 + 主动回忆回写 验收测试（phase-1）

覆盖:
  A. FSRSScheduler 状态机（D/S/R）— 成功复习稳定性上升、失败重置
  B. retrievability 衰减 / due 判定 / grade_from_confidence
  C. HierarchicalMemoryStore.record_recall 回写闭环（修复 last_reviewed 只写不更新）
  D. record_lapse 主动遗忘惩罚
  E. retrieve 排序按 review_urgency（importance × (1-R)）
  F. FSRS 字段持久化 roundtrip
"""
import json
import math
import time

import pytest


# ═══════════ A. FSRSScheduler 状态机 ═══════════

class TestFSRSScheduler:
    def test_success_review_increases_stability_and_interval(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        sched = FSRSScheduler()
        card = sched.get_or_create("m1")
        assert card.stability == 1.0
        r1 = sched.review(card, grade=4)
        assert r1.passed
        assert card.stability > 1.0, "成功复习后稳定性应上升"
        assert card.interval_days >= 1.0
        assert card.reviews == 1
        assert card.last_review > 0 and card.next_review > card.last_review

    def test_perfect_grade_strengthens_more_than_minimal_pass(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        s1 = FSRSScheduler()
        c1 = s1.get_or_create("a")
        s1.review(c1, grade=3)
        s2 = FSRSScheduler()
        c2 = s2.get_or_create("b")
        s2.review(c2, grade=5)
        assert c2.stability > c1.stability, "grade5 应比 grade3 增益更大"

    def test_failure_resets_interval_and_degrades_stability(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        sched = FSRSScheduler()
        card = sched.get_or_create("m1")
        sched.review(card, grade=5)   # 第一次：间隔 1 天
        sched.review(card, grade=5)   # 第二次：间隔增长
        stable_before = card.stability
        assert card.interval_days > 1.0
        r2 = sched.review(card, grade=0)  # 遗忘
        assert not r2.passed
        assert card.interval_days == 1.0, "失败后间隔应重置为 1 天"
        assert card.stability < stable_before, "失败后稳定性应下降"
        assert card.lapses == 1

    def test_repeated_success_extends_interval_monotonically(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        sched = FSRSScheduler()
        card = sched.get_or_create("m1")
        intervals = []
        for g in [4, 4, 5, 5, 5]:
            sched.review(card, grade=g)
            intervals.append(card.interval_days)
        assert all(intervals[i] <= intervals[i + 1] for i in range(len(intervals) - 1))
        assert intervals[-1] > 1.0

    def test_difficulty_bounded_and_decreases_on_success(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        sched = FSRSScheduler()
        card = sched.get_or_create("m1")
        card.difficulty = 9.0  # 很难
        sched.review(card, grade=5)
        assert 0.0 <= card.difficulty <= 10.0
        assert card.difficulty < 9.0, "成功后难度应降低"


# ═══════════ B. retrievability / due / grade ═══════════

class TestFSRSRetrievability:
    def test_retrievability_decays_over_time(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        sched = FSRSScheduler()
        card = sched.get_or_create("m1")
        now = time.time()
        card.last_review = now - 86400.0 * 1   # 1 天前
        card.stability = 1.0
        r_now = card.retrievability(now)
        assert abs(r_now - 0.1) < 1e-9  # 10^(-1/1) = 0.1
        r_later = card.retrievability(now + 86400.0 * 3)
        assert r_later < r_now, "时间越长保留度越低"

    def test_retrievability_full_when_fresh(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        card = FSRSScheduler().get_or_create("m1")
        card.last_review = time.time()
        assert card.retrievability() == pytest.approx(1.0, abs=1e-3)

    def test_due_logic(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        sched = FSRSScheduler()
        card = sched.get_or_create("m1")
        now = time.time()
        assert card.is_due(now), "从未安排复习应视为到期"
        card.next_review = now + 3600.0
        assert not card.is_due(now), "未到 next_review 不应到期"
        card.next_review = now - 1.0
        assert card.is_due(now)

    def test_grade_from_confidence_mapping(self):
        from src.core.fsrs_scheduler import grade_from_confidence
        assert grade_from_confidence(0.99) == 5
        assert grade_from_confidence(0.85) == 4
        assert grade_from_confidence(0.70) == 3
        assert grade_from_confidence(0.50) == 2
        assert grade_from_confidence(0.30) == 1
        assert grade_from_confidence(0.10) == 0


# ═══════════ C. record_recall 回写闭环（修复 last_reviewed） ═══════════

class TestRecordRecallClosedLoop:
    def test_recall_updates_last_reviewed(self):
        """核心缺陷修复：检索命中后 last_reviewed 必须更新（原来只写不更新）。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        item = MemoryItem(key="k1", value="v1", importance=0.8)
        item.last_reviewed = time.time() - 86400.0 * 10  # 10 天前
        store.store(item)
        before = item.last_reviewed
        store.record_recall(item.id, grade=4)
        assert item.last_reviewed > before, "检索命中后 last_reviewed 必须推进"
        assert item.review_count == 1
        assert item.next_review > item.last_reviewed, "必须安排下次复习"

    def test_recall_strengthens_stability(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        item = MemoryItem(key="k1", value="v1")
        store.store(item)
        s0 = item.stability
        store.record_recall(item.id, grade=5)
        assert item.stability > s0, "成功回忆后 stability 应上升"

    def test_confidence_calibration(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        item = MemoryItem(key="k1", value="v1")
        store.store(item)
        store.record_recall(item.id, confidence=0.9)
        assert item.confidence == pytest.approx(0.9)
        # confidence → grade 映射生效
        assert item.review_count == 1

    def test_record_lapse_punishes(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        item = MemoryItem(key="k1", value="v1")
        store.store(item)
        store.record_recall(item.id, grade=5)  # 强化
        s_before = item.stability
        store.record_lapse(item.id)            # 遗忘
        assert item.lapses == 1
        assert item.stability < s_before, "遗忘后稳定性应下降"

    def test_get_due_items(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        due = MemoryItem(key="due", value="d")
        due.next_review = time.time() - 1.0      # 已到期
        future = MemoryItem(key="future", value="f")
        future.next_review = time.time() + 3600.0  # 未到期
        store.store(due)
        store.store(future)
        due_ids = {i.id for i in store.get_due_items()}
        assert due.id in due_ids
        assert future.id not in due_ids

    def test_retrieve_ranks_by_urgency(self):
        """到期且高 importance 的记忆应优先于高 importance 但刚复习过的。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        stale = MemoryItem(key="stale", value="old important", importance=0.9)
        stale.last_reviewed = time.time() - 86400.0 * 30  # 30 天前，R≈0
        fresh = MemoryItem(key="fresh", value="fresh important", importance=0.9)
        fresh.last_reviewed = time.time()                   # 刚复习，R≈1
        store.store(stale)
        store.store(fresh)
        out = store.retrieve("", top_k=2)
        assert out[0].id == stale.id, "遗忘紧迫的高价值记忆应排最前"


# ═══════════ D. 持久化 roundtrip ═══════════

class TestFSRSPersistence:
    def test_roundtrip_keeps_fsrs_fields(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        item = MemoryItem(key="k1", value="v1")
        store.store(item)
        store.record_recall(item.id, grade=5, confidence=0.95)
        d = item.to_json_dict()
        assert "stability" in d and "difficulty" in d and "next_review" in d
        assert "lapses" in d and "ease_factor" in d
        restored = MemoryItem.from_json_dict(d)
        assert restored.stability == item.stability
        assert restored.next_review == item.next_review
        assert restored.review_count == item.review_count
        assert restored.confidence == item.confidence

    def test_old_snapshot_loads_with_defaults(self):
        """旧格式快照（无 FSRS 字段）加载不应报错，用默认值。"""
        from src.core.memory_hierarchy import MemoryItem
        old = {
            "id": "x", "key": "k", "value": "v", "level": 3,
            "importance": 0.5, "created_at": 0.0, "last_reviewed": 0.0,
        }
        item = MemoryItem.from_json_dict(old)
        assert item.stability == 24.0
        assert item.difficulty == 5.0
        assert item.next_review == 0.0
        assert item.lapses == 0

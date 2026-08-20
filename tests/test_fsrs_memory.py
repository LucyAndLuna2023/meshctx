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
        # 首次复习（无 R 可依）用经验增益（FSRS v4 R 感知公式的初始化分支）
        assert card.stability > 1.0, "首次成功复习后稳定性应上升"
        assert card.interval_days >= 1.0
        assert card.reviews == 1
        assert card.last_review > 0 and card.next_review > card.last_review

    def test_perfect_grade_strengthens_more_than_minimal_pass(self):
        from src.core.fsrs_scheduler import FSRSScheduler
        s1 = FSRSScheduler()
        c1 = s1.get_or_create("a")
        s1.review(c1, grade=3)
        s1.review(c1, grade=3)
        s2 = FSRSScheduler()
        c2 = s2.get_or_create("b")
        s2.review(c2, grade=5)
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
        store.record_recall(item.id, grade=5)   # 首次: FSRS-4 不涨
        store.record_recall(item.id, grade=5)   # 第二次: 开始强化
        assert item.stability > s0, "重复成功回忆后 stability 应上升（LTP 两阶段巩固）"

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

    def test_write_structured_memories_persists_fsrs_state(self, tmp_path, monkeypatch):
        """P2 审计遗留：_write_structured_memories 重写记忆文件时必须保留 FSRS 状态，
        重启后复习进度不丢失（读回+写回全量字段，而非仅 6-7 个旧字段）。"""
        import json as _json
        from src.cli import _write_structured_memories
        from src.core.memory_hierarchy import MemoryItem

        # 隔离到临时目录，避免污染真实 memories/
        class FakeCPS:
            def __init__(self, base_path=None):
                self.base_path = tmp_path
        monkeypatch.setattr("src.cross_platform_engine.CrossPlatformStorage", FakeCPS)

        # 1) 预置一份"重启前已复习"的记忆文件（带 FSRS 状态）
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        old_item = MemoryItem(key="persist_k", value="persist_v", importance=0.8)
        old_item.stability = 167.0          # 多次成功复习后的稳定值
        old_item.difficulty = 4.1
        old_item.next_review = 1788000000.0  # 未来到期时间
        old_item.review_count = 4
        old_item.lapses = 1
        old_item.last_reviewed = 1787000000.0
        (mem_dir / f"{old_item.id}.json").write_text(
            _json.dumps(old_item.to_json_dict(), ensure_ascii=False), encoding="utf-8")

        # 2) 模拟新对话自动保存（同一 key 的新提取记忆）
        n = _write_structured_memories([{"key": "persist_k", "value": "persist_v", "importance": 0.8}])
        assert n >= 0

        # 3) 重读落盘文件：FSRS 状态必须保留（未被重置为默认值）
        loaded = None
        for fp in mem_dir.glob("*.json"):
            d = _json.loads(fp.read_text(encoding="utf-8"))
            if d.get("key") == "persist_k":
                loaded = MemoryItem.from_json_dict(d)
        assert loaded is not None, "记忆文件应存在"
        assert loaded.stability == 167.0, f"stability 应跨重启保留, got {loaded.stability}"
        assert loaded.next_review == 1788000000.0, f"next_review 应跨重启保留, got {loaded.next_review}"
        assert loaded.difficulty == 4.1
        assert loaded.lapses == 1
        assert loaded.review_count == 4


# ═══════════ G. P2 优化验收（002 审计 41ab3fe5 建议补充） ═══════════

class TestP2MemoryOptimization:
    """P2-1~P2-4 验收：10底stability排序 / M1分类 / M3防抖回写 / T3相关性注入。"""

    def test_score_prefers_higher_stability_same_recency(self):
        """同 recency 下 stability 高者排序靠前（10底 retention 生效）。"""
        from src.chat_tools import _memory_item_score
        now = time.time()
        base = {"importance": 0.5, "last_reviewed": now - 3600 * 10,
                "created_at": now - 3600 * 10, "schema_layer": "episodic"}
        low = dict(base, key="a", value="v", stability=1.0)
        high = dict(base, key="b", value="v", stability=240.0)
        assert _memory_item_score(high) > _memory_item_score(low), \
            "同 recency 下 stability 240h 应显著高于 1h（10^(-t/S)）"

    def test_score_floor_and_importance_scale(self):
        """retention floor 0.05 生效；importance 线性放大。"""
        from src.chat_tools import _memory_item_score
        now = time.time()
        r = {"key": "a", "value": "v", "importance": 0.9,
             "last_reviewed": now - 3600 * 24 * 30, "created_at": now - 3600 * 24 * 30,
             "stability": 1.0, "schema_layer": "episodic"}
        s = _memory_item_score(r)
        assert 0.04 < s <= 0.9, f"floor 后应 >0（实得 {s}）且 ≤importance"

    def test_classify_memory_rules(self):
        """M1 规则分类：task>preference>decision>context>fact。"""
        from src.core.memory_hierarchy import classify_memory
        assert classify_memory("请帮我部署到生产环境") == "task"
        assert classify_memory("记得明天买牛奶") == "task"
        assert classify_memory("我喜欢深色主题") == "preference"
        assert classify_memory("用户偏好简洁风格") == "preference"
        assert classify_memory("我决定采用方案B") == "decision"
        assert classify_memory("这家公司成立于2015年") == "fact"
        assert classify_memory("随便写点什么") == "other"

    def test_store_auto_categorizes_other_only(self):
        """M1 触发条件：category=other 才自动分类，显式指定不覆盖。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        auto = MemoryItem(key="k1", value="请帮我部署", importance=0.5)
        store.store(auto)
        assert auto.category == "task", f"应自动分类为 task, got {auto.category}"
        explicit = MemoryItem(key="k2", value="请帮我部署", importance=0.5, category="fact")
        store.store(explicit)
        assert explicit.category == "fact", "显式 category 不应被覆盖"

    def test_auto_review_debounce_and_writeback(self):
        """M3 防抖：刚复习 1h 内不重复刷写；超时后 record_recall 回写。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem
        store = HierarchicalMemoryStore()
        item = MemoryItem(key="k", value="hello world")
        store.store(item)
        # 刚创建（created≈now）→ 距上次复习 <1h → 不触发
        store._auto_review(item)
        assert item.review_count == 0 and item.last_reviewed == 0.0
        # 模拟 2h 前复习过 → 触发回写（grade=3 保守）
        item.last_reviewed = time.time() - 7200.0
        store._auto_review(item)
        assert item.review_count >= 1
        assert item.last_reviewed > time.time() - 10
        assert item.stability > 0
        # 刚回写 → 1h 防抖内不再刷写
        prev = item.review_count
        store._auto_review(item)
        assert item.review_count == prev

    def test_collect_memory_entries_stability_roundtrip_and_query_rank(self, tmp_path):
        """T3：stability 字段 roundtrip；current_query 相关性优先于纯分数（中英文均支持）。"""
        import json as _json
        from src.chat_tools import _collect_memory_entries
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        # 高 stability 但无关查询
        (mem_dir / "a.json").write_text(_json.dumps({
            "key": "misc", "value": "随机闲聊内容", "importance": 0.9,
            "last_reviewed": 0.0, "created_at": 0.0, "stability": 240.0,
            "schema_layer": "episodic"}, ensure_ascii=False), encoding="utf-8")
        # 低 stability 但强相关
        (mem_dir / "b.json").write_text(_json.dumps({
            "key": "deploy", "value": "生产环境部署步骤：先备份再发布", "importance": 0.5,
            "last_reviewed": 0.0, "created_at": 0.0, "stability": 24.0,
            "schema_layer": "semantic"}, ensure_ascii=False), encoding="utf-8")
        rows = _collect_memory_entries(current_query="生产环境如何部署", base_dirs=[str(mem_dir)], max_entries=10)
        assert rows, "应收集到记忆条目"
        assert "部署" in rows[0], f"中文 2-gram 相关性应优先, 首条={rows[0][:40]}"

    def test_prompt_injection_review_coverage(self, tmp_path):
        """P2 复习覆盖面：注入命中条目触发 FSRS 复习回写；防抖 1h 内不重复。"""
        import json as _json
        from src.chat_tools import _collect_memory_entries, _maybe_review_memory_file
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        fp = mem_dir / "deploy.json"
        fp.write_text(_json.dumps({
            "id": "deploy1", "key": "deploy", "value": "生产环境部署步骤：先备份再发布",
            "importance": 0.5, "last_reviewed": 0.0, "created_at": 0.0,
            "stability": 24.0, "schema_layer": "semantic"}, ensure_ascii=False), encoding="utf-8")
        rows = _collect_memory_entries(current_query="生产环境如何部署", base_dirs=[str(mem_dir)], max_entries=10)
        assert rows, "应收集到记忆条目"
        m = _json.loads(fp.read_text(encoding="utf-8"))
        assert m["review_count"] >= 1, "注入命中条目应触发复习回写"
        assert m["last_reviewed"] > 0
        # 防抖：立即再次收集 → review_count 不增长
        _collect_memory_entries(current_query="生产环境如何部署", base_dirs=[str(mem_dir)], max_entries=10)
        m2 = _json.loads(fp.read_text(encoding="utf-8"))
        assert m2["review_count"] == m["review_count"], "防抖 1h 内不应重复刷写"
        # 回拨 last_reviewed → 再次触发
        m["last_reviewed"] = 0.0
        fp.write_text(_json.dumps(m, ensure_ascii=False), encoding="utf-8")
        _maybe_review_memory_file(str(fp))
        m3 = _json.loads(fp.read_text(encoding="utf-8"))
        assert m3["review_count"] == m["review_count"] + 1, "回拨后应再次触发复习"

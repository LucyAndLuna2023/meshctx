"""P2 记忆优化验收测试（002 审计 41ab3fe5 非阻塞建议①，commit 364f660 未新增测试）。

覆盖 4 类缺口：
1. _memory_item_score：同 recency、stability 1h vs 240h → 高 stability 排序靠前
2. classify_memory：规则分类（task/preference/decision/context/fact/other）
3. _auto_review：防抖 1h 内不重复刷写；record_recall 后 last_reviewed/stability 变化
4. _collect_memory_entries：stability roundtrip（落盘 JSON → 读出）
"""
import json
import time

import pytest


# ── 1. _memory_item_score：per-item FSRS stability 参与排序 ─────────────
class TestMemoryItemScoreStability:
    def test_higher_stability_ranks_first_same_recency(self):
        """同 recency（同 last_reviewed）、stability 1h vs 240h → 高 stability 靠前。"""
        from src.chat_tools import _memory_item_score
        from src.core.memory_hierarchy import MemoryItem, MemoryLevel

        now = time.time()
        low = MemoryItem(key="a", value="低稳定性", importance=0.5, level=MemoryLevel.LONG_TERM)
        low.last_reviewed = now
        low.stability = 1.0  # 1 小时
        high = MemoryItem(key="b", value="高稳定性", importance=0.5, level=MemoryLevel.LONG_TERM)
        high.last_reviewed = now
        high.stability = 240.0  # 240 小时
        assert _memory_item_score(high) > _memory_item_score(low), \
            "同 recency 下高 stability 保留度更高，应排序靠前"

    def test_stability_dominates_over_importance_at_same_recency(self):
        """同 recency：stability 240h + importance 0.3 > stability 1h + importance 0.9。"""
        from src.chat_tools import _memory_item_score
        from src.core.memory_hierarchy import MemoryItem, MemoryLevel

        now = time.time() - 86400  # 24h 前复习（retention 才体现 stability 差异）
        low = MemoryItem(key="a", value="低稳高重", importance=0.9, level=MemoryLevel.LONG_TERM)
        low.last_reviewed = now
        low.stability = 1.0
        high = MemoryItem(key="b", value="高稳低重", importance=0.3, level=MemoryLevel.LONG_TERM)
        high.last_reviewed = now
        high.stability = 240.0
        assert _memory_item_score(high) > _memory_item_score(low)

    def test_floor_zero_confidence(self):
        """极端久远条目不低于 0.05 下限（避免排序吞没）。"""
        from src.chat_tools import _memory_item_score
        from src.core.memory_hierarchy import MemoryItem, MemoryLevel

        it = MemoryItem(key="a", value="远古", importance=0.1, level=MemoryLevel.LONG_TERM)
        it.last_reviewed = 0.0  # 1970
        it.stability = 1.0
        assert _memory_item_score(it) >= 0.05 * 0.1  # floor × importance


# ── 2. classify_memory：规则分类 ────────────────────────────────────────
class TestClassifyMemory:
    def test_task_keyword(self):
        from src.core.memory_hierarchy import classify_memory
        assert classify_memory("帮我部署生产环境") == "task"

    def test_preference_keyword(self):
        from src.core.memory_hierarchy import classify_memory
        assert classify_memory("我喜欢深色模式") == "preference"

    def test_decision_keyword(self):
        from src.core.memory_hierarchy import classify_memory
        assert classify_memory("决定采用微服务架构") == "decision"

    def test_context_and_fact(self):
        from src.core.memory_hierarchy import classify_memory
        assert classify_memory("当前正在进行重构") == "context"
        assert classify_memory("公司总部位于北京") == "fact"

    def test_empty_other(self):
        from src.core.memory_hierarchy import classify_memory
        assert classify_memory("") == "other"
        assert classify_memory("   ") == "other"
        assert classify_memory("随便一条无关键词记录") == "other"


# ── 3. _auto_review：防抖 + record_recall 效果 ─────────────────────────
class TestAutoReview:
    def test_first_hit_records_recall(self):
        """首次检索命中：last_reviewed 被更新、review_count +1。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel

        store = HierarchicalMemoryStore()
        it = MemoryItem(key="k", value="待复习", importance=0.5, level=MemoryLevel.LONG_TERM)
        it.created_at = time.time() - 7200  # 2h 前创建（避开新建 1h 防抖）
        store._items[it.id] = it
        before = it.last_reviewed or 0.0
        store._auto_review(it)
        assert it.last_reviewed and it.last_reviewed > before
        assert it.review_count >= 1

    def test_debounce_within_hour_skips(self):
        """1h 防抖：刚复习过再命中 → 不重复刷写。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel

        store = HierarchicalMemoryStore()
        it = MemoryItem(key="k", value="刚复习", importance=0.5, level=MemoryLevel.LONG_TERM)
        store._items[it.id] = it
        it.last_reviewed = time.time() - 300  # 5 分钟前
        rc_before = it.review_count
        store._auto_review(it)
        assert it.review_count == rc_before, "防抖期内不应重复刷写"

    def test_after_hour_records_again(self):
        """超过 1h 再命中 → 再次回写。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel

        store = HierarchicalMemoryStore()
        it = MemoryItem(key="k", value="隔时复习", importance=0.5, level=MemoryLevel.LONG_TERM)
        store._items[it.id] = it
        it.last_reviewed = time.time() - 7200  # 2 小时前
        rc_before = it.review_count
        store._auto_review(it)
        assert it.review_count > rc_before

    def test_record_recall_updates_stability(self):
        """record_recall 后 stability 按 FSRS 更新（不再是初始默认 24.0 且单调增长）。"""
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel

        store = HierarchicalMemoryStore()
        it = MemoryItem(key="k", value="FSRS", importance=0.5, level=MemoryLevel.LONG_TERM)
        store._items[it.id] = it
        s_before = it.stability
        store.record_recall(it.id, grade=4)
        assert it.stability >= s_before, "grade=4 复习后 stability 应增长"
        assert it.review_count >= 1


# ── 4. _collect_memory_entries：stability roundtrip + 参与排序 ─────────
class TestCollectEntriesStability:
    def test_stability_roundtrip(self, tmp_path, monkeypatch):
        """memories/*.json 落盘 stability → 读出并参与排序（返回值列表为 value）。"""
        from src.chat_tools import _collect_memory_entries

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        (mem_dir / "m1.json").write_text(json.dumps({
            "key": "k1", "value": "高稳定记忆", "importance": 0.5,
            "stability": 240.0, "schema_layer": "semantic",
        }), encoding="utf-8")
        rows = _collect_memory_entries(base_dirs=[str(mem_dir)])
        assert rows == ["高稳定记忆"]

    def test_default_stability_when_absent(self, tmp_path, monkeypatch):
        """无 stability 字段的旧记忆 → 默认 24.0 可正常读出。"""
        from src.chat_tools import _collect_memory_entries

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        (mem_dir / "m1.json").write_text(json.dumps({
            "key": "k1", "value": "旧记忆", "importance": 0.5,
        }), encoding="utf-8")
        rows = _collect_memory_entries(base_dirs=[str(mem_dir)])
        assert rows == ["旧记忆"]

    def test_stability_drives_ranking_no_query(self, tmp_path, monkeypatch):
        """无 query 时：高 stability 同 importance → 排前。"""
        from src.chat_tools import _collect_memory_entries

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        (mem_dir / "a.json").write_text(json.dumps({
            "key": "a", "value": "低稳定", "importance": 0.5,
            "stability": 1.0, "created_at": time.time() - 86400,
        }), encoding="utf-8")
        (mem_dir / "b.json").write_text(json.dumps({
            "key": "b", "value": "高稳定", "importance": 0.5,
            "stability": 240.0, "created_at": time.time() - 86400,
        }), encoding="utf-8")
        rows = _collect_memory_entries(base_dirs=[str(mem_dir)])
        assert rows[0] == "高稳定", "高 stability 应排序靠前"

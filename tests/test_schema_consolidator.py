"""Schema Consolidator 单元测试（phase-2 task4 图式化三层管线）。

验收指标（第二阶段实施计划 任务④ 验证）：
  - 10 条合成会议记忆 → 合并为 ≤3 条语义 + 原情景条目降权
  - embedding 相似度 >0.85 + 同实体 → 去重
  - 高频语义 → 核心层原则
  - store.consolidate() 入口集成
  - schema_layer 序列化持久化
"""
import math

import pytest

from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel
from src.core.schema_consolidator import (
    SCHEMA_CORE,
    SCHEMA_EPISODIC,
    SCHEMA_SEMANTIC,
    consolidate,
    deduplicate,
    extract_theme,
    group_by_theme,
    merge_to_semantic,
    promote_to_core,
    run_consolidation,
)


def _meeting(theme: str, detail: str, importance: float = 0.6, **kw) -> MemoryItem:
    """构造一条情景层会议记忆。entities 决定主题分组。"""
    return MemoryItem(
        level=MemoryLevel.WORKING,
        key=f"meeting:{theme}:{detail[:8]}",
        value=f"[{theme}会议] {detail}",
        entities=[theme],
        importance=importance,
        schema_layer=SCHEMA_EPISODIC,
        **kw,
    )


# ── 主题抽取与分组 ───────────────────────────────────────────────
class TestThemeGroup:
    def test_extract_theme_from_entity(self):
        it = _meeting("产品发布", "确认发布日期")
        # P3-2: '产品发布' 含 '发布' → 同义词归一化为 release
        assert extract_theme(it) == "entity:release"

    def test_extract_theme_fallback_to_topic(self):
        it = MemoryItem(value="讨论预算审批流程", entities=[])
        assert extract_theme(it).startswith("topic:")

    def test_group_by_theme_requires_min3(self):
        items = [_meeting("预算", f"明细{i}") for i in range(2)]
        assert group_by_theme(items, group_min=3) == {}


# ── 去重 ─────────────────────────────────────────────────────────
class TestDeduplicate:
    def test_embedding_similar_deduped(self):
        # 两条同一主题、embedding 高度相似（余弦 ≈ 1.0）→ 合并为 1 条
        base = [0.1, 0.2, 0.3, 0.4]
        a = _meeting("预算", "预算 5000 元", importance=0.6, embedding=list(base))
        b = _meeting("预算", "预算 5000 元（含税）", importance=0.7, embedding=[x + 1e-4 for x in base])
        out = deduplicate([a, b], sim_threshold=0.85)
        assert len(out) == 1

    def test_dissimilar_kept(self):
        a = _meeting("预算", "预算 5000 元", embedding=[0.1, 0.2, 0.3, 0.4])
        b = _meeting("预算", "采购打印机", embedding=[0.9, -0.2, 0.1, 0.0])
        out = deduplicate([a, b], sim_threshold=0.85)
        assert len(out) == 2

    def test_keep_most_detailed(self):
        short = _meeting("预算", "预算 5000")
        long = _meeting("预算", "预算 5000 元，其中设备 3000、培训 2000，分两期支付")
        out = deduplicate([short, long], sim_threshold=0.85)
        assert len(out) == 1
        # 保留更详细的
        assert "设备 3000" in (out[0].value or "")


# ── 语义层合并 ───────────────────────────────────────────────────
class TestMergeSemantic:
    def test_merge_to_one_semantic(self):
        group = [
            _meeting("产品发布", f"发布计划点 {i}", importance=0.5 + i * 0.1)
            for i in range(3)
        ]
        sem = merge_to_semantic(group)
        assert sem.schema_layer == SCHEMA_SEMANTIC
        assert sem.key.startswith("schema:entity:release")
        assert len(sem.related_memory_ids) == 3
        # importance 取组内最大、stability 继承（不重新学习）
        assert sem.importance == pytest.approx(0.7)
        assert sem.stability == max(it.stability for it in group)


# ── 核心层提升 ───────────────────────────────────────────────────
class TestPromoteCore:
    def test_frequent_semantic_promoted(self):
        sems = [
            merge_to_semantic([_meeting("代码规范", f"点{i}") for i in range(3)]),
            merge_to_semantic([_meeting("代码规范", f"点{i}") for i in range(3)]),
        ]
        cores = promote_to_core(sems, min_freq=2)
        assert len(cores) == 1
        assert cores[0].schema_layer == SCHEMA_CORE
        # P3-2: '代码规范' 归一化为 entity:code → core 值用规范主题键
        assert "entity:code" in cores[0].value

    def test_rare_semantic_not_promoted(self):
        sems = [merge_to_semantic([_meeting("一次性事件", f"点{i}") for i in range(3)])]
        assert promote_to_core(sems, min_freq=2) == []


# ── 主入口 consolidate（纯函数） ─────────────────────────────────
class TestConsolidate:
    def test_ten_meetings_merge_to_le3_semantic(self):
        """验收：10 条合成会议记忆 → 语义层 ≤3 条 + 原 10 条降权。"""
        # 主题A×5、主题B×3、主题C×2（C 不足 3 条不触发）
        items = (
            [_meeting("产品发布", f"主题A点{i}") for i in range(5)]
            + [_meeting("预算", f"主题B点{i}") for i in range(3)]
            + [_meeting("团队分工", f"主题C点{i}") for i in range(2)]
        )
        new_items, stats = consolidate(items)
        assert stats["grouped_themes"] == 2          # A、B 触发
        assert stats["semantic_created"] == 2        # 2 条语义
        assert stats["episodic_demoted"] == 8        # 5+3 条降权
        assert stats["episodic_kept"] == 2           # C 组 2 条保留

        semantics = [it for it in new_items if it.schema_layer == SCHEMA_SEMANTIC]
        assert len(semantics) <= 3                   # 验收：≤3 条语义
        # 原情景条目仍在（降权保留），importance 减半
        episodics = [it for it in new_items if it.schema_layer == SCHEMA_EPISODIC]
        assert len(episodics) == 10
        demoted = [it for it in episodics if it.importance < 0.6]
        assert len(demoted) == 8

    def test_no_group_below_threshold_no_change(self):
        items = [_meeting("独苗", f"点{i}") for i in range(2)]
        new_items, stats = consolidate(items)
        assert stats["semantic_created"] == 0
        assert len(new_items) == 2

    def test_pure_function_no_mutation(self):
        """纯函数：入参对象不被修改（可回滚）。"""
        items = [_meeting("产品发布", f"点{i}") for i in range(4)]
        before = [(it.id, it.importance) for it in items]
        consolidate(items)
        after = [(it.id, it.importance) for it in items]
        assert before == after


# ── store 集成 ───────────────────────────────────────────────────
class TestStoreIntegration:
    def test_store_consolidate_creates_semantic(self):
        store = HierarchicalMemoryStore()
        for i in range(5):
            store.store(_meeting("产品发布", f"发布点{i}"))
        for i in range(3):
            store.store(_meeting("预算", f"预算点{i}"))
        stats = store.consolidate()
        assert stats["semantic_created"] == 2
        layers = {it.schema_layer for _, it in store._all_items()}
        assert SCHEMA_SEMANTIC in layers

    def test_semantic_inherits_fsrs_stability(self):
        """合并后语义条目继承组内最大 stability（不重新学习）。"""
        store = HierarchicalMemoryStore()
        items = [_meeting("产品发布", f"点{i}") for i in range(4)]
        items[0].stability = 500.0   # 已稳定记忆
        for it in items:
            store.store(it)
        store.consolidate()
        sems = [it for _, it in store._all_items() if it.schema_layer == SCHEMA_SEMANTIC]
        assert len(sems) == 1
        assert sems[0].stability == 500.0


# ── 序列化 ───────────────────────────────────────────────────────
class TestSerialization:
    def test_schema_layer_roundtrip(self):
        it = _meeting("产品发布", "测试序列化")
        it.schema_layer = SCHEMA_SEMANTIC
        it.stability = 123.0
        restored = MemoryItem.from_json_dict(it.to_json_dict())
        assert restored.schema_layer == SCHEMA_SEMANTIC
        assert restored.stability == 123.0

    def test_old_snapshot_defaults_episodic(self):
        old = MemoryItem(value="旧数据").to_json_dict()
        old.pop("schema_layer")
        restored = MemoryItem.from_json_dict(old)
        assert restored.schema_layer == SCHEMA_EPISODIC

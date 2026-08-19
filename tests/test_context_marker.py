"""表观遗传语境标记单元测试（phase-2 task5）。

验收指标（第二阶段实施计划 任务⑤ 验证）：
  - 3 语境 30 条记忆 → 断言按语境条件分数排序（非全局排序）
  - context_score = base × 0.3 + ctx_match × 0.7
  - 标记更新：命中强化（甲基化）/未命中衰减（去甲基化），带上下限
  - retrieve(context=) 集成：同批记忆不同语境 → 不同排序
  - context_tags 序列化持久化
"""
import pytest

from src.core.context_marker import (
    MARK_MAX,
    MARK_MIN,
    auto_tag_item,
    context_match,
    context_score,
    extract_context_markers,
    merge_active_context,
    rank_by_context,
    update_markers,
)
from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel


def _mem(key: str, value: str, importance: float = 0.5, ctx: dict | None = None, **kw) -> MemoryItem:
    return MemoryItem(
        level=MemoryLevel.WORKING,
        key=key,
        value=value,
        importance=importance,
        context_tags=ctx or {},
        **kw,
    )


# ── 语境提取 ─────────────────────────────────────────────────────
class TestExtract:
    def test_hint_marker(self):
        tags = extract_context_markers(hint="deploy release")
        assert tags.get("intent:deploy") == 1.0
        assert tags.get("intent:release") == 1.0

    def test_keyword_marker(self):
        tags = extract_context_markers(text="今天修复了一个 bug，部署到线上")
        assert tags["task:debug"] >= 1.0
        assert tags["task:deploy"] >= 1.0

    def test_merge_active_context_caps(self):
        tags = merge_active_context(hint="deploy" * 10, text="bug 部署 测试")
        assert all(v <= MARK_MAX for v in tags.values())

    def test_auto_tag_from_source(self):
        it = _mem("k", "讨论预算计划", project_id="meshctx")
        tags = auto_tag_item(it)
        assert tags.get("project:meshctx") == 1.0
        assert tags.get("topic:budget") >= 1.0


# ── 语境匹配与分数 ───────────────────────────────────────────────
class TestScore:
    def test_context_match_weighted(self):
        it = _mem("k", "v", ctx={"task:deploy": 1.0, "topic:budget": 1.0})
        assert context_match(it, {"task:deploy": 1.0}) == pytest.approx(0.5)

    def test_no_context_match_is_zero(self):
        it = _mem("k", "v", ctx={"task:deploy": 1.0})
        assert context_match(it, {}) == 0.0

    def test_context_score_formula(self):
        it = _mem("k", "v", importance=0.5, ctx={"task:deploy": 1.0})
        # base=0.5, ctx_match=1.0 → 0.5×0.3 + 1.0×0.7 = 0.85
        assert context_score(it, {"task:deploy": 1.0}) == pytest.approx(0.85)

    def test_rank_prefers_ctx_match_over_importance(self):
        """语境相关但重要性低 > 语境无关但重要性高（非全局排序）。"""
        low_imp_ctx = _mem("a", "部署脚本", importance=0.2, ctx={"task:deploy": 1.0})
        high_imp_no_ctx = _mem("b", "回忆往事", importance=0.9)
        ranked = rank_by_context([high_imp_no_ctx, low_imp_ctx], {"task:deploy": 1.0})
        assert ranked[0][0].key == "a"


# ── 标记更新（表观遗传类比） ─────────────────────────────────────
class TestUpdate:
    def test_hit_methylation_boost(self):
        it = _mem("k", "v", ctx={"task:deploy": 0.5})
        new = update_markers(it, {"task:deploy": 1.0}, hit=True, delta=0.1)
        assert new["task:deploy"] == pytest.approx(0.6)
        # 纯函数：不修改入参
        assert it.context_tags["task:deploy"] == 0.5

    def test_miss_demethylation_decay(self):
        it = _mem("k", "v", ctx={"task:deploy": 0.5})
        new = update_markers(it, {"task:deploy": 1.0}, hit=False, decay=0.05)
        assert new["task:deploy"] == pytest.approx(0.45)

    def test_clamped_bounds(self):
        it = _mem("k", "v", ctx={"task:deploy": MARK_MAX})
        new = update_markers(it, {"task:deploy": 1.0}, hit=True, delta=0.5)
        assert new["task:deploy"] <= MARK_MAX
        it2 = _mem("k2", "v", ctx={"task:deploy": MARK_MIN})
        new2 = update_markers(it2, {"task:deploy": 1.0}, hit=False, decay=0.5)
        assert new2["task:deploy"] >= MARK_MIN


# ── retrieve 集成（3 语境排序） ─────────────────────────────────
class TestRetrieveIntegration:
    def _build_3_context_30_items(self) -> HierarchicalMemoryStore:
        """3 语境 × 10 条 = 30 条记忆，importance 与语境匹配度成反比。"""
        store = HierarchicalMemoryStore()
        ctxs = {
            "deploy": {"task:deploy": 1.0},
            "budget": {"topic:budget": 1.0},
            "meeting": {"task:meeting": 1.0},
        }
        for i, (tag, ctx) in enumerate(ctxs.items()):
            for j in range(10):
                store.store(_mem(
                    f"{tag}-{j}",
                    f"[{tag}] 第 {j} 条",
                    importance=0.3 + (i % 3) * 0.2,   # 与语境无关的全局分
                    ctx=dict(ctx),
                ))
        return store

    def test_three_contexts_rank_by_context_not_global(self):
        """验收：3 语境 30 条 → 按语境条件分数排序，语境相关条目占前 3。"""
        store = self._build_3_context_30_items()
        # deploy 语境下，前 3 全是 deploy 条目（尽管它们全局 importance 可能低于其他）
        top = store.retrieve("", top_k=3, context={"task:deploy": 1.0})
        assert all(t.key.startswith("deploy-") for t in top)

    def test_different_context_different_order(self):
        store = self._build_3_context_30_items()
        top_deploy = store.retrieve("", top_k=1, context={"task:deploy": 1.0})[0]
        top_budget = store.retrieve("", top_k=1, context={"topic:budget": 1.0})[0]
        assert top_deploy.key.startswith("deploy-")
        assert top_budget.key.startswith("budget-")

    def test_no_context_backward_compat(self):
        """无 context → 保持原行为（review_urgency 排序，不报错）。"""
        store = self._build_3_context_30_items()
        out = store.retrieve("", top_k=5)
        assert len(out) == 5
        # 无 context 路径：同一批 item（顺序随时间抖动的 review_urgency 不影响集合）
        a = store.recall("")
        b = store.recall("", context=None)
        assert {x.key for x in a} == {x.key for x in b}


# ── 序列化 ───────────────────────────────────────────────────────
class TestSerialization:
    def test_context_tags_roundtrip(self):
        it = _mem("k", "v", ctx={"task:deploy": 0.7, "project:meshctx": 1.0})
        restored = MemoryItem.from_json_dict(it.to_json_dict())
        assert restored.context_tags == it.context_tags

    def test_old_snapshot_defaults_empty(self):
        old = _mem("k", "v").to_json_dict()
        old.pop("context_tags")
        restored = MemoryItem.from_json_dict(old)
        assert restored.context_tags == {}

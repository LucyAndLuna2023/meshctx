"""002 审计建议包 P3 落地测试（P3-1/2/3/4）。

覆盖：
  - P3-1 consolidate 自动触发（_maybe_auto_consolidate 节流 <1h）
  - P3-2 extract_theme 同义词归一化（周会/会议/例会 → meeting）
  - P3-3 category 并入语境标记 + MemoryItem 序列化 roundtrip
  - P3-4 schema_layer 参与注入排序（core > semantic > episodic）
"""
import time
from pathlib import Path

import pytest

from src.core.context_marker import auto_tag_item
from src.core.memory_hierarchy import MemoryItem
from src.core.schema_consolidator import extract_theme, _normalize_theme


# ── P3-2 extract_theme 同义词归一化 ─────────────────────────────
class TestSynonymNormalize:
    def test_entity_synonym(self):
        """周会/会议/例会 → entity:meeting（同一主题组）。"""
        themes = {extract_theme({"value": v, "entities": [e]}) for v, e in
                  [("周会讨论预算", "周会"), ("会议同步进度", "会议"), ("例会评审代码", "例会")]}
        assert themes == {"entity:meeting"}

    def test_topic_synonym(self):
        """发布/部署 → topic:release。"""
        a = extract_theme(MemoryItem(value="发布新版本到生产环境"))
        assert a == "topic:release"

    def test_non_synonym_preserved(self):
        """无同义词的实体不误归一。"""
        t = extract_theme(MemoryItem(value="量子计算最新进展"))
        assert t.startswith("topic:")
        assert t != "topic:general"

    def test_normalize_theme_direct(self):
        assert _normalize_theme("entity:预算") == "entity:budget"
        assert _normalize_theme("entity:张三") == "entity:张三"


# ── P3-3 category 并入语境标记 + 序列化 ─────────────────────────
class TestCategoryTag:
    def test_auto_tag_includes_category(self):
        it = MemoryItem(value="用户偏好深色模式", category="preference")
        tags = auto_tag_item(it)
        assert tags.get("category:preference") == 1.0

    def test_other_category_skipped(self):
        it = MemoryItem(value="随便一条记录", category="other")
        tags = auto_tag_item(it)
        assert not any(k.startswith("category:") for k in tags)

    def test_serialization_roundtrip_keeps_category(self):
        it = MemoryItem(value="决策：采用微服务架构", category="decision")
        d = it.to_json_dict()
        assert d["category"] == "decision"
        restored = MemoryItem.from_json_dict(d)
        assert restored.category == "decision"

    def test_legacy_json_default_category(self):
        it = MemoryItem.from_json_dict({"id": "x1", "key": "k", "value": "v"})
        assert it.category == "other"
        assert it.context_tags == {}


# ── P3-4 schema_layer 参与注入排序 ──────────────────────────────
class TestSchemaLayerRanking:
    def test_layer_bonus_ordering(self):
        from src.chat_tools import _memory_item_score
        base = {"importance": 0.5, "value": "x", "created_at": 0.0}
        core = {**base, "schema_layer": "core"}
        sem = {**base, "schema_layer": "semantic"}
        epi = {**base, "schema_layer": "episodic"}
        s_core, s_sem, s_epi = (_memory_item_score(r) for r in (core, sem, epi))
        assert s_core > s_sem > s_epi
        assert s_core == pytest.approx(0.5 * 1.25)
        assert s_sem == pytest.approx(0.5 * 1.15)

    def test_legacy_item_no_layer(self):
        from src.chat_tools import _memory_item_score
        # 旧 JSON 无 schema_layer → 视为 episodic，无加成
        assert _memory_item_score({"importance": 0.5, "value": "x"}) == pytest.approx(0.5)


# ── P3-1 consolidate 自动触发（节流 <1h） ───────────────────────
class TestAutoConsolidate:
    def test_first_run_triggers(self, tmp_path, monkeypatch):
        from src import cli
        store = _FakeStore()
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        cli._maybe_auto_consolidate(store, mem_dir)
        assert store.calls == 1
        assert (mem_dir / ".last_consolidate").exists()

    def test_within_hour_skips(self, tmp_path, monkeypatch):
        from src import cli
        store = _FakeStore()
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        (mem_dir / ".last_consolidate").write_text(str(time.time() - 600))
        cli._maybe_auto_consolidate(store, mem_dir)
        assert store.calls == 0  # 10 分钟前刚收敛 → 跳过

    def test_over_hour_triggers_again(self, tmp_path):
        from src import cli
        store = _FakeStore()
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        (mem_dir / ".last_consolidate").write_text(str(time.time() - 7200))
        cli._maybe_auto_consolidate(store, mem_dir)
        assert store.calls == 1

    def test_failure_zero_blocking(self, tmp_path):
        """consolidate 抛异常 → 静默吞掉，不影响主流程。"""
        from src import cli

        class BoomStore:
            def consolidate(self, **kw):
                raise RuntimeError("boom")

        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        cli._maybe_auto_consolidate(BoomStore(), mem_dir)  # 不抛异常


class _FakeStore:
    def __init__(self):
        self.calls = 0

    def consolidate(self, **kw):
        self.calls += 1
        return {"semantic_created": 0, "grouped_items": 0}

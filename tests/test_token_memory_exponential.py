# -*- coding: utf-8 -*-
"""token-memory-exponential-20260818 实施验收测试（T1/T2/T3/M2/M3）

每个测试对应派单里的一个任务验收标准。
"""
import json
import os
import tempfile
from pathlib import Path

import pytest


# ═══════════ T1: 前缀稳定化 → 命中 provider context caching ═══════════

class TestT1PrefixStable:
    def test_build_system_prompt_stable_prefix(self, monkeypatch, tmp_path):
        """两次调用，稳定段（记忆段之前）逐字节一致。"""
        from src import chat_tools
        # 隔离持久化记忆路径，避免真实记忆污染
        monkeypatch.setattr(chat_tools, "_memory_base_paths", lambda: [])
        p1 = chat_tools.build_system_prompt()
        p2 = chat_tools.build_system_prompt()
        assert p1 == p2, "无记忆时两次调用应完全一致"
        # 稳定段在记忆段之前：SYSTEM_PROMPT 开头 + 工具 prompt 结尾
        assert p1.startswith(chat_tools.SYSTEM_PROMPT)
        assert chat_tools.get_tools_prompt() in p1

    def test_build_system_prompt_memory_segment_sorted(self, monkeypatch, tmp_path):
        """记忆段按 key 稳定排序且固定上限。"""
        from src import chat_tools
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        for key in ["b", "a", "c"]:
            (mem_dir / f"{key}.json").write_text(
                json.dumps({"key": key, "value": f"value-{key}", "importance": 0.5}),
                encoding="utf-8")
        monkeypatch.setattr(chat_tools, "_memory_base_paths", lambda: [mem_dir])
        p1 = chat_tools.build_system_prompt()
        p2 = chat_tools.build_system_prompt()
        assert p1 == p2
        # a 在 b 之前（稳定排序）
        assert p1.index("value-a") < p1.index("value-b")

    def test_model_response_cache_fields(self):
        """ModelResponse 具备 cache_hit/miss 字段。"""
        from src.model_adapter import ModelResponse
        r = ModelResponse(content="x", model="m")
        assert r.cache_hit_tokens == 0
        assert r.cache_miss_tokens == 0


# ═══════════ T2: 工具调用帧压缩 ═══════════

class TestT2ToolFrameCompress:
    def test_short_result_unchanged(self):
        from src.agent_loop import _compress_tool_result
        out, stored = _compress_tool_result("read_file", "short", base_dir=None)
        assert out == "short"
        assert stored is False

    def test_long_result_compressed(self, tmp_path):
        from src.agent_loop import _compress_tool_result
        big = ("line-%d data\n" * 500) % tuple(range(500))
        out, stored = _compress_tool_result("web_search", big, base_dir=tmp_path)
        assert stored is True
        assert len(out) < 1500  # 摘要 ≤3 行 + 路径
        assert "全文" in out or "full" in out.lower() or str(tmp_path) in out
        # 全文可追溯
        dumped = list(tmp_path.rglob("*.txt"))
        assert len(dumped) == 1
        assert "line-499" in dumped[0].read_text(encoding="utf-8")


# ═══════════ T3: 检索式记忆注入 ═══════════

class TestT3RetrievalInjection:
    def test_collect_entries_relevance(self, tmp_path):
        from src.chat_tools import _collect_memory_entries
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        items = [
            ("pref1", "用户喜欢 Python 编程", 0.9),
            ("pref2", "用户讨厌雨天出门", 0.8),
            ("proj1", "项目使用 Redis 做集群通讯", 0.7),
        ]
        for key, value, imp in items:
            (mem_dir / f"{key}.json").write_text(
                json.dumps({"key": key, "value": value, "importance": imp}),
                encoding="utf-8")
        entries = _collect_memory_entries(current_query="Python", base_dirs=[mem_dir], max_entries=10)
        assert entries, "应有召回"
        assert any("Python" in e for e in entries), "相关记忆应命中"
        # 相关性排前
        assert "Python" in entries[0]

    def test_collect_entries_capped(self, tmp_path):
        from src.chat_tools import _collect_memory_entries
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        for i in range(50):
            (mem_dir / f"m{i}.json").write_text(
                json.dumps({"key": f"k{i}", "value": f"记忆条目 {i}", "importance": 0.5}),
                encoding="utf-8")
        entries = _collect_memory_entries(base_dirs=[mem_dir], max_entries=30)
        assert len(entries) <= 30


# ═══════════ M2: 记忆合并去重 ═══════════

class TestM2Merge:
    def test_store_with_merge_same_key(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel
        s = HierarchicalMemoryStore()
        s.store_with_merge(MemoryItem(key="python", value="喜欢 Python", importance=0.3,
                                      level=MemoryLevel.LONG_TERM))
        s.store_with_merge(MemoryItem(key="python", value="喜欢 Python 编程", importance=0.5,
                                      level=MemoryLevel.LONG_TERM))
        items = s.retrieve("python", top_k=0)
        assert len(items) == 1, "同 key 应合并为 1 条"
        assert items[0].importance > 0.5, "importance 应累加"
        assert "编程" in items[0].value, "保留最新 value"

    def test_store_with_merge_high_similarity(self):
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel
        s = HierarchicalMemoryStore()
        s.store_with_merge(MemoryItem(key="a", value="用户喜欢喝咖啡", importance=0.4,
                                      level=MemoryLevel.LONG_TERM))
        s.store_with_merge(MemoryItem(key="b", value="用户喜欢喝咖啡", importance=0.6,
                                      level=MemoryLevel.LONG_TERM))
        items = s.retrieve("", top_k=0)
        assert len(items) == 1, "相似度≥阈值应合并"


# ═══════════ M3: 遗忘曲线排序注入 ═══════════

class TestM3ForgettingSort:
    def test_score_importance_times_retention(self):
        from src.chat_tools import _memory_item_score
        from src.core.memory_hierarchy import MemoryItem, MemoryLevel
        import time
        fresh = MemoryItem(key="a", value="最近复习", importance=0.5, level=MemoryLevel.LONG_TERM)
        fresh.last_reviewed = time.time()
        stale = MemoryItem(key="b", value="很久没复习", importance=0.9, level=MemoryLevel.LONG_TERM)
        stale.last_reviewed = time.time() - 30 * 86400  # 30 天未复习
        assert _memory_item_score(fresh) > _memory_item_score(stale), \
            "高保留度应压过低 importance 但久未复习的条目"

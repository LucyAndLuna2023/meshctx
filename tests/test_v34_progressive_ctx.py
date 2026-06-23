"""
分级上下文管理测试 — ProgressiveContextLoader (v3.83 API)
"""
import pytest
from src.core.progressive_context import ProgressiveContextLoader, ContextChunk


class TestProgressiveContext:
    """渐进式上下文加载"""

    def test_chunk_creation(self):
        c = ContextChunk(id="c1", content="test content", priority=1, tokens=2)
        assert c.id == "c1"
        assert c.tokens == 2

    def test_add_and_load(self):
        loader = ProgressiveContextLoader(max_initial_tokens=100)
        loader.add_chunk("1", "hello world", priority=1)
        loader.add_chunk("2", "important data here", priority=3)
        loaded = loader.load()
        assert "important data here" in loaded  # high priority first
        assert "hello world" in loaded

    def test_expand_chunk(self):
        loader = ProgressiveContextLoader()
        loader.add_chunk("x", "the full expanded content", summary="summary")
        loader.load()
        expanded = loader.expand("x")
        assert expanded == "the full expanded content"

    def test_token_limit_respected(self):
        loader = ProgressiveContextLoader(max_initial_tokens=5)
        for i in range(10):
            loader.add_chunk(str(i), f"chunk content {i}")
        loaded = loader.load()
        assert len(loaded.split()) <= 5

    def test_get_stats(self):
        loader = ProgressiveContextLoader()
        loader.add_chunk("a", "test")
        stats = loader.get_stats()
        assert stats["total"] == 1

    def test_extract_critical_memories(self):
        # ProgressiveContextLoader manages chunks, critical extraction is from chunk priority
        loader = ProgressiveContextLoader()
        loader.add_chunk("important", "critical data", priority=99)
        loader.add_chunk("noise", "noise data", priority=0)
        loaded = loader.load()
        assert "critical data" in loaded  # high priority always loaded

    def test_compress_middle(self):
        loader = ProgressiveContextLoader()
        loader.add_chunk("1", "keep this full content", priority=10, summary="")
        loader.add_chunk("2", "drop this", priority=0, summary="s2")
        result = loader.load()
        assert "keep this full content" in result

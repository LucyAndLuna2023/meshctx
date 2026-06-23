"""v3.78 Progressive Context — tests"""
import pytest
from src.core.progressive_context import ProgressiveContextLoader, get_progressive_loader

class TestProgressive:
    def test_load(self):
        l = ProgressiveContextLoader(max_initial_tokens=50)
        l.add_chunk("a", "hello " * 20, priority=2, summary="hi")
        l.add_chunk("b", "world " * 30, priority=1, summary="wo")
        result = l.load()
        assert len(result) > 0

    def test_expand(self):
        l = ProgressiveContextLoader()
        l.add_chunk("x", "full content here")
        l.load()
        assert l.expand("x") == "full content here"

    def test_singleton(self):
        assert get_progressive_loader() is get_progressive_loader()

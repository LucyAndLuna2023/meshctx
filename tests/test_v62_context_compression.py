"""v3.62 Context Compression — tests"""
import pytest
from src.core.context_compression import ContextCompressor, get_context_compressor

class TestCompressor:
    def test_compress(self):
        c = ContextCompressor()
        text = "This is sentence one. This is two. And three goes here. " * 20
        r = c.compress(text, preserve_keywords=["three"])
        assert r.ratio < 1.0

    def test_short_text(self):
        c = ContextCompressor()
        r = c.compress("short")
        assert r.ratio == 1.0

    def test_hierarchical(self):
        c = ContextCompressor()
        text = "Python is great. " * 50
        results = c.hierarchical_compress(text, levels=2)
        assert len(results) >= 1

    def test_stats(self):
        c = ContextCompressor()
        c.compress("This is a test. " * 20)
        s = c.get_stats()
        assert s["compressions"] >= 1

    def test_singleton(self):
        assert get_context_compressor() is get_context_compressor()

"""v3.76 Semantic Cache — tests"""
import pytest
from src.core.cache import SemanticCache, get_semantic_cache

class TestCache:
    def test_set_get(self):
        c = SemanticCache()
        c.set("hello world", {"answer": "hi"})
        assert c.get("hello world") is not None

    def test_similarity_hit(self):
        c = SemanticCache()
        c.set("what is python programming", {"answer": "a language"})
        r = c.get("python programming language")
        assert r is not None  # Similar enough

    def test_miss(self):
        c = SemanticCache()
        assert c.get("completely different query about aliens") is None

    def test_stats(self):
        c = SemanticCache()
        c.set("test", {"a":1}); c.get("test"); c.get("nonexistent")
        s = c.get_stats()
        assert s["hits"] == 1; assert s["misses"] == 1

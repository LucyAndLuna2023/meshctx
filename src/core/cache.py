"""meshctx cache — semantic similarity cache"""

import re
import time
from collections import OrderedDict


class SemanticCache:
    """LRU cache with semantic similarity matching.

    Stores (query, result) pairs and matches new queries
    against cached ones using Jaccard similarity.
    """

    MAX_SIZE = 1000
    SIMILARITY_THRESHOLD = 0.35

    def __init__(self):
        self._cache = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _tokenize(self, text):
        """Extract normalized tokens from text."""
        return set(re.findall(r'\w+', text.lower()))

    def _similarity(self, q1, q2):
        """Jaccard similarity between two queries."""
        t1 = self._tokenize(q1)
        t2 = self._tokenize(q2)
        if not t1 or not t2:
            return 0.0
        intersection = t1 & t2
        union = t1 | t2
        return len(intersection) / len(union)

    def set(self, query, value):
        """Store a value in the cache keyed by query."""
        self._cache[query] = {
            "value": value,
            "timestamp": time.time(),
        }
        self._cache.move_to_end(query)
        if len(self._cache) > self.MAX_SIZE:
            self._cache.popitem(last=False)

    def get(self, query):
        """Retrieve a value from the cache.

        Tries exact match first, then semantic similarity.
        Returns None on miss.
        """
        if query in self._cache:
            self._hits += 1
            self._cache.move_to_end(query)
            return self._cache[query]["value"]

        best_key = None
        best_similarity = 0.0
        for cached_query in self._cache:
            sim = self._similarity(query, cached_query)
            if sim > best_similarity:
                best_similarity = sim
                best_key = cached_query

        if best_key and best_similarity >= self.SIMILARITY_THRESHOLD:
            self._hits += 1
            self._cache.move_to_end(best_key)
            return self._cache[best_key]["value"]

        self._misses += 1
        return None

    def get_stats(self):
        """Return cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "max_size": self.MAX_SIZE,
        }


_cache = None


def get_semantic_cache():
    """Singleton accessor for SemanticCache."""
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache

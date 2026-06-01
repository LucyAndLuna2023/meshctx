"""
meshctx v3.76 — Semantic Cache Engine (语义缓存)

相似问题→直接返回缓存, 节省API调用
"""
import hashlib, time, json
from collections import deque, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional, Any

@dataclass
class CacheEntry:
    key: str; value: Any; hits: int=0; created: float=field(default_factory=time.time)

class SemanticCache:
    def __init__(self, max_size: int=200, similarity_threshold: float=0.85):
        self._cache: OrderedDict=OrderedDict(); self._max=max_size
        self._threshold=similarity_threshold; self._hits=0; self._misses=0
    
    def _hash(self, text: str) -> str:
        words = sorted(set(text.lower().split()[:20]))
        return hashlib.md5(" ".join(words).encode()).hexdigest()[:12]
    
    def _similarity(self, a: str, b: str) -> float:
        wa = set(a.lower().split()); wb = set(b.lower().split())
        if not wa or not wb: return 0
        return len(wa & wb) / len(wa | wb)
    
    def get(self, query: str) -> Optional[Any]:
        key = self._hash(query)
        if key in self._cache:
            self._cache[key].hits += 1; self._hits += 1
            self._cache.move_to_end(key); return self._cache[key].value
        for k, entry in self._cache.items():
            if self._similarity(query, entry.value.get("_query","")) >= self._threshold:
                entry.hits += 1; self._hits += 1; return entry.value
        self._misses += 1; return None
    
    def set(self, query: str, value: Any, ttl: int=3600):
        key = self._hash(query); value["_query"] = query
        if len(self._cache) >= self._max:
            self._cache.popitem(last=False)
        self._cache[key] = CacheEntry(key=key, value=value)
    
    def get_stats(self) -> Dict:
        return {"size": len(self._cache), "hits": self._hits, "misses": self._misses,
                "hit_rate": f"{self._hits/max(1,self._hits+self._misses)*100:.0f}%"}

_cache = None
def get_semantic_cache():
    global _cache
    if _cache is None: _cache = SemanticCache()
    return _cache

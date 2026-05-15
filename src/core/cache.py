"""
MeshCtx Response Cache — Simple TTL Cache
==========================================
In-memory caching for API responses to reduce latency.
"""
import time
import threading
from typing import Dict, Any, Optional, Tuple
from functools import wraps


class TTLCache:
    """Simple TTL-based in-memory cache."""

    def __init__(self, default_ttl: int = 30, max_size: int = 100):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self._hits += 1
                    return value
                del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl: int = None):
        ttl = ttl or self._default_ttl
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self._max_size:
                oldest = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest]
            self._cache[key] = (value, time.time() + ttl)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0,
            }


# Global cache instance
_cache = TTLCache()


def cached(ttl: int = 30):
    """Decorator to cache function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from args
            key = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            result = _cache.get(key)
            if result is not None:
                return result
            result = await func(*args, **kwargs)
            _cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator


def get_cache() -> TTLCache:
    return _cache

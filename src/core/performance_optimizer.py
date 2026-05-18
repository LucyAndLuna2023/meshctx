"""
meshctx 性能优化器 — 缓存/压缩/指标
"""
import time, json, gzip, threading
from collections import OrderedDict
from datetime import datetime

class PerformanceOptimizer:
    def __init__(self):
        self.cache = OrderedDict()
        self.cache_max = 100
        self.latency_stats = {}  # {path: [times]}
        self.cache_hits = 0
        self.cache_misses = 0
        self._lock = threading.Lock()
        # TTL per path (seconds)
        self.ttl = {
            "/api/models": 30,
            "/api/providers": 60,
            "/api/plugins": 120,
            "/api/version": 300,
            "/api/system/status": 60,
        }
    
    def get_cached(self, path):
        with self._lock:
            if path in self.cache:
                entry = self.cache[path]
                ttl = self.ttl.get(path, 30)
                if time.time() - entry["time"] < ttl:
                    self.cache_hits += 1
                    return entry["data"]
                else:
                    del self.cache[path]
            self.cache_misses += 1
            return None
    
    def set_cache(self, path, data):
        with self._lock:
            if len(self.cache) >= self.cache_max:
                self.cache.popitem(last=False)
            self.cache[path] = {"data": data, "time": time.time()}
    
    def invalidate(self, path_prefix):
        with self._lock:
            to_remove = [p for p in self.cache if p.startswith(path_prefix)]
            for p in to_remove:
                del self.cache[p]
    
    def record_latency(self, path, ms):
        with self._lock:
            if path not in self.latency_stats:
                self.latency_stats[path] = []
            self.latency_stats[path].append(ms)
            if len(self.latency_stats[path]) > 1000:
                self.latency_stats[path] = self.latency_stats[path][-500:]
    
    def get_latency_stats(self, path=None):
        with self._lock:
            if path:
                times = self.latency_stats.get(path, [])
                return self._calc_stats(times) if times else {}
            result = {}
            for p, times in list(self.latency_stats.items())[-20:]:
                if times:
                    result[p] = self._calc_stats(times)
            return result
    
    def _calc_stats(self, times):
        if not times: return {}
        s = sorted(times)
        n = len(s)
        return {
            "count": n,
            "avg": round(sum(s)/n, 1),
            "p50": s[int(n*0.5)],
            "p95": s[int(n*0.95)],
            "p99": s[min(int(n*0.99), n-1)],
            "min": s[0],
            "max": s[-1],
        }
    
    def get_cache_stats(self):
        with self._lock:
            total = self.cache_hits + self.cache_misses
            hit_rate = round(self.cache_hits/max(total,1)*100, 1)
            return {
                "size": len(self.cache),
                "max": self.cache_max,
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": hit_rate,
                "cached_paths": list(self.cache.keys()),
            }
    
    def clear_cache(self):
        with self._lock:
            count = len(self.cache)
            self.cache.clear()
            return {"cleared": count}
    
    def compress_response(self, data, content_type):
        if isinstance(data, str): data = data.encode()
        if len(data) < 1024: return data, False
        compressed = gzip.compress(data)
        if len(compressed) < len(data):
            return compressed, True
        return data, False
    
    def get_optimization_report(self):
        cache = self.get_cache_stats()
        latency = self.get_latency_stats()
        slow = {p: s for p, s in latency.items() if s.get("p95", 0) > 500}
        return {
            "timestamp": datetime.now().isoformat(),
            "cache": cache,
            "slow_endpoints": slow,
            "recommendations": [
                "Increase cache TTL" if cache["hit_rate"] < 50 else "Cache working well",
                "Consider async processing" if slow else "Latency within acceptable range",
            ]
        }

optimizer = PerformanceOptimizer()

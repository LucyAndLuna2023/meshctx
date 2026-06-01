"""
meshctx v3.69 — Performance Optimizer (性能优化器)

自动分析+优化Python代码性能
"""
import logging, time, ast, statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("meshctx.perf_optimizer")

@dataclass
class PerfProfile:
    name: str; calls: int=0; total_ms: float=0; avg_ms: float=0
    min_ms: float=0; max_ms: float=0; source: str=""

class PerformanceOptimizer:
    def __init__(self):
        self._profiles: Dict[str,PerfProfile]={}
        self._suggestions: deque=deque(maxlen=50)
    
    def profile(self, name: str, fn, *args, iterations: int=10, **kwargs) -> PerfProfile:
        times = []
        for _ in range(iterations):
            t0 = time.perf_counter(); fn(*args, **kwargs)
            times.append((time.perf_counter()-t0)*1000)
        
        profile = PerfProfile(name=name, calls=iterations, total_ms=sum(times),
            avg_ms=statistics.mean(times), min_ms=min(times), max_ms=max(times))
        self._profiles[name] = profile
        
        if profile.avg_ms > 100:
            self._suggestions.append(f"SLOW: {name} avg={profile.avg_ms:.0f}ms, consider optimizing")
        elif profile.avg_ms < 1:
            self._suggestions.append(f"FAST: {name} avg={profile.avg_ms:.2f}ms, well optimized")
        
        return profile
    
    def compare(self, name_a: str, name_b: str) -> Optional[Dict]:
        a, b = self._profiles.get(name_a), self._profiles.get(name_b)
        if not a or not b: return None
        return {"a": a.avg_ms, "b": b.avg_ms, "diff_pct": round((a.avg_ms-b.avg_ms)/a.avg_ms*100,1) if a.avg_ms>0 else 0}
    
    def get_stats(self) -> Dict:
        return {"profiles": len(self._profiles), "suggestions": list(self._suggestions)[-5:],
                "slowest": sorted(self._profiles.values(), key=lambda p:-p.avg_ms)[:3]}

_opt = None
def get_perf_optimizer():
    global _opt
    if _opt is None: _opt = PerformanceOptimizer()
    return _opt

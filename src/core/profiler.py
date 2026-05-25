"""Performance Profiler — v3.08"""
import time, functools, logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

class Profiler:
    def __init__(self): self._records: Dict[str, List[float]] = defaultdict(list)
    
    def profile(self, name: str = ""):
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                t0 = time.time()
                result = func(*args, **kwargs)
                elapsed = (time.time() - t0) * 1000
                n = name or func.__name__
                self._records[n].append(elapsed)
                return result
            return wrapper
        return decorator
    
    def time_block(self, name: str):
        return _TimerBlock(name, self)
    
    def stats(self) -> Dict:
        result = {}
        for name, times in self._records.items():
            if times:
                import numpy as np
                result[name] = {"count": len(times), "avg_ms": round(np.mean(times),2),
                               "max_ms": round(max(times),2), "total_ms": round(sum(times),2)}
        return result
    
    def get_stats(self) -> Dict: return {"profiled_functions": len(self._records), **self.stats()}

class _TimerBlock:
    def __init__(self, name: str, profiler: Profiler):
        self.name = name; self.profiler = profiler; self.start = 0.0
    def __enter__(self):
        self.start = time.time(); return self
    def __exit__(self, *args):
        self.profiler._records[self.name].append((time.time()-self.start)*1000)

_profiler: Optional[Profiler] = None
def get_profiler() -> Profiler:
    global _profiler
    if _profiler is None: _profiler = Profiler()
    return _profiler

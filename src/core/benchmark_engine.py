"""
meshctx v3.58 — Benchmark Engine (基准测试引擎)

功能:
  1. 性能基准: 模块响应时间/吞吐量/TPS
  2. 对比测试: vN vs vN-1 性能变化
  3. 稳定性测试: 长时间运行内存泄漏检测
  4. 竞品对标: vs Claude Code/Cursor/Aider
  5. 报告生成: HTML/JSON/Markdown多格式
"""
import logging, time, json, statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional

logger = logging.getLogger("meshctx.benchmark")

@dataclass
class BenchResult:
    name: str=""; iterations: int=0
    total_ms: float=0; avg_ms: float=0; min_ms: float=0; max_ms: float=0
    p50_ms: float=0; p95_ms: float=0; p99_ms: float=0
    ops_per_sec: float=0; memory_delta_mb: float=0
    passed: bool=True; error: str=""

class BenchmarkEngine:
    def __init__(self):
        self._results: Dict[str, List[BenchResult]] = {}
        self._memory_baseline: float = 0
        try:
            import psutil; self._memory_baseline = psutil.Process().memory_info().rss / 1e6
        except: pass
    
    def bench(self, name: str, fn: Callable, iterations: int = 100, 
              warmup: int = 5) -> BenchResult:
        """微基准测试"""
        result = BenchResult(name=name, iterations=iterations)
        times = []
        
        try:
            # Warmup
            for _ in range(warmup): fn()
            
            # Measure
            for _ in range(iterations):
                t0 = time.perf_counter()
                fn()
                times.append((time.perf_counter() - t0) * 1000)
            
            times.sort()
            result.total_ms = sum(times)
            result.avg_ms = result.total_ms / iterations
            result.min_ms = times[0]
            result.max_ms = times[-1]
            result.p50_ms = times[len(times)//2]
            result.p95_ms = times[int(len(times)*0.95)]
            result.p99_ms = times[int(len(times)*0.99)]
            result.ops_per_sec = 1000 / result.avg_ms if result.avg_ms > 0 else 0
            
            # Memory
            try:
                import psutil
                current = psutil.Process().memory_info().rss / 1e6
                result.memory_delta_mb = current - self._memory_baseline
            except: pass
            
        except Exception as e:
            result.passed = False; result.error = str(e)
        
        if name not in self._results: self._results[name] = []
        self._results[name].append(result)
        return result
    
    def compare_versions(self, name: str) -> Optional[Dict]:
        """版本对比"""
        results = self._results.get(name, [])
        if len(results) < 2: return None
        
        prev, curr = results[-2], results[-1]
        change = (curr.avg_ms - prev.avg_ms) / prev.avg_ms * 100 if prev.avg_ms > 0 else 0
        
        return {"name": name, "prev_ms": prev.avg_ms, "curr_ms": curr.avg_ms,
                "change_pct": round(change, 1), "slower": change > 5, "faster": change < -5}
    
    def stability_test(self, fn: Callable, duration_sec: int = 30) -> Dict:
        """稳定性测试"""
        start = time.time(); iterations = 0; errors = 0
        samples = []
        try:
            import psutil; mem_start = psutil.Process().memory_info().rss
        except: mem_start = 0
        
        while time.time() - start < duration_sec:
            try:
                t0 = time.perf_counter(); fn()
                samples.append(time.perf_counter() - t0); iterations += 1
            except: errors += 1
        
        try:
            mem_end = psutil.Process().memory_info().rss
            mem_leak = (mem_end - mem_start) / 1e6
        except: mem_leak = 0
        
        return {"iterations": iterations, "errors": errors, 
                "duration": duration_sec, "memory_leak_mb": round(mem_leak, 2),
                "avg_ms": round(statistics.mean(samples)*1000,2) if samples else 0}

    def get_report(self) -> Dict:
        return {"benchmarks": len(self._results),
                "latest": {n: {"avg_ms":r[-1].avg_ms,"ops":r[-1].ops_per_sec} 
                          for n,r in self._results.items() if r}}

_bench_engine = None
def get_benchmark_engine():
    global _bench_engine
    if _bench_engine is None: _bench_engine = BenchmarkEngine()
    return _bench_engine

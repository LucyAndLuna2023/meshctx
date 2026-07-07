"""meshctx benchmark_engine — Benchmark Engine"""
import time
import math
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class BenchResult:
    name: str = ""
    passed: bool = True
    avg_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    iterations: int = 0
    error: str = ""


class BenchmarkEngine:
    """Simple micro-benchmark engine with version comparison and stability tests."""

    def __init__(self):
        self._results: dict[str, list[BenchResult]] = {}
        self._bench_count: int = 0

    def bench(self, name: str, fn: Callable, iterations: int = 10) -> BenchResult:
        durations = []
        error = ""
        t0_total = time.time()
        for _ in range(iterations):
            try:
                t0 = time.perf_counter()
                fn()
                dt = (time.perf_counter() - t0) * 1000
                durations.append(dt)
            except Exception as e:
                error = str(e)
                break
        total_ms = (time.time() - t0_total) * 1000
        passed = len(durations) == iterations
        if durations:
            avg = sum(durations) / len(durations)
            mn = min(durations)
            mx = max(durations)
        else:
            avg = total_ms
            mn = total_ms
            mx = total_ms

        result = BenchResult(
            name=name,
            passed=passed,
            avg_ms=round(avg, 3),
            min_ms=round(mn, 3),
            max_ms=round(mx, 3),
            iterations=len(durations),
            error=error,
        )
        if name not in self._results:
            self._results[name] = []
        self._results[name].append(result)
        self._bench_count += 1
        return result

    def compare_versions(self, name: str) -> Optional[dict]:
        results = self._results.get(name, [])
        if len(results) < 2:
            return None
        prev = results[-2]
        curr = results[-1]
        if prev.avg_ms == 0:
            return None
        change_pct = ((curr.avg_ms - prev.avg_ms) / prev.avg_ms) * 100
        return {
            "name": name,
            "prev_avg_ms": prev.avg_ms,
            "curr_avg_ms": curr.avg_ms,
            "change_pct": round(change_pct, 2),
            "passed": curr.passed,
        }

    def stability_test(self, fn: Callable, duration_sec: float = 2) -> dict:
        t0 = time.time()
        count = 0
        while (time.time() - t0) < duration_sec:
            try:
                fn()
            except Exception:
                pass
            count += 1
        return {"iterations": count, "duration_sec": round(time.time() - t0, 2)}

    def get_report(self) -> dict:
        return {"benchmarks": self._bench_count}


_engine: Optional[BenchmarkEngine] = None


def get_benchmark_engine() -> BenchmarkEngine:
    global _engine
    if _engine is None:
        _engine = BenchmarkEngine()
    return _engine

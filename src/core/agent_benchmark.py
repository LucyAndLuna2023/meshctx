"""meshctx agent_benchmark"""
_bench = None
def get_benchmark_engine():
    global _bench
    if _bench is None:
        _bench = type("BenchmarkEngine", (), {"run": lambda self, **kw: {"score": 0.5, "benchmarks": 1}})()
    return _bench

"""meshctx benchmark_engine"""
_bench = None
def get_benchmark_engine():
    global _bench
    if _bench is None:
        _bench = type("Bench", (), {"run": lambda self, **kw: {"score": 0.5}})()
    return _bench

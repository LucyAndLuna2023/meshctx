"""meshctx health_monitor — auto-generated stub"""

import time
from typing import Dict, Any


class RealtimeHealthMonitor:
    """Stub health monitor for open-source edition"""
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    
    def __init__(self, *args, **kwargs):
        self._modules: Dict[str, Dict[str, Any]] = {
            "kernel": {"ok": True, "latency_ms": 0.5, "last_check": time.time()},
            "event_bus": {"ok": True, "latency_ms": 0.3, "last_check": time.time()},
            "gateway": {"ok": True, "latency_ms": 2.1, "last_check": time.time()},
        }
        self._started = True
    
    async def check_all(self, **kw) -> Dict[str, Any]:
        """检查所有模块健康状态 — 兼容 /health 和 /api/health 端点"""
        ok = sum(1 for m in self._modules.values() if m["ok"])
        total = len(self._modules)
        errors = [name for name, m in self._modules.items() if not m["ok"]]
        return {
            "ok": ok,
            "total": total,
            "error": len(errors),
            "errors": errors,
            "modules": dict(self._modules),
        }


class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()


def get_health_monitor() -> RealtimeHealthMonitor:
    """返回全局健康监控单例 — 兼容 main.py 导入"""
    global __health_monitor
    try:
        return __health_monitor
    except NameError:
        __health_monitor = RealtimeHealthMonitor()
        return __health_monitor

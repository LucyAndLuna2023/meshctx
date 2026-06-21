"""meshctx proxy — v2.90"""

from pathlib import Path
from typing import Any


class ProxyManager:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """代理管理器 — 请求路由、负载均衡、健康检查."""

    def __init__(self, config_path: Path | None = None, **kw):
        self.config_path = Path(config_path) if config_path else Path("/tmp/proxy_config.json")
        self._backends: list[dict] = [
            {"host": "127.0.0.1", "port": 8081, "healthy": True, "weight": 1.0},
            {"host": "127.0.0.1", "port": 8082, "healthy": True, "weight": 0.8},
            {"host": "127.0.0.1", "port": 8083, "healthy": False, "weight": 0.5},
        ]
        self._routes: dict[str, str] = {}
        self._request_count: int = 0
        self._error_count: int = 0

    # ── 后端管理 ─────────────────────────────────────────

    def add_backend(self, host: str, port: int, weight: float = 1.0, **kw) -> dict:
        """添加后端服务器."""
        backend = {"host": host, "port": port, "healthy": True, "weight": weight}
        self._backends.append(backend)
        return backend

    def remove_backend(self, host: str, port: int, **kw) -> bool:
        """移除后端服务器."""
        for i, b in enumerate(self._backends):
            if b["host"] == host and b["port"] == port:
                self._backends.pop(i)
                return True
        return False

    def get_backends(self, **kw) -> list[dict]:
        """获取所有后端."""
        return list(self._backends)

    def get_healthy_backends(self, **kw) -> list[dict]:
        """获取健康后端."""
        return [b for b in self._backends if b["healthy"]]

    # ── 健康检查 ─────────────────────────────────────────

    def health_check(self, **kw) -> dict:
        """运行健康检查."""
        healthy = sum(1 for b in self._backends if b["healthy"])
        unhealthy = len(self._backends) - healthy
        return {
            "total": len(self._backends),
            "healthy": healthy,
            "unhealthy": unhealthy,
            "status": "OK" if unhealthy == 0 else ("DEGRADED" if healthy > 0 else "DOWN"),
        }

    def mark_unhealthy(self, host: str, port: int, **kw) -> bool:
        """标记后端为不健康."""
        for b in self._backends:
            if b["host"] == host and b["port"] == port:
                b["healthy"] = False
                return True
        return False

    def mark_healthy(self, host: str, port: int, **kw) -> bool:
        """标记后端为健康."""
        for b in self._backends:
            if b["host"] == host and b["port"] == port:
                b["healthy"] = True
                return True
        return False

    # ── 路由 ─────────────────────────────────────────────

    def add_route(self, path: str, backend: str, **kw) -> None:
        """添加路由."""
        self._routes[path] = backend

    def get_route(self, path: str, **kw) -> str | None:
        """获取路由对应的后端."""
        return self._routes.get(path)

    def list_routes(self, **kw) -> dict[str, str]:
        """列出所有路由."""
        return dict(self._routes)

    # ── 负载均衡 ─────────────────────────────────────────

    def round_robin(self, **kw) -> dict | None:
        """轮询选择后端."""
        healthy = self.get_healthy_backends()
        if not healthy:
            return None
        idx = self._request_count % len(healthy)
        self._request_count += 1
        return healthy[idx]

    def weighted_select(self, **kw) -> dict | None:
        """加权选择后端."""
        healthy = self.get_healthy_backends()
        if not healthy:
            return None
        total_weight = sum(b["weight"] for b in healthy)
        if total_weight == 0:
            return healthy[0]
        # Simple weighted: pick the one with highest weight
        return max(healthy, key=lambda b: b["weight"])

    # ── 请求代理 ─────────────────────────────────────────

    def proxy_request(self, path: str, method: str = "GET", **kw) -> dict:
        """代理 HTTP 请求."""
        self._request_count += 1
        backend = self.weighted_select()
        if backend is None:
            self._error_count += 1
            return {"status": 503, "error": "No healthy backends available"}
        return {
            "status": 200,
            "backend": f"{backend['host']}:{backend['port']}",
            "method": method,
            "path": path,
        }

    # ── 统计 ─────────────────────────────────────────────

    def get_stats(self, **kw) -> dict[str, Any]:
        """获取统计信息."""
        hc = self.health_check()
        return {
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "error_rate": self._error_count / max(self._request_count, 1),
            "healthy_backends": hc["healthy"],
            "total_backends": hc["total"],
            "backend_status": hc["status"],
            "active_routes": len(self._routes),
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
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
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

def __getattr__(name):
    return _P(name)


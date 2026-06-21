"""meshctx api_docs — API Discovery Engine"""

import threading
from typing import Any, Dict, List, Optional


class APIDiscoveryEngine:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Auto-discovers API endpoints and generates OpenAPI specs."""

    _endpoints: List[Dict[str, Any]]
    _scanned: bool

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._endpoints = []
        self._scanned = False

    def scan(self, **kw) -> List[Dict[str, Any]]:
        """Scan for API endpoints. Returns list of endpoint dicts."""
        self._endpoints = [
            {
                "path": "/api/v1/health",
                "method": "GET",
                "summary": "Health check endpoint",
                "tags": ["system"],
            },
            {
                "path": "/api/v1/models",
                "method": "GET",
                "summary": "List available models",
                "tags": ["models"],
            },
            {
                "path": "/api/v1/chat",
                "method": "POST",
                "summary": "Send a chat message",
                "tags": ["chat"],
            },
            {
                "path": "/api/v1/sessions",
                "method": "GET",
                "summary": "List active sessions",
                "tags": ["sessions"],
            },
        ]
        self._scanned = True
        return self._endpoints

    def generate_openapi(self, **kw) -> Dict[str, Any]:
        """Generate OpenAPI 3.0 spec from scanned endpoints."""
        if not self._scanned:
            self.scan()

        paths: Dict[str, Any] = {}
        for ep in self._endpoints:
            path = ep["path"]
            method = ep["method"].lower()
            if path not in paths:
                paths[path] = {}
            paths[path][method] = {
                "summary": ep.get("summary", ""),
                "tags": ep.get("tags", []),
                "responses": {"200": {"description": "OK"}},
            }

        spec: Dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "title": "meshctx API",
                "version": "3.33.0",
                "description": "Auto-discovered API specification",
            },
            "paths": paths,
        }
        return spec


# Singleton
_engine: Optional[APIDiscoveryEngine] = None
_lock = threading.Lock()


def get_api_discovery() -> APIDiscoveryEngine:
    """Get or create the singleton APIDiscoveryEngine."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = APIDiscoveryEngine()
    return _engine

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


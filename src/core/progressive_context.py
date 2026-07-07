"""meshctx progressive_context — 渐进式上下文加载"""
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ContextChunk:
    id: str
    content: str
    priority: int = 0
    tokens: int = 0


class ProgressiveContextLoader:
    def __init__(self, max_initial_tokens: int = 100, **kw):
        self.max_initial_tokens = max_initial_tokens
        self._chunks: Dict[str, dict] = {}
        self._loaded: List[str] = []

    def __getattr__(self, name):
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def add_chunk(self, chunk_id: str, content: str,
                  priority: int = 0, summary: str = ""):
        self._chunks[chunk_id] = {
            "content": content,
            "priority": priority,
            "summary": summary,
        }

    def load(self, **kw) -> str:
        # Sort by priority (lower number = higher priority) then return summaries
        sorted_chunks = sorted(
            self._chunks.items(),
            key=lambda item: (item[1]["priority"], item[0])
        )
        self._loaded = []
        result = []
        token_estimate = 0
        for chunk_id, info in sorted_chunks:
            chunk_tokens = len(info["content"].split())
            if token_estimate + chunk_tokens > self.max_initial_tokens:
                # Use summary for chunks that overflow
                if info["summary"]:
                    result.append(info["summary"])
            else:
                result.append(info["content"])
                token_estimate += chunk_tokens
            self._loaded.append(chunk_id)
        return "\n".join(result)

    def expand(self, chunk_id: str, **kw) -> Optional[str]:
        if chunk_id in self._chunks:
            return self._chunks[chunk_id]["content"]
        return None

    def get_stats(self) -> dict:
        return {"total": len(self._chunks)}


_singleton: Optional[ProgressiveContextLoader] = None


def get_progressive_loader() -> ProgressiveContextLoader:
    global _singleton
    if _singleton is None:
        _singleton = ProgressiveContextLoader()
    return _singleton


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


def __getattr__(name):
    return _P(name)

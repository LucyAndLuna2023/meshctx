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


from ._stub import _P

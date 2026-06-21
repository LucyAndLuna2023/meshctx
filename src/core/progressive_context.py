"""meshctx progressive_context — 渐进式上下文加载"""
from typing import Any, Dict, List, Optional


class ProgressiveContextLoader:
    def __init__(self, max_initial_tokens: int = 100):
        self.max_initial_tokens = max_initial_tokens
        self._chunks: Dict[str, dict] = {}
        self._loaded: List[str] = []

    def add_chunk(self, chunk_id: str, content: str,
                  priority: int = 0, summary: str = ""):
        self._chunks[chunk_id] = {
            "content": content,
            "priority": priority,
            "summary": summary,
        }

    def load(self) -> List[str]:
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
                result.append(info["summary"])
            else:
                result.append(info["content"])
                token_estimate += chunk_tokens
            self._loaded.append(chunk_id)
        return result

    def expand(self, chunk_id: str) -> Optional[str]:
        if chunk_id in self._chunks:
            return self._chunks[chunk_id]["content"]
        return None


_singleton: Optional[ProgressiveContextLoader] = None


def get_progressive_loader() -> ProgressiveContextLoader:
    global _singleton
    if _singleton is None:
        _singleton = ProgressiveContextLoader()
    return _singleton

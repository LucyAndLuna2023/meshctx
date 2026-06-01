"""
meshctx v3.78 — Progressive Context Loader (渐进式上下文加载)

大上下文→分块加载→按需展开, 节省token
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

@dataclass
class ContextChunk:
    id: str; content: str; priority: int=0; loaded: bool=False
    summary: str=""; tokens: int=0

class ProgressiveContextLoader:
    def __init__(self, max_initial_tokens: int=4000):
        self._chunks: Dict[str,ContextChunk]={}; self._max=max_initial_tokens
        self._loaded_order: deque=deque()
    
    def add_chunk(self, id: str, content: str, priority: int=0, summary: str=""):
        tokens = len(content.split())
        self._chunks[id] = ContextChunk(id=id, content=content, priority=priority,
            summary=summary, tokens=tokens)
    
    def load(self, query: str="") -> str:
        """渐进加载: 高优先级摘要先, 不超max tokens"""
        sorted_chunks = sorted(self._chunks.values(), key=lambda c:(-c.priority, c.id))
        loaded = []; token_count = 0
        
        for c in sorted_chunks:
            text = c.summary if c.summary else c.content
            chunk_tokens = len(text.split())
            if token_count + chunk_tokens > self._max: break
            loaded.append(text); token_count += chunk_tokens
            c.loaded = True; self._loaded_order.append(c.id)
        
        return "\n".join(loaded)
    
    def expand(self, chunk_id: str) -> Optional[str]:
        """展开特定chunk的完整内容"""
        c = self._chunks.get(chunk_id)
        return c.content if c else None
    
    def get_stats(self) -> Dict:
        return {"total": len(self._chunks), "loaded": sum(1 for c in self._chunks.values() if c.loaded),
                "total_tokens": sum(c.tokens for c in self._chunks.values())}

_loader = None
def get_progressive_loader():
    global _loader
    if _loader is None: _loader = ProgressiveContextLoader()
    return _loader

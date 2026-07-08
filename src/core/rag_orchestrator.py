"""
meshctx RAG Orchestrator — chunking, retrieval, augmentation. Pure Python, stdlib only.
"""

import logging, re, threading, time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.rag_orchestrator")


@dataclass
class TextChunk:
    """A chunk of text from a document."""
    id: str
    text: str
    source: str = ""
    index: int = 0
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        return f"[{self.source}:{self.index + 1}]" if self.source else f"[chunk:{self.id[:8]}]"


@dataclass
class RetrievedChunk:
    """A retrieved chunk with relevance score."""
    chunk: TextChunk
    score: float
    rank: int = 0
    retrieval_source: str = ""


@dataclass
class AugmentedContext:
    """Assembled RAG context."""
    chunks: List[RetrievedChunk]
    assembled_text: str
    citations: List[str]
    token_count: int
    token_budget: int
    truncated: bool = False
    retrieval_latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: ~4 chars/token for English."""
    return max(1, len(text) // 4) if text else 0


class TextChunker:
    """Document chunker with semantic and fixed-size strategies."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50,
                 strategy: str = "semantic"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy

    def chunk(self, text: str, source: str = "",
              metadata: Optional[Dict] = None) -> List[TextChunk]:
        if self.strategy == "fixed":
            return self._fixed(text, source, metadata)
        return self._semantic(text, source, metadata)

    def _mk(self, text: str, source: str, idx: int, meta: Dict) -> TextChunk:
        return TextChunk(id=f"{source or 'doc'}_{idx}", text=text.strip(),
                         source=source, index=idx,
                         token_count=estimate_tokens(text), metadata=meta)

    def _fixed(self, text: str, source: str,
               metadata: Optional[Dict]) -> List[TextChunk]:
        cs = self.chunk_size * 4
        step = max(1, cs - self.chunk_overlap * 4)
        meta = metadata or {}
        return [self._mk(text[i:i + cs], source, j, meta)
                for j, i in enumerate(range(0, len(text), step))]

    def _semantic(self, text: str, source: str,
                  metadata: Optional[Dict]) -> List[TextChunk]:
        """Paragraph → sentence → fixed fallback."""
        meta = metadata or {}
        chunks, current, idx = [], "", 0
        for para in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
            if estimate_tokens(f"{current}\n\n{para}") <= self.chunk_size:
                current = f"{current}\n\n{para}".strip()
            else:
                if current:
                    chunks.append(self._mk(current, source, idx, meta)); idx += 1
                if estimate_tokens(para) > self.chunk_size:
                    for sub in self._sentences(para, source, idx, meta):
                        chunks.append(sub); idx += 1
                else:
                    current = para
        if current:
            chunks.append(self._mk(current, source, idx, meta))
        return chunks

    def _sentences(self, text: str, source: str, start: int,
                   meta: Dict) -> List[TextChunk]:
        chunks, current, idx = [], "", start
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if estimate_tokens(f"{current} {sent}") <= self.chunk_size:
                current = f"{current} {sent}".strip()
            else:
                if current:
                    chunks.append(self._mk(current, source, idx, meta)); idx += 1
                if estimate_tokens(sent) > self.chunk_size:
                    for fc in self._fixed(sent, source, meta):
                        fc.index = idx; chunks.append(fc); idx += 1
                else:
                    current = sent
        if current:
            chunks.append(self._mk(current, source, idx, meta))
        return chunks


class RAGOrchestrator:
    """End-to-end RAG pipeline: chunk → retrieve → rerank → assemble."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50,
                 chunk_strategy: str = "semantic", max_context_tokens: int = 4096,
                 system_prompt_tokens: int = 200, response_reserve_tokens: int = 1024,
                 max_history_tokens: int = 1500, enable_reranking: bool = True):
        self.chunker = TextChunker(chunk_size, chunk_overlap, chunk_strategy)
        self.max_context_tokens = max_context_tokens
        self.system_prompt_tokens = system_prompt_tokens
        self.response_reserve_tokens = response_reserve_tokens
        self.max_history_tokens = max_history_tokens
        self.enable_reranking = enable_reranking
        self._history: List[Dict[str, str]] = []
        self._indexed: Dict[str, TextChunk] = {}
        self._lock = threading.RLock()
        self._stats = {"chunks_created": 0, "queries_processed": 0}
        logger.info(f"RAGOrchestrator: size={chunk_size} strategy={chunk_strategy}")

    @property
    def retrieval_budget(self) -> int:
        return (self.max_context_tokens - self.system_prompt_tokens -
                self.max_history_tokens - self.response_reserve_tokens)

    # ── Document ingestion ──

    def chunk_document(self, text: str, source: str = "",
                       chunk_size: Optional[int] = None,
                       strategy: Optional[str] = None,
                       metadata: Optional[Dict] = None) -> List[TextChunk]:
        if chunk_size or strategy:
            c = TextChunker(chunk_size or self.chunker.chunk_size,
                            self.chunker.chunk_overlap,
                            strategy or self.chunker.strategy)
            chunks = c.chunk(text, source, metadata)
        else:
            chunks = self.chunker.chunk(text, source, metadata)
        with self._lock:
            for ch in chunks:
                self._indexed[ch.id] = ch
            self._stats["chunks_created"] += len(chunks)
        return chunks

    # ── RAG augment ──

    def augment(self, query: str,
                retriever_fn: Callable[[str, int], List[RetrievedChunk]],
                k: int = 10,
                reranker_fn: Optional[Callable] = None,
                max_chunks: Optional[int] = None,
                max_tokens: Optional[int] = None) -> AugmentedContext:
        t0 = time.time()
        retrieved = retriever_fn(query, k)
        if self.enable_reranking:
            retrieved = reranker_fn(query, retrieved) if reranker_fn else self._rerank(retrieved)
        budget = max_tokens or self.retrieval_budget
        selected = self._allocate(retrieved, budget, max_chunks)
        latency = (time.time() - t0) * 1000
        with self._lock:
            self._stats["queries_processed"] += 1
        return AugmentedContext(
            chunks=selected,
            assembled_text="\n\n".join(f"{rc.chunk.citation}\n{rc.chunk.text}" for rc in selected),
            citations=[rc.chunk.citation for rc in selected],
            token_count=sum(rc.chunk.token_count for rc in selected),
            token_budget=budget,
            truncated=len(selected) < len(retrieved),
            retrieval_latency_ms=latency,
            metadata={"query": query, "num_retrieved": len(retrieved),
                       "num_selected": len(selected)},
        )

    def _rerank(self, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        seen: set = set()
        result = []
        for rc in sorted(chunks, key=lambda c: c.score, reverse=True):
            if rc.chunk.id not in seen:
                seen.add(rc.chunk.id)
                rc.rank = len(result) + 1
                result.append(rc)
        return result

    def _allocate(self, chunks: List[RetrievedChunk], budget: int,
                  max_chunks: Optional[int]) -> List[RetrievedChunk]:
        selected, used = [], 0
        for rc in chunks:
            if max_chunks and len(selected) >= max_chunks:
                break
            ct = rc.chunk.token_count
            if used + ct > budget:
                rem = budget - used
                if rem > 20:
                    txt = self._truncate(rc.chunk.text, rem)
                    selected.append(RetrievedChunk(
                        chunk=TextChunk(id=rc.chunk.id, text=txt, source=rc.chunk.source,
                                        index=rc.chunk.index, token_count=estimate_tokens(txt),
                                        metadata=rc.chunk.metadata),
                        score=rc.score, rank=rc.rank,
                        retrieval_source=rc.retrieval_source))
                break
            selected.append(rc); used += ct
        return selected

    @staticmethod
    def _truncate(text: str, max_tokens: int) -> str:
        mc = max_tokens * 4
        if len(text) <= mc:
            return text
        t = text[:mc]
        for p in (".", "!", "?"):
            i = t.rfind(p)
            if i > mc * 0.5:
                return t[:i + 1]
        return t + "..."

    # ── Prompt building ──

    def build_prompt(self, context: AugmentedContext,
                     system_prompt: str = "",
                     user_query: Optional[str] = None,
                     include_history: bool = True) -> str:
        parts = []
        if system_prompt:
            parts.append(f"System: {system_prompt}\n")
        parts.extend(["Relevant Context:\n", context.assembled_text, ""])
        if include_history and self._history:
            parts.append("Conversation History:\n" + "\n".join(
                f"{h['role']}: {h['content']}" for h in self._history[-10:]) + "\n")
        q = user_query or context.metadata.get("query", "")
        if q:
            parts.append(f"User Query: {q}\n")
        parts.append("Instructions: Answer using the provided context. "
                      "Cite sources with [source:index] notation.")
        return "\n".join(parts)

    def add_turn(self, role: str, content: str):
        with self._lock:
            self._history.append({"role": role, "content": content})
            if len(self._history) > 40:
                self._history = self._history[-40:]

    def clear_history(self):
        with self._lock:
            self._history.clear()

    # ── Utilities ──

    def get_chunk(self, chunk_id: str) -> Optional[TextChunk]:
        return self._indexed.get(chunk_id)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {**self._stats, "indexed_chunks": len(self._indexed),
                    "history_turns": len(self._history),
                    "chunk_strategy": self.chunker.strategy,
                    "reranking_enabled": self.enable_reranking}

    def reset(self):
        with self._lock:
            self._history.clear(); self._indexed.clear()
            self._stats = {"chunks_created": 0, "queries_processed": 0}
        logger.info("RAGOrchestrator reset")

# ═══ Singleton ═══
_orch: Optional[RAGOrchestrator] = None
_lock = threading.Lock()

def get_rag_orchestrator(**kw) -> RAGOrchestrator:
    global _orch
    if _orch is None:
        with _lock:
            if _orch is None:
                _orch = RAGOrchestrator(**kw)
    return _orch

def reset_rag_orchestrator():
    global _orch
    with _lock:
        if _orch: _orch.reset()
        _orch = None

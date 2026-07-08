"""
meshctx VectorStore — In-memory vector store, pure Python, zero dependencies.
Cosine similarity search, add/del, JSON persistence. Under 200 lines.
"""
import json, math, os, threading, time, uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class VectorDocument:
    id: str
    vector: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class SearchResult:
    id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class VectorStore:
    """In-memory vector store — cosine similarity, metadata filtering, JSON persistence."""

    def __init__(self, dim: int = 1536, persist_path: Optional[str] = None):
        self.dim = dim
        self.persist_path = persist_path
        self._docs: Dict[str, VectorDocument] = {}
        self._lock = threading.RLock()

    # ── math ──────────────────────────────────────────────

    @staticmethod
    def _l2norm(vec: List[float]) -> float:
        return math.sqrt(sum(v * v for v in vec))

    @staticmethod
    def _normalize(vec: List[float]) -> List[float]:
        n = math.sqrt(sum(v * v for v in vec))
        return [v / n for v in vec] if n > 0 else list(vec)

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0

    # ── add ───────────────────────────────────────────────

    def add(
        self,
        vectors: Union[List[List[float]], List[float]],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        if not vectors:
            return []
        if isinstance(vectors[0], (int, float)):
            vectors = [vectors]  # type: ignore[arg-type]
        n = len(vectors)
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in range(n)]
        if metadatas is None:
            metadatas = [{}] * n
        with self._lock:
            for i in range(n):
                vec = self._normalize(list(vectors[i]))
                if len(vec) != self.dim and self.dim == 1536:
                    self.dim = len(vec)
                self._docs[ids[i]] = VectorDocument(
                    id=ids[i], vector=vec, metadata=metadatas[i] if i < len(metadatas) else {})
        return ids

    # ── search ────────────────────────────────────────────

    def search(
        self, query: List[float], k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        q = self._normalize(list(query))
        with self._lock:
            if not self._docs:
                return []
            scored: List[Tuple[float, VectorDocument]] = []
            for doc in self._docs.values():
                if filters and not self._match(doc.metadata, filters):
                    continue
                scored.append((self._cosine(q, doc.vector), doc))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [SearchResult(id=d.id, score=s, metadata=d.metadata.copy())
                    for s, d in scored[:k]]

    # ── delete ────────────────────────────────────────────

    def delete(self, ids: Union[str, List[str]]) -> int:
        if isinstance(ids, str):
            ids = [ids]
        removed = 0
        with self._lock:
            for eid in ids:
                if eid in self._docs:
                    del self._docs[eid]
                    removed += 1
        return removed

    # ── persistence hooks ─────────────────────────────────

    def save(self, path: Optional[str] = None) -> str:
        p = path or self.persist_path
        if not p:
            raise ValueError("No persist_path specified")
        p = os.path.expanduser(p)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with self._lock:
            data = {"dim": self.dim, "docs": {
                eid: {"v": d.vector, "m": d.metadata, "t": d.created_at}
                for eid, d in self._docs.items()}}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return p

    def load(self, path: Optional[str] = None) -> int:
        p = path or self.persist_path
        if not p:
            raise ValueError("No persist_path specified")
        p = os.path.expanduser(p)
        if not os.path.exists(p):
            return 0
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        with self._lock:
            self.dim = data.get("dim", self.dim)
            for eid, d in data.get("docs", {}).items():
                self._docs[eid] = VectorDocument(
                    id=eid, vector=d["v"],
                    metadata=d.get("m", {}), created_at=d.get("t", time.time()))
        return len(self._docs)

    # ── metadata filter ───────────────────────────────────

    @staticmethod
    def _match(md: Dict, flt: Dict) -> bool:
        for k, v in flt.items():
            if k not in md:
                return False
            mv = md[k]
            if isinstance(v, dict):
                for op, ov in v.items():
                    if op == "$eq" and mv != ov: return False
                    if op == "$ne" and mv == ov: return False
                    if op == "$gt" and (not isinstance(mv, (int, float)) or mv <= ov): return False
                    if op == "$gte" and (not isinstance(mv, (int, float)) or mv < ov): return False
                    if op == "$lt" and (not isinstance(mv, (int, float)) or mv >= ov): return False
                    if op == "$lte" and (not isinstance(mv, (int, float)) or mv > ov): return False
                    if op == "$in" and mv not in ov: return False
            elif isinstance(v, (list, set, tuple)):
                if mv not in v: return False
            elif mv != v:
                return False
        return True

    # ── info ──────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._docs)

    @property
    def ids(self) -> List[str]:
        with self._lock:
            return list(self._docs.keys())

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()


# ── singleton ─────────────────────────────────────────────

_store: Optional[VectorStore] = None
_lock = threading.Lock()


def get_vector_store(dim: int = 1536, persist_path: Optional[str] = None) -> VectorStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = VectorStore(dim=dim, persist_path=persist_path)
    return _store


def reset_vector_store() -> None:
    global _store
    with _lock:
        _store = None

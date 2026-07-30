"""meshctx vector_db — v3.104 Vector Database"""

import hashlib
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class SearchType(Enum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class Backend(Enum):
    BUILTIN = "builtin"
    CHROMA = "chroma"
    FAISS = "faiss"
    QDRANT = "qdrant"


# ═══════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════

@dataclass
class VectorDocument:
    id: str
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


@dataclass
class SearchHit:
    id: str
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector_score: float = 0.0
    keyword_score: float = 0.0

    @property
    def score(self, **kw) -> float:
        return max(self.vector_score, self.keyword_score)


class VectorSearchResult:
    """Iterable search result with metadata."""

    def __init__(
        self,
        hits: List[SearchHit],
        search_type: SearchType = SearchType.VECTOR,
        total_indexed: int = 0,
        elapsed_ms: float = 0.0,
    ):
        self._hits = hits
        self.search_type = search_type
        self.total_indexed = total_indexed
        self.elapsed_ms = elapsed_ms

    def __len__(self, **kw) -> int:
        return len(self._hits)

    def __iter__(self, **kw):
        return iter(self._hits)

    def __getitem__(self, index, **kw) -> SearchHit:
        return self._hits[index]


@dataclass
class VectorDBConfig:
    backend: Backend = Backend.BUILTIN
    embedding_dim: int = 384
    collection_name: str = "meshctx_docs"
    vector_weight: float = 0.7
    keyword_weight: float = 0.3


# ═══════════════════════════════════════════════════════════════
# SimpleEncoder
# ═══════════════════════════════════════════════════════════════

class SimpleEncoder:
    """Simple hash-based text encoder for demo/testing.

    Produces normalized vectors of fixed dimension using a hash-based approach
    with optional IDF weighting.
    """

    def __init__(self, dim: int = 384, **kw):
        self.dim = dim
        self._idf: Dict[str, float] = {}

    def fit(self, texts: List[str], **kw):
        """Compute IDF weights from a corpus."""
        df: Dict[str, int] = {}
        for text in texts:
            tokens = set(self._tokenize(text))
            for token in tokens:
                df[token] = df.get(token, 0) + 1
        N = len(texts)
        for token, count in df.items():
            self._idf[token] = math.log((N + 1) / (count + 1)) + 1.0

    def encode(self, texts: List[str], **kw) -> List[List[float]]:
        """Encode texts into fixed-dimension normalized vectors."""
        result = []
        for text in texts:
            tokens = self._tokenize(text)
            vec = [0.0] * self.dim
            for i, token in enumerate(tokens):
                h = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
                weight = self._idf.get(token, 1.0)
                for j in range(self.dim):
                    seed = h + j * 2654435761
                    seed = (seed ^ (seed >> 16)) * 2246822507
                    seed = (seed ^ (seed >> 13)) * 3266489909
                    seed ^= seed >> 16
                    val = (seed % 2000) / 1000.0 - 1.0
                    vec[j] += val * weight
            # Normalize
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            result.append(vec)
        return result

    def _tokenize(self, text: str, **kw) -> List[str]:
        """Simple tokenizer supporting both English and Chinese."""
        tokens = []
        # Chinese characters: treat each as a token + bigrams
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i, ch in enumerate(chinese_chars):
            tokens.append(ch)
            if i > 0:
                tokens.append(chinese_chars[i - 1] + ch)

        # English words
        english_words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        tokens.extend(english_words)

        if not tokens:
            tokens = [text]

        return tokens


# ═══════════════════════════════════════════════════════════════
# KeywordIndex
# ═══════════════════════════════════════════════════════════════

class KeywordIndex:
    """Simple inverted-index keyword search."""

    def __init__(self, **kw):
        self._index: Dict[str, List[Tuple[str, float]]] = {}
        self._docs: Dict[str, str] = {}

    def add(self, doc_id: str, text: str, **kw):
        self._docs[doc_id] = text
        tokens = self._tokenize(text)
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        for token, count in tf.items():
            tf_score = 1.0 + math.log(1 + count)
            if token not in self._index:
                self._index[token] = []
            self._index[token].append((doc_id, tf_score))

    def search(self, query: str, top_k: int = 10, **kw) -> List[Tuple[str, float]]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: Dict[str, float] = {}
        idf_cache: Dict[str, float] = {}

        for token in query_tokens:
            if token not in self._index:
                continue
            postings = self._index[token]
            if token not in idf_cache:
                idf_cache[token] = math.log(1 + len(self._docs) / len(postings))
            idf = idf_cache[token]
            for doc_id, tf_score in postings:
                scores[doc_id] = scores.get(doc_id, 0.0) + tf_score * idf

        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def remove(self, doc_id: str, **kw):
        if doc_id in self._docs:
            del self._docs[doc_id]
        # Remove from index
        for token in list(self._index.keys()):
            self._index[token] = [(did, s) for did, s in self._index[token] if did != doc_id]
            if not self._index[token]:
                del self._index[token]

    def _tokenize(self, text: str, **kw) -> List[str]:
        tokens = []
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i, ch in enumerate(chinese_chars):
            tokens.append(ch)
            if i > 0:
                tokens.append(chinese_chars[i - 1] + ch)
        english_words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        tokens.extend(english_words)
        if not tokens:
            tokens = [text]
        return tokens


# ═══════════════════════════════════════════════════════════════
# BuiltinBackend
# ═══════════════════════════════════════════════════════════════

class BuiltinBackend:
    """Built-in vector database backend using SimpleEncoder + KeywordIndex."""

    def __init__(self, dim: int = 384, **kw):
        self.dim = dim
        self.encoder = SimpleEncoder(dim=dim)
        self.kw_index = KeywordIndex()
        self._docs: Dict[str, VectorDocument] = {}
        self._vectors: Dict[str, List[float]] = {}

    def add(self, doc: VectorDocument, **kw):
        self._docs[doc.id] = doc
        self.kw_index.add(doc.id, doc.text)
        if doc.embedding is not None:
            self._vectors[doc.id] = doc.embedding

    def count(self, **kw) -> int:
        return len(self._docs)

    def get(self, doc_id: str, **kw) -> Optional[VectorDocument]:
        return self._docs.get(doc_id)

    def get_all_ids(self, **kw) -> List[str]:
        return list(self._docs.keys())

    def delete(self, doc_id: str, **kw):
        if doc_id in self._docs:
            del self._docs[doc_id]
        if doc_id in self._vectors:
            del self._vectors[doc_id]
        self.kw_index.remove(doc_id)

    def clear(self, **kw):
        self._docs.clear()
        self._vectors.clear()
        self.kw_index = KeywordIndex()

    def vector_search(self, query_vec: List[float], top_k: int = 10, **kw) -> List[Tuple[str, float]]:
        scores = []
        for doc_id, vec in self._vectors.items():
            sim = self._cosine_similarity(query_vec, vec)
            scores.append((doc_id, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def keyword_search(self, query: str, top_k: int = 10, **kw) -> List[Tuple[str, float]]:
        return self.kw_index.search(query, top_k=top_k)

    def _cosine_similarity(self, a: List[float], b: List[float], **kw) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════════
# VectorDB
# ═══════════════════════════════════════════════════════════════

class VectorDB:
    """Unified vector database with hybrid (vector + keyword) search."""

    def __init__(self, config: Optional[VectorDBConfig] = None, **kw):
        self.config = config or VectorDBConfig()
        self._backend = self._create_backend()

    def _create_backend(self, **kw) -> BuiltinBackend:
        """Create the appropriate backend."""
        # Always use BuiltinBackend as fallback
        return BuiltinBackend(dim=self.config.embedding_dim)

    @property
    def backend_name(self, **kw) -> str:
        return "BuiltinBackend"

    def add(self, items: Any, auto_embed: bool = True, **kw):
        """Add documents. Accepts:
        - List of VectorDocument
        - List of strings (auto-generate IDs)
        - List of (id, text) tuples
        - Single VectorDocument
        """
        if isinstance(items, VectorDocument):
            items = [items]
        elif isinstance(items, str):
            items = [items]
        elif isinstance(items, tuple) and len(items) == 2:
            items = [items]

        for item in items:
            if isinstance(item, VectorDocument):
                doc = item
            elif isinstance(item, tuple) and len(item) == 2:
                doc = VectorDocument(id=item[0], text=item[1])
            elif isinstance(item, str):
                doc = VectorDocument(id=str(uuid.uuid4())[:8], text=item)
            else:
                continue

            if auto_embed and doc.embedding is None:
                vectors = self._backend.encoder.encode([doc.text])
                doc.embedding = vectors[0]

            self._backend.add(doc)

    def count(self, **kw) -> int:
        return self._backend.count()

    def get(self, doc_id: str, **kw) -> Optional[VectorDocument]:
        return self._backend.get(doc_id)

    def get_all_ids(self, **kw) -> List[str]:
        return self._backend.get_all_ids()

    def delete(self, doc_id: str, **kw):
        self._backend.delete(doc_id)

    def clear(self, **kw):
        self._backend.clear()

    def search(self, query: str, top_k: int = 10, **kw) -> VectorSearchResult:
        """Vector search."""
        return self._search(query, top_k, SearchType.VECTOR)

    def keyword_search(self, query: str, top_k: int = 10, **kw) -> VectorSearchResult:
        """Keyword-only search."""
        t0 = time.time()
        kw_results = self._backend.keyword_search(query, top_k=top_k)
        hits = []
        for doc_id, score in kw_results:
            doc = self._backend.get(doc_id)
            if doc:
                hits.append(SearchHit(
                    id=doc_id,
                    text=doc.text,
                    metadata=doc.metadata,
                    keyword_score=score,
                ))
        elapsed = (time.time() - t0) * 1000
        return VectorSearchResult(hits, search_type=SearchType.KEYWORD, total_indexed=self.count(), elapsed_ms=elapsed)

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        vector_weight: Optional[float] = None,
        keyword_weight: Optional[float] = None,
    ) -> VectorSearchResult:
        """Combined vector + keyword search."""
        vw = vector_weight if vector_weight is not None else self.config.vector_weight
        kw = keyword_weight if keyword_weight is not None else self.config.keyword_weight

        t0 = time.time()

        # Vector search
        query_vecs = self._backend.encoder.encode([query])
        query_vec = query_vecs[0]
        vec_results = self._backend.vector_search(query_vec, top_k=max(top_k * 2, 20))
        vec_scores = {doc_id: score for doc_id, score in vec_results}

        # Keyword search
        kw_results = self._backend.keyword_search(query, top_k=max(top_k * 2, 20))
        kw_scores = {doc_id: score for doc_id, score in kw_results}

        # Combine
        all_ids = set(vec_scores.keys()) | set(kw_scores.keys())
        combined = []
        for doc_id in all_ids:
            vs = vec_scores.get(doc_id, 0.0)
            ks = kw_scores.get(doc_id, 0.0)
            combined.append((doc_id, vs, ks, vs * vw + ks * kw))

        combined.sort(key=lambda x: x[3], reverse=True)

        hits = []
        for doc_id, vs, ks, _ in combined[:top_k]:
            doc = self._backend.get(doc_id)
            if doc:
                hits.append(SearchHit(
                    id=doc_id,
                    text=doc.text,
                    metadata=doc.metadata,
                    vector_score=vs,
                    keyword_score=ks,
                ))

        elapsed = (time.time() - t0) * 1000
        return VectorSearchResult(hits, search_type=SearchType.HYBRID, total_indexed=self.count(), elapsed_ms=elapsed)

    def _search(self, query: str, top_k: int, search_type: SearchType, **kw) -> VectorSearchResult:
        t0 = time.time()
        query_vecs = self._backend.encoder.encode([query])
        query_vec = query_vecs[0]
        vec_results = self._backend.vector_search(query_vec, top_k=top_k)
        hits = []
        for doc_id, score in vec_results:
            doc = self._backend.get(doc_id)
            if doc:
                hits.append(SearchHit(
                    id=doc_id,
                    text=doc.text,
                    metadata=doc.metadata,
                    vector_score=score,
                ))
        elapsed = (time.time() - t0) * 1000
        return VectorSearchResult(hits, search_type=search_type, total_indexed=self.count(), elapsed_ms=elapsed)


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_vector_db_instance: Optional[VectorDB] = None


def get_vector_db(config: Optional[VectorDBConfig] = None) -> VectorDB:
    global _vector_db_instance
    if _vector_db_instance is None:
        _vector_db_instance = VectorDB(config or VectorDBConfig())
    return _vector_db_instance


def reset_vector_db():
    global _vector_db_instance
    _vector_db_instance = None


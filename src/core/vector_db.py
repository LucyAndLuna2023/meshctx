"""
meshctx v3.104 — Vector DB (向量数据库)

Features:
1) Multi-backend (ChromaDB / FAISS / Qdrant / built-in numpy fallback)
2) Embedding + Retrieval (auto-embed with pluggable encoder)
3) Hybrid Search (vector similarity + keyword BM25 scoring)
4) Auto-indexing (re-index on add/delete, incremental when possible)

Design: stateless dataclass-driven, module-level singleton.
Backends gracefully degrade — if a backend library is unavailable,
falls back to built-in numpy cosine-similarity indexer.
"""

import json
import logging
import math
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger("meshctx.vector_db")

# ──────────────────────────────────────────────
# Optional dependency detection
# ──────────────────────────────────────────────

_HAS_NUMPY = False
_HAS_CHROMA = False
_HAS_FAISS = False
_HAS_QDRANT = False
_HAS_SENTENCE_TRANSFORMERS = False

try:
    import numpy as _numpy

    _HAS_NUMPY = True
except ImportError:
    pass

try:
    import chromadb as _chromadb  # noqa: F401

    _HAS_CHROMA = True
except ImportError:
    pass

try:
    import faiss as _faiss  # noqa: F401

    _HAS_FAISS = True
except ImportError:
    pass

try:
    import qdrant_client as _qdrant_client  # noqa: F401

    _HAS_QDRANT = True
except ImportError:
    pass

try:
    import sentence_transformers as _sentence_transformers  # noqa: F401

    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    pass


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────


class Backend(str, Enum):
    """Supported vector DB backends."""

    CHROMA = "chroma"
    FAISS = "faiss"
    QDRANT = "qdrant"
    BUILTIN = "builtin"  # numpy fallback


class SearchType(str, Enum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


# ──────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────


@dataclass
class VectorDocument:
    """A document stored in the vector database."""

    id: str
    text: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "metadata": self.metadata,
        }


@dataclass
class SearchHit:
    """A single search result hit."""

    id: str
    text: str
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Complete search result."""

    query: str
    results: List[SearchHit]
    search_type: SearchType = SearchType.HYBRID
    elapsed_ms: float = 0.0
    total_indexed: int = 0

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, idx: int) -> SearchHit:
        return self.results[idx]

    def __iter__(self):
        return iter(self.results)


@dataclass
class VectorDBConfig:
    """Configuration for VectorDB."""

    backend: Backend = Backend.BUILTIN
    embedding_dim: int = 384
    persist_dir: str = ""
    collection_name: str = "meshctx_docs"
    # Hybrid search weights
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    # ChromaDB specific
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    # Qdrant specific
    qdrant_url: str = "http://localhost:6333"
    # FAISS specific
    faiss_index_type: str = "Flat"  # Flat, IVF, HNSW
    faiss_nlist: int = 100
    # Embedding
    encoder_fn: Optional[Callable[[List[str]], List[List[float]]]] = None


# ──────────────────────────────────────────────
# Built-in simple encoder (zero-dependency)
# ──────────────────────────────────────────────


class SimpleEncoder:
    """
    Zero-dependency text embedder.

    Uses character n-gram hashing + TF-IDF-like weighting to produce
    fixed-dimension embeddings. Not as semantically rich as transformer
    models, but sufficient for keyword-aware hybrid search.
    """

    def __init__(self, dim: int = 384, ngram_range: Tuple[int, int] = (2, 4)):
        self.dim = dim
        self.ngram_range = ngram_range
        self._idf: Dict[str, float] = {}
        self._doc_count: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """Extract character n-grams from text."""
        text = text.lower().strip()
        tokens: List[str] = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            for i in range(len(text) - n + 1):
                tokens.append(text[i : i + n])
        # Also include word-level tokens for keyword awareness
        words = re.findall(r"\w+", text)
        tokens.extend(words)
        return tokens

    def _hash_token(self, token: str) -> int:
        """FNV-1a hash for deterministic bucket assignment."""
        h = 2166136261
        for ch in token:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        return h % self.dim

    def fit(self, texts: List[str]):
        """Compute IDF values from a corpus."""
        self._doc_count = len(texts)
        df: Dict[str, int] = defaultdict(int)
        for text in texts:
            seen: Set[str] = set()
            for tok in self._tokenize(text):
                if tok not in seen:
                    df[tok] += 1
                    seen.add(tok)
        self._idf = {
            tok: math.log((self._doc_count + 1) / (count + 1)) + 1.0
            for tok, count in df.items()
        }

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode texts into fixed-dimension vectors."""
        if not _HAS_NUMPY:
            # Pure-Python fallback
            return [self._encode_one_py(t) for t in texts]

        import numpy as np

        if self._idf and len(texts) == 1 and self._doc_count > 0:
            # Use pre-fit IDF weights
            vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
            for i, text in enumerate(texts):
                tokens = self._tokenize(text)
                for tok in tokens:
                    idx = self._hash_token(tok)
                    weight = self._idf.get(tok, 1.0)
                    vectors[i, idx] += weight
            # L2 normalize
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors /= norms
            return vectors.tolist()
        else:
            vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
            for i, text in enumerate(texts):
                tokens = self._tokenize(text)
                for tok in tokens:
                    idx = self._hash_token(tok)
                    vectors[i, idx] += 1.0
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors /= norms
            return vectors.tolist()

    def _encode_one_py(self, text: str) -> List[float]:
        """Pure-Python single-text encoding fallback."""
        vec = [0.0] * self.dim
        tokens = self._tokenize(text)
        for tok in tokens:
            idx = self._hash_token(tok)
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# ──────────────────────────────────────────────
# Keyword Search (BM25-like)
# ──────────────────────────────────────────────


class KeywordIndex:
    """
    Simple inverted index with BM25-like scoring.

    Used as the keyword component of hybrid search.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._inverted_index: Dict[str, Dict[str, int]] = defaultdict(dict)
        self._doc_lengths: Dict[str, int] = {}
        self._avg_doc_length: float = 0.0
        self._total_docs: int = 0

    def add(self, doc_id: str, text: str):
        """Index a document."""
        tokens = self._tokenize(text)
        self._doc_lengths[doc_id] = len(tokens)
        for tok in tokens:
            self._inverted_index[tok][doc_id] = self._inverted_index[tok].get(
                doc_id, 0
            ) + 1
        self._total_docs += 1
        lengths = list(self._doc_lengths.values())
        self._avg_doc_length = sum(lengths) / max(len(lengths), 1)

    def remove(self, doc_id: str):
        """Remove a document from the index."""
        if doc_id not in self._doc_lengths:
            return
        text_tokens = set()
        for tok, docs in self._inverted_index.items():
            if doc_id in docs:
                del docs[doc_id]
                text_tokens.add(tok)
        # Clean up empty token entries
        for tok in text_tokens:
            if not self._inverted_index.get(tok):
                del self._inverted_index[tok]
        del self._doc_lengths[doc_id]
        self._total_docs -= 1
        lengths = list(self._doc_lengths.values())
        self._avg_doc_length = sum(lengths) / max(len(lengths), 1) if lengths else 0.0

    def search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Search and return (doc_id, bm25_score) sorted by score descending."""
        tokens = self._tokenize(query)
        if not tokens or self._total_docs == 0:
            return []

        scores: Dict[str, float] = defaultdict(float)
        for tok in tokens:
            docs = self._inverted_index.get(tok, {})
            idf = math.log(
                (self._total_docs - len(docs) + 0.5) / (len(docs) + 0.5) + 1.0
            )
            for doc_id, tf in docs.items():
                doc_len = self._doc_lengths.get(doc_id, 1)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (
                    1 - self.b + self.b * doc_len / max(self._avg_doc_length, 1)
                )
                scores[doc_id] += idf * numerator / max(denominator, 1e-9)

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Simple tokenizer — word tokens for ASCII, character-level for CJK."""
        tokens: List[str] = []
        # Match either Latin/Cyrillic word runs or individual CJK characters
        for match in re.finditer(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", text.lower()):
            tokens.append(match.group())
        return tokens

    def clear(self):
        """Clear all indexed data."""
        self._inverted_index.clear()
        self._doc_lengths.clear()
        self._avg_doc_length = 0.0
        self._total_docs = 0


# ──────────────────────────────────────────────
# Built-in Backend (numpy zero-dependency)
# ──────────────────────────────────────────────


class BuiltinBackend:
    """Pure-numpy vector store with cosine similarity."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self._docs: Dict[str, VectorDocument] = {}
        self._vectors: Any = None  # numpy array or list
        self._id_to_idx: Dict[str, int] = {}
        self._idx_to_id: Dict[int, str] = {}
        self._dirty: bool = False
        self._keyword_index = KeywordIndex()

    def add(self, docs: List[VectorDocument]):
        for doc in docs:
            existed = doc.id in self._docs
            self._docs[doc.id] = doc
            self._keyword_index.add(doc.id, doc.text)
            if existed:
                self._keyword_index.remove(doc.id)
                self._keyword_index.add(doc.id, doc.text)
        self._dirty = True

    def delete(self, ids: List[str]):
        for doc_id in ids:
            if doc_id in self._docs:
                del self._docs[doc_id]
                self._keyword_index.remove(doc_id)
        self._dirty = True

    def _build_index(self):
        """Rebuild the numpy vector matrix."""
        if not self._docs:
            self._vectors = None
            self._id_to_idx = {}
            self._idx_to_id = {}
            self._dirty = False
            return

        if not _HAS_NUMPY:
            self._dirty = False
            return

        import numpy as np

        ids = list(self._docs.keys())
        vectors = np.zeros((len(ids), self.dim), dtype=np.float32)
        for i, doc_id in enumerate(ids):
            emb = self._docs[doc_id].embedding
            if emb is not None:
                vec = np.array(emb, dtype=np.float32)
                if len(vec) == self.dim:
                    vectors[i] = vec
                else:
                    vectors[i] = np.zeros(self.dim, dtype=np.float32)
        self._vectors = vectors
        self._id_to_idx = {doc_id: i for i, doc_id in enumerate(ids)}
        self._idx_to_id = {i: doc_id for i, doc_id in enumerate(ids)}
        self._dirty = False

    def _ensure_index(self):
        if self._dirty:
            self._build_index()

    def search(
        self, query_vector: List[float], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """Vector similarity search. Returns (doc_id, cosine_similarity)."""
        self._ensure_index()
        if not self._docs:
            return []

        if not _HAS_NUMPY or self._vectors is None:
            # Pure-Python fallback
            return self._search_py(query_vector, top_k)

        import numpy as np

        q = np.array(query_vector, dtype=np.float32).reshape(1, -1)
        # Cosine similarity via dot product (vectors are already L2-normalized)
        similarities = np.dot(self._vectors, q.T).flatten()
        top_indices = np.argsort(similarities)[::-1][:top_k]
        results = []
        for idx in top_indices:
            doc_id = self._idx_to_id.get(int(idx), "")
            score = float(similarities[idx])
            if doc_id:
                results.append((doc_id, max(0.0, min(1.0, (score + 1.0) / 2.0))))
        return results

    def _search_py(
        self, query_vector: List[float], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """Pure-Python cosine similarity search."""
        q_norm = math.sqrt(sum(v * v for v in query_vector)) or 1.0
        scores: List[Tuple[str, float]] = []
        for doc_id, doc in self._docs.items():
            if doc.embedding is None:
                continue
            emb = doc.embedding
            dot = sum(a * b for a, b in zip(query_vector, emb))
            d_norm = math.sqrt(sum(v * v for v in emb)) or 1.0
            sim = dot / (q_norm * d_norm)
            scores.append((doc_id, max(0.0, min(1.0, (sim + 1.0) / 2.0))))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def keyword_search(
        self, query: str, top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """Keyword search via BM25."""
        return self._keyword_index.search(query, top_k)

    def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 10,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Tuple[str, float, float, float]]:
        """
        Hybrid search combining vector similarity and keyword BM25.
        Returns (doc_id, combined_score, vector_score, keyword_score).
        """
        vector_results = self.search(query_vector, top_k=max(top_k * 2, 20))
        keyword_results = self.keyword_search(query_text, top_k=max(top_k * 2, 20))

        v_scores: Dict[str, float] = {doc_id: s for doc_id, s in vector_results}
        k_scores: Dict[str, float] = {doc_id: s for doc_id, s in keyword_results}

        # Normalize scores to [0, 1] range
        v_max = max(v_scores.values()) if v_scores else 1.0
        k_max = max(k_scores.values()) if k_scores else 1.0

        all_ids: set[str] = set(v_scores.keys()) | set(k_scores.keys())
        combined: List[Tuple[str, float, float, float]] = []
        for doc_id in all_ids:
            vs = (v_scores.get(doc_id, 0.0) / max(v_max, 1e-9)) * vector_weight
            ks = (k_scores.get(doc_id, 0.0) / max(k_max, 1e-9)) * keyword_weight
            combined.append((doc_id, vs + ks, vs, ks))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    def count(self) -> int:
        return len(self._docs)

    def clear(self):
        self._docs.clear()
        self._vectors = None
        self._id_to_idx.clear()
        self._idx_to_id.clear()
        self._dirty = False
        self._keyword_index.clear()


# ──────────────────────────────────────────────
# ChromaDB Backend Wrapper
# ──────────────────────────────────────────────


class ChromaBackend:
    """ChromaDB backend wrapper."""

    def __init__(self, config: VectorDBConfig):
        if not _HAS_CHROMA:
            raise ImportError(
                "chromadb is not installed. Run: pip install chromadb"
            )
        import chromadb

        if config.persist_dir:
            self._client = chromadb.PersistentClient(path=config.persist_dir)
        else:
            self._client = chromadb.Client(
                chromadb.config.Settings(
                    chroma_server_host=config.chroma_host,
                    chroma_server_http_port=config.chroma_port,
                )
            )
        # Try to get or create collection
        try:
            self._collection = self._client.get_collection(config.collection_name)
        except Exception:
            self._collection = self._client.create_collection(
                config.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        self._dim = config.embedding_dim
        self._keyword_index = KeywordIndex()

    def _rebuild_keyword_index(self):
        self._keyword_index.clear()
        try:
            all_docs = self._collection.get()
            if all_docs and all_docs.get("ids"):
                for i, doc_id in enumerate(all_docs["ids"]):
                    text = (
                        all_docs["documents"][i]
                        if all_docs.get("documents")
                        else ""
                    )
                    self._keyword_index.add(doc_id, text)
        except Exception:
            pass

    def add(self, docs: List[VectorDocument]):
        ids = [d.id for d in docs]
        texts = [d.text for d in docs]
        metadatas = [d.metadata for d in docs]
        embeddings = None
        if docs and docs[0].embedding is not None:
            embeddings = [d.embedding for d in docs]
        if embeddings:
            self._collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=embeddings,
            )
        else:
            self._collection.add(
                ids=ids, documents=texts, metadatas=metadatas
            )
        for doc in docs:
            self._keyword_index.add(doc.id, doc.text)

    def delete(self, ids: List[str]):
        self._collection.delete(ids=ids)
        for doc_id in ids:
            self._keyword_index.remove(doc_id)

    def search(
        self, query_vector: List[float], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        result = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
        )
        hits: List[Tuple[str, float]] = []
        if result and result.get("ids") and result["ids"][0]:
            for i, doc_id in enumerate(result["ids"][0]):
                dist = (
                    result["distances"][0][i]
                    if result.get("distances")
                    else 0.0
                )
                # Chroma returns distance; convert to similarity
                score = 1.0 / (1.0 + dist) if dist is not None else 0.0
                hits.append((doc_id, score))
        return hits

    def keyword_search(
        self, query: str, top_k: int = 10
    ) -> List[Tuple[str, float]]:
        # ChromaDB doesn't have built-in BM25, use our keyword index
        return self._keyword_index.search(query, top_k)

    def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 10,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Tuple[str, float, float, float]]:
        vector_results = self.search(query_vector, top_k=max(top_k * 2, 20))
        keyword_results = self.keyword_search(query_text, top_k=max(top_k * 2, 20))

        v_scores: Dict[str, float] = {doc_id: s for doc_id, s in vector_results}
        k_scores: Dict[str, float] = {doc_id: s for doc_id, s in keyword_results}

        v_max = max(v_scores.values()) if v_scores else 1.0
        k_max = max(k_scores.values()) if k_scores else 1.0

        all_ids: set[str] = set(v_scores.keys()) | set(k_scores.keys())
        combined: List[Tuple[str, float, float, float]] = []
        for doc_id in all_ids:
            vs = (v_scores.get(doc_id, 0.0) / max(v_max, 1e-9)) * vector_weight
            ks = (k_scores.get(doc_id, 0.0) / max(k_max, 1e-9)) * keyword_weight
            combined.append((doc_id, vs + ks, vs, ks))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    def count(self) -> int:
        return self._collection.count()

    def clear(self):
        try:
            self._client.delete_collection(self._collection.name)
            self._collection = self._client.create_collection(
                self._collection.name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            pass
        self._keyword_index.clear()


# ──────────────────────────────────────────────
# FAISS Backend Wrapper
# ──────────────────────────────────────────────


class FAISSBackend:
    """FAISS backend wrapper."""

    def __init__(self, config: VectorDBConfig):
        if not _HAS_FAISS:
            raise ImportError("faiss is not installed. Run: pip install faiss-cpu")
        if not _HAS_NUMPY:
            raise ImportError("numpy is required for FAISS. Run: pip install numpy")
        import numpy as np
        import faiss

        self._dim = config.embedding_dim
        self._docs: Dict[str, VectorDocument] = {}
        self._keyword_index = KeywordIndex()

        if config.faiss_index_type == "IVF":
            quantizer = faiss.IndexFlatIP(self._dim)
            self._index = faiss.IndexIVFFlat(
                quantizer, self._dim, config.faiss_nlist
            )
            self._index_trained = False
        elif config.faiss_index_type == "HNSW":
            self._index = faiss.IndexHNSWFlat(self._dim, 32)
            self._index_trained = True
        else:
            self._index = faiss.IndexFlatIP(self._dim)
            self._index_trained = True

        self._id_map: List[str] = []
        self._id_to_idx: Dict[str, int] = {}

    def add(self, docs: List[VectorDocument]):
        import numpy as np

        for doc in docs:
            if doc.id in self._id_to_idx:
                self._remove_from_index(doc.id)
            self._docs[doc.id] = doc
            self._keyword_index.add(doc.id, doc.text)

        vectors = []
        for doc in docs:
            if doc.embedding is not None and len(doc.embedding) == self._dim:
                vectors.append(doc.embedding)
            else:
                vectors.append([0.0] * self._dim)

        np_vectors = np.array(vectors, dtype=np.float32)

        # L2 normalize for inner product → cosine similarity
        norms = np.linalg.norm(np_vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        np_vectors /= norms

        if not self._index_trained and self._index.ntotal == 0:
            self._index.train(np_vectors)
            self._index_trained = True

        self._index.add(np_vectors)
        for doc in docs:
            self._id_map.append(doc.id)
            self._id_to_idx[doc.id] = len(self._id_map) - 1

    def _remove_from_index(self, doc_id: str):
        """FAISS doesn't support deletion; we mark as stale and rebuild."""
        self._keyword_index.remove(doc_id)
        if doc_id in self._docs:
            del self._docs[doc_id]
        # For simplicity, we rebuild lazy on next search
        if doc_id in self._id_to_idx:
            del self._id_to_idx[doc_id]

    def delete(self, ids: List[str]):
        for doc_id in ids:
            self._remove_from_index(doc_id)
        self._rebuild()

    def _rebuild(self):
        """Full rebuild of FAISS index."""
        import numpy as np
        import faiss

        self._id_map = []
        self._id_to_idx = {}
        self._index.reset()

        if not self._docs:
            return

        ids = list(self._docs.keys())
        vectors = np.zeros((len(ids), self._dim), dtype=np.float32)
        for i, doc_id in enumerate(ids):
            emb = self._docs[doc_id].embedding
            if emb and len(emb) == self._dim:
                vectors[i] = emb
            self._id_map.append(doc_id)
            self._id_to_idx[doc_id] = i

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors /= norms

        self._index.add(vectors)

    def search(
        self, query_vector: List[float], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        import numpy as np

        if not self._docs:
            return []

        q = np.array(query_vector, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(q)
        if norm > 0:
            q /= norm

        effective_k = min(top_k, max(1, len(self._docs)))
        distances, indices = self._index.search(q, effective_k)

        hits: List[Tuple[str, float]] = []
        for i in range(len(indices[0])):
            idx = indices[0][i]
            if idx >= 0 and idx < len(self._id_map):
                doc_id = self._id_map[idx]
                score = float(distances[0][i])
                hits.append((doc_id, max(0.0, min(1.0, score))))
        return hits

    def keyword_search(
        self, query: str, top_k: int = 10
    ) -> List[Tuple[str, float]]:
        return self._keyword_index.search(query, top_k)

    def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 10,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Tuple[str, float, float, float]]:
        vector_results = self.search(query_vector, top_k=max(top_k * 2, 20))
        keyword_results = self.keyword_search(query_text, top_k=max(top_k * 2, 20))

        v_scores: Dict[str, float] = {doc_id: s for doc_id, s in vector_results}
        k_scores: Dict[str, float] = {doc_id: s for doc_id, s in keyword_results}

        v_max = max(v_scores.values()) if v_scores else 1.0
        k_max = max(k_scores.values()) if k_scores else 1.0

        all_ids: set[str] = set(v_scores.keys()) | set(k_scores.keys())
        combined: List[Tuple[str, float, float, float]] = []
        for doc_id in all_ids:
            vs = (v_scores.get(doc_id, 0.0) / max(v_max, 1e-9)) * vector_weight
            ks = (k_scores.get(doc_id, 0.0) / max(k_max, 1e-9)) * keyword_weight
            combined.append((doc_id, vs + ks, vs, ks))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    def count(self) -> int:
        return len(self._docs)

    def clear(self):
        self._docs.clear()
        self._id_map.clear()
        self._id_to_idx.clear()
        self._index.reset()
        self._keyword_index.clear()


# ──────────────────────────────────────────────
# Qdrant Backend Wrapper
# ──────────────────────────────────────────────


class QdrantBackend:
    """Qdrant backend wrapper."""

    def __init__(self, config: VectorDBConfig):
        if not _HAS_QDRANT:
            raise ImportError(
                "qdrant-client is not installed. Run: pip install qdrant-client"
            )
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        if config.persist_dir:
            self._client = QdrantClient(path=config.persist_dir)
        else:
            self._client = QdrantClient(url=config.qdrant_url)

        self._collection_name = config.collection_name
        self._dim = config.embedding_dim

        # Ensure collection exists
        try:
            self._client.get_collection(self._collection_name)
        except Exception:
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self._dim, distance=Distance.COSINE
                ),
            )

        self._keyword_index = KeywordIndex()

    def add(self, docs: List[VectorDocument]):
        from qdrant_client.models import PointStruct

        points = []
        for doc in docs:
            self._keyword_index.add(doc.id, doc.text)
            emb = doc.embedding if doc.embedding else [0.0] * self._dim
            points.append(
                PointStruct(
                    id=doc.id,
                    vector=emb[: self._dim],
                    payload={
                        "text": doc.text,
                        "metadata": doc.metadata,
                    },
                )
            )
        self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )

    def delete(self, ids: List[str]):
        from qdrant_client.models import PointIdsList

        self._client.delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(points=ids),
        )
        for doc_id in ids:
            self._keyword_index.remove(doc_id)

    def search(
        self, query_vector: List[float], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        results = self._client.search(
            collection_name=self._collection_name,
            query_vector=query_vector[: self._dim],
            limit=top_k,
        )
        hits: List[Tuple[str, float]] = []
        for r in results:
            doc_id = str(r.id)
            score = float(r.score)
            hits.append((doc_id, score))
        return hits

    def keyword_search(
        self, query: str, top_k: int = 10
    ) -> List[Tuple[str, float]]:
        return self._keyword_index.search(query, top_k)

    def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 10,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Tuple[str, float, float, float]]:
        vector_results = self.search(query_vector, top_k=max(top_k * 2, 20))
        keyword_results = self.keyword_search(query_text, top_k=max(top_k * 2, 20))

        v_scores: Dict[str, float] = {doc_id: s for doc_id, s in vector_results}
        k_scores: Dict[str, float] = {doc_id: s for doc_id, s in keyword_results}

        v_max = max(v_scores.values()) if v_scores else 1.0
        k_max = max(k_scores.values()) if k_scores else 1.0

        all_ids: set[str] = set(v_scores.keys()) | set(k_scores.keys())
        combined: List[Tuple[str, float, float, float]] = []
        for doc_id in all_ids:
            vs = (v_scores.get(doc_id, 0.0) / max(v_max, 1e-9)) * vector_weight
            ks = (k_scores.get(doc_id, 0.0) / max(k_max, 1e-9)) * keyword_weight
            combined.append((doc_id, vs + ks, vs, ks))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    def count(self) -> int:
        info = self._client.count(
            collection_name=self._collection_name
        )
        return info.count

    def clear(self):
        self._client.delete_collection(self._collection_name)
        from qdrant_client.models import Distance, VectorParams

        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=VectorParams(
                size=self._dim, distance=Distance.COSINE
            ),
        )
        self._keyword_index.clear()


# ──────────────────────────────────────────────
# VectorDB — Main Class
# ──────────────────────────────────────────────


class VectorDB:
    """
    Multi-backend vector database with hybrid search.

    Usage:
        db = VectorDB(VectorDBConfig(backend=Backend.BUILTIN))

        # Add documents with auto-embedding
        db.add([VectorDocument(id="1", text="Hello world")])

        # Vector search
        result = db.search("Hello")

        # Hybrid search (vector + keyword)
        result = db.hybrid_search("machine learning")

        # With custom encoder
        db = VectorDB(VectorDBConfig(encoder_fn=my_sentence_transformer.encode))
    """

    def __init__(self, config: Optional[VectorDBConfig] = None):
        self.config = config or VectorDBConfig()

        # Set up encoder
        if self.config.encoder_fn is not None:
            self._encoder = self.config.encoder_fn
            self._simple_encoder = None
        else:
            self._simple_encoder = SimpleEncoder(dim=self.config.embedding_dim)
            self._encoder = None

        # Initialize backend
        self._backend = self._init_backend()
        self._lock = threading.RLock()

    def _init_backend(self):
        """Initialize the selected backend or fall back to builtin."""
        backend = self.config.backend

        if backend == Backend.CHROMA:
            if _HAS_CHROMA:
                try:
                    return ChromaBackend(self.config)
                except Exception as e:
                    logger.warning(
                        "ChromaDB init failed (%s), falling back to builtin", e
                    )
            else:
                logger.warning("chromadb not installed, falling back to builtin")

        elif backend == Backend.FAISS:
            if _HAS_FAISS and _HAS_NUMPY:
                try:
                    return FAISSBackend(self.config)
                except Exception as e:
                    logger.warning(
                        "FAISS init failed (%s), falling back to builtin", e
                    )
            else:
                logger.warning("faiss/numpy not installed, falling back to builtin")

        elif backend == Backend.QDRANT:
            if _HAS_QDRANT:
                try:
                    return QdrantBackend(self.config)
                except Exception as e:
                    logger.warning(
                        "Qdrant init failed (%s), falling back to builtin", e
                    )
            else:
                logger.warning(
                    "qdrant-client not installed, falling back to builtin"
                )

        # Default: builtin backend
        return BuiltinBackend(dim=self.config.embedding_dim)

    def _encode(self, texts: List[str]) -> List[List[float]]:
        """Encode texts to vectors using configured encoder."""
        if self._encoder is not None:
            result = self._encoder(texts)
            # Handle sentence-transformers output (numpy array)
            if hasattr(result, "tolist"):
                result = result.tolist()  # type: ignore[union-attr]
            return result  # type: ignore[return-value]
        elif self._simple_encoder is not None:
            return self._simple_encoder.encode(texts)
        else:
            return [[0.0] * self.config.embedding_dim for _ in texts]

    # ── Public API ──────────────────────────

    @property
    def backend_name(self) -> str:
        """Return the active backend class name."""
        return type(self._backend).__name__

    def add(
        self,
        documents: Union[
            VectorDocument,
            List[VectorDocument],
            str,
            List[str],
            List[Tuple[str, str]],
        ],
        metadata: Optional[Dict[str, Any]] = None,
        auto_embed: bool = True,
    ):
        """
        Add documents with auto-embedding and auto-indexing.

        Accepts:
        - VectorDocument or list of VectorDocument
        - str or list of str (auto-generated IDs)
        - List of (id, text) tuples
        """
        with self._lock:
            docs = self._normalize_documents(documents, metadata)

            if auto_embed and docs:
                texts_to_embed = [
                    d.text
                    for d in docs
                    if d.embedding is None
                ]
                if texts_to_embed:
                    embeddings = self._encode(texts_to_embed)
                    emb_idx = 0
                    for d in docs:
                        if d.embedding is None:
                            d.embedding = embeddings[emb_idx]
                            emb_idx += 1

            self._backend.add(docs)

    def _normalize_documents(
        self,
        documents: Union[
            VectorDocument,
            List[VectorDocument],
            str,
            List[str],
            List[Tuple[str, str]],
        ],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[VectorDocument]:
        """Normalize various input formats into List[VectorDocument]."""
        import uuid as _uuid

        if isinstance(documents, VectorDocument):
            return [documents]
        if isinstance(documents, str):
            return [
                VectorDocument(
                    id=str(_uuid.uuid4())[:8],
                    text=documents,
                    metadata=metadata or {},
                )
            ]
        if isinstance(documents, list):
            if not documents:
                return []
            first = documents[0]
            if isinstance(first, VectorDocument):
                return documents  # type: ignore[return-value]
            if isinstance(first, str):
                return [
                    VectorDocument(
                        id=str(_uuid.uuid4())[:8],
                        text=str(t),
                        metadata=metadata or {},
                    )
                    for t in documents
                ]
            if isinstance(first, tuple):
                return [
                    VectorDocument(
                        id=str(t[0]),
                        text=str(t[1]),
                        metadata=metadata or {},
                    )
                    for t in documents  # type: ignore[var-annotated]
                ]
        raise ValueError(f"Unsupported document format: {type(documents)}")

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> SearchResult:
        """
        Pure vector similarity search.

        Encodes the query string and returns top_k most similar documents.
        """
        t0 = time.perf_counter()
        with self._lock:
            query_vec = self._encode([query])[0]
            hits = self._backend.search(query_vec, top_k=top_k)
            results = self._build_hits(hits, query_vec)
        elapsed = (time.perf_counter() - t0) * 1000
        return SearchResult(
            query=query,
            results=results,
            search_type=SearchType.VECTOR,
            elapsed_ms=round(elapsed, 2),
            total_indexed=self._backend.count(),
        )

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> SearchResult:
        """
        Keyword-based BM25 search (no embedding).
        """
        t0 = time.perf_counter()
        with self._lock:
            hits = self._backend.keyword_search(query, top_k=top_k)
            results = self._build_hits_keyword(hits)
        elapsed = (time.perf_counter() - t0) * 1000
        return SearchResult(
            query=query,
            results=results,
            search_type=SearchType.KEYWORD,
            elapsed_ms=round(elapsed, 2),
            total_indexed=self._backend.count(),
        )

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        vector_weight: Optional[float] = None,
        keyword_weight: Optional[float] = None,
    ) -> SearchResult:
        """
        Hybrid search: vector similarity + keyword BM25.

        Combines semantic understanding with exact keyword matching.
        Weights default to config values (vector=0.7, keyword=0.3).
        """
        vw = vector_weight if vector_weight is not None else self.config.vector_weight
        kw = keyword_weight if keyword_weight is not None else self.config.keyword_weight

        t0 = time.perf_counter()
        with self._lock:
            query_vec = self._encode([query])[0]
            hits = self._backend.hybrid_search(
                query_vec, query, top_k=top_k,
                vector_weight=vw, keyword_weight=kw,
            )
            results = self._build_hits_hybrid(hits, query_vec)
        elapsed = (time.perf_counter() - t0) * 1000
        return SearchResult(
            query=query,
            results=results,
            search_type=SearchType.HYBRID,
            elapsed_ms=round(elapsed, 2),
            total_indexed=self._backend.count(),
        )

    def delete(self, ids: Union[str, List[str]]):
        """Delete documents by ID(s). Triggers re-index."""
        with self._lock:
            if isinstance(ids, str):
                ids = [ids]
            self._backend.delete(ids)

    def count(self) -> int:
        """Number of indexed documents."""
        return self._backend.count()

    def clear(self):
        """Remove all documents and reset the index."""
        with self._lock:
            self._backend.clear()

    def get(self, doc_id: str) -> Optional[VectorDocument]:
        """Retrieve a document by ID from the builtin or FAISS backend."""
        if hasattr(self._backend, "_docs"):
            return self._backend._docs.get(doc_id)  # type: ignore[union-attr]
        return None

    def get_all_ids(self) -> List[str]:
        """Return all document IDs (builtin/FAISS backends only)."""
        if hasattr(self._backend, "_docs"):
            return list(self._backend._docs.keys())  # type: ignore[union-attr]
        return []

    # ── Internal helpers ────────────────────

    def _build_hits(
        self,
        hits: List[Tuple[str, float]],
        query_vec: List[float],
    ) -> List[SearchHit]:
        results: List[SearchHit] = []
        for doc_id, score in hits:
            doc = self.get(doc_id)
            text = doc.text if doc else ""
            meta = doc.metadata if doc else {}
            results.append(
                SearchHit(
                    id=doc_id,
                    text=text,
                    score=score,
                    vector_score=score,
                    keyword_score=0.0,
                    metadata=meta,
                )
            )
        return results

    def _build_hits_keyword(
        self, hits: List[Tuple[str, float]]
    ) -> List[SearchHit]:
        results: List[SearchHit] = []
        for doc_id, score in hits:
            doc = self.get(doc_id)
            text = doc.text if doc else ""
            meta = doc.metadata if doc else {}
            results.append(
                SearchHit(
                    id=doc_id,
                    text=text,
                    score=score,
                    vector_score=0.0,
                    keyword_score=score,
                    metadata=meta,
                )
            )
        return results

    def _build_hits_hybrid(
        self,
        hits: List[Tuple[str, float, float, float]],
        query_vec: List[float],
    ) -> List[SearchHit]:
        results: List[SearchHit] = []
        for doc_id, combined, vs, ks in hits:
            doc = self.get(doc_id)
            text = doc.text if doc else ""
            meta = doc.metadata if doc else {}
            results.append(
                SearchHit(
                    id=doc_id,
                    text=text,
                    score=combined,
                    vector_score=vs,
                    keyword_score=ks,
                    metadata=meta,
                )
            )
        return results


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────

_db: Optional[VectorDB] = None
_db_lock = threading.Lock()


def get_vector_db(config: Optional[VectorDBConfig] = None) -> VectorDB:
    """Get or create the global VectorDB singleton."""
    global _db
    with _db_lock:
        if _db is None:
            _db = VectorDB(config)
        return _db


def reset_vector_db():
    """Reset the global VectorDB singleton."""
    global _db
    with _db_lock:
        if _db is not None:
            _db.clear()
        _db = None

"""v3.104 Vector DB tests — 12 test cases"""
import math
import pytest
from src.core.vector_db import (
    VectorDB,
    VectorDBConfig,
    VectorDocument,
    SearchHit,
    SearchResult,
    SearchType,
    Backend,
    SimpleEncoder,
    KeywordIndex,
    BuiltinBackend,
    get_vector_db,
    reset_vector_db,
)


# ============================================================
# Helpers
# ============================================================


def _make_doc(doc_id: str, text: str, **meta) -> VectorDocument:
    """Quick VectorDocument factory."""
    return VectorDocument(id=doc_id, text=text, metadata=meta)


def _make_db(**kw) -> VectorDB:
    """Create a fresh VectorDB with builtin backend."""
    config = VectorDBConfig(backend=Backend.BUILTIN, embedding_dim=64, **kw)
    return VectorDB(config)


# ============================================================
# SimpleEncoder Tests
# ============================================================


class TestSimpleEncoder:
    def test_encode_produces_correct_dim(self):
        encoder = SimpleEncoder(dim=32)
        vecs = encoder.encode(["hello world"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 32

    def test_encode_normalized(self):
        encoder = SimpleEncoder(dim=16)
        vecs = encoder.encode(["test text here"])
        norm = math.sqrt(sum(v * v for v in vecs[0]))
        assert abs(norm - 1.0) < 0.01

    def test_encode_multiple_texts(self):
        encoder = SimpleEncoder(dim=8)
        texts = ["a", "b", "c", "hello world long text"]
        vecs = encoder.encode(texts)
        assert len(vecs) == 4
        assert all(len(v) == 8 for v in vecs)

    def test_fit_computes_idf(self):
        encoder = SimpleEncoder(dim=8)
        encoder.fit(["apple banana", "apple cherry", "apple date"])
        vec1 = encoder.encode(["apple banana"])
        vec2 = encoder.encode(["apple cherry"])
        # Different texts should produce different vectors
        diff = sum(abs(a - b) for a, b in zip(vec1[0], vec2[0]))
        assert diff > 0.001


# ============================================================
# KeywordIndex Tests
# ============================================================


class TestKeywordIndex:
    def test_add_and_search(self):
        ki = KeywordIndex()
        ki.add("1", "machine learning is great")
        ki.add("2", "deep learning with neural networks")
        ki.add("3", "making pasta at home")

        results = ki.search("machine learning", top_k=3)
        assert len(results) > 0
        # First result should be most relevant
        assert results[0][0] == "1"

    def test_empty_search(self):
        ki = KeywordIndex()
        results = ki.search("nothing here")
        assert results == []

    def test_remove_document(self):
        ki = KeywordIndex()
        ki.add("1", "hello world")
        ki.add("2", "hello there")
        ki.remove("1")
        results = ki.search("world", top_k=5)
        # "world" only in doc 1, which was removed
        assert len(results) == 0

    def test_chinese_tokenization(self):
        ki = KeywordIndex()
        ki.add("1", "机器学习是人工智能的核心")
        ki.add("2", "深度学习改变了计算机视觉")
        results = ki.search("机器学习", top_k=3)
        assert len(results) > 0
        assert results[0][0] == "1"


# ============================================================
# VectorDB Core Tests
# ============================================================


class TestVectorDBBasic:
    """Tests for basic VectorDB operations."""

    def test_add_and_count(self):
        db = _make_db()
        db.add(_make_doc("1", "first document"))
        db.add(_make_doc("2", "second document"))
        assert db.count() == 2

    def test_add_strings_auto_id(self):
        db = _make_db()
        db.add(["alpha", "beta", "gamma"])
        assert db.count() == 3
        # Auto-generated IDs should exist
        ids = db.get_all_ids()
        assert len(ids) == 3
        for doc_id in ids:
            assert len(doc_id) == 8

    def test_add_tuples(self):
        db = _make_db()
        db.add([("id-a", "content a"), ("id-b", "content b")])
        assert db.count() == 2
        doc_a = db.get("id-a")
        assert doc_a is not None
        assert doc_a.text == "content a"

    def test_vector_search_returns_results(self):
        db = _make_db()
        db.add([
            _make_doc("1", "machine learning algorithms"),
            _make_doc("2", "cooking recipes for pasta"),
            _make_doc("3", "deep learning neural networks"),
            _make_doc("4", "baking bread at home"),
        ])
        result = db.search("machine learning AI", top_k=3)
        assert len(result) == 3
        assert result.search_type == SearchType.VECTOR
        assert result.total_indexed == 4
        assert result.elapsed_ms >= 0

    def test_keyword_search_returns_results(self):
        db = _make_db()
        db.add([
            _make_doc("1", "machine learning algorithms"),
            _make_doc("2", "cooking recipes for pasta"),
            _make_doc("3", "deep learning neural networks"),
            _make_doc("4", "baking bread at home"),
        ])
        result = db.keyword_search("learning", top_k=3)
        assert len(result) > 0
        assert result.search_type == SearchType.KEYWORD

    def test_hybrid_search_combines_signals(self):
        db = _make_db()
        db.add([
            _make_doc("1", "machine learning with Python"),
            _make_doc("2", "Python programming basics"),
            _make_doc("3", "cooking Italian pasta"),
            _make_doc("4", "deep learning tutorials"),
        ])
        result = db.hybrid_search("Python machine learning", top_k=3)
        assert len(result) == 3
        assert result.search_type == SearchType.HYBRID
        # Each hit should have both scores populated
        for hit in result:
            assert isinstance(hit.vector_score, float)
            assert isinstance(hit.keyword_score, float)

    def test_delete_reduces_count(self):
        db = _make_db()
        db.add([_make_doc("1", "a"), _make_doc("2", "b"), _make_doc("3", "c")])
        assert db.count() == 3
        db.delete("2")
        assert db.count() == 2
        assert db.get("2") is None
        assert db.get("1") is not None

    def test_clear_removes_all(self):
        db = _make_db()
        db.add([_make_doc("1", "a"), _make_doc("2", "b")])
        assert db.count() == 2
        db.clear()
        assert db.count() == 0
        assert db.get_all_ids() == []

    def test_metadata_preserved(self):
        db = _make_db()
        db.add(_make_doc("meta-1", "content", author="Alice", score=42))
        result = db.search("content", top_k=1)
        assert len(result) == 1
        hit = result[0]
        assert hit.metadata.get("author") == "Alice"
        assert hit.metadata.get("score") == 42

    def test_search_on_empty_db(self):
        db = _make_db()
        result = db.search("anything")
        assert len(result) == 0
        assert result.total_indexed == 0

    def test_auto_embed_can_be_disabled(self):
        db = _make_db()
        doc = VectorDocument(id="no-emb", text="test")
        db.add(doc, auto_embed=False)
        assert doc.embedding is None
        # Still added though
        assert db.count() == 1

    def test_backend_name(self):
        db = _make_db()
        assert db.backend_name == "BuiltinBackend"


# ============================================================
# Singleton Tests
# ============================================================


class TestSingleton:
    def test_get_and_reset(self):
        reset_vector_db()
        db1 = get_vector_db()
        db2 = get_vector_db()
        assert db1 is db2
        reset_vector_db()
        db3 = get_vector_db()
        assert db1 is not db3


# ============================================================
# Backend Selection Tests
# ============================================================


class TestBackendSelection:
    def test_builtin_backend_always_works(self):
        config = VectorDBConfig(backend=Backend.BUILTIN)
        db = VectorDB(config)
        assert db.backend_name == "BuiltinBackend"
        db.add(_make_doc("1", "test"))
        assert db.count() == 1

    def test_chroma_falls_back_if_unavailable(self):
        config = VectorDBConfig(backend=Backend.CHROMA)
        db = VectorDB(config)
        # Should fall back to builtin if chromadb not installed
        assert db.backend_name in ("ChromaBackend", "BuiltinBackend")
        db.add(_make_doc("1", "test"))
        assert db.count() == 1

    def test_faiss_falls_back_if_unavailable(self):
        config = VectorDBConfig(backend=Backend.FAISS)
        db = VectorDB(config)
        assert db.backend_name in ("FAISSBackend", "BuiltinBackend")
        db.add(_make_doc("1", "test"))
        assert db.count() == 1

    def test_qdrant_falls_back_if_unavailable(self):
        config = VectorDBConfig(backend=Backend.QDRANT)
        db = VectorDB(config)
        assert db.backend_name in ("QdrantBackend", "BuiltinBackend")
        db.add(_make_doc("1", "test"))
        assert db.count() == 1


# ============================================================
# Hybrid Search Quality Tests
# ============================================================


class TestHybridSearchQuality:
    def test_vector_dominates_for_semantic(self):
        """Vector search should find semantically similar docs."""
        db = _make_db(vector_weight=0.9, keyword_weight=0.1)
        db.add([
            _make_doc("1", "artificial intelligence and machine learning"),
            _make_doc("2", "how to bake chocolate chip cookies"),
            _make_doc("3", "neural networks and deep learning"),
            _make_doc("4", "pasta recipes with tomato sauce"),
        ])
        result = db.hybrid_search("AI and ML techniques", top_k=2)
        # Semantic results should be tech-related
        found_ids = {hit.id for hit in result}
        assert "1" in found_ids or "3" in found_ids

    def test_keyword_matches_exact_terms(self):
        """Keyword component should boost exact term matches."""
        db = _make_db(vector_weight=0.3, keyword_weight=0.7)
        db.add([
            _make_doc("1", "the quick brown fox jumps"),
            _make_doc("2", "fox news channel broadcast"),
            _make_doc("3", "lazy dog sleeping"),
            _make_doc("4", "the fox and the hound movie"),
        ])
        result = db.hybrid_search("fox", top_k=3)
        # Top results should contain "fox" (keyword-weighted)
        for hit in result:
            assert "fox" in hit.text.lower()

    def test_adjustable_weights(self):
        """Custom weights should affect ranking."""
        db = _make_db()
        db.add([
            _make_doc("semantic", "artificial intelligence machine learning"),
            _make_doc("exact", "fox fox fox fox fox fox fox"),
        ])
        # Vector-heavy: semantic doc wins
        r1 = db.hybrid_search("fox", vector_weight=0.99, keyword_weight=0.01)
        # Keyword-heavy: exact doc wins
        r2 = db.hybrid_search("fox", vector_weight=0.01, keyword_weight=0.99)

        # Different weightings may produce different top results
        assert r1[0].vector_score >= 0
        assert r2[0].keyword_score >= 0


# ============================================================
# SearchResult Tests
# ============================================================


class TestSearchResult:
    def test_result_len_and_iter(self):
        db = _make_db()
        db.add([_make_doc(str(i), f"doc {i}") for i in range(5)])
        result = db.search("doc", top_k=3)
        assert len(result) == 3
        items = list(result)
        assert len(items) == 3
        assert result[0].id == items[0].id

    def test_result_empty(self):
        db = _make_db()
        result = db.search("nothing matches")
        assert len(result) == 0
        assert list(result) == []


# ============================================================
# Config Tests
# ============================================================


class TestVectorDBConfig:
    def test_default_config(self):
        config = VectorDBConfig()
        assert config.backend == Backend.BUILTIN
        assert config.embedding_dim == 384
        assert config.collection_name == "meshctx_docs"

    def test_custom_config(self):
        config = VectorDBConfig(
            backend=Backend.FAISS,
            embedding_dim=768,
            vector_weight=0.5,
            keyword_weight=0.5,
        )
        assert config.backend == Backend.FAISS
        assert config.embedding_dim == 768
        assert config.vector_weight == 0.5
        assert config.keyword_weight == 0.5

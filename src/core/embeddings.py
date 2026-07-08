"""
meshctx EmbeddingEngine — TF-IDF style text embeddings
======================================================
Pure Python, stdlib-only embedding engine using TF-IDF with
character n-grams. No external dependencies (no numpy, no openai).

Core API:
  EmbeddingEngine(dim=256)              — create engine
  embed(text) -> list[float]            — embed single text
  batch_embed(texts) -> list[list[float]]  — embed multiple texts
  cosine_similarity(v1, v2) -> float    — compute similarity
  fit(texts)                            — learn vocabulary from corpus (optional)

Design:
  - Character n-grams (2/3/4-grams) serve as features
  - Without fit(): uses hash-based vectorization (deterministic, always works)
  - With fit(): learns vocabulary + IDF weights from corpus for better semantics
  - L2 normalization on all output vectors
"""

import hashlib
import math

from ._stub import _P


class EmbeddingEngine:
    """TF-IDF style embedding engine using character n-grams.

    Works out-of-the-box without pre-fitting via hash-based vectorization.
    Optional ``fit()`` on a corpus learns a proper vocabulary with IDF
    weights for improved semantic quality on domain-specific text.

    Pure Python + stdlib only — zero external dependencies.
    """

    def __init__(self, dim: int = 256):
        """Create an embedding engine.

        Args:
            dim: Output vector dimension. Default 256.
        """
        self.dim = dim
        self.vocab: dict[str, int] = {}       # term → index
        self.idf: dict[str, float] = {}        # term → IDF weight
        self._fitted = False

    # ── tokenization ──────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Extract character n-grams (2, 3, 4-grams) from text."""
        text = text.lower()
        ngrams: list[str] = []
        L = len(text)
        if L >= 2:
            ngrams.extend(text[i:i + 2] for i in range(L - 1))
        if L >= 3:
            ngrams.extend(text[i:i + 3] for i in range(L - 2))
        if L >= 4:
            ngrams.extend(text[i:i + 4] for i in range(L - 3))
        return ngrams

    # ── fitting (optional) ────────────────────────────────

    def fit(self, texts: list[str]) -> None:
        """Build vocabulary and compute IDF weights from a corpus.

        Optional — the engine works without fitting via hash-based
        vectors.  Fitting improves semantic quality when you have
        representative text to build a vocabulary from.
        """
        df: dict[str, int] = {}
        N = len(texts)

        for text in texts:
            for term in set(self._tokenize(text)):
                df[term] = df.get(term, 0) + 1

        # Most-frequent n-grams first, capped at dim
        sorted_terms = sorted(df, key=lambda t: df[t], reverse=True)
        self.vocab = {term: i for i, term in enumerate(sorted_terms[:self.dim])}

        # Smooth IDF: log((N+1)/(df+1)) + 1
        for term, idx in self.vocab.items():
            self.idf[term] = math.log((N + 1) / (df[term] + 1)) + 1.0

        self._fitted = True

    # ── public API ────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Convert a single text to a fixed-size float vector."""
        if not text:
            return [0.0] * self.dim
        return self._tfidf_vector(text) if self._fitted else self._hash_vector(text)

    def batch_embed(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns one vector per text."""
        return [self.embed(t) for t in texts]

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Cosine similarity between two vectors. Range [-1, 1]."""
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return dot / (n1 * n2)

    # ── internal vectorization ────────────────────────────

    def _tfidf_vector(self, text: str) -> list[float]:
        """TF-IDF weighted vector using the fitted vocabulary."""
        vec = [0.0] * self.dim

        tf: dict[str, int] = {}
        for term in self._tokenize(text):
            tf[term] = tf.get(term, 0) + 1

        for term, freq in tf.items():
            idx = self.vocab.get(term)
            if idx is not None:
                vec[idx] = freq * self.idf[term]

        return _l2_normalize(vec)

    def _hash_vector(self, text: str) -> list[float]:
        """Hash-based vector — no vocabulary required."""
        vec = [0.0] * self.dim
        ngrams = self._tokenize(text)

        for i, ng in enumerate(ngrams):
            # Deterministic hash: MD5 of n-gram, modulo dim
            h = int(hashlib.md5(ng.encode()).hexdigest(), 16) % self.dim
            vec[h] += 1.0

        return _l2_normalize(vec)


# ── helpers ────────────────────────────────────────────────

def _l2_normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector in-place-style (returns new list)."""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


# ── module-level stub proxy (meshctx convention) ──────────

def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    return _P(name)

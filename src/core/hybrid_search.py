"""
meshctx HybridSearch — 混合检索引擎
====================================
关键词 (BM25) + 向量 (语义) 混合搜索，RRF 融合重排。

核心能力:
  1. 关键词评分 — BM25 (Okapi) 精确实现
  2. 向量评分 — 余弦相似度 / L2
  3. RRF 融合 — Reciprocal Rank Fusion 合并两种排名
  4. 权重可调 — α·semantic + (1-α)·keyword
  5. 结果重排 — 融合后二次排序 + 多样性重排

混合策略:
  - Convex Combination: score = α × vector_score + (1-α) × keyword_score
  - RRF (Reciprocal Rank Fusion): score = Σ 1/(k + rank_i)  适合排名差异大的场景
  - 权重 α ∈ [0, 1]: α=0 纯关键词, α=1 纯语义, α=0.5 等权重

设计原则:
  - 零外部依赖: BM25 纯 Python 实现
  - 可插拔: 向量后端通过接口注入
  - 线程安全: 索引更新加锁

API:
  index(docs)                            → 构建索引
  search(query, k, alpha, strategy)      → [(id, score, metadata)]
  get_hybrid_searcher()                  → HybridSearcher singleton (auto-create)
"""

import logging
import math
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import numpy as np

logger = logging.getLogger("meshctx.hybrid_search")


# ═══════════════════════════════════════════════════════════
# 文本预处理
# ═══════════════════════════════════════════════════════════

class TextNormalizer:
    """文本标准化 + 分词"""

    # 英文分词正则: 单词 + 连字符保留
    _WORD_PATTERN = re.compile(r"[a-zA-Z0-9]+(?:[-'][a-zA-Z0-9]+)*")

    # 停用词 (英文常见)
    STOP_WORDS: Set[str] = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "shall", "should", "may", "might", "must", "can",
        "could", "it", "its", "this", "that", "these", "those", "i", "me",
        "my", "we", "our", "you", "your", "he", "she", "him", "her", "they",
        "them", "their", "not", "no", "nor", "so", "as", "if", "than",
        "very", "just", "about", "also", "into", "over", "after", "before",
    }

    @classmethod
    def tokenize(cls, text: str, remove_stopwords: bool = True) -> List[str]:
        """英文分词 + 小写化 + 停用词移除"""
        tokens = cls._WORD_PATTERN.findall(text.lower())
        if remove_stopwords:
            tokens = [t for t in tokens if t not in cls.STOP_WORDS and len(t) > 1]
        return tokens


# ═══════════════════════════════════════════════════════════
# BM25 评分器
# ═══════════════════════════════════════════════════════════

@dataclass
class BM25Stats:
    """BM25 文档统计"""
    doc_id: str
    doc_length: int
    term_freqs: Dict[str, int]  # term → frequency in this doc


class BM25Scorer:
    """BM25 (Okapi BM25) 精确实现

    BM25 公式:
      score(D, Q) = Σ IDF(q_i) × (f(q_i, D) × (k1 + 1)) / (f(q_i, D) + k1 × (1 - b + b × |D|/avgdl))

    其中:
      IDF(q) = ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1)
      f(q, D) = 词 q 在文档 D 中的频率
      |D| = 文档 D 的长度
      avgdl = 平均文档长度
      k1 = 词频饱和度参数 (默认 1.5)
      b = 长度归一化参数 (默认 0.75)
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: Dict[str, BM25Stats] = {}
        self._doc_freqs: Dict[str, int] = defaultdict(int)  # term → 出现该词的文档数
        self._total_docs: int = 0
        self._total_length: int = 0
        self._avgdl: float = 0.0
        self._lock = threading.RLock()

    def index(self, docs: Dict[str, str]):
        """索引文档集合

        Args:
            docs: {doc_id: text} 映射
        """
        with self._lock:
            for doc_id, text in docs.items():
                tokens = TextNormalizer.tokenize(text)
                term_freqs = Counter(tokens)
                doc_len = len(tokens)

                self._docs[doc_id] = BM25Stats(
                    doc_id=doc_id,
                    doc_length=doc_len,
                    term_freqs=dict(term_freqs),
                )

                # 更新文档频率
                for term in set(tokens):
                    self._doc_freqs[term] += 1

            self._total_docs = len(self._docs)
            self._total_length = sum(d.doc_length for d in self._docs.values())
            self._avgdl = self._total_length / max(1, self._total_docs)

            logger.info(f"BM25 indexed {self._total_docs} docs, "
                        f"vocab={len(self._doc_freqs)}, avgdl={self._avgdl:.1f}")

    def add_doc(self, doc_id: str, text: str):
        """增量添加文档"""
        self.index({doc_id: text})

    def remove_doc(self, doc_id: str):
        """移除文档"""
        with self._lock:
            if doc_id not in self._docs:
                return
            doc = self._docs[doc_id]
            for term in doc.term_freqs:
                self._doc_freqs[term] = max(0, self._doc_freqs[term] - 1)
                if self._doc_freqs[term] == 0:
                    del self._doc_freqs[term]
            del self._docs[doc_id]
            self._total_docs = len(self._docs)
            self._total_length = sum(d.doc_length for d in self._docs.values())
            self._avgdl = self._total_length / max(1, self._total_docs)

    def score(self, doc_id: str, query_terms: List[str]) -> float:
        """计算文档的 BM25 分数

        Args:
            doc_id: 文档 ID
            query_terms: 查询词列表

        Returns:
            BM25 分数
        """
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc is None:
                return 0.0

            score = 0.0
            for term in query_terms:
                tf = doc.term_freqs.get(term, 0)
                if tf == 0:
                    continue

                df = self._doc_freqs.get(term, 0)
                # IDF
                idf = math.log(
                    (self._total_docs - df + 0.5) / (df + 0.5) + 1.0
                )

                # TF 饱和度
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (
                    1 - self.b + self.b * doc.doc_length / self._avgdl
                )
                score += idf * numerator / denominator

            return score

    def search(self, query: str, k: int = 10) -> List[Tuple[str, float]]:
        """BM25 搜索

        Returns:
            [(doc_id, bm25_score), ...] 按分数降序
        """
        query_terms = TextNormalizer.tokenize(query)
        if not query_terms:
            return []

        scores = []
        with self._lock:
            for doc_id in self._docs:
                s = self.score(doc_id, query_terms)
                if s > 0:
                    scores.append((doc_id, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]

    def size(self) -> int:
        return self._total_docs

    def clear(self):
        with self._lock:
            self._docs.clear()
            self._doc_freqs.clear()
            self._total_docs = 0
            self._total_length = 0
            self._avgdl = 0.0


# ═══════════════════════════════════════════════════════════
# RRF 融合
# ═══════════════════════════════════════════════════════════

class RRFFusion:
    """Reciprocal Rank Fusion (RRF)

    RRF 公式:
      RRF(d) = Σ_{r in rankings} 1 / (k + rank_r(d))

    其中:
      k = 平滑常数 (默认 60, 来自原始论文)
      rank_r(d) = 文档 d 在排名 r 中的位置 (1-indexed)
    """

    def __init__(self, k: int = 60):
        self.k = k

    def fuse(self, rankings: List[List[Tuple[str, float]]]) -> List[Tuple[str, float]]:
        """融合多个排名列表

        Args:
            rankings: [(doc_id, score), ...] 的列表的列表 (已排序)

        Returns:
            [(doc_id, rrf_score), ...] 按 RRF 分数降序
        """
        scores: Dict[str, float] = defaultdict(float)

        for ranking in rankings:
            for rank, (doc_id, _) in enumerate(ranking, start=1):
                scores[doc_id] += 1.0 / (self.k + rank)

        # 排序
        result = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return result

    def fuse_with_weights(self,
                          rankings: List[List[Tuple[str, float]]],
                          weights: List[float]) -> List[Tuple[str, float]]:
        """加权 RRF 融合

        Args:
            rankings: 多个排名列表
            weights: 每个排名的权重

        Returns:
            [(doc_id, weighted_rrf_score), ...]
        """
        scores: Dict[str, float] = defaultdict(float)

        for ranking, weight in zip(rankings, weights):
            for rank, (doc_id, _) in enumerate(ranking, start=1):
                scores[doc_id] += weight * (1.0 / (self.k + rank))

        result = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return result


# ═══════════════════════════════════════════════════════════
# 融合策略
# ═══════════════════════════════════════════════════════════

class FusionStrategy:
    """融合策略工厂"""

    @staticmethod
    def convex_combine(keyword_results: List[Tuple[str, float]],
                       vector_results: List[Tuple[str, float]],
                       alpha: float = 0.5) -> List[Tuple[str, float]]:
        """凸组合融合: score = α × vec + (1-α) × kw

        前提: 两种分数需要归一化到 [0, 1] 才能加权相加
        """
        # 归一化
        kw_scores = dict(keyword_results)
        vec_scores = dict(vector_results)

        all_ids = set(kw_scores.keys()) | set(vec_scores.keys())

        # Min-max 归一化
        kw_values = list(kw_scores.values())
        vec_values = list(vec_scores.values())

        kw_max = max(kw_values) if kw_values else 1.0
        kw_min = min(kw_values) if kw_values else 0.0
        vec_max = max(vec_values) if vec_values else 1.0
        vec_min = min(vec_values) if vec_values else 0.0

        kw_range = max(kw_max - kw_min, 1e-10)
        vec_range = max(vec_max - vec_min, 1e-10)

        combined = {}
        for doc_id in all_ids:
            kw = kw_scores.get(doc_id, 0.0)
            vec = vec_scores.get(doc_id, 0.0)
            kw_norm = (kw - kw_min) / kw_range
            vec_norm = (vec - vec_min) / vec_range
            combined[doc_id] = alpha * vec_norm + (1 - alpha) * kw_norm

        return sorted(combined.items(), key=lambda x: x[1], reverse=True)

    @staticmethod
    def rrf(keyword_results: List[Tuple[str, float]],
            vector_results: List[Tuple[str, float]],
            k: int = 60) -> List[Tuple[str, float]]:
        """RRF 融合 (等权重)"""
        rrf = RRFFusion(k=k)
        return rrf.fuse([keyword_results, vector_results])

    @staticmethod
    def weighted_rrf(keyword_results: List[Tuple[str, float]],
                     vector_results: List[Tuple[str, float]],
                     keyword_weight: float = 0.3,
                     vector_weight: float = 0.7,
                     k: int = 60) -> List[Tuple[str, float]]:
        """加权 RRF 融合"""
        rrf = RRFFusion(k=k)
        return rrf.fuse_with_weights(
            [keyword_results, vector_results],
            [keyword_weight, vector_weight],
        )


# ═══════════════════════════════════════════════════════════
# 多样性重排 (MMR)
# ═══════════════════════════════════════════════════════════

class DiversityReranker:
    """Maximal Marginal Relevance (MMR) 多样性重排

    MMR 公式:
      MMR = argmax_{d ∈ R\\S} [ λ × sim1(d, Q) - (1-λ) × max_{d' ∈ S} sim2(d, d') ]

    其中:
      λ = 相关性-多样性权衡 (0.7 偏向相关, 0.3 偏向多样)
      sim1 = 查询-文档相似度
      sim2 = 文档间相似度
    """

    def rerank(self,
               results: List[Tuple[str, float]],
               doc_vectors: Dict[str, np.ndarray],
               query_vector: Optional[np.ndarray] = None,
               lambda_param: float = 0.7,
               k: int = 10) -> List[Tuple[str, float]]:
        """MMR 重排

        Args:
            results: [(doc_id, score), ...] 候选结果
            doc_vectors: {doc_id: vector} 文档向量映射
            query_vector: 查询向量 (None 则用分数代替相似度)
            lambda_param: 相关性权重 (0-1)
            k: 返回数量

        Returns:
            重排后的结果
        """
        if len(results) <= 1:
            return results[:k]

        result_ids = [r[0] for r in results]
        scores = dict(results)

        # 相似度函数
        def _similarity(a: str, b: str) -> float:
            va = doc_vectors.get(a)
            vb = doc_vectors.get(b)
            if va is not None and vb is not None:
                return float(np.dot(va, vb) / (
                    np.linalg.norm(va) * np.linalg.norm(vb) + 1e-10
                ))
            return 0.0

        selected = []
        remaining = list(result_ids)

        # 第一个结果选最高分
        first = remaining.pop(0)
        selected.append(first)

        while remaining and len(selected) < k:
            mmr_scores = {}
            for doc_id in remaining:
                # 相关性 (用原始分数或向量相似度)
                if query_vector is not None and doc_id in doc_vectors:
                    relevance = float(np.dot(
                        doc_vectors[doc_id], query_vector,
                    ) / (np.linalg.norm(doc_vectors[doc_id]) *
                         np.linalg.norm(query_vector) + 1e-10))
                else:
                    relevance = scores.get(doc_id, 0.0)

                # 与已选文档的最大相似度
                max_sim = max(
                    _similarity(doc_id, sel) for sel in selected
                )

                mmr_scores[doc_id] = (
                    lambda_param * relevance - (1 - lambda_param) * max_sim
                )

            best = max(mmr_scores, key=mmr_scores.get)
            selected.append(best)
            remaining.remove(best)

        return [(doc_id, scores.get(doc_id, 0.0)) for doc_id in selected]


# ═══════════════════════════════════════════════════════════
# HybridSearcher 主类
# ═══════════════════════════════════════════════════════════

@dataclass
class HybridSearchResult:
    """混合搜索结果"""
    id: str
    score: float
    keyword_score: float = 0.0
    vector_score: float = 0.0
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    rank_sources: Dict[str, int] = field(default_factory=dict)  # source → rank

    def __repr__(self) -> str:
        return (f"HybridResult(id={self.id!r}, score={self.score:.4f}, "
                f"kw={self.keyword_score:.4f}, vec={self.vector_score:.4f})")


class HybridSearcher:
    """混合搜索引擎

    组合 BM25 关键词搜索 + 向量语义搜索，通过 RRF 或凸组合融合。
    """

    def __init__(self,
                 vector_search_fn: Callable[..., List[Tuple[str, float]]],
                 alpha: float = 0.5,
                 fusion_strategy: str = "rrf",
                 bm25_k1: float = 1.5,
                 bm25_b: float = 0.75,
                 rrf_k: int = 60,
                 enable_diversity_rerank: bool = False,
                 diversity_lambda: float = 0.7):
        """
        Args:
            vector_search_fn: 向量搜索函数 (query_text, k) → [(doc_id, score), ...]
            alpha: 语义权重 (0=纯关键词, 1=纯语义)
            fusion_strategy: 融合策略 ("rrf" / "convex" / "weighted_rrf")
            bm25_k1: BM25 词频饱和度参数
            bm25_b: BM25 长度归一化参数
            rrf_k: RRF 平滑常数
            enable_diversity_rerank: 是否启用 MMR 多样性重排
            diversity_lambda: MMR 相关性权重
        """
        self.alpha = alpha
        self.fusion_strategy = fusion_strategy
        self.vector_search_fn = vector_search_fn
        self.bm25 = BM25Scorer(k1=bm25_k1, b=bm25_b)
        self.reranker = DiversityReranker() if enable_diversity_rerank else None
        self.diversity_lambda = diversity_lambda
        self.rrf_k = rrf_k

        self._doc_texts: Dict[str, str] = {}
        self._doc_vectors: Dict[str, np.ndarray] = {}
        self._doc_metadata: Dict[str, Dict] = {}
        self._lock = threading.RLock()

        logger.info(f"HybridSearcher initialized: alpha={alpha}, "
                    f"fusion={fusion_strategy}, diversity={enable_diversity_rerank}")

    # ── 索引 ────────────────────────────────────────────

    def index(self, documents: List[Dict[str, Any]],
              embedding_fn: Optional[Callable[[str], np.ndarray]] = None,
              text_key: str = "text",
              id_key: str = "id"):
        """索引文档集合

        Args:
            documents: 文档列表
            embedding_fn: 可选的嵌入函数 (用于 MMR 多样性重排)
            text_key: 文本字段 key
            id_key: ID 字段 key
        """
        with self._lock:
            # BM25 索引
            bm25_docs = {}
            for doc in documents:
                doc_id = str(doc.get(id_key, doc.get("id", str(hash(doc[text_key])))))
                text = doc[text_key]
                bm25_docs[doc_id] = text
                self._doc_texts[doc_id] = text
                self._doc_metadata[doc_id] = doc.get("metadata", {})

            self.bm25.index(bm25_docs)

            # 向量索引 (用于 MMR)
            if embedding_fn:
                for doc_id, text in self._doc_texts.items():
                    if doc_id not in self._doc_vectors:
                        try:
                            vec = embedding_fn(text)
                            if isinstance(vec, list):
                                vec = np.array(vec, dtype=np.float32)
                            self._doc_vectors[doc_id] = vec
                        except Exception as e:
                            logger.debug(f"Embedding failed for {doc_id}: {e}")

            logger.info(f"HybridSearcher indexed {len(documents)} documents")

    def add_document(self, doc_id: str, text: str,
                     metadata: Optional[Dict] = None,
                     embedding_fn: Optional[Callable] = None):
        """增量添加文档"""
        self.index([{"id": doc_id, "text": text, "metadata": metadata or {}}],
                   embedding_fn=embedding_fn)

    def remove_document(self, doc_id: str):
        """移除文档"""
        with self._lock:
            self.bm25.remove_doc(doc_id)
            self._doc_texts.pop(doc_id, None)
            self._doc_vectors.pop(doc_id, None)
            self._doc_metadata.pop(doc_id, None)

    # ── 搜索 ────────────────────────────────────────────

    def search(self, query: str, k: int = 10,
               alpha: Optional[float] = None,
               fusion_strategy: Optional[str] = None,
               metadata_filters: Optional[Dict] = None) -> List[HybridSearchResult]:
        """混合搜索

        Args:
            query: 查询文本
            k: 返回结果数
            alpha: 语义权重 (覆盖实例默认值)
            fusion_strategy: 融合策略 (覆盖实例默认值)
            metadata_filters: 元数据过滤条件

        Returns:
            HybridSearchResult 列表
        """
        alpha = alpha if alpha is not None else self.alpha
        strategy = fusion_strategy or self.fusion_strategy

        # 1. 关键词搜索
        keyword_results = self.bm25.search(query, k=k * 2)  # 多取用于融合

        # 2. 向量搜索
        vector_results = self.vector_search_fn(query, k * 2)

        # 3. 归一化向量分数到 [0,1]
        if vector_results:
            max_vs = max(s[1] for s in vector_results)
            min_vs = min(s[1] for s in vector_results)
            vr = max(max_vs - min_vs, 1e-10)
            vector_results = [(doc_id, (score - min_vs) / vr)
                              for doc_id, score in vector_results]

        # 4. 融合
        if strategy == "convex":
            fused = FusionStrategy.convex_combine(
                keyword_results, vector_results, alpha=alpha,
            )
        elif strategy == "weighted_rrf":
            fused = FusionStrategy.weighted_rrf(
                keyword_results, vector_results,
                keyword_weight=1 - alpha,
                vector_weight=alpha,
                k=self.rrf_k,
            )
        else:  # rrf (default)
            fused = FusionStrategy.rrf(
                keyword_results, vector_results, k=self.rrf_k,
            )

        # 5. 构建结果
        kw_dict = dict(keyword_results)
        vec_dict = dict(vector_results)

        results = []
        for doc_id, score in fused[:k]:
            # 元数据过滤
            if metadata_filters:
                meta = self._doc_metadata.get(doc_id, {})
                if not self._match_filters(meta, metadata_filters):
                    continue

            results.append(HybridSearchResult(
                id=doc_id,
                score=score,
                keyword_score=kw_dict.get(doc_id, 0.0),
                vector_score=vec_dict.get(doc_id, 0.0),
                text=self._doc_texts.get(doc_id, ""),
                metadata=self._doc_metadata.get(doc_id, {}),
            ))

        # 6. MMR 多样性重排 (可选)
        if self.reranker and len(results) > 1:
            mmr_input = [(r.id, r.score) for r in results]
            mmr_output = self.reranker.rerank(
                mmr_input, self._doc_vectors,
                lambda_param=self.diversity_lambda, k=k,
            )
            # 重新映射
            score_map = {r.id: r for r in results}
            results = []
            for doc_id, _ in mmr_output:
                if doc_id in score_map:
                    results.append(score_map[doc_id])

        return results

    def _match_filters(self, metadata: Dict, filters: Dict) -> bool:
        """元数据过滤匹配"""
        for key, value in filters.items():
            if key not in metadata:
                return False
            mv = metadata[key]
            if isinstance(value, (list, set, tuple)):
                if mv not in value:
                    return False
            elif isinstance(value, dict):
                for op, op_val in value.items():
                    if op == "$eq" and mv != op_val:
                        return False
                    elif op == "$ne" and mv == op_val:
                        return False
                    elif op == "$gt" and mv <= op_val:
                        return False
                    elif op == "$gte" and mv < op_val:
                        return False
                    elif op == "$lt" and mv >= op_val:
                        return False
                    elif op == "$lte" and mv > op_val:
                        return False
                    elif op == "$in" and mv not in op_val:
                        return False
                    elif op == "$contains" and op_val not in str(mv):
                        return False
            else:
                if mv != value:
                    return False
        return True

    # ── 信息 ────────────────────────────────────────────

    @property
    def size(self) -> int:
        return self.bm25.size()

    def stats(self) -> Dict[str, Any]:
        return {
            "doc_count": self.bm25.size(),
            "avg_doc_length": self.bm25._avgdl,
            "vocab_size": len(self.bm25._doc_freqs),
            "alpha": self.alpha,
            "fusion_strategy": self.fusion_strategy,
            "diversity_enabled": self.reranker is not None,
        }

    def clear(self):
        with self._lock:
            self.bm25.clear()
            self._doc_texts.clear()
            self._doc_vectors.clear()
            self._doc_metadata.clear()


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_searcher: Optional[HybridSearcher] = None
_searcher_lock = threading.Lock()


def get_hybrid_searcher(
    vector_search_fn: Optional[Callable] = None,
    alpha: float = 0.5,
    **kwargs,
) -> HybridSearcher:
    """获取 HybridSearcher 全局单例 (auto-create)

    Args:
        vector_search_fn: 向量搜索函数 (首次创建时必需)
        alpha: 语义权重
        **kwargs: 传递给 HybridSearcher() 的其他参数

    Returns:
        HybridSearcher 实例
    """
    global _searcher
    if _searcher is None:
        with _searcher_lock:
            if _searcher is None:
                if vector_search_fn is None:
                    raise ValueError(
                        "vector_search_fn is required for first initialization. "
                        "Provide a function like: lambda q, k: vector_store.search(q, k)"
                    )
                _searcher = HybridSearcher(
                    vector_search_fn=vector_search_fn,
                    alpha=alpha,
                    **kwargs,
                )
    return _searcher


def reset_hybrid_searcher():
    """重置全局实例 (用于测试)"""
    global _searcher
    with _searcher_lock:
        _searcher = None

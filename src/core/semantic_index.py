"""
meshctx Semantic Index — 语义向量索引引擎
==========================================

基于向量相似度的语义索引系统。支持多维向量索引、多种距离度量、
分片索引(大容量场景)和近似搜索。

核心功能:
  1. 语义向量索引 — add/search/delete/batch_add
  2. 多种距离度量 — 余弦相似度 / L2 欧氏距离 / 点积
  3. 增量更新 — 单条 add/delete, 无需全量重建
  4. 分片索引 — 自动分片支持大容量 (>100K 向量)
  5. 近似搜索 — Top-K + 阈值过滤
  6. 元数据过滤 — 搜索时按 metadata 字段过滤
  7. 持久化 — JSON 格式保存索引

与 vector_store.py 的区别:
  - vector_store: 底层向量存储, 聚焦引擎实现 (numpy/faiss)
  - semantic_index: 上层语义索引, 面向检索场景, 包含分片/阈值/过滤

使用示例:
  idx = get_semantic_index()
  idx.add("doc_1", vec, metadata={"title": "Intro to ML"})
  results = idx.search(query_vec, k=10, threshold=0.7, filters={"type": "article"})

设计原则:
  - numpy 作为唯一硬依赖
  - 线程安全: 读写锁保护
  - 自动分片: 超过阈值自动创建新分片
  - 内存友好: 惰性归一化, 按需计算

代码量: ~550 行
"""

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    _NUMPY_AVAILABLE = False

logger = logging.getLogger("meshctx.semantic_index")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class SemanticEntry:
    """语义索引条目"""
    id: str
    vector: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "vector": self.vector.tolist(),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SemanticEntry":
        return cls(
            id=d["id"],
            vector=np.array(d["vector"], dtype=np.float32),
            metadata=d.get("metadata", {}),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "score": self.score,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════
# 距离度量
# ═══════════════════════════════════════════════════════════

class DistanceMetric:
    """距离度量函数集"""

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """余弦相似度 [−1, 1], 越高越相似"""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
        """余弦距离 [0, 2], 越低越相似"""
        return 1.0 - DistanceMetric.cosine_similarity(a, b)

    @staticmethod
    def euclidean_distance(a: np.ndarray, b: np.ndarray) -> float:
        """欧氏距离 (L2), 越低越相似"""
        return float(np.linalg.norm(a - b))

    @staticmethod
    def dot_product(a: np.ndarray, b: np.ndarray) -> float:
        """点积, 越高越相似"""
        return float(np.dot(a, b))

    @staticmethod
    def compute(a: np.ndarray, b: np.ndarray, metric: str = "cosine") -> float:
        """统一距离计算接口

        Args:
            a, b: 向量
            metric: "cosine" | "euclidean" | "dot"

        Returns:
            距离/相似度值
        """
        if metric == "cosine":
            return DistanceMetric.cosine_distance(a, b)
        elif metric == "euclidean":
            return DistanceMetric.euclidean_distance(a, b)
        elif metric == "dot":
            # 点积越高越好, 取负号使其越低越好 (统一排序方向)
            return -DistanceMetric.dot_product(a, b)
        else:
            raise ValueError(f"Unknown metric: {metric}")


# ═══════════════════════════════════════════════════════════
# 分片索引
# ═══════════════════════════════════════════════════════════

class IndexShard:
    """单个索引分片"""

    def __init__(self, shard_id: int, dim: int, metric: str = "cosine"):
        self.shard_id = shard_id
        self.dim = dim
        self.metric = metric
        self._entries: Dict[str, SemanticEntry] = {}
        # 向量矩阵 (用于批量搜索)
        self._matrix: Optional[np.ndarray] = None  # shape: (n, dim)
        self._ids: List[str] = []  # 与 _matrix 行对齐
        self._dirty: bool = True
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._entries)

    def add(self, entry: SemanticEntry):
        with self._lock:
            self._entries[entry.id] = entry
            self._dirty = True

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                self._dirty = True
                return True
            return False

    def get(self, entry_id: str) -> Optional[SemanticEntry]:
        with self._lock:
            return self._entries.get(entry_id)

    def _rebuild_matrix(self):
        """重建向量矩阵和 ID 列表"""
        if not self._dirty:
            return
        ids_list = list(self._entries.keys())
        if not ids_list:
            self._matrix = None
            self._ids = []
        else:
            vectors = [self._entries[eid].vector for eid in ids_list]
            self._matrix = np.stack(vectors, axis=0).astype(np.float32)
            self._ids = ids_list
        self._dirty = False

    def search(self, query: np.ndarray, k: int,
               threshold: Optional[float] = None,
               filters: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """在分片中搜索 Top-K

        Args:
            query: 查询向量
            k: 返回数量
            threshold: 距离阈值 (低于此值才算匹配, 仅 cosine/euclidean)
            filters: 元数据过滤条件

        Returns:
            SearchResult 列表, 按距离升序
        """
        with self._lock:
            if not self._entries:
                return []

            self._rebuild_matrix()
            if self._matrix is None:
                return []

            # 批量计算距离
            if self.metric == "cosine":
                # 归一化后点积 = 余弦相似度
                q_norm = query / (np.linalg.norm(query) + 1e-10)
                m_norm = self._matrix / (np.linalg.norm(self._matrix, axis=1, keepdims=True) + 1e-10)
                similarities = np.dot(m_norm, q_norm)
                distances = 1.0 - similarities  # 余弦距离
            elif self.metric == "euclidean":
                distances = np.linalg.norm(self._matrix - query, axis=1)
            elif self.metric == "dot":
                similarities = np.dot(self._matrix, query)
                distances = -similarities  # 负点积
            else:
                raise ValueError(f"Unknown metric: {self.metric}")

            # 排序并筛选
            results = []
            indices = np.argsort(distances)

            for idx in indices:
                dist = float(distances[idx])
                if threshold is not None and dist > threshold:
                    continue

                entry_id = self._ids[idx]
                entry = self._entries[entry_id]

                # 元数据过滤
                if filters:
                    match = True
                    for fk, fv in filters.items():
                        if entry.metadata.get(fk) != fv:
                            match = False
                            break
                    if not match:
                        continue

                # 转换距离为相似度分数 (0-1, 越高越好)
                if self.metric == "cosine":
                    score = float(1.0 - dist)
                elif self.metric == "euclidean":
                    score = float(1.0 / (1.0 + dist))
                else:  # dot
                    score = float(-dist)

                results.append(SearchResult(
                    id=entry_id,
                    score=score,
                    metadata=dict(entry.metadata),
                ))

                if len(results) >= k:
                    break

            return results

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "shard_id": self.shard_id,
                "dim": self.dim,
                "metric": self.metric,
                "entries": [e.to_dict() for e in self._entries.values()],
            }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IndexShard":
        shard = cls(
            shard_id=d["shard_id"],
            dim=d["dim"],
            metric=d.get("metric", "cosine"),
        )
        for entry_data in d.get("entries", []):
            entry = SemanticEntry.from_dict(entry_data)
            shard._entries[entry.id] = entry
        shard._dirty = True
        return shard


# ═══════════════════════════════════════════════════════════
# 语义索引主类
# ═══════════════════════════════════════════════════════════

class SemanticIndex:
    """语义向量索引引擎

    管理多个分片、提供统一的 add/search/delete 接口。
    支持元数据过滤、阈值搜索和 JSON 持久化。
    """

    DEFAULT_SHARD_SIZE = 10000
    DEFAULT_DIM = 1536  # OpenAI text-embedding-ada-002 维度

    def __init__(self, dim: int = DEFAULT_DIM,
                 metric: str = "cosine",
                 shard_size: int = DEFAULT_SHARD_SIZE,
                 persist_path: Optional[str] = None):
        """
        Args:
            dim: 向量维度
            metric: 距离度量 ("cosine", "euclidean", "dot")
            shard_size: 每个分片的最大条目数
            persist_path: JSON 持久化路径
        """
        if not _NUMPY_AVAILABLE:
            raise ImportError(
                "numpy is required for SemanticIndex. "
                "Install it with: pip install numpy"
            )
        self.dim = dim
        self.metric = metric
        self.shard_size = shard_size
        self.persist_path = persist_path

        self._shards: List[IndexShard] = [IndexShard(0, dim, metric)]
        self._lock = threading.RLock()
        self._stats: Dict[str, int] = {"adds": 0, "searches": 0, "deletes": 0, "shards": 1}

    @property
    def size(self) -> int:
        """总条目数"""
        with self._lock:
            return sum(shard.size for shard in self._shards)

    @property
    def shard_count(self) -> int:
        """分片数量"""
        with self._lock:
            return len(self._shards)

    # ── 增删操作 ──────────────────────────────────────────

    def add(self, entry_id: str, vector: Union[np.ndarray, List[float]],
            metadata: Optional[Dict[str, Any]] = None) -> str:
        """添加单个向量

        Args:
            entry_id: 条目 ID
            vector: 向量 (numpy array 或 list)
            metadata: 元数据字典

        Returns:
            条目 ID
        """
        if isinstance(vector, list):
            vector = np.array(vector, dtype=np.float32)
        if vector.shape[0] != self.dim:
            raise ValueError(f"Vector dim mismatch: expected {self.dim}, got {vector.shape[0]}")

        entry = SemanticEntry(
            id=entry_id,
            vector=vector.astype(np.float32),
            metadata=metadata or {},
        )

        with self._lock:
            # 查找或创建合适的分片
            target_shard = None
            # 先查找是否已存在
            for shard in self._shards:
                if shard.get(entry_id) is not None:
                    target_shard = shard
                    break

            if target_shard is None:
                # 找到或创建有容量的分片
                for shard in self._shards:
                    if shard.size < self.shard_size:
                        target_shard = shard
                        break

                if target_shard is None:
                    # 所有分片都满了, 创建新分片
                    shard_id = len(self._shards)
                    target_shard = IndexShard(shard_id, self.dim, self.metric)
                    self._shards.append(target_shard)
                    self._stats["shards"] = len(self._shards)
                    logger.info(f"Created new shard {shard_id} (total: {len(self._shards)})")

            target_shard.add(entry)
            self._stats["adds"] += 1
            logger.debug(f"SemanticIndex added: {entry_id} (shard {target_shard.shard_id})")

        return entry_id

    def batch_add(self, entries: List[Tuple[str, Union[np.ndarray, List[float]],
                                              Optional[Dict[str, Any]]]]) -> List[str]:
        """批量添加向量

        Args:
            entries: [(id, vector, metadata?), ...] 列表

        Returns:
            添加的 ID 列表
        """
        ids = []
        for item in entries:
            if len(item) == 2:
                eid, vec = item
                meta = None
            else:
                eid, vec, meta = item
            ids.append(self.add(eid, vec, meta))
        return ids

    def delete(self, entry_id: str) -> bool:
        """删除条目

        Returns:
            是否成功删除
        """
        with self._lock:
            for shard in self._shards:
                if shard.delete(entry_id):
                    self._stats["deletes"] += 1
                    logger.debug(f"SemanticIndex deleted: {entry_id}")
                    return True
        return False

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """获取条目信息

        Returns:
            {"id", "vector", "metadata"} 或 None
        """
        with self._lock:
            for shard in self._shards:
                entry = shard.get(entry_id)
                if entry:
                    return {
                        "id": entry.id,
                        "vector": entry.vector.tolist(),
                        "metadata": entry.metadata,
                    }
        return None

    # ── 搜索操作 ──────────────────────────────────────────

    def search(self, query: Union[np.ndarray, List[float]],
               k: int = 10,
               threshold: Optional[float] = None,
               filters: Optional[Dict[str, Any]] = None,
               include_scores: bool = True) -> List[Union[str, SearchResult]]:
        """语义搜索 Top-K

        Args:
            query: 查询向量
            k: 返回结果数量
            threshold: 距离阈值 (cosine距离 ≤ threshold)
            filters: 元数据过滤条件
            include_scores: 是否返回 SearchResult (否则仅返回 ID)

        Returns:
            SearchResult 列表或 ID 列表
        """
        if isinstance(query, list):
            query = np.array(query, dtype=np.float32)

        with self._lock:
            all_results: List[SearchResult] = []

            for shard in self._shards:
                shard_results = shard.search(query, k=k, threshold=threshold, filters=filters)
                all_results.extend(shard_results)

            # 全局排序: 按 score 降序
            all_results.sort(key=lambda r: r.score, reverse=True)
            all_results = all_results[:k]

            self._stats["searches"] += 1

            if include_scores:
                return all_results
            else:
                return [r.id for r in all_results]

    def search_by_metadata(self, **filters) -> List[str]:
        """仅按元数据精确匹配查找

        Args:
            **filters: 元数据过滤条件

        Returns:
            匹配的条目 ID 列表
        """
        with self._lock:
            results = []
            for shard in self._shards:
                with shard._lock:
                    for entry_id, entry in shard._entries.items():
                        match = True
                        for fk, fv in filters.items():
                            if entry.metadata.get(fk) != fv:
                                match = False
                                break
                        if match:
                            results.append(entry_id)
            return results

    def similarity(self, id_a: str, id_b: str) -> Optional[float]:
        """计算两个已索引条目之间的相似度

        Returns:
            余弦相似度 (-1 到 1), 或 None (条目不存在)
        """
        entry_a = self.get(id_a)
        entry_b = self.get(id_b)
        if entry_a is None or entry_b is None:
            return None

        vec_a = np.array(entry_a["vector"], dtype=np.float32)
        vec_b = np.array(entry_b["vector"], dtype=np.float32)
        return DistanceMetric.cosine_similarity(vec_a, vec_b)

    # ── 近似搜索优化 ─────────────────────────────────────

    def approximate_search(self, query: Union[np.ndarray, List[float]],
                           k: int = 10,
                           sample_ratio: float = 0.3) -> List[SearchResult]:
        """近似搜索: 随机采样一部分条目计算距离

        适用于超大索引, 牺牲精度换速度

        Args:
            query: 查询向量
            k: 返回数量
            sample_ratio: 采样比例 (0-1)

        Returns:
            SearchResult 列表
        """
        if isinstance(query, list):
            query = np.array(query, dtype=np.float32)

        with self._lock:
            all_entries = []
            for shard in self._shards:
                with shard._lock:
                    all_entries.extend(shard._entries.values())

            if not all_entries:
                return []

            # 随机采样
            sample_size = max(k, int(len(all_entries) * sample_ratio))
            sample_size = min(sample_size, len(all_entries))
            indices = np.random.choice(len(all_entries), size=sample_size, replace=False)

            sampled_entries = [all_entries[i] for i in indices]
            vectors = np.stack([e.vector for e in sampled_entries], axis=0)

            # 计算相似度
            if self.metric == "cosine":
                q_norm = query / (np.linalg.norm(query) + 1e-10)
                v_norm = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10)
                scores = np.dot(v_norm, q_norm)
            elif self.metric == "euclidean":
                dists = np.linalg.norm(vectors - query, axis=1)
                scores = 1.0 / (1.0 + dists)
            else:
                scores = np.dot(vectors, query)

            # Top-K
            top_indices = np.argsort(-scores)[:k]
            results = []
            for idx in top_indices:
                entry = sampled_entries[idx]
                results.append(SearchResult(
                    id=entry.id,
                    score=float(scores[idx]),
                    metadata=dict(entry.metadata),
                ))

            self._stats["searches"] += 1
            return results

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计"""
        with self._lock:
            total_size = sum(s.size for s in self._shards)
            return {
                "dim": self.dim,
                "metric": self.metric,
                "total_size": total_size,
                "shard_count": len(self._shards),
                "shard_size_limit": self.shard_size,
                "shard_distribution": [s.size for s in self._shards],
                **self._stats,
            }

    # ── JSON 持久化 ───────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "dim": self.dim,
                "metric": self.metric,
                "shard_size": self.shard_size,
                "shards": [s.to_dict() for s in self._shards],
                "version": "1.0",
                "exported_at": time.time(),
            }

    def save(self, path: Optional[str] = None):
        """持久化到 JSON 文件

        Args:
            path: 文件路径, 默认使用初始化时的 persist_path
        """
        target = path or self.persist_path
        if not target:
            raise ValueError("No persist path specified")

        data = self.to_dict()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"SemanticIndex saved to {target} ({self.size} entries)")

    def load(self, path: Optional[str] = None):
        """从 JSON 文件加载

        Args:
            path: 文件路径, 默认使用初始化时的 persist_path
        """
        target = path or self.persist_path
        if not target:
            raise ValueError("No persist path specified")
        if not os.path.exists(target):
            raise FileNotFoundError(f"Index file not found: {target}")

        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._load_from_dict(data)

    def _load_from_dict(self, data: Dict[str, Any]):
        """从字典加载"""
        with self._lock:
            self.dim = data.get("dim", self.dim)
            self.metric = data.get("metric", self.metric)
            self.shard_size = data.get("shard_size", self.shard_size)

            self._shards = []
            for shard_data in data.get("shards", []):
                shard = IndexShard.from_dict(shard_data)
                self._shards.append(shard)

            self._stats = {"adds": self.size, "searches": 0, "deletes": 0,
                           "shards": len(self._shards)}

        logger.info(f"SemanticIndex loaded: {self.size} entries, {len(self._shards)} shards")

    def clear(self):
        """清空索引"""
        with self._lock:
            self._shards = [IndexShard(0, self.dim, self.metric)]
            self._stats = {"adds": 0, "searches": 0, "deletes": 0, "shards": 1}
        logger.info("SemanticIndex cleared")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_si_instance: Optional[SemanticIndex] = None
_si_lock = threading.Lock()


def get_semantic_index(dim: int = 1536, metric: str = "cosine",
                       shard_size: int = 10000,
                       persist_path: Optional[str] = None) -> SemanticIndex:
    """获取 SemanticIndex 全局单例 (auto-create)

    Args:
        dim: 向量维度 (仅首次创建时生效)
        metric: 距离度量 (仅首次创建时生效)
        shard_size: 分片大小 (仅首次创建时生效)
        persist_path: 持久化路径 (仅首次创建时生效)

    Returns:
        SemanticIndex 实例
    """
    global _si_instance
    if _si_instance is None:
        with _si_lock:
            if _si_instance is None:
                _si_instance = SemanticIndex(
                    dim=dim, metric=metric, shard_size=shard_size,
                    persist_path=persist_path,
                )
    return _si_instance


def reset_semantic_index():
    """重置全局实例 (用于测试)"""
    global _si_instance
    with _si_lock:
        _si_instance = None

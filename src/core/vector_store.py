"""
meshctx VectorStore — 向量存储引擎
====================================
高性能向量存储与检索，支持 numpy/faiss 双后端。

核心能力:
  1. 向量索引 — add / search / delete 基本操作
  2. 距离度量 — 余弦相似度 / L2 欧氏距离
  3. 批量索引 — 批量添加 + 自动归一化
  4. 元数据过滤 — 按 tag/source/date 过滤搜索结果
  5. 持久化 — JSON 格式存储向量 + 元数据

后端选择:
  - numpy: 纯 Python，零额外依赖，适合 <100K 向量
  - faiss: 高性能近似搜索，适合百万级向量 (可选依赖)

设计原则:
  - 零外部强制依赖: numpy 作为唯一硬依赖
  - faiss 可选: 仅在 import 成功时启用
  - 线程安全: 读写锁保护索引操作
  - 惰性持久化: 仅显式调用 save() 时写盘

API:
  add(vectors, metadata_list)       → ids
  search(query, k, metric, filters) → [(id, score, metadata)]
  delete(ids)                       → count
  save(path) / load(path)           → 持久化
  get_vector_store()                → VectorStore singleton (auto-create)
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

import numpy as np

logger = logging.getLogger("meshctx.vector_store")

# ── 可选依赖 ──────────────────────────────────────────────
try:
    import faiss  # noqa: F401
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class VectorEntry:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """向量条目"""
    id: str
    vector: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self, **kw) -> Dict:
        return {
            "id": self.id,
            "vector": self.vector.tolist(),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict, **kw) -> "VectorEntry":
        return cls(
            id=d["id"],
            vector=np.array(d["vector"], dtype=np.float32),
            metadata=d.get("metadata", {}),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


@dataclass
class SearchResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """搜索结果"""
    id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self, **kw) -> str:
        return f"SearchResult(id={self.id!r}, score={self.score:.4f})"


# ═══════════════════════════════════════════════════════════
# 距离度量
# ═══════════════════════════════════════════════════════════

class DistanceMetric:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """距离度量函数集合"""

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray, **kw) -> float:
        """余弦相似度 (归一化向量点积)"""
        # 假设向量已归一化
        return float(np.dot(a, b))

    @staticmethod
    def cosine_distance(a: np.ndarray, b: np.ndarray, **kw) -> float:
        """余弦距离 = 1 - 余弦相似度"""
        return 1.0 - DistanceMetric.cosine_similarity(a, b)

    @staticmethod
    def l2_distance(a: np.ndarray, b: np.ndarray, **kw) -> float:
        """L2 欧氏距离"""
        return float(np.linalg.norm(a - b))

    @staticmethod
    def l2_similarity(a: np.ndarray, b: np.ndarray, **kw) -> float:
        """L2 距离转为相似度分数 [0,1]"""
        d = DistanceMetric.l2_distance(a, b)
        return 1.0 / (1.0 + d)

    @staticmethod
    def dot_product(a: np.ndarray, b: np.ndarray, **kw) -> float:
        """点积 (适用于未归一化的向量)"""
        return float(np.dot(a, b))


# ═══════════════════════════════════════════════════════════
# FAISS 后端 (可选)
# ═══════════════════════════════════════════════════════════

class FaissIndex:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """FAISS 索引包装器 — 高性能近似最近邻搜索"""

    def __init__(self, dim: int, metric: str = "cosine", **kw):
        if not _FAISS_AVAILABLE:
            raise ImportError("faiss not installed. pip install faiss-cpu")
        self.dim = dim
        self.metric = metric

        if metric == "cosine":
            # IndexFlatIP 用于内积 → 配合归一化向量 = 余弦相似度
            self.index = faiss.IndexFlatIP(dim)
        elif metric == "l2":
            self.index = faiss.IndexFlatL2(dim)
        else:
            self.index = faiss.IndexFlatIP(dim)

        self._id_map: Dict[int, str] = {}       # faiss_id → entry_id
        self._reverse_map: Dict[str, int] = {}   # entry_id → faiss_id
        self._next_id: int = 0
        self._lock = threading.Lock()

    def add(self, vectors: np.ndarray, ids: List[str], **kw) -> int:
        """批量添加向量"""
        vectors = vectors.astype(np.float32)
        if self.metric == "cosine":
            # 归一化以确保内积 = 余弦相似度
            faiss.normalize_L2(vectors)

        with self._lock:
            start_idx = self.index.ntotal
            self.index.add(vectors)
            for i, eid in enumerate(ids):
                fid = start_idx + i
                self._id_map[fid] = eid
                self._reverse_map[eid] = fid
        return len(ids)

    def search(self, query: np.ndarray, k: int = 10, **kw) -> List[Tuple[str, float]]:
        """搜索最相似的 k 个向量"""
        query = query.astype(np.float32).reshape(1, -1)
        if self.metric == "cosine":
            faiss.normalize_L2(query)

        distances, indices = self.index.search(query, k)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            eid = self._id_map.get(int(idx))
            if eid:
                # 转换距离为相似度分数
                if self.metric == "cosine":
                    score = float(dist)  # 内积 = 余弦相似度 (归一化后)
                elif self.metric == "l2":
                    score = 1.0 / (1.0 + float(dist))
                else:
                    score = float(dist)
                results.append((eid, score))
        return results

    def remove(self, ids: List[str], **kw) -> int:
        """从索引中移除向量 (FAISS 不支持直接删除，重建索引)"""
        # FAISS IndexFlat 不支持删除，需要重建
        # 对于小规模使用，直接标记 + 搜索时过滤
        removed = 0
        with self._lock:
            for eid in ids:
                if eid in self._reverse_map:
                    del self._reverse_map[eid]
                    removed += 1
        return removed

    @property
    def size(self, **kw) -> int:
        return self.index.ntotal


# ═══════════════════════════════════════════════════════════
# NumPy 后端 (默认)
# ═══════════════════════════════════════════════════════════

class NumpyIndex:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """NumPy 向量索引 — 纯 Python 精确搜索"""

    def __init__(self, dim: int, metric: str = "cosine", **kw):
        self.dim = dim
        self.metric = metric
        self._entries: Dict[str, VectorEntry] = {}
        self._matrix: Optional[np.ndarray] = None  # [n, dim]
        self._id_list: List[str] = []               # 映射 row_index → entry_id
        self._lock = threading.RLock()
        self._dirty: bool = False

    def _rebuild_matrix(self, **kw):
        """重建矩阵 (惰性)"""
        if not self._dirty:
            return
        n = len(self._entries)
        if n == 0:
            self._matrix = None
            self._id_list = []
        else:
            self._matrix = np.zeros((n, self.dim), dtype=np.float32)
            self._id_list = []
            for i, (eid, entry) in enumerate(self._entries.items()):
                self._matrix[i] = entry.vector
                self._id_list.append(eid)
        self._dirty = False

    def _normalize(self, vec: np.ndarray, **kw) -> np.ndarray:
        """L2 归一化"""
        norm = np.linalg.norm(vec)
        if norm > 0:
            return vec / norm
        return vec

    def add(self, vectors: Union[np.ndarray, List[np.ndarray]],
            ids: List[str], metadatas: Optional[List[Dict]] = None) -> int:
        """添加向量"""
        vectors_arr = np.asarray(vectors, dtype=np.float32)
        if vectors_arr.ndim == 1:
            vectors_arr = vectors_arr.reshape(1, -1)

        if metadatas is None:
            metadatas = [{}] * len(ids)

        with self._lock:
            for i, eid in enumerate(ids):
                vec = vectors_arr[i].copy()
                if self.metric == "cosine":
                    vec = self._normalize(vec)
                self._entries[eid] = VectorEntry(
                    id=eid, vector=vec,
                    metadata=metadatas[i] if i < len(metadatas) else {},
                )
            self._dirty = True
        return len(ids)

    def search(self, query: np.ndarray, k: int = 10,
               metric: Optional[str] = None,
               filters: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """搜索最近邻"""
        query = np.asarray(query, dtype=np.float32).flatten()

        metric_fn_name = metric or self.metric
        if metric_fn_name == "cosine":
            query = self._normalize(query)
            sim_fn = DistanceMetric.cosine_similarity
        elif metric_fn_name == "l2":
            sim_fn = lambda a, b: 1.0 / (1.0 + DistanceMetric.l2_distance(a, b))
        else:
            sim_fn = DistanceMetric.cosine_similarity

        with self._lock:
            self._rebuild_matrix()
            if self._matrix is None or len(self._entries) == 0:
                return []

            # 批量计算相似度
            if metric_fn_name == "cosine":
                scores = np.dot(self._matrix, query)  # [n]
            elif metric_fn_name == "l2":
                diffs = self._matrix - query
                scores = 1.0 / (1.0 + np.linalg.norm(diffs, axis=1))
            else:
                scores = np.dot(self._matrix, query)

            # 排序 + 过滤
            results = []
            sorted_indices = np.argsort(-scores)  # 降序
            for idx in sorted_indices:
                if len(results) >= k:
                    break
                eid = self._id_list[idx]
                entry = self._entries.get(eid)
                if entry is None:
                    continue
                # 元数据过滤
                if filters and not self._match_filters(entry.metadata, filters):
                    continue
                results.append(SearchResult(
                    id=eid,
                    score=float(scores[idx]),
                    metadata=entry.metadata.copy(),
                ))
        return results

    def _match_filters(self, metadata: Dict, filters: Dict, **kw) -> bool:
        """检查元数据是否匹配过滤条件"""
        for key, value in filters.items():
            if key not in metadata:
                return False
            mv = metadata[key]
            if isinstance(value, (list, set, tuple)):
                if mv not in value:
                    return False
            elif isinstance(value, dict):
                # 范围过滤: {"$gte": 0.5, "$lte": 0.9}
                for op, op_val in value.items():
                    if op == "$eq" and mv != op_val:
                        return False
                    elif op == "$ne" and mv == op_val:
                        return False
                    elif op == "$gt" and (not isinstance(mv, (int, float)) or mv <= op_val):
                        return False
                    elif op == "$gte" and (not isinstance(mv, (int, float)) or mv < op_val):
                        return False
                    elif op == "$lt" and (not isinstance(mv, (int, float)) or mv >= op_val):
                        return False
                    elif op == "$lte" and (not isinstance(mv, (int, float)) or mv > op_val):
                        return False
                    elif op == "$in" and mv not in op_val:
                        return False
                    elif op == "$contains" and op_val not in str(mv):
                        return False
            else:
                if mv != value:
                    return False
        return True

    def remove(self, ids: List[str], **kw) -> int:
        """删除向量"""
        removed = 0
        with self._lock:
            for eid in ids:
                if eid in self._entries:
                    del self._entries[eid]
                    removed += 1
            if removed > 0:
                self._dirty = True
        return removed

    def get(self, eid: str, **kw) -> Optional[VectorEntry]:
        """获取单个向量条目"""
        return self._entries.get(eid)

    @property
    def size(self, **kw) -> int:
        return len(self._entries)

    @property
    def ids(self, **kw) -> List[str]:
        with self._lock:
            return list(self._entries.keys())


# ═══════════════════════════════════════════════════════════
# VectorStore 主类
# ═══════════════════════════════════════════════════════════

class VectorStore:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """向量存储引擎

    支持 numpy (默认) 和 faiss (可选) 后端。
    自动选择最优后端: FAISS 可用时使用 FAISS, 否则回退到 NumPy。
    """

    def __init__(self, dim: int = 1536, metric: str = "cosine",
                 backend: str = "auto", persist_path: Optional[str] = None):
        """
        Args:
            dim: 向量维度 (1536=text-embedding-ada-002, 768=常见开源模型)
            metric: 距离度量 ("cosine" / "l2")
            backend: 后端选择 ("auto" / "numpy" / "faiss")
            persist_path: 持久化文件路径
        """
        self.dim = dim
        self.metric = metric
        self.persist_path = persist_path

        # 选择后端
        if backend == "faiss" and _FAISS_AVAILABLE:
            self._backend_type = "faiss"
            self._faiss_index = FaissIndex(dim, metric)
            self._numpy_index: Optional[NumpyIndex] = None
        elif backend == "numpy" or not _FAISS_AVAILABLE:
            self._backend_type = "numpy"
            self._faiss_index = None
            self._numpy_index = NumpyIndex(dim, metric)
        else:  # auto
            if _FAISS_AVAILABLE:
                self._backend_type = "faiss"
                self._faiss_index = FaissIndex(dim, metric)
                self._numpy_index = None
            else:
                self._backend_type = "numpy"
                self._faiss_index = None
                self._numpy_index = NumpyIndex(dim, metric)

        # 元数据存储 (FAISS 模式下仍用 numpy 索引存元数据)
        if self._backend_type == "faiss":
            self._numpy_index = NumpyIndex(dim, metric)

        self._lock = threading.RLock()
        self._stats = {"adds": 0, "searches": 0, "deletes": 0}

        logger.info(f"VectorStore initialized: dim={dim}, metric={metric}, "
                    f"backend={self._backend_type}, faiss_available={_FAISS_AVAILABLE}")

    # ── 核心操作 ────────────────────────────────────────

    def add(self, vectors: Union[np.ndarray, List[List[float]]],
            ids: Optional[List[str]] = None,
            metadatas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        """添加向量到索引

        Args:
            vectors: 向量数组 [n, dim] 或 List[List[float]]
            ids: 可选的 ID 列表，不提供则自动生成 UUID
            metadatas: 可选的元数据列表

        Returns:
            添加的向量 ID 列表
        """
        vectors_arr = np.asarray(vectors, dtype=np.float32)
        if vectors_arr.ndim == 1:
            vectors_arr = vectors_arr.reshape(1, -1)

        n = vectors_arr.shape[0]

        # 自动生成 ID
        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in range(n)]
        else:
            ids = list(ids)

        if metadatas is None:
            metadatas = [{} for _ in range(n)]

        with self._lock:
            if self._backend_type == "faiss":
                # FAISS 索引
                self._faiss_index.add(vectors_arr, ids)
                # NumPy 索引用作元数据存储
                self._numpy_index.add(vectors_arr, ids, metadatas)
            else:
                self._numpy_index.add(vectors_arr, ids, metadatas)

            self._stats["adds"] += n

        logger.debug(f"Added {n} vectors, total size={self.size}")
        return ids

    def search(self, query: Union[np.ndarray, List[float]], k: int = 10,
               metric: Optional[str] = None,
               filters: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """搜索最相似的 k 个向量

        Args:
            query: 查询向量 [dim]
            k: 返回结果数量
            metric: 距离度量 (覆盖默认)
            filters: 元数据过滤条件

        Returns:
            SearchResult 列表，按相似度降序排列
        """
        query_arr = np.asarray(query, dtype=np.float32).flatten()
        if query_arr.shape[0] != self.dim:
            raise ValueError(f"Query dim {query_arr.shape[0]} != index dim {self.dim}")

        with self._lock:
            self._stats["searches"] += 1

            if self._backend_type == "faiss":
                # FAISS 快速搜索
                raw_results = self._faiss_index.search(query_arr, k=k * 2)  # 多取一些用于过滤
                results = []
                metric_fn_name = metric or self.metric
                for eid, score in raw_results:
                    if len(results) >= k:
                        break
                    entry = self._numpy_index.get(eid)
                    if entry is None:
                        continue
                    if filters and not self._numpy_index._match_filters(entry.metadata, filters):
                        continue
                    results.append(SearchResult(id=eid, score=score, metadata=entry.metadata.copy()))
                return results
            else:
                return self._numpy_index.search(query_arr, k=k, metric=metric, filters=filters)

    def delete(self, ids: Union[str, List[str]], **kw) -> int:
        """删除向量

        Args:
            ids: 要删除的向量 ID 或 ID 列表

        Returns:
            实际删除的数量
        """
        if isinstance(ids, str):
            ids = [ids]

        with self._lock:
            count = 0
            if self._backend_type == "faiss":
                count = self._faiss_index.remove(ids)
            count += self._numpy_index.remove(ids)
            self._stats["deletes"] += count

        logger.debug(f"Deleted {count} vectors")
        return count

    def get(self, eid: str, **kw) -> Optional[VectorEntry]:
        """获取向量条目"""
        if self._numpy_index:
            return self._numpy_index.get(eid)
        return None

    def get_batch(self, ids: List[str], **kw) -> Dict[str, Optional[VectorEntry]]:
        """批量获取向量条目"""
        result = {}
        for eid in ids:
            result[eid] = self.get(eid)
        return result

    # ── 批量操作 ────────────────────────────────────────

    def index_documents(self, documents: List[Dict[str, Any]],
                        embedding_fn: Callable[[str], np.ndarray],
                        text_key: str = "text",
                        id_key: Optional[str] = None,
                        batch_size: int = 100) -> List[str]:
        """批量索引文档

        Args:
            documents: 文档列表 [{"text": "...", "metadata": {...}}, ...]
            embedding_fn: 文本 → 向量 的嵌入函数
            text_key: 文档中文本字段的 key
            id_key: 文档中 ID 字段的 key
            batch_size: 批处理大小

        Returns:
            所有添加的 ID 列表
        """
        all_ids = []
        total = len(documents)

        for i in range(0, total, batch_size):
            batch = documents[i:i + batch_size]
            texts = [doc[text_key] for doc in batch]
            ids = [doc.get(id_key) if id_key else None for doc in batch]
            ids = [eid or f"doc_{i + j}" for j, eid in enumerate(ids)]

            # 批量计算嵌入
            vectors = []
            for text in texts:
                vec = embedding_fn(text)
                if isinstance(vec, list):
                    vec = np.array(vec, dtype=np.float32)
                vectors.append(vec)

            vectors_arr = np.stack(vectors) if vectors else np.zeros((0, self.dim), dtype=np.float32)
            metadatas = [doc.get("metadata", {}) for doc in batch]

            batch_ids = self.add(vectors_arr, ids=ids, metadatas=metadatas)
            all_ids.extend(batch_ids)

            logger.info(f"Indexed batch {i // batch_size + 1}: "
                        f"docs {i}-{min(i + batch_size, total)}/{total}")

        return all_ids

    # ── 持久化 ──────────────────────────────────────────

    def save(self, path: Optional[str] = None, **kw) -> str:
        """持久化到 JSON 文件

        Args:
            path: 保存路径，默认使用初始化时的 persist_path

        Returns:
            保存的文件路径
        """
        save_path = path or self.persist_path
        if not save_path:
            raise ValueError("No persist_path specified")

        save_path = os.path.expanduser(save_path)
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        with self._lock:
            data = {
                "dim": self.dim,
                "metric": self.metric,
                "backend": self._backend_type,
                "size": self.size,
                "stats": self._stats,
                "entries": {},
            }
            if self._numpy_index:
                for eid, entry in self._numpy_index._entries.items():
                    data["entries"][eid] = entry.to_dict()

            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {self.size} vectors to {save_path}")
        return save_path

    def load(self, path: Optional[str] = None, **kw) -> int:
        """从 JSON 文件加载

        Args:
            path: 加载路径

        Returns:
            加载的向量数量
        """
        load_path = path or self.persist_path
        if not load_path:
            raise ValueError("No persist_path specified")

        load_path = os.path.expanduser(load_path)
        if not os.path.exists(load_path):
            logger.warning(f"Persist file not found: {load_path}")
            return 0

        with open(load_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        loaded_dim = data.get("dim", self.dim)
        if loaded_dim != self.dim:
            logger.warning(f"Dimension mismatch: stored={loaded_dim}, current={self.dim}")
            self.dim = loaded_dim
            # 重建后端
            self.__init__(dim=loaded_dim, metric=self.metric, backend=self._backend_type)

        entries = data.get("entries", {})
        vectors_list = []
        ids_list = []
        metadatas_list = []

        for eid, entry_dict in entries.items():
            entry = VectorEntry.from_dict(entry_dict)
            vectors_list.append(entry.vector)
            ids_list.append(entry.id)
            metadatas_list.append(entry.metadata)

        if vectors_list:
            vectors_arr = np.stack(vectors_list)
            self.add(vectors_arr, ids=ids_list, metadatas=metadatas_list)

        logger.info(f"Loaded {len(entries)} vectors from {load_path}")
        return len(entries)

    # ── 信息 ────────────────────────────────────────────

    @property
    def size(self, **kw) -> int:
        if self._backend_type == "faiss":
            return self._numpy_index.size if self._numpy_index else 0
        return self._numpy_index.size if self._numpy_index else 0

    @property
    def ids(self, **kw) -> List[str]:
        if self._numpy_index:
            return self._numpy_index.ids
        return []

    def stats(self, **kw) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "dim": self.dim,
            "metric": self.metric,
            "backend": self._backend_type,
            "faiss_available": _FAISS_AVAILABLE,
            "size": self.size,
            **self._stats,
        }

    def clear(self, **kw):
        """清空索引"""
        with self._lock:
            if self._numpy_index:
                self._numpy_index._entries.clear()
                self._numpy_index._dirty = True
            if self._faiss_index:
                self._faiss_index = FaissIndex(self.dim, self.metric)
            self._stats = {"adds": 0, "searches": 0, "deletes": 0}
        logger.info("VectorStore cleared")


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_store: Optional[VectorStore] = None
_store_lock = threading.Lock()


def get_vector_store(dim: int = 1536, metric: str = "cosine",
                     backend: str = "auto",
                     persist_path: Optional[str] = None) -> VectorStore:
    """获取 VectorStore 全局单例 (auto-create)

    Args:
        dim: 向量维度 (仅首次创建时生效)
        metric: 距离度量 (仅首次创建时生效)
        backend: 后端选择 (仅首次创建时生效)
        persist_path: 持久化路径 (仅首次创建时生效)

    Returns:
        VectorStore 实例
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = VectorStore(dim=dim, metric=metric,
                                     backend=backend, persist_path=persist_path)
            else:
                # 已由其他线程创建，检查维度
                if _store.dim != dim:
                    logger.warning(f"VectorStore already exists with dim={_store.dim}, "
                                   f"requested dim={dim} ignored")
    return _store


def reset_vector_store():
    """重置全局实例 (用于测试)"""
    global _store
    with _store_lock:
        _store = None

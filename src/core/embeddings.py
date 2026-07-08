"""
meshctx Embeddings — 多层嵌入引擎
==================================
多层 embedding 架构，支持 OpenAI / 本地 / 缓存三个层级。

核心能力:
  1. OpenAI 嵌入 — 通过 API 调用 text-embedding-ada-002 / text-embedding-3-small/large
  2. 本地嵌入 — 基于 sentence-transformers 的离线嵌入 (可选)
  3. 缓存层 — LRU + 持久化缓存，最大化缓存命中率
  4. 批处理 — 批量文本嵌入 + 并发控制
  5. 维度配置 — 768 (开源) / 1536 (OpenAI) / 3072 (large)
  6. Model Fallback — OpenAI 不可用时回退到本地模型

缓存策略:
  - L1: 内存 LRU 缓存 (快速命中)
  - L2: 磁盘持久化缓存 (跨进程复用)
  - Key: SHA256(text) → vector

设计原则:
  - 渐进增强: 无外部依赖时仍可工作 (通过 Mock 模式)
  - 零强制依赖: openai 和 sentence-transformers 都是可选
  - 线程安全: 缓存操作加锁
  - 批处理优先: 自动合并短请求为批量调用

API:
  embed(text) / embed_batch(texts)        → np.ndarray / List[np.ndarray]
  get_embeddings()                        → Embeddings singleton (auto-create)
"""

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("meshctx.embeddings")

# ── 可选依赖 ──────────────────────────────────────────────
try:
    import openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

# OpenAI 模型 → 维度映射
OPENAI_MODEL_DIMS = {
    "text-embedding-ada-002": 1536,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

# 本地模型 → 维度映射 (常见)
LOCAL_MODEL_DIMS = {
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "multi-qa-mpnet-base-dot-v1": 768,
    "e5-large-v2": 1024,
    "bge-large-en-v1.5": 1024,
}

DEFAULT_OPENAI_MODEL = "text-embedding-ada-002"
DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"
DEFAULT_DIM = 1536


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class EmbedResult:
    """嵌入结果"""
    text: str
    vector: np.ndarray
    model: str
    cached: bool = False
    latency_ms: float = 0.0
    tokens: int = 0

    @property
    def dim(self, **kw) -> int:
        return len(self.vector)


@dataclass
class EmbedStats:
    """嵌入统计"""
    total_requests: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    local_calls: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def cache_hit_rate(self, **kw) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests

    @property
    def avg_latency_ms(self, **kw) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests


# ═══════════════════════════════════════════════════════════
# 缓存层
# ═══════════════════════════════════════════════════════════

class EmbeddingCache:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """两层嵌入缓存: L1 内存 LRU + L2 磁盘持久化"""

    def __init__(self, max_memory_entries: int = 10000,
                 disk_cache_path: Optional[str] = None):
        self._max_memory = max_memory_entries
        self._disk_path = disk_cache_path
        self._lock = threading.RLock()
        self._memory: OrderedDict[str, np.ndarray] = OrderedDict()
        self._disk_cache: Dict[str, np.ndarray] = {}
        self._disk_dirty: bool = False

        if disk_cache_path:
            self._load_disk_cache()

    def _make_key(self, text: str, **kw) -> str:
        """生成缓存 key: SHA256(text)"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str, **kw) -> Optional[np.ndarray]:
        """获取缓存的向量"""
        key = self._make_key(text)
        with self._lock:
            # L1: 内存缓存
            if key in self._memory:
                # 移到 LRU 末尾
                self._memory.move_to_end(key)
                return self._memory[key].copy()

            # L2: 磁盘缓存
            if key in self._disk_cache:
                vec = self._disk_cache[key].copy()
                # 提升到 L1
                self._set_memory(key, vec)
                return vec

        return None

    def set(self, text: str, vector: np.ndarray, **kw):
        """缓存向量"""
        key = self._make_key(text)
        vec_copy = vector.astype(np.float32).copy()
        with self._lock:
            self._set_memory(key, vec_copy)
            self._set_disk(key, vec_copy)

    def _set_memory(self, key: str, vec: np.ndarray, **kw):
        """写入 L1 内存缓存"""
        self._memory[key] = vec
        self._memory.move_to_end(key)
        # LRU 淘汰
        while len(self._memory) > self._max_memory:
            self._memory.popitem(last=False)

    def _set_disk(self, key: str, vec: np.ndarray, **kw):
        """写入 L2 磁盘缓存"""
        self._disk_cache[key] = vec
        self._disk_dirty = True

    def _load_disk_cache(self, **kw):
        """从磁盘加载缓存"""
        if not self._disk_path or not os.path.exists(self._disk_path):
            return

        try:
            with open(self._disk_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            loaded = 0
            for key, vec_list in data.items():
                self._disk_cache[key] = np.array(vec_list, dtype=np.float32)
                loaded += 1

            logger.info(f"Loaded {loaded} entries from disk cache: {self._disk_path}")
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load disk cache: {e}")

    def save_disk_cache(self, **kw):
        """保存磁盘缓存"""
        if not self._disk_path:
            return

        with self._lock:
            if not self._disk_dirty:
                return
            os.makedirs(os.path.dirname(self._disk_path) or ".", exist_ok=True)
            data = {}
            for key, vec in self._disk_cache.items():
                data[key] = vec.tolist()

            with open(self._disk_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            self._disk_dirty = False

        logger.debug(f"Saved {len(self._disk_cache)} entries to disk cache")

    def clear(self, **kw):
        """清空所有缓存"""
        with self._lock:
            self._memory.clear()
            self._disk_cache.clear()
            self._disk_dirty = True

    def size(self, **kw) -> Dict[str, int]:
        """缓存大小"""
        with self._lock:
            return {
                "memory": len(self._memory),
                "disk": len(self._disk_cache),
            }


# ═══════════════════════════════════════════════════════════
# OpenAI 嵌入提供者
# ═══════════════════════════════════════════════════════════

class OpenAIEmbedder:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """OpenAI 嵌入 API 提供者"""

    def __init__(self, model: str = DEFAULT_OPENAI_MODEL,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 max_retries: int = 3):
        if not _OPENAI_AVAILABLE:
            raise ImportError("openai package not installed. pip install openai")

        self.model = model
        self.dim = OPENAI_MODEL_DIMS.get(model, DEFAULT_DIM)

        client_kwargs = {"max_retries": max_retries}
        if api_key:
            client_kwargs["api_key"] = api_key
        elif "OPENAI_API_KEY" in os.environ:
            client_kwargs["api_key"] = os.environ["OPENAI_API_KEY"]
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = openai.OpenAI(**client_kwargs)
        logger.info(f"OpenAI embedder initialized: model={model}, dim={self.dim}")

    def embed(self, text: str, **kw) -> np.ndarray:
        """嵌入单个文本"""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str], **kw) -> List[np.ndarray]:
        """批量嵌入文本 (最多 2048 条/次)"""
        # OpenAI 限制: 每批最多 2048 个文本
        all_vectors = []
        batch_size = 2048

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            vectors = [
                np.array(item.embedding, dtype=np.float32)
                for item in resp.data
            ]
            all_vectors.extend(vectors)

        return all_vectors


# ═══════════════════════════════════════════════════════════
# 本地嵌入提供者
# ═══════════════════════════════════════════════════════════

class LocalEmbedder:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """本地 sentence-transformers 嵌入提供者"""

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL,
                 device: str = "cpu"):
        if not _ST_AVAILABLE:
            raise ImportError("sentence-transformers not installed. "
                              "pip install sentence-transformers")

        self.model_name = model_name
        self.device = device
        self._model: Optional[SentenceTransformer] = None
        self.dim = LOCAL_MODEL_DIMS.get(model_name, 768)
        self._lock = threading.Lock()

        logger.info(f"Local embedder configured: model={model_name}, "
                    f"dim={self.dim}, device={device}")

    @property
    def model(self, **kw) -> SentenceTransformer:
        """惰性加载模型"""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info(f"Loading local model: {self.model_name}...")
                    self._model = SentenceTransformer(
                        self.model_name, device=self.device,
                    )
                    # 更新实际维度
                    test_vec = self._model.encode("test", convert_to_numpy=True)
                    self.dim = len(test_vec)
                    logger.info(f"Local model loaded: dim={self.dim}")
        return self._model

    def embed(self, text: str, **kw) -> np.ndarray:
        return self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True)

    def embed_batch(self, texts: List[str], batch_size: int = 32, **kw) -> List[np.ndarray]:
        vectors = self.model.encode(
            texts, convert_to_numpy=True, normalize_embeddings=True,
            batch_size=batch_size, show_progress_bar=False,
        )
        return [v for v in vectors]


# ═══════════════════════════════════════════════════════════
# 模拟嵌入提供者 (零依赖 Fallback)
# ═══════════════════════════════════════════════════════════

class MockEmbedder:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """模拟嵌入 — 零依赖确定性嵌入 (开发/测试用)

    使用字符级哈希生成固定维度向量。
    不是语义嵌入，仅用于测试管道。
    """

    def __init__(self, dim: int = 768, **kw):
        self.dim = dim
        logger.warning("Using MockEmbedder — NOT for production use. "
                       f"dim={dim}")

    def embed(self, text: str, **kw) -> np.ndarray:
        """确定性模拟嵌入"""
        if not text:
            return np.zeros(self.dim, dtype=np.float32)

        vec = np.zeros(self.dim, dtype=np.float32)
        for i, ch in enumerate(text):
            idx = (ord(ch) * (i + 1)) % self.dim
            vec[idx] += 1.0

        # 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec

    def embed_batch(self, texts: List[str], **kw) -> List[np.ndarray]:
        return [self.embed(t) for t in texts]


# ═══════════════════════════════════════════════════════════
# Embeddings 主类
# ═══════════════════════════════════════════════════════════

class Embeddings:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """多层嵌入引擎

    架构:
      API 层 (OpenAI) → Fallback 层 (本地) → Mock 层 (开发)
      ↓
      缓存层 (L1 内存 + L2 磁盘)

    自动选择最优提供者:
      1. OpenAI (如果 API key 可用)
      2. 本地 sentence-transformers (如果已安装)
      3. Mock (零依赖回退)
    """

    def __init__(self,
                 provider: str = "auto",
                 model: Optional[str] = None,
                 dim: int = DEFAULT_DIM,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 local_model: Optional[str] = None,
                 cache_size: int = 10000,
                 disk_cache_path: Optional[str] = None,
                 max_workers: int = 10):
        """
        Args:
            provider: 提供者选择 ("auto" / "openai" / "local" / "mock")
            model: OpenAI 模型名
            dim: 目标维度
            api_key: OpenAI API key
            base_url: OpenAI base URL (用于代理/兼容服务)
            local_model: 本地模型名
            cache_size: 内存缓存最大条目数
            disk_cache_path: 磁盘缓存路径
            max_workers: 并发批处理线程数
        """
        self.dim = dim
        self.max_workers = max_workers
        self._stats = EmbedStats()
        self._lock = threading.RLock()

        # 初始化缓存
        self.cache = EmbeddingCache(
            max_memory_entries=cache_size,
            disk_cache_path=disk_cache_path,
        )

        # 解析提供者
        self.provider_type, self._embedder = self._resolve_provider(
            provider, model, api_key, base_url, local_model, dim,
        )

        logger.info(f"Embeddings initialized: provider={self.provider_type}, "
                    f"dim={self.dim}, cache_size={cache_size}")

    def _resolve_provider(self, provider: str, model: Optional[str],
                          api_key: Optional[str], base_url: Optional[str],
                          local_model: Optional[str], dim: int):
        """解析嵌入提供者"""
        # 显式指定
        if provider == "openai":
            if not _OPENAI_AVAILABLE:
                raise ImportError("openai package required. pip install openai")
            embedder = OpenAIEmbedder(
                model=model or DEFAULT_OPENAI_MODEL,
                api_key=api_key,
                base_url=base_url,
            )
            return ("openai", embedder)

        if provider == "local":
            if not _ST_AVAILABLE:
                raise ImportError("sentence-transformers required. "
                                  "pip install sentence-transformers")
            embedder = LocalEmbedder(
                model_name=local_model or DEFAULT_LOCAL_MODEL,
            )
            return ("local", embedder)

        if provider == "mock":
            embedder = MockEmbedder(dim=dim)
            return ("mock", embedder)

        # auto 模式: 优先级 OpenAI > 本地 > Mock
        if _OPENAI_AVAILABLE and (api_key or os.environ.get("OPENAI_API_KEY")):
            try:
                embedder = OpenAIEmbedder(
                    model=model or DEFAULT_OPENAI_MODEL,
                    api_key=api_key, base_url=base_url,
                )
                return ("openai", embedder)
            except Exception as e:
                logger.warning(f"OpenAI init failed: {e}, trying local...")
        elif _OPENAI_AVAILABLE:
            logger.info("OpenAI available but no API key found, "
                        "checking local fallback...")

        if _ST_AVAILABLE:
            try:
                embedder = LocalEmbedder(
                    model_name=local_model or DEFAULT_LOCAL_MODEL,
                )
                return ("local", embedder)
            except Exception as e:
                logger.warning(f"Local model init failed: {e}, using mock...")

        logger.warning("No embedding provider available, using mock embedder")
        embedder = MockEmbedder(dim=dim)
        return ("mock", embedder)

    # ── 核心 API ────────────────────────────────────────

    def embed(self, text: str, use_cache: bool = True, **kw) -> EmbedResult:
        """嵌入单个文本

        Args:
            text: 要嵌入的文本
            use_cache: 是否使用缓存

        Returns:
            EmbedResult 包含向量和元数据
        """
        start_time = time.time()

        # 检查缓存
        if use_cache:
            cached_vec = self.cache.get(text)
            if cached_vec is not None:
                with self._lock:
                    self._stats.total_requests += 1
                    self._stats.cache_hits += 1
                latency = (time.time() - start_time) * 1000
                return EmbedResult(
                    text=text, vector=cached_vec,
                    model=self._get_model_name(),
                    cached=True, latency_ms=latency,
                )

        # 调用嵌入
        vector = self._embedder.embed(text)
        latency = (time.time() - start_time) * 1000

        # 更新缓存
        if use_cache:
            self.cache.set(text, vector)

        # 统计
        with self._lock:
            self._stats.total_requests += 1
            self._stats.api_calls += 1 if self.provider_type == "openai" else 0
            self._stats.local_calls += 1 if self.provider_type == "local" else 0
            self._stats.total_latency_ms += latency

        return EmbedResult(
            text=text, vector=vector,
            model=self._get_model_name(),
            cached=False, latency_ms=latency,
        )

    def embed_batch(self, texts: List[str], use_cache: bool = True,
                    batch_size: int = 32, concurrent: bool = True) -> List[EmbedResult]:
        """批量嵌入文本

        Args:
            texts: 要嵌入的文本列表
            use_cache: 是否使用缓存
            batch_size: 每批数量
            concurrent: 是否使用并发

        Returns:
            EmbedResult 列表
        """
        if not texts:
            return []

        total_start = time.time()

        # 分离缓存命中和未命中
        cache_hit_results = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            if use_cache:
                cached_vec = self.cache.get(text)
                if cached_vec is not None:
                    cache_hit_results.append((i, EmbedResult(
                        text=text, vector=cached_vec,
                        model=self._get_model_name(),
                        cached=True, latency_ms=0,
                    )))
                    continue
            uncached_texts.append(text)
            uncached_indices.append(i)

        # 批量嵌入未命中文本
        uncached_results = []
        if uncached_texts:
            if concurrent and len(uncached_texts) > batch_size:
                uncached_results = self._embed_concurrent(
                    uncached_texts, batch_size,
                )
            else:
                uncached_results = self._embed_sequential(
                    uncached_texts, batch_size,
                )

            # 写入缓存
            if use_cache:
                for result in uncached_results:
                    self.cache.set(result.text, result.vector)

        # 合并结果
        all_results = [None] * len(texts)
        for idx, result in cache_hit_results:
            all_results[idx] = result
        for idx, result in zip(uncached_indices, uncached_results):
            all_results[idx] = result

        # 统计
        with self._lock:
            self._stats.total_requests += len(texts)
            self._stats.cache_hits += len(cache_hit_results)
            self._stats.api_calls += (
                len(uncached_texts) if self.provider_type == "openai" else 0
            )
            self._stats.local_calls += (
                len(uncached_texts) if self.provider_type == "local" else 0
            )
            total_latency = (time.time() - total_start) * 1000
            self._stats.total_latency_ms += total_latency

        return all_results

    def _embed_sequential(self, texts: List[str],
                          batch_size: int) -> List[EmbedResult]:
        """顺序批处理嵌入"""
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            t0 = time.time()
            vectors = self._embedder.embed_batch(batch)
            latency = (time.time() - t0) * 1000 / len(batch)
            for text, vec in zip(batch, vectors):
                results.append(EmbedResult(
                    text=text, vector=vec,
                    model=self._get_model_name(),
                    cached=False, latency_ms=latency,
                ))
        return results

    def _embed_concurrent(self, texts: List[str],
                          batch_size: int) -> List[EmbedResult]:
        """并发批处理嵌入"""
        batches = []
        for i in range(0, len(texts), batch_size):
            batches.append(texts[i:i + batch_size])

        results = [None] * len(texts)

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(batches))) as executor:
            futures = {}
            for bi, batch in enumerate(batches):
                future = executor.submit(self._embed_single_batch, batch, bi)
                futures[future] = bi

            for future in as_completed(futures):
                bi = futures[future]
                batch_results, start_idx = future.result()
                for j, result in enumerate(batch_results):
                    results[start_idx + j] = result

        return results

    def _embed_single_batch(self, batch: List[str],
                            batch_idx: int) -> Tuple[List[EmbedResult], int]:
        """嵌入单个批次 (线程安全)"""
        t0 = time.time()
        vectors = self._embedder.embed_batch(batch)
        latency = (time.time() - t0) * 1000 / len(batch)
        results = [
            EmbedResult(
                text=text, vector=vec,
                model=self._get_model_name(),
                cached=False, latency_ms=latency,
            )
            for text, vec in zip(batch, vectors)
        ]
        return results, batch_idx * len(batch)  # start_idx 由外层计算

    # ── 信息 ────────────────────────────────────────────

    def _get_model_name(self, **kw) -> str:
        """获取当前模型名"""
        if hasattr(self._embedder, "model"):
            return getattr(self._embedder, "model", "unknown")
        if hasattr(self._embedder, "model_name"):
            return self._embedder.model_name
        return "mock"

    def stats(self, **kw) -> EmbedStats:
        """获取统计信息"""
        with self._lock:
            return self._stats

    def cache_stats(self, **kw) -> Dict[str, Any]:
        """获取缓存统计"""
        sizes = self.cache.size()
        hit_rate = self._stats.cache_hit_rate
        return {
            "memory_entries": sizes["memory"],
            "disk_entries": sizes["disk"],
            "hit_rate": round(hit_rate, 4),
            "total_requests": self._stats.total_requests,
        }

    def save_cache(self, **kw):
        """持久化磁盘缓存"""
        self.cache.save_disk_cache()

    def clear_cache(self, **kw):
        """清空所有缓存"""
        self.cache.clear()
        with self._lock:
            self._stats = EmbedStats()

    @property
    def dim(self, **kw):
        return self._dim

    @dim.setter
    def dim(self, value: int, **kw):
        self._dim = value


# ═══════════════════════════════════════════════════════════
# 嵌入工具函数
# ═══════════════════════════════════════════════════════════

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """两个向量的余弦相似度"""
    a_norm = a / (np.linalg.norm(a) + 1e-10)
    b_norm = b / (np.linalg.norm(b) + 1e-10)
    return float(np.dot(a_norm, b_norm))


def batch_cosine_similarity(query: np.ndarray,
                            matrix: np.ndarray) -> np.ndarray:
    """查询向量与矩阵中所有向量的余弦相似度"""
    query_norm = query / (np.linalg.norm(query) + 1e-10)
    matrix_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return np.dot(matrix_norm, query_norm)


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_embeddings: Optional[Embeddings] = None
_embeddings_lock = threading.Lock()


def get_embeddings(provider: str = "auto",
                   dim: int = DEFAULT_DIM,
                   **kwargs) -> Embeddings:
    """获取 Embeddings 全局单例 (auto-create)

    Args:
        provider: 提供者选择 ("auto" / "openai" / "local" / "mock")
        dim: 目标维度
        **kwargs: 传递给 Embeddings() 的其他参数

    Returns:
        Embeddings 实例
    """
    global _embeddings
    if _embeddings is None:
        with _embeddings_lock:
            if _embeddings is None:
                _embeddings = Embeddings(provider=provider, dim=dim, **kwargs)
    return _embeddings


def reset_embeddings():
    """重置全局实例 (用于测试)"""
    global _embeddings
    with _embeddings_lock:
        _embeddings = None

"""
meshctx v1.0 层次记忆系统

L0: 感知记忆 (当前对话流)
L1: 工作记忆 (当前任务上下文, ~10K tokens)
L2: 短时记忆 (近7天, ~100K tokens, Ebbinghaus衰减)
L3: 长时记忆 (全部历史, 向量+图混合检索)
L4: 归档记忆 (跨项目通用知识, 自动去重+合并)

检索策略: Hybrid(向量 + 图谱 + 时间衰减)
"""
import asyncio
import hashlib
import json
import math
import os
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .kernel import Event, EventPriority, Plugin, PluginInfo, get_kernel


logger = None  # 延迟导入避免循环


# ═══════════════════════════════════════════════════════════
# Ebbinghaus 遗忘曲线
# ═══════════════════════════════════════════════════════════

class EbbinghausForgetting:
    """
    艾宾浩斯遗忘曲线数学实现
    
    R = e^(-t/S)
    
    其中:
    - R: 记忆保留率 (0-1)
    - t: 经过的时间(秒)
    - S: 记忆强度(取决于初始重要性+复习次数)
    
    参考点:
    - 20分钟后: 58% 保留
    - 1小时后: 44% 保留
    - 1天后: 33% 保留
    - 6天后: 25% 保留
    - 30天后: 21% 保留
    """

    # 基础衰减常数(秒) — 对应1小时后约44%保留
    BASE_DECAY = 3600 / math.log(1 / 0.44)  # ≈ 4370秒

    @staticmethod
    def retention(t_seconds: float, strength: float = 1.0,
                  reviews: int = 0) -> float:
        """
        计算记忆保留率
        
        Args:
            t_seconds: 距上次激活的时间(秒)
            strength: 初始重要性(0-1),越高衰减越慢
            reviews: 复习次数,每次复习减缓衰减
        """
        if t_seconds <= 0:
            return 1.0
        
        # 有效衰减常数: 基础值 * 强度因子 * 复习因子
        effective_decay = (
            EbbinghausForgetting.BASE_DECAY *
            (1.0 + (1.0 - strength) * 2.0) *  # 重要性低→衰减快
            (1.0 + reviews * 0.5)               # 复习→减缓衰减
        )
        
        retention = math.exp(-t_seconds / effective_decay)
        return max(0.01, min(1.0, retention))  # 保底1%

    @staticmethod
    def next_review_interval(strength: float, reviews: int) -> float:
        """计算下次建议复习间隔(秒)"""
        # 基于SuperMemo SM-2算法简化版
        if reviews == 0:
            return 86400  # 1天
        elif reviews == 1:
            return 86400 * 3  # 3天
        else:
            return 86400 * 3 * (1.5 ** (reviews - 1)) * strength


# ═══════════════════════════════════════════════════════════
# 记忆数据模型
# ═══════════════════════════════════════════════════════════

class MemoryLevel(Enum):
    SENSORY = 0    # 感知记忆
    WORKING = 1    # 工作记忆
    SHORT_TERM = 2 # 短时记忆
    LONG_TERM = 3  # 长时记忆
    ARCHIVAL = 4   # 归档记忆


@dataclass
class MemoryItem:
    """统一记忆条目"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    level: MemoryLevel = MemoryLevel.SHORT_TERM
    
    # 内容
    key: str = ""           # 记忆关键词
    value: str = ""         # 记忆内容
    summary: str = ""       # 压缩摘要(用于检索)
    embedding: Optional[List[float]] = None  # 向量表示
    
    # 元数据
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    source: str = ""        # 来源(user/assistant/system/extracted)
    
    # 时间戳
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    last_reviewed: float = field(default_factory=time.time)
    
    # 重要性
    importance: float = 0.5          # 初始重要性(0-1)
    access_count: int = 0            # 被访问次数
    review_count: int = 0            # 被复习次数
    
    # 关联
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)  # 命名实体
    related_memory_ids: List[str] = field(default_factory=list)
    
    # 元认知
    confidence: float = 1.0          # 信息确信度
    is_corrected: bool = False       # 是否被修正过
    correction_history: List[Dict] = field(default_factory=list)

    def current_retention(self) -> float:
        """当前记忆保留率"""
        elapsed = time.time() - self.last_reviewed
        return EbbinghausForgetting.retention(
            elapsed, self.importance, self.review_count
        )

    def effective_importance(self) -> float:
        """有效重要性 = 初始重要性 * 访问频率加成 * 保留率"""
        retention = self.current_retention()
        frequency_bonus = math.log(2 + self.access_count) / math.log(10)
        return min(1.0, self.importance * (1 + frequency_bonus * 0.3) * retention)

    def touch(self):
        """标记为已访问"""
        self.last_accessed = time.time()
        self.access_count += 1

    def review(self):
        """标记为已复习"""
        self.last_reviewed = time.time()
        self.review_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level.name,
            "key": self.key,
            "value": self.value,
            "summary": self.summary,
            "importance": self.importance,
            "retention": round(self.current_retention(), 3),
            "effective_importance": round(self.effective_importance(), 3),
            "access_count": self.access_count,
            "review_count": self.review_count,
            "tags": self.tags,
            "entities": self.entities,
        }

    def to_json_dict(self) -> Dict[str, Any]:
        """完整的序列化dict（用于文件持久化）"""
        d: Dict[str, Any] = {
            "id": self.id,
            "level": self.level.value,
            "key": self.key,
            "value": self.value,
            "summary": self.summary,
            "embedding": self.embedding,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "source": self.source,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "last_reviewed": self.last_reviewed,
            "importance": self.importance,
            "access_count": self.access_count,
            "review_count": self.review_count,
            "tags": self.tags,
            "entities": self.entities,
            "related_memory_ids": self.related_memory_ids,
            "confidence": self.confidence,
            "is_corrected": self.is_corrected,
            "correction_history": self.correction_history,
        }
        return d

    @classmethod
    def from_json_dict(cls, d: Dict[str, Any]) -> "MemoryItem":
        """从dict反序列化（用于文件持久化）"""
        item = cls.__new__(cls)
        item.id = d["id"]
        item.level = MemoryLevel(d["level"])
        item.key = d.get("key", "")
        item.value = d.get("value", "")
        item.summary = d.get("summary", "")
        item.embedding = d.get("embedding")
        item.project_id = d.get("project_id")
        item.conversation_id = d.get("conversation_id")
        item.source = d.get("source", "")
        item.created_at = d.get("created_at", time.time())
        item.last_accessed = d.get("last_accessed", time.time())
        item.last_reviewed = d.get("last_reviewed", time.time())
        item.importance = d.get("importance", 0.5)
        item.access_count = d.get("access_count", 0)
        item.review_count = d.get("review_count", 0)
        item.tags = d.get("tags", [])
        item.entities = d.get("entities", [])
        item.related_memory_ids = d.get("related_memory_ids", [])
        item.confidence = d.get("confidence", 1.0)
        item.is_corrected = d.get("is_corrected", False)
        item.correction_history = d.get("correction_history", [])
        return item


# ═══════════════════════════════════════════════════════════
# 向量索引
# ═══════════════════════════════════════════════════════════

class VectorIndex:
    """
    轻量向量索引
    使用numpy实现余弦相似度检索
    生产环境可替换为FAISS/Milvus
    """

    def __init__(self, dim: int = 384):
        self.dim = dim
        self._vectors: Dict[str, np.ndarray] = {}
        self._id_to_vectors: Dict[str, np.ndarray] = {}

    def add(self, item_id: str, embedding: List[float]):
        """添加向量"""
        vec = np.array(embedding, dtype=np.float32)
        if vec.shape[0] != self.dim:
            # 自适应维度
            self.dim = vec.shape[0]
        self._vectors[item_id] = vec

    def remove(self, item_id: str):
        """移除向量"""
        self._vectors.pop(item_id, None)

    def search(self, query_embedding: List[float], top_k: int = 10,
               filter_ids: Optional[Set[str]] = None) -> List[Tuple[str, float]]:
        """
        余弦相似度检索
        
        Returns:
            [(item_id, similarity_score), ...]
        """
        if not self._vectors:
            return []

        query = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query) + 1e-10

        scores = []
        for item_id, vec in self._vectors.items():
            if filter_ids and item_id not in filter_ids:
                continue
            vec_norm = np.linalg.norm(vec) + 1e-10
            sim = float(np.dot(query, vec) / (query_norm * vec_norm))
            scores.append((item_id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def count(self) -> int:
        return len(self._vectors)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可JSON序列化的dict"""
        vectors_list = []
        for item_id in sorted(self._vectors.keys()):
            vectors_list.append({
                "item_id": item_id,
                "embedding": self._vectors[item_id].tolist(),
            })
        return {
            "dim": self.dim,
            "vectors": vectors_list,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VectorIndex":
        """从dict反序列化"""
        index = cls(dim=data.get("dim", 384))
        for entry in data.get("vectors", []):
            index.add(entry["item_id"], entry["embedding"])
        return index


# ═══════════════════════════════════════════════════════════
# 知识图谱(轻量实现，可替换Neo4j)
# ═══════════════════════════════════════════════════════════

class KnowledgeGraph:
    """
    轻量知识图谱
    存储实体间关系，支持图遍历检索
    """

    def __init__(self):
        # 实体 -> {属性}
        self._entities: Dict[str, Dict[str, Any]] = {}
        # (主体, 关系, 客体) -> 权重
        self._relations: Dict[Tuple[str, str, str], float] = {}
        # 实体 -> 关联记忆ID列表
        self._entity_memories: Dict[str, Set[str]] = defaultdict(set)

    def add_entity(self, name: str, entity_type: str = "concept",
                   properties: Dict = None):
        """添加实体"""
        if name not in self._entities:
            self._entities[name] = {
                "type": entity_type,
                "properties": properties or {},
                "created_at": time.time(),
            }

    def add_relation(self, subject: str, relation: str, object_: str,
                     weight: float = 1.0):
        """添加关系"""
        self.add_entity(subject)
        self.add_entity(object_)
        key = (subject, relation, object_)
        if key in self._relations:
            self._relations[key] = max(self._relations[key], weight)
        else:
            self._relations[key] = weight

    def link_memory(self, entity: str, memory_id: str):
        """关联实体与记忆"""
        self._entity_memories[entity].add(memory_id)

    def get_related_memories(self, entity: str, depth: int = 1) -> Set[str]:
        """
        获取与实体相关的所有记忆ID
        支持多跳图遍历
        """
        result = set(self._entity_memories.get(entity, set()))

        if depth > 0:
            # 一跳: 直接关联实体
            for (s, r, o), w in self._relations.items():
                if s == entity:
                    result.update(self._entity_memories.get(o, set()))
                elif o == entity:
                    result.update(self._entity_memories.get(s, set()))

            if depth > 1:
                # 二跳: 间接关联
                indirect = set()
                for mid in list(result):
                    indirect.update(self.get_related_memories_from_id(mid))
                result.update(indirect)

        return result

    def get_related_memories_from_id(self, memory_id: str) -> Set[str]:
        """通过记忆ID查找关联的实体，再获取关联记忆"""
        related_entities = set()
        for entity, memories in self._entity_memories.items():
            if memory_id in memories:
                related_entities.add(entity)

        result = set()
        for entity in related_entities:
            result.update(self.get_related_memories(entity, depth=0))
        return result

    def search_entities(self, query: str) -> List[str]:
        """模糊搜索实体"""
        query_lower = query.lower()
        matches = []
        for name in self._entities:
            if query_lower in name.lower():
                matches.append(name)
        return matches

    def get_stats(self) -> Dict[str, int]:
        return {
            "entities": len(self._entities),
            "relations": len(self._relations),
            "entity_memory_links": sum(
                len(v) for v in self._entity_memories.values()
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可JSON序列化的dict"""
        # entities
        entities_dict = {}
        for name, info in self._entities.items():
            entities_dict[name] = {
                "type": info["type"],
                "properties": info["properties"],
                "created_at": info["created_at"],
            }
        # relations
        relations_list = []
        for (s, r, o), w in self._relations.items():
            relations_list.append({
                "subject": s,
                "relation": r,
                "object": o,
                "weight": w,
            })
        # entity_memories
        entity_memories_dict = {}
        for entity, mem_ids in self._entity_memories.items():
            entity_memories_dict[entity] = sorted(mem_ids)
        return {
            "entities": entities_dict,
            "relations": relations_list,
            "entity_memories": entity_memories_dict,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraph":
        """从dict反序列化"""
        kg = cls()
        for name, info in data.get("entities", {}).items():
            kg._entities[name] = {
                "type": info["type"],
                "properties": info["properties"],
                "created_at": info["created_at"],
            }
        for rel in data.get("relations", []):
            key = (rel["subject"], rel["relation"], rel["object"])
            kg._relations[key] = rel.get("weight", 1.0)
        for entity, mem_ids in data.get("entity_memories", {}).items():
            kg._entity_memories[entity] = set(mem_ids)
        return kg


# ═══════════════════════════════════════════════════════════
# 层次记忆存储
# ═══════════════════════════════════════════════════════════

class HierarchicalMemoryStore:
    """
    层次记忆存储引擎

    核心特性:
    - L0-L4层次管理
    - 自动升级/降级记忆
    - 记忆压缩(长摘要)
    - 去重合并
    """

    def __init__(self):
        # 各层次记忆存储
        self._stores: Dict[MemoryLevel, OrderedDict[str, MemoryItem]] = {
            level: OrderedDict() for level in MemoryLevel
        }

        # 容量限制
        self._capacity: Dict[MemoryLevel, int] = {
            MemoryLevel.SENSORY: 100,       # 最近100条消息
            MemoryLevel.WORKING: 50,        # 当前任务50条记忆
            MemoryLevel.SHORT_TERM: 500,    # 近7天500条
            MemoryLevel.LONG_TERM: 10000,   # 无上限(向量检索)
            MemoryLevel.ARCHIVAL: 50000,    # 压缩归档
        }

        # 升级阈值
        self._upgrade_thresholds = {
            MemoryLevel.SENSORY: {"access_count": 2, "min_importance": 0.3},
            MemoryLevel.WORKING: {"access_count": 5, "min_importance": 0.5},
            MemoryLevel.SHORT_TERM: {"access_count": 10, "min_importance": 0.7},
            MemoryLevel.LONG_TERM: {"access_count": 20, "min_importance": 0.8},
        }

        # 向量索引 + 知识图谱
        self.vector_index = VectorIndex()
        self.knowledge_graph = KnowledgeGraph()

    # ── 存储操作 ──────────────────────────────────────────

    def store(self, item: MemoryItem) -> str:
        """存储记忆条目到适当层次"""
        store = self._stores[item.level]
        store[item.id] = item

        # 容量控制: LRU淘汰
        if len(store) > self._capacity[item.level]:
            oldest = next(iter(store))
            self._evict(oldest, item.level)

        # 自动保存
        self._maybe_auto_save()

        return item.id

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        """获取记忆条目"""
        for level in MemoryLevel:
            if memory_id in self._stores[level]:
                item = self._stores[level][memory_id]
                item.touch()
                # 检查是否需要升级
                self._maybe_upgrade(item)
                return item
        return None

    def _maybe_upgrade(self, item: MemoryItem):
        """检查并升级记忆层次"""
        if item.level.value >= MemoryLevel.ARCHIVAL.value:
            return

        next_level = MemoryLevel(item.level.value + 1)
        threshold = self._upgrade_thresholds.get(item.level, {})

        access_ok = item.access_count >= threshold.get("access_count", 999)
        importance_ok = item.importance >= threshold.get("min_importance", 1.0)

        if access_ok and importance_ok:
            self._promote(item, next_level)

    def _promote(self, item: MemoryItem, new_level: MemoryLevel):
        """升级记忆到更高层次"""
        old_store = self._stores[item.level]
        if item.id in old_store:
            del old_store[item.id]

        item.level = new_level
        self._stores[new_level][item.id] = item

        if new_level == MemoryLevel.LONG_TERM:
            # 升级到L3时生成摘要
            item.summary = self._generate_summary(item)

    def _evict(self, memory_id: str, level: MemoryLevel):
        """淘汰记忆(降级到低层次或删除)"""
        store = self._stores[level]
        item = store.pop(memory_id, None)
        if not item:
            return

        if level.value > MemoryLevel.SHORT_TERM.value:
            # 高层记忆降级到归档
            item.level = MemoryLevel.ARCHIVAL
            item.summary = self._generate_summary(item)
            self._stores[MemoryLevel.ARCHIVAL][item.id] = item
        # L0-L1直接丢弃

    def _generate_summary(self, item: MemoryItem) -> str:
        """生成记忆摘要(压缩)"""
        if len(item.value) <= 200:
            return item.value
        # 简单截取+关键信息
        return f"[{item.key}] {item.value[:150]}..."

    # ── 检索操作 ──────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 10,
                 project_id: Optional[str] = None,
                 min_importance: float = 0.0) -> List[MemoryItem]:
        """
        混合检索: 向量相似度 + 图关联 + 时间衰减
        
        FinalScore = α*VectorSim + β*GraphRelevance + γ*RecencyBias - δ*DecayFactor
        """
        # 向量检索
        if self.vector_index.count() > 0 and hasattr(self, '_embedding_fn'):
            vector_results = self._vector_search(query, top_k * 3, project_id)
        else:
            vector_results = self._keyword_search(query, top_k * 3, project_id)

        # 图增强
        graph_boosted = self._graph_boost(vector_results, query)

        # 计算最终分数
        scored = []
        for item_id, score in graph_boosted:
            item = self.get(item_id)
            if not item:
                continue

            if item.effective_importance() < min_importance:
                continue

            # 时间衰减
            recency = self._recency_score(item)
            # 有效重要性
            importance = item.effective_importance()

            # 混合分数
            final_score = (
                0.4 * score +          # 向量相似度
                0.3 * importance +     # 记忆重要性
                0.2 * recency +        # 时间新鲜度
                0.1 * (item.access_count / max(1, item.access_count + 10))  # 访问频率
            )

            scored.append((item, final_score))

        # 去重(按key)
        seen_keys = set()
        deduped = []
        for item, score in sorted(scored, key=lambda x: x[1], reverse=True):
            if item.key not in seen_keys:
                seen_keys.add(item.key)
                deduped.append(item)

        return deduped[:top_k]

    def _vector_search(self, query: str, top_k: int,
                       project_id: Optional[str] = None) -> List[Tuple[str, float]]:
        """向量检索"""
        # 获取查询嵌入
        query_emb = self._embed(query)
        filter_set = None
        if project_id:
            filter_set = {
                mid for mid, item in self._all_items()
                if item.project_id == project_id
            }
        return self.vector_index.search(query_emb, top_k, filter_set)

    def _keyword_search(self, query: str, top_k: int,
                        project_id: Optional[str] = None) -> List[Tuple[str, float]]:
        """关键词回退检索"""
        query_lower = query.lower()
        keywords = query_lower.split()
        scores = []

        for item_id, item in self._all_items():
            if project_id and item.project_id != project_id:
                continue
            text = f"{item.key} {item.value} {item.summary}".lower()
            score = sum(1 for kw in keywords if kw in text) / max(1, len(keywords))
            if score > 0:
                scores.append((item_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _graph_boost(self, vector_results: List[Tuple[str, float]],
                     query: str) -> List[Tuple[str, float]]:
        """知识图谱增强: 检索相关实体的关联记忆"""
        entities = self.knowledge_graph.search_entities(query)
        if not entities:
            return vector_results

        # 获取图谱关联记忆
        graph_memories = set()
        for entity in entities[:5]:
            graph_memories.update(
                self.knowledge_graph.get_related_memories(entity, depth=1)
            )

        if not graph_memories:
            return vector_results

        # 提升图谱关联记忆的分数
        boosted = []
        for item_id, score in vector_results:
            if item_id in graph_memories:
                boosted.append((item_id, min(1.0, score + 0.2)))
            else:
                boosted.append((item_id, score))

        return boosted

    def _recency_score(self, item: MemoryItem) -> float:
        """计算时间新鲜度分数"""
        elapsed = time.time() - item.last_accessed
        # 指数衰减: 1小时内满分，24小时0.5分，7天0.1分
        return math.exp(-elapsed / 86400)  # 以天为单位的衰减

    def _embed(self, text: str) -> List[float]:
        """文本嵌入(轻量hash回退)"""
        if hasattr(self, '_embedding_fn') and self._embedding_fn:
            return self._embedding_fn(text)
        # Hash回退: 384维伪向量
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(0, 384, 4):
            val = int.from_bytes(h[i:i+4], 'big') if i+4 <= len(h) else 0
            vec.append(float(val) / (2**32) * 2 - 1)
        return vec

    def set_embedding_fn(self, fn):
        """设置嵌入函数(用于真实向量)"""
        self._embedding_fn = fn

    # ═══════════════════════════════════════════════════════════
    # 持久化 (save_to_file / load_from_file)
    # ═══════════════════════════════════════════════════════════

    # 文件格式版本 — 用于向前兼容
    PERSISTENCE_VERSION = 1

    # 自动保存：每次写入N条记忆后触发 (0=禁用)
    auto_save_threshold: int = 0
    _auto_save_path: Optional[str] = None
    _write_count_since_save: int = 0

    def set_auto_save(self, path: str, threshold: int = 10):
        """配置自动保存

        Args:
            path: 自动保存的文件路径
            threshold: 每写入threshold条记忆后自动保存 (0=禁用)
        """
        self._auto_save_path = path
        self.auto_save_threshold = threshold
        self._write_count_since_save = 0

    def _maybe_auto_save(self):
        """检查是否需要自动保存"""
        if self.auto_save_threshold <= 0 or not self._auto_save_path:
            return
        self._write_count_since_save += 1
        if self._write_count_since_save >= self.auto_save_threshold:
            self.save_to_file(self._auto_save_path)
            self._write_count_since_save = 0

    def _serialize_memory_items(self) -> List[Dict[str, Any]]:
        """序列化所有记忆条目"""
        items = []
        for item_id, item in sorted(
            self._all_items(), key=lambda x: (
                x[1].level.value, x[1].created_at, x[0]
            )
        ):
            items.append(item.to_json_dict())
        return items

    def _deserialize_memory_items(self, items_data: List[Dict[str, Any]]):
        """反序列化并加载所有记忆条目"""
        for d in items_data:
            item = MemoryItem.from_json_dict(d)
            self._stores[item.level][item.id] = item
            if item.embedding is not None:
                self.vector_index.add(item.id, item.embedding)
            # 重建图谱关联
            for entity in item.entities:
                self.knowledge_graph.link_memory(entity, item.id)

    def save_to_file(self, path: str) -> str:
        """将整个记忆系统保存到JSON文件

        Args:
            path: 文件路径

        Returns:
            写入的文件路径 (绝对路径规范化后)

        Raises:
            IOError: 写入失败
        """
        # 收集所有记忆条目
        items_data = self._serialize_memory_items()

        # 组装完整快照
        snapshot: Dict[str, Any] = {
            "version": self.PERSISTENCE_VERSION,
            "meta": {
                "saved_at": time.time(),
                "total_items": len(items_data),
                "total_stores": sum(
                    len(s) for s in self._stores.values()
                ),
                "vector_count": self.vector_index.count(),
                "graph_stats": self.knowledge_graph.get_stats(),
            },
            "items": items_data,
            "vector_index": self.vector_index.to_dict(),
            "knowledge_graph": self.knowledge_graph.to_dict(),
        }

        # 写入文件 (原子写入: 先写临时文件再重命名)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except (IOError, OSError) as e:
            # 清理临时文件
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise IOError(f"保存记忆失败: {e}") from e

        return os.path.abspath(path)

    @classmethod
    def load_from_file(cls, path: str) -> "HierarchicalMemoryStore":
        """从JSON文件加载整个记忆系统

        Args:
            path: 文件路径

        Returns:
            加载完成的 HierarchicalMemoryStore 实例

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 版本不兼容或格式错误
            IOError: 读取失败
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"记忆文件不存在: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise IOError(f"读取记忆文件失败: {e}") from e

        # 版本检查
        version = snapshot.get("version", 0)
        if version != cls.PERSISTENCE_VERSION:
            raise ValueError(
                f"版本不兼容: 文件版本={version}, "
                f"期望版本={cls.PERSISTENCE_VERSION}"
            )

        # 创建空实例
        store = cls()

        # 加载向量索引
        vi_data = snapshot.get("vector_index")
        if vi_data:
            store.vector_index = VectorIndex.from_dict(vi_data)

        # 加载知识图谱
        kg_data = snapshot.get("knowledge_graph")
        if kg_data:
            store.knowledge_graph = KnowledgeGraph.from_dict(kg_data)

        # 加载记忆条目
        items_data = snapshot.get("items", [])
        store._deserialize_memory_items(items_data)

        return store

    # ── 维护操作 ──────────────────────────────────────────

    def _all_items(self):
        """遍历所有层次的记忆"""
        for level in MemoryLevel:
            yield from self._stores[level].items()

    def compact(self):
        """记忆压缩: 去重+合并相似记忆"""
        # 在每层内去重
        for level in MemoryLevel:
            store = self._stores[level]
            seen_keys = {}
            to_remove = []
            for item_id, item in store.items():
                if item.key in seen_keys:
                    existing = seen_keys[item.key]
                    # 保留更新的、更重要的
                    if item.importance > existing.importance:
                        to_remove.append(existing.id)
                        seen_keys[item.key] = item
                    else:
                        to_remove.append(item.id)
                else:
                    seen_keys[item.key] = item
            for rid in to_remove:
                store.pop(rid, None)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {}
        for level in MemoryLevel:
            store = self._stores[level]
            items = list(store.values())
            stats[level.name] = {
                "count": len(store),
                "avg_importance": (
                    sum(i.importance for i in items) / len(items)
                    if items else 0
                ),
                "avg_retention": (
                    sum(i.current_retention() for i in items) / len(items)
                    if items else 0
                ),
            }
        stats["vector_index"] = self.vector_index.count()
        stats["knowledge_graph"] = self.knowledge_graph.get_stats()
        return stats


# ═══════════════════════════════════════════════════════════
# 记忆引擎插件
# ═══════════════════════════════════════════════════════════

class MemoryPlugin(Plugin):
    """
    记忆引擎插件
    注册到微内核，监听事件驱动记忆操作
    """

    info = PluginInfo(
        name="memory",
        version="1.0.0",
        description="层次记忆引擎 — Ebbinghaus遗忘曲线 + 混合检索",
        author="meshctx",
    )

    def __init__(self):
        self.store = HierarchicalMemoryStore()
        self._compaction_task: Optional[asyncio.Task] = None

    async def on_load(self):
        """加载插件: 注册事件处理器"""
        global logger
        import logging
        logger = logging.getLogger("meshctx.memory")

        bus = self.kernel.bus

        # 核心事件
        bus.subscribe("message.added", self._on_message_added,
                      plugin_name="memory")
        bus.subscribe("project.created", self._on_project_created,
                      plugin_name="memory")
        bus.subscribe("memory.search", self._on_search_request,
                      plugin_name="memory")
        bus.subscribe("memory.compact", self._on_compact_request,
                      plugin_name="memory")

        # 定时压缩任务(每小时)
        self._compaction_task = asyncio.create_task(self._periodic_compaction())

        logger.info("记忆引擎已加载"
                     f" (L0-L4层次, {self.store.vector_index.count()} 向量)")

    async def on_unload(self):
        """卸载: 取消定时任务"""
        if self._compaction_task:
            self._compaction_task.cancel()
        logger.info("记忆引擎已卸载")

    # ── 事件处理器 ────────────────────────────────────────

    async def _on_message_added(self, event: Event):
        """消息添加时: 提取记忆+更新索引"""
        data = event.data
        content = data.get("content", "")
        role = data.get("role", "user")
        project_id = data.get("project_id")
        conversation_id = data.get("conversation_id")

        # L0: 感知记忆(总是存储最近消息)
        l0_item = MemoryItem(
            level=MemoryLevel.SENSORY,
            key=f"msg_{role}",
            value=content,
            project_id=project_id,
            conversation_id=conversation_id,
            source=role,
            importance=0.2,
        )
        self.store.store(l0_item)

        # 重要性判断: 包含关键词的消息提升到L1
        important_keywords = [
            "记住", "重要", "关键", "目标", "决定", "结论",
            "禁止", "必须", "配置", "密码", "API", "密钥",
        ]
        is_important = any(kw in content for kw in important_keywords)

        if is_important or role == "system":
            item = MemoryItem(
                level=MemoryLevel.WORKING,
                key=self._extract_key(content),
                value=content,
                project_id=project_id,
                conversation_id=conversation_id,
                source=role,
                importance=0.7 if is_important else 0.4,
            )
            # 生成嵌入
            item.embedding = self.store._embed(content)
            self.store.store(item)
            self.store.vector_index.add(item.id, item.embedding)

            logger.debug(f"提取记忆: [{item.key}] → L1")

    async def _on_project_created(self, event: Event):
        """项目创建时: 初始化项目记忆空间"""
        data = event.data
        item = MemoryItem(
            level=MemoryLevel.WORKING,
            key="project_created",
            value=f"项目 [{data.get('name')}] 创建: {data.get('description')}",
            project_id=data.get("id"),
            importance=0.8,
        )
        self.store.store(item)

    async def _on_search_request(self, event: Event):
        """搜索请求"""
        data = event.data
        query = data.get("query", "")
        top_k = data.get("top_k", 10)
        project_id = data.get("project_id")

        results = self.store.retrieve(query, top_k, project_id)

        # 发布结果
        await self.kernel.bus.publish(Event(
            type="memory.search_result",
            source="memory",
            correlation_id=event.id,
            data={
                "query": query,
                "results": [r.to_dict() for r in results],
            },
        ))

    async def _on_compact_request(self, event: Event):
        """压缩请求"""
        self.store.compact()
        logger.info("记忆压缩完成")

    async def _periodic_compaction(self):
        """定时记忆压缩(每小时)"""
        while True:
            await asyncio.sleep(3600)
            try:
                self.store.compact()
                logger.debug("定时记忆压缩完成")
            except Exception as e:
                logger.error(f"定时压缩失败: {e}")

    # ── 工具方法 ──────────────────────────────────────────

    def _extract_key(self, content: str) -> str:
        """从内容提取关键短语"""
        # 简化的关键短语提取
        key_indicators = ["是", "为", ":", "：", "=", "目标", "决定"]
        for indicator in key_indicators:
            if indicator in content:
                parts = content.split(indicator, 1)
                if len(parts) > 1:
                    return parts[1].strip()[:30]
        # 回退: 前30字符
        return content[:30].strip()

    def get_context_for_task(self, task_description: str,
                             project_id: Optional[str] = None,
                             max_items: int = 20) -> List[Dict]:
        """为任务组装上下文记忆"""
        results = self.store.retrieve(task_description, max_items, project_id)

        context = []
        for item in results:
            context.append({
                "key": item.key,
                "value": item.value,
                "importance": round(item.effective_importance(), 2),
                "retention": round(item.current_retention(), 2),
                "age_hours": round(
                    (time.time() - item.created_at) / 3600, 1
                ),
            })

        return context

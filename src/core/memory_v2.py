"""
meshctx v2.0 记忆系统 — 向量检索 + 知识图谱

极简零外部依赖实现:
- VectorStore: numpy 余弦相似度 + TF-IDF 文本向量化(无需sentence-transformers)
- KnowledgeGraph: dict-of-dicts 实体-关系图谱(无需networkx)
- MemoryManager: 统一接口，整合向量检索 + KG + 旧版层次记忆

持久化: ~/.meshctx/memory_v2/
自动从旧版 memory_hierarchy.py 导入数据
"""
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

# ── 数据目录 ────────────────────────────────────────────────
MEMORY_V2_DIR = Path.home() / ".meshctx" / "memory_v2"
MEMORY_V2_DIR.mkdir(parents=True, exist_ok=True)

VECTORS_FILE = MEMORY_V2_DIR / "vectors.json"
GRAPH_FILE = MEMORY_V2_DIR / "graph.json"
ITEMS_FILE = MEMORY_V2_DIR / "items.json"
TFIDF_FILE = MEMORY_V2_DIR / "tfidf_vocab.json"


# ═══════════════════════════════════════════════════════════
# TF-IDF 文本向量化 (零外部依赖)
# ═══════════════════════════════════════════════════════════

class TfidfVectorizer:
    """极简TF-IDF: 将文本转为稀疏向量，用于余弦相似度检索"""

    def __init__(self, max_features: int = 1024):
        self.max_features = max_features
        self.vocab: Dict[str, int] = {}          # token -> index
        self.idf: Dict[str, float] = {}          # token -> idf
        self.doc_count = 0

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """简单分词: 中文单字+英文单词"""
        tokens = []
        # 英文单词
        for word in re.findall(r'[a-zA-Z0-9]+', text.lower()):
            tokens.append(word)
        # 中文单字/双字
        chinese = re.findall(r'[\u4e00-\u9fff]+', text)
        for seg in chinese:
            if len(seg) <= 2:
                tokens.append(seg)
            else:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i+2])
                tokens.append(seg[-1])
        return tokens

    def fit(self, documents: List[str]):
        """构建词汇表和IDF"""
        df = defaultdict(int)
        self.doc_count = len(documents)

        for doc in documents:
            tokens = set(self._tokenize(doc))
            for t in tokens:
                df[t] += 1

        # 按文档频率排序，取top max_features
        sorted_terms = sorted(df.items(), key=lambda x: -x[1])[:self.max_features]
        self.vocab = {term: idx for idx, (term, _) in enumerate(sorted_terms)}

        # 计算IDF
        for term, idx in self.vocab.items():
            self.idf[term] = math.log(
                (self.doc_count + 1) / (df[term] + 1)
            ) + 1.0

    def transform(self, text: str) -> np.ndarray:
        """将文本转为TF-IDF向量"""
        tokens = self._tokenize(text)
        vec = np.zeros(len(self.vocab), dtype=np.float32)

        # 计算TF
        tf = defaultdict(int)
        for t in tokens:
            if t in self.vocab:
                tf[t] += 1

        # TF-IDF
        for term, count in tf.items():
            idx = self.vocab[term]
            vec[idx] = (count / max(len(tokens), 1)) * self.idf.get(term, 1.0)

        # L2归一化
        norm = np.linalg.norm(vec) + 1e-10
        return vec / norm

    def to_dict(self) -> dict:
        return {
            "max_features": self.max_features,
            "vocab": self.vocab,
            "idf": self.idf,
            "doc_count": self.doc_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TfidfVectorizer":
        v = cls(max_features=data.get("max_features", 1024))
        v.vocab = data.get("vocab", {})
        v.idf = data.get("idf", {})
        v.doc_count = data.get("doc_count", 0)
        return v


# ═══════════════════════════════════════════════════════════
# 向量存储 V2
# ═══════════════════════════════════════════════════════════

@dataclass
class VectorEntry:
    """向量条目"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    vector: Optional[np.ndarray] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class VectorStore:
    """
    向量存储引擎 V2
    - numpy 余弦相似度检索
    - TF-IDF 文本向量化 (零外部依赖)
    - 支持增量添加/删除
    - JSON 持久化
    """

    def __init__(self):
        self._entries: Dict[str, VectorEntry] = {}
        self._tfidf = TfidfVectorizer()
        self._loaded = False

    # ── 核心操作 ──────────────────────────────────────────

    def add(self, text: str, meta: Dict = None,
            entry_id: str = None) -> str:
        """添加文本到向量存储"""
        entry = VectorEntry(
            id=entry_id or str(uuid.uuid4()),
            text=text,
            meta=meta or {},
        )
        self._entries[entry.id] = entry
        return entry.id

    def remove(self, entry_id: str) -> bool:
        """移除条目"""
        return self._entries.pop(entry_id, None) is not None

    def search(self, query: str, top_k: int = 10,
               min_score: float = 0.0,
               filter_meta: Dict = None) -> List[Tuple[VectorEntry, float]]:
        """
        余弦相似度检索

        使用TF-IDF向量化查询和所有文档，计算余弦相似度
        """
        if not self._entries:
            return []

        # 构建/更新TF-IDF
        all_texts = [e.text for e in self._entries.values()]
        if not self._tfidf.vocab:
            self._tfidf.fit(all_texts)

        # 向量化文档
        doc_vectors = {}
        for eid, entry in self._entries.items():
            doc_vectors[eid] = self._tfidf.transform(entry.text)

        # 向量化查询
        query_vec = self._tfidf.transform(query)

        # 计算余弦相似度
        scores = []
        for eid, doc_vec in doc_vectors.items():
            sim = float(np.dot(query_vec, doc_vec))
            if sim < min_score:
                continue
            entry = self._entries[eid]
            # 元数据过滤
            if filter_meta:
                match = all(
                    entry.meta.get(k) == v
                    for k, v in filter_meta.items()
                )
                if not match:
                    continue
            scores.append((entry, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def get(self, entry_id: str) -> Optional[VectorEntry]:
        return self._entries.get(entry_id)

    def count(self) -> int:
        return len(self._entries)

    def all_entries(self) -> List[VectorEntry]:
        return list(self._entries.values())

    def rebuild_index(self):
        """重建TF-IDF索引"""
        all_texts = [e.text for e in self._entries.values()]
        if all_texts:
            self._tfidf = TfidfVectorizer()
            self._tfidf.fit(all_texts)

    # ── 持久化 ────────────────────────────────────────────

    def save(self) -> str:
        """保存到JSON"""
        data = {
            "entries": [],
            "tfidf": self._tfidf.to_dict(),
        }
        for entry in self._entries.values():
            data["entries"].append({
                "id": entry.id,
                "text": entry.text,
                "meta": entry.meta,
                "created_at": entry.created_at,
            })
        tmp = str(VECTORS_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(VECTORS_FILE))
        return str(VECTORS_FILE)

    def load(self) -> bool:
        """从JSON加载"""
        if not VECTORS_FILE.exists():
            return False
        try:
            with open(VECTORS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        self._entries.clear()
        for e in data.get("entries", []):
            entry = VectorEntry(
                id=e["id"],
                text=e["text"],
                meta=e.get("meta", {}),
                created_at=e.get("created_at", time.time()),
            )
            self._entries[entry.id] = entry

        if "tfidf" in data:
            self._tfidf = TfidfVectorizer.from_dict(data["tfidf"])
        else:
            self.rebuild_index()

        self._loaded = True
        return True

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_vectors": len(self._entries),
            "vocab_size": len(self._tfidf.vocab),
            "doc_count": self._tfidf.doc_count,
            "storage_file": str(VECTORS_FILE),
        }


# ═══════════════════════════════════════════════════════════
# 知识图谱 V2 (dict-of-dicts, 零外部依赖)
# ═══════════════════════════════════════════════════════════

class KnowledgeGraphV2:
    """
    知识图谱引擎 V2
    - 纯 dict-of-dicts 实现 (无 networkx)
    - 实体 + 关系 + 属性
    - 图遍历、邻居查询、最短路径
    - JSON 持久化
    """

    def __init__(self):
        # entities: {name: {type, properties, created_at}}
        self._entities: Dict[str, Dict] = {}
        # relations: {(subject, relation, object): weight}
        self._relations: Dict[Tuple[str, str, str], float] = {}
        # 实体关联的记忆ID
        self._entity_memories: Dict[str, Set[str]] = defaultdict(set)
        # 邻接表 (加速遍历)
        self._adj_out: Dict[str, Set[str]] = defaultdict(set)  # subject -> {object}
        self._adj_in: Dict[str, Set[str]] = defaultdict(set)   # object -> {subject}

    # ── 实体操作 ──────────────────────────────────────────

    def add_entity(self, name: str, entity_type: str = "concept",
                   properties: Dict = None) -> str:
        """添加实体，返回实体名"""
        if name not in self._entities:
            self._entities[name] = {
                "type": entity_type,
                "properties": properties or {},
                "created_at": time.time(),
            }
        else:
            # 更新属性
            self._entities[name]["type"] = entity_type
            if properties:
                self._entities[name]["properties"].update(properties)
        return name

    def get_entity(self, name: str) -> Optional[Dict]:
        return self._entities.get(name)

    def list_entities(self, entity_type: str = None) -> List[str]:
        if entity_type:
            return [
                n for n, info in self._entities.items()
                if info.get("type") == entity_type
            ]
        return list(self._entities.keys())

    def remove_entity(self, name: str):
        """移除实体及其所有关联"""
        self._entities.pop(name, None)
        # 移除关联关系
        to_remove = []
        for (s, r, o) in self._relations:
            if s == name or o == name:
                to_remove.append((s, r, o))
        for key in to_remove:
            self._relations.pop(key, None)
        # 清理邻接表
        self._adj_out.pop(name, None)
        self._adj_in.pop(name, None)
        for adj in self._adj_out.values():
            adj.discard(name)
        for adj in self._adj_in.values():
            adj.discard(name)
        # 清理记忆关联
        self._entity_memories.pop(name, None)

    # ── 关系操作 ──────────────────────────────────────────

    def add_relation(self, subject: str, relation: str,
                     object_: str, weight: float = 1.0):
        """添加三元组关系"""
        self.add_entity(subject)
        self.add_entity(object_)
        key = (subject, relation, object_)
        self._relations[key] = max(
            self._relations.get(key, 0.0), weight
        )
        # 更新邻接表
        self._adj_out[subject].add(object_)
        self._adj_in[object_].add(subject)

    def get_relations(self, entity: str = None,
                      relation_type: str = None) -> List[Dict]:
        """查询关系"""
        results = []
        for (s, r, o), w in self._relations.items():
            if entity and s != entity and o != entity:
                continue
            if relation_type and r != relation_type:
                continue
            results.append({
                "subject": s, "relation": r,
                "object": o, "weight": w,
            })
        return results

    def remove_relation(self, subject: str, relation: str,
                        object_: str):
        """移除关系"""
        key = (subject, relation, object_)
        self._relations.pop(key, None)
        if object_ in self._adj_out.get(subject, set()):
            self._adj_out[subject].discard(object_)
        if subject in self._adj_in.get(object_, set()):
            self._adj_in[object_].discard(subject)

    # ── 记忆关联 ──────────────────────────────────────────

    def link_memory(self, entity: str, memory_id: str):
        """关联实体与记忆"""
        self._entity_memories[entity].add(memory_id)

    def get_entity_memories(self, entity: str) -> List[str]:
        return sorted(self._entity_memories.get(entity, set()))

    # ── 图遍历 ────────────────────────────────────────────

    def get_neighbors(self, entity: str, direction: str = "both") -> List[str]:
        """获取邻居实体"""
        neighbors = set()
        if direction in ("out", "both"):
            neighbors.update(self._adj_out.get(entity, set()))
        if direction in ("in", "both"):
            neighbors.update(self._adj_in.get(entity, set()))
        return sorted(neighbors)

    def get_related_memories(self, entity: str, depth: int = 1) -> List[str]:
        """获取与实体相关的所有记忆 (支持多跳)"""
        result = set(self._entity_memories.get(entity, set()))
        if depth <= 0:
            return sorted(result)

        visited_entities = {entity}
        frontier = {entity}
        for _ in range(depth):
            next_frontier = set()
            for e in frontier:
                for neighbor in self.get_neighbors(e):
                    if neighbor not in visited_entities:
                        visited_entities.add(neighbor)
                        next_frontier.add(neighbor)
                        result.update(
                            self._entity_memories.get(neighbor, set())
                        )
            frontier = next_frontier
            if not frontier:
                break

        return sorted(result)

    def shortest_path(self, start: str, end: str,
                      max_depth: int = 5) -> Optional[List[str]]:
        """BFS最短路径"""
        if start == end:
            return [start]
        if start not in self._entities or end not in self._entities:
            return None

        queue = [(start, [start])]
        visited = {start}

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            for neighbor in self.get_neighbors(current):
                if neighbor == end:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return None

    def search_entities(self, query: str) -> List[str]:
        """模糊搜索实体名"""
        q = query.lower()
        matches = []
        for name in self._entities:
            if q in name.lower():
                matches.append(name)
        return sorted(matches)

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            "entities": len(self._entities),
            "relations": len(self._relations),
            "entity_memory_links": sum(
                len(v) for v in self._entity_memories.values()
            ),
            "entity_types": self._count_entity_types(),
        }

    def _count_entity_types(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for info in self._entities.values():
            counts[info.get("type", "unknown")] += 1
        return dict(counts)

    def to_graph_data(self) -> Dict[str, Any]:
        """导出为前端可视化格式 (nodes + edges)"""
        nodes = []
        for name, info in self._entities.items():
            nodes.append({
                "id": name,
                "label": name,
                "type": info.get("type", "concept"),
                "properties": info.get("properties", {}),
                "memory_count": len(self._entity_memories.get(name, set())),
            })

        edges = []
        for (s, r, o), w in self._relations.items():
            edges.append({
                "source": s,
                "target": o,
                "label": r,
                "weight": w,
            })

        return {"nodes": nodes, "edges": edges}

    # ── 持久化 ────────────────────────────────────────────

    def save(self) -> str:
        """保存到JSON"""
        data = {
            "entities": {},
            "relations": [],
            "entity_memories": {},
        }
        for name, info in self._entities.items():
            data["entities"][name] = {
                "type": info["type"],
                "properties": info["properties"],
                "created_at": info["created_at"],
            }
        for (s, r, o), w in self._relations.items():
            data["relations"].append({
                "subject": s, "relation": r,
                "object": o, "weight": w,
            })
        for entity, mem_ids in self._entity_memories.items():
            data["entity_memories"][entity] = sorted(mem_ids)

        tmp = str(GRAPH_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(GRAPH_FILE))
        return str(GRAPH_FILE)

    def load(self) -> bool:
        """从JSON加载"""
        if not GRAPH_FILE.exists():
            return False
        try:
            with open(GRAPH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        self._entities.clear()
        self._relations.clear()
        self._entity_memories.clear()
        self._adj_out.clear()
        self._adj_in.clear()

        for name, info in data.get("entities", {}).items():
            self._entities[name] = {
                "type": info.get("type", "concept"),
                "properties": info.get("properties", {}),
                "created_at": info.get("created_at", time.time()),
            }

        for rel in data.get("relations", []):
            s, r, o = rel["subject"], rel["relation"], rel["object"]
            w = rel.get("weight", 1.0)
            self._relations[(s, r, o)] = w
            self._adj_out[s].add(o)
            self._adj_in[o].add(s)

        for entity, mem_ids in data.get("entity_memories", {}).items():
            self._entity_memories[entity] = set(mem_ids)

        return True


# ═══════════════════════════════════════════════════════════
# 记忆条目 V2
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """统一记忆条目 V2"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    mem_type: str = "fact"  # fact | episode | skill
    source: str = "user"    # user | system | extracted
    importance: float = 0.5
    access_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)

    def touch(self):
        self.access_count += 1
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "summary": self.summary,
            "tags": self.tags,
            "entities": self.entities,
            "type": self.mem_type,
            "source": self.source,
            "importance": self.importance,
            "access_count": self.access_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            content=d.get("content", ""),
            summary=d.get("summary", ""),
            tags=d.get("tags", []),
            entities=d.get("entities", []),
            mem_type=d.get("type", "fact"),
            source=d.get("source", "user"),
            importance=d.get("importance", 0.5),
            access_count=d.get("access_count", 0),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            meta=d.get("meta", {}),
        )


# ═══════════════════════════════════════════════════════════
# 统一记忆管理器 V2
# ═══════════════════════════════════════════════════════════

class MemoryManager:
    """
    记忆管理器 V2 — 统一接口

    整合:
    - VectorStore: 语义向量检索
    - KnowledgeGraphV2: 实体关系图谱
    - 旧版 HierarchicalMemoryStore: 层次记忆 (自动导入)
    """

    def __init__(self):
        self.vector_store = VectorStore()
        self.knowledge_graph = KnowledgeGraphV2()
        self._entries: Dict[str, MemoryEntry] = {}
        self._old_store = None  # 延迟加载旧版
        self._initialized = False

    def initialize(self):
        """初始化：加载持久化数据 + 自动导入旧版"""
        if self._initialized:
            return

        # 加载 V2 数据
        self.vector_store.load()
        self.knowledge_graph.load()
        self._load_items()

        # 自动导入旧版记忆
        self._import_from_old_store()

        self._initialized = True

    # ── 导入旧版 ──────────────────────────────────────────

    def _import_from_old_store(self):
        """从旧版 HierarchicalMemoryStore 自动导入记忆"""
        if self._entries:
            return  # 已有数据，不重复导入

        try:
            from .memory_hierarchy import HierarchicalMemoryStore, MemoryLevel
        except ImportError:
            return

        # 查找旧版持久化文件
        old_paths = [
            Path.home() / ".meshctx" / "memory_snapshot.json",
            Path.home() / ".meshctx" / "memory.json",
        ]
        for old_path in old_paths:
            if old_path.exists():
                try:
                    old_store = HierarchicalMemoryStore.load_from_file(
                        str(old_path)
                    )
                    self._import_from_store(old_store)
                    break
                except Exception:
                    continue

    def _import_from_store(self, old_store):
        """从旧版存储实例导入数据"""
        from .memory_hierarchy import MemoryLevel

        imported = 0
        for level in MemoryLevel:
            store_dict = old_store._stores.get(level, {})
            for mem_id, item in store_dict.items():
                # 转换为 V2 条目
                entry = MemoryEntry(
                    id=mem_id,
                    content=item.value,
                    summary=item.summary or item.value[:200],
                    tags=item.tags,
                    entities=item.entities,
                    mem_type=self._map_old_type(item),
                    source=item.source,
                    importance=item.importance,
                    access_count=item.access_count,
                    created_at=item.created_at,
                    updated_at=item.last_accessed,
                    meta={
                        "old_level": level.name,
                        "old_confidence": item.confidence,
                    },
                )
                self._entries[mem_id] = entry

                # 添加到向量存储
                self.vector_store.add(
                    text=item.value,
                    meta={"id": mem_id, "tags": item.tags},
                    entry_id=mem_id,
                )

                # 添加到知识图谱
                for entity in item.entities:
                    self.knowledge_graph.add_entity(entity)
                    self.knowledge_graph.link_memory(entity, mem_id)

                imported += 1

        if imported > 0:
            self.vector_store.rebuild_index()
            self._save_all()
            import logging
            logging.getLogger("meshctx.memory_v2").info(
                f"从旧版导入 {imported} 条记忆"
            )

    @staticmethod
    def _map_old_type(item) -> str:
        """映射旧版记忆层次到类型"""
        from .memory_hierarchy import MemoryLevel
        mapping = {
            MemoryLevel.SENSORY: "episode",
            MemoryLevel.WORKING: "episode",
            MemoryLevel.SHORT_TERM: "fact",
            MemoryLevel.LONG_TERM: "skill",
            MemoryLevel.ARCHIVAL: "fact",
        }
        return mapping.get(item.level, "fact")

    # ── 核心操作 ──────────────────────────────────────────

    def add(self, content: str, tags: List[str] = None,
            entities: List[str] = None,
            mem_type: str = "fact",
            source: str = "user",
            importance: float = 0.5) -> MemoryEntry:
        """添加记忆"""
        entry = MemoryEntry(
            content=content,
            summary=content[:200],
            tags=tags or [],
            entities=entities or [],
            mem_type=mem_type,
            source=source,
            importance=importance,
        )

        # 存储条目
        self._entries[entry.id] = entry

        # 向量索引
        self.vector_store.add(
            text=content,
            meta={"id": entry.id, "tags": tags or [], "type": mem_type},
            entry_id=entry.id,
        )

        # 知识图谱
        for entity in (entities or []):
            self.knowledge_graph.add_entity(entity)
            self.knowledge_graph.link_memory(entity, entry.id)

        # 自动提取实体
        auto_entities = self._extract_entities(content)
        for ae in auto_entities:
            if ae not in (entities or []):
                self.knowledge_graph.add_entity(ae)
                self.knowledge_graph.link_memory(ae, entry.id)

        # 持久化
        self._save_all()

        return entry

    def search(self, query: str, top_k: int = 10,
               mem_type: str = None,
               tags: List[str] = None) -> List[Dict]:
        """
        语义搜索记忆

        检索策略: 向量相似度 + 图谱增强
        """
        # 向量检索
        filter_meta = {}
        if mem_type:
            filter_meta["type"] = mem_type

        vec_results = self.vector_store.search(
            query, top_k=top_k * 2, filter_meta=filter_meta
        )

        # 图谱增强: 搜索相关实体
        kg_entities = self.knowledge_graph.search_entities(query)
        kg_memory_ids = set()
        for entity in kg_entities:
            kg_memory_ids.update(
                self.knowledge_graph.get_entity_memories(entity)
            )

        # 合并结果
        results = []
        seen_ids = set()

        # 先添加向量检索结果
        for entry, score in vec_results:
            mem_entry = self._entries.get(entry.id)
            if not mem_entry:
                continue
            if tags and not any(t in mem_entry.tags for t in tags):
                continue

            # 图谱加成
            kg_boost = 1.2 if entry.id in kg_memory_ids else 1.0

            mem_entry.touch()
            results.append({
                **mem_entry.to_dict(),
                "score": round(score * kg_boost, 4),
                "match_type": "semantic",
            })
            seen_ids.add(entry.id)

        # 补充图谱关联的记忆
        for mid in kg_memory_ids - seen_ids:
            mem_entry = self._entries.get(mid)
            if not mem_entry:
                continue
            if tags and not any(t in mem_entry.tags for t in tags):
                continue
            if len(results) >= top_k:
                break
            mem_entry.touch()
            results.append({
                **mem_entry.to_dict(),
                "score": 0.6,
                "match_type": "graph",
            })
            seen_ids.add(mid)

        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        """获取单条记忆"""
        entry = self._entries.get(memory_id)
        if entry:
            entry.touch()
        return entry

    def remove(self, memory_id: str) -> bool:
        """删除记忆"""
        self.vector_store.remove(memory_id)
        if memory_id in self._entries:
            del self._entries[memory_id]
            self._save_all()
            return True
        return False

    def list_by_type(self, mem_type: str = None) -> List[MemoryEntry]:
        """按类型列出记忆"""
        if mem_type:
            return [e for e in self._entries.values()
                    if e.mem_type == mem_type]
        return list(self._entries.values())

    def list_by_tag(self, tag: str) -> List[MemoryEntry]:
        """按标签列出记忆"""
        return [e for e in self._entries.values() if tag in e.tags]

    # ── 实体提取 ──────────────────────────────────────────

    @staticmethod
    def _extract_entities(text: str) -> List[str]:
        """简单实体提取 (中文人名、地名、专有名词)"""
        entities = []
        # 提取英文大写开头的连续词 (专有名词)
        for match in re.finditer(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text):
            entities.append(match.group())
        # 提取中文引号内容
        for match in re.finditer(r'[「「]([^」」]+)[」」]', text):
            entities.append(match.group(1))
        return entities[:10]  # 最多10个

    # ── 知识图谱 API ──────────────────────────────────────

    def add_entity(self, name: str, entity_type: str = "concept",
                   properties: Dict = None) -> str:
        return self.knowledge_graph.add_entity(
            name, entity_type, properties
        )

    def add_relation(self, subject: str, relation: str,
                     object_: str, weight: float = 1.0):
        self.knowledge_graph.add_relation(
            subject, relation, object_, weight
        )
        self.knowledge_graph.save()

    def get_graph_data(self) -> Dict[str, Any]:
        """获取图谱可视化数据"""
        return self.knowledge_graph.to_graph_data()

    def search_graph(self, query: str) -> Dict[str, Any]:
        """搜索知识图谱"""
        entities = self.knowledge_graph.search_entities(query)
        neighbors = set()
        relations = []
        for e in entities:
            neighbors.update(self.knowledge_graph.get_neighbors(e))
            relations.extend(self.knowledge_graph.get_relations(e))

        return {
            "query": query,
            "matched_entities": entities,
            "related_entities": sorted(neighbors - set(entities)),
            "relations": relations[:50],
        }

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计"""
        type_counts = defaultdict(int)
        for e in self._entries.values():
            type_counts[e.mem_type] += 1

        return {
            "total_memories": len(self._entries),
            "by_type": dict(type_counts),
            "vector_store": self.vector_store.get_stats(),
            "knowledge_graph": self.knowledge_graph.get_stats(),
            "storage_dir": str(MEMORY_V2_DIR),
        }

    # ── 持久化 ────────────────────────────────────────────

    def _save_all(self):
        """保存所有数据"""
        self.vector_store.save()
        self.knowledge_graph.save()
        self._save_items()

    def _save_items(self):
        """保存记忆条目"""
        data = []
        for entry in self._entries.values():
            data.append(entry.to_dict())
        tmp = str(ITEMS_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(ITEMS_FILE))

    def _load_items(self):
        """加载记忆条目"""
        if not ITEMS_FILE.exists():
            return
        try:
            with open(ITEMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return

        for d in data:
            entry = MemoryEntry.from_dict(d)
            self._entries[entry.id] = entry


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """获取全局 MemoryManager 单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
        _memory_manager.initialize()
    return _memory_manager

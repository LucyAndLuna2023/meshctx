"""Memory Hierarchy — hierarchical memory store with persistence (v3.115+)"""

from __future__ import annotations
import json
import os
import time
import uuid
import math
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional


# ── enums ──────────────────────────────────────────────────────────────

class MemoryLevel(Enum):
    SENSORY = -1
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4
    WORKING = 2
    SHORT_TERM = 1
    LONG_TERM = 3
    ARCHIVAL = 4


# ── VectorIndex ────────────────────────────────────────────────────────

class VectorIndex:
    """Simple in-memory cosine-similarity vector index."""

    def __init__(self, dim: int = 384):
        self._dim = dim
        self._vectors: dict[str, list[float]] = {}

    @property
    def dim(self) -> int:
        return self._dim

    def add(self, item_id: str, embedding: list[float]):
        self._vectors[item_id] = list(embedding)
        if len(embedding) != self._dim and self._dim == 384:
            self._dim = len(embedding)

    def count(self) -> int:
        return len(self._vectors)

    def search(self, query: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        if not self._vectors:
            return []
        results = []
        for vid, vec in self._vectors.items():
            sim = self._cosine_similarity(query, vec)
            results.append((vid, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def to_dict(self) -> dict:
        return {
            "dim": self._dim,
            "vectors": [
                {"id": vid, "embedding": vec}
                for vid, vec in self._vectors.items()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> VectorIndex:
        dim = data.get("dim", 384)
        vi = cls(dim=dim)
        for entry in data.get("vectors", []):
            vi.add(entry["id"], entry["embedding"])
        return vi


# ── KnowledgeGraph ──────────────────────────────────────────────────────

class KnowledgeGraph:
    """Simple entity-relation knowledge graph."""

    def __init__(self):
        self._entities: dict[str, dict] = {}
        self._relations: dict[tuple, float] = {}
        self._entity_memories: dict[str, set] = {}

    def add_entity(self, name: str, etype: str, properties: dict | None = None):
        self._entities[name] = {
            "type": etype,
            "properties": properties or {},
        }

    def add_relation(self, source: str, relation: str, target: str, weight: float = 1.0):
        self._relations[(source, relation, target)] = weight

    def link_memory(self, entity: str, memory_id: str):
        if entity not in self._entity_memories:
            self._entity_memories[entity] = set()
        self._entity_memories[entity].add(memory_id)

    def search_entities(self, query: str) -> set[str]:
        results = set()
        qlower = query.lower()
        for name in self._entities:
            if qlower in name.lower():
                results.add(name)
        return results

    def get_related_memories(self, entity: str) -> set[str]:
        return self._entity_memories.get(entity, set())

    def get_stats(self) -> dict:
        return {
            "entities": len(self._entities),
            "relations": len(self._relations),
            "entity_memory_links": sum(len(v) for v in self._entity_memories.values()),
        }

    def to_dict(self) -> dict:
        return {
            "entities": {
                name: {"type": data["type"], "properties": data["properties"]}
                for name, data in self._entities.items()
            },
            "relations": [
                {"source": s, "relation": r, "target": t, "weight": w}
                for (s, r, t), w in self._relations.items()
            ],
            "entity_memories": {
                k: list(v) for k, v in self._entity_memories.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> KnowledgeGraph:
        kg = cls()
        for name, edata in data.get("entities", {}).items():
            kg.add_entity(name, edata.get("type", ""), edata.get("properties", {}))
        for rel in data.get("relations", []):
            kg.add_relation(
                rel["source"], rel["relation"], rel["target"],
                weight=rel.get("weight", 1.0),
            )
        for entity, mem_ids in data.get("entity_memories", {}).items():
            for mid in mem_ids:
                kg.link_memory(entity, mid)
        return kg


# ── HierarchicalMemoryItem ─────────────────────────────────────────────────────────

@dataclass
class HierarchicalHierarchicalMemoryItem:
    """A single memory item with metadata."""
    level: MemoryLevel = MemoryLevel.L1
    key: str = ""
    value: str = ""
    id: str = ""
    content: str = ""
    summary: str = ""
    project_id: str = ""
    conversation_id: str = ""
    source: str = ""
    importance: float = 0.5
    access_count: int = 0
    review_count: int = 0
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.5
    is_corrected: bool = False
    correction_history: list[dict] = field(default_factory=list)
    related_memory_ids: list[str] = field(default_factory=list)
    embedding: Optional[list[float]] = None
    created_at: float = 0.0
    last_accessed: float = 0.0
    last_reviewed: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = time.time()

    def current_retention(self) -> float:
        elapsed = time.time() - (self.last_reviewed or self.created_at or time.time())
        hours = elapsed / 3600
        return max(0.05, 1.0 / (1.0 + hours * 0.8))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.value,
            "key": self.key,
            "value": self.value,
            "content": self.content or self.value,
            "summary": self.summary,
            "importance": self.importance,
            "created_at": self.created_at,
            "last_reviewed": self.last_reviewed,
        }

    def to_json_dict(self) -> dict:
        return {
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
            "tags": list(self.tags),
            "entities": list(self.entities),
            "related_memory_ids": list(self.related_memory_ids),
            "confidence": self.confidence,
            "is_corrected": self.is_corrected,
            "correction_history": list(self.correction_history),
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> HierarchicalMemoryItem:
        level_val = data.get("level", 0)
        level = MemoryLevel(level_val)
        return cls(
            id=data.get("id", ""),
            level=level,
            key=data.get("key", ""),
            value=data.get("value", ""),
            summary=data.get("summary", ""),
            embedding=data.get("embedding"),
            project_id=data.get("project_id", ""),
            conversation_id=data.get("conversation_id", ""),
            source=data.get("source", ""),
            created_at=data.get("created_at", 0.0),
            last_accessed=data.get("last_accessed", 0.0),
            last_reviewed=data.get("last_reviewed", 0.0),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            review_count=data.get("review_count", 0),
            tags=data.get("tags", []),
            entities=data.get("entities", []),
            related_memory_ids=data.get("related_memory_ids", []),
            confidence=data.get("confidence", 0.5),
            is_corrected=data.get("is_corrected", False),
            correction_history=data.get("correction_history", []),
        )


# ── EbbinghausForgetting ───────────────────────────────────────────────

class EbbinghausForgetting:
    """Ebbinghaus forgetting curve model."""

    def __init__(self):
        pass

    def decay(self, elapsed_hours: float = 0.0) -> float:
        if elapsed_hours <= 0:
            return 1.0
        return max(0.05, 1.0 / (1.0 + elapsed_hours * 0.8))


# ── HierarchicalMemoryStore ────────────────────────────────────────────

class HierarchicalMemoryStore:
    """Hierarchical memory store with persistence, vector index, and knowledge graph."""

    PERSISTENCE_VERSION: int = 1

    def __init__(self):
        self._items: dict[str, HierarchicalMemoryItem] = {}
        self._ordered_ids: list[str] = []
        self.vector_index = VectorIndex(dim=384)
        self.knowledge_graph = KnowledgeGraph()
        self._auto_save_threshold: int = 0
        self._auto_save_path: str = ""
        self._auto_save_counter: int = 0

    # ── store / retrieve ──

    def store(self, item: HierarchicalMemoryItem):
        self._items[item.id] = item
        if item.id not in self._ordered_ids:
            self._ordered_ids.append(item.id)
        self._auto_save_counter += 1
        if self._auto_save_threshold > 0 and self._auto_save_counter >= self._auto_save_threshold:
            self.save_to_file(self._auto_save_path)
            self._auto_save_counter = 0

    def retrieve(self, query: str, top_k: int = 5) -> list[HierarchicalHierarchicalMemoryItem]:
        results = []
        qlower = query.lower()
        for item in self._items.values():
            score = 0.0
            if qlower in item.key.lower():
                score += 2.0
            if qlower in item.value.lower():
                score += 1.0
            if qlower in (item.content or "").lower():
                score += 1.0
            if qlower in (item.summary or "").lower():
                score += 1.5
            if score > 0:
                results.append((score, item))
        results.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in results[:top_k]]

    def recall(self, query: str) -> list[HierarchicalHierarchicalMemoryItem]:
        return self.retrieve(query)

    def compact(self):
        """Deduplicate items by key, keeping the most recent (last stored)."""
        seen: dict[str, HierarchicalMemoryItem] = {}
        for item in self._items.values():
            seen[item.key] = item
        self._items = {item.id: item for item in seen.values()}
        self._ordered_ids = list(self._items.keys())

    def _all_items(self):
        """Yield (id, item) pairs for all stored items."""
        for item_id in self._ordered_ids:
            if item_id in self._items:
                yield (item_id, self._items[item_id])

    # ── stats ──

    # Map canonical enum values to preferred display names
    _LEVEL_DISPLAY = {
        -1: "SENSORY",
        0: "L0",
        1: "SHORT_TERM",
        2: "WORKING",
        3: "LONG_TERM",
        4: "ARCHIVAL",
    }

    def get_stats(self) -> dict:
        level_counts: dict[str, int] = {}
        for item in self._items.values():
            display = self._LEVEL_DISPLAY.get(item.level.value, item.level.name)
            level_counts[display] = level_counts.get(display, 0) + 1

        base = {
            "SENSORY": {"count": level_counts.get("SENSORY", 0)},
            "L0": {"count": level_counts.get("L0", 0)},
            "L1": {"count": level_counts.get("L1", 0)},
            "L2": {"count": level_counts.get("L2", 0)},
            "L3": {"count": level_counts.get("L3", 0)},
            "L4": {"count": level_counts.get("L4", 0)},
            "WORKING": {"count": level_counts.get("WORKING", 0)},
            "SHORT_TERM": {"count": level_counts.get("SHORT_TERM", 0)},
            "LONG_TERM": {"count": level_counts.get("LONG_TERM", 0)},
            "ARCHIVAL": {"count": level_counts.get("ARCHIVAL", 0)},
            "total_items": len(self._items),
        }

        base["vector_index"] = {"count": self.vector_index.count()}
        base["knowledge_graph"] = self.knowledge_graph.get_stats()
        return base

    def stats(self) -> dict:
        return self.get_stats()

    # ── persistence ──

    def set_auto_save(self, path: str, threshold: int = 0):
        self._auto_save_path = path
        self._auto_save_threshold = threshold
        self._auto_save_counter = 0

    def save_to_file(self, path: str) -> str:
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

        data = {
            "version": self.PERSISTENCE_VERSION,
            "meta": {
                "saved_at": time.time(),
                "total_items": len(self._items),
                "total_stores": len(self._items),
                "vector_count": self.vector_index.count(),
                "graph_stats": self.knowledge_graph.get_stats(),
            },
            "items": [item.to_json_dict() for item in self._items.values()],
            "vector_index": self.vector_index.to_dict(),
            "knowledge_graph": self.knowledge_graph.to_dict(),
        }

        tmp_path = abs_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, abs_path)
        return abs_path

    @classmethod
    def load_from_file(cls, path: str) -> HierarchicalMemoryStore:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise IOError(f"Invalid JSON in file: {path}") from e

        version = data.get("version", -1)
        if version < 1 or version > cls.PERSISTENCE_VERSION:
            if version > cls.PERSISTENCE_VERSION:
                raise ValueError(f"版本不兼容: file version {version} > store version {cls.PERSISTENCE_VERSION}")
            raise ValueError(f"版本不兼容: file version {version} != store version {cls.PERSISTENCE_VERSION}")

        store = cls()

        for item_data in data.get("items", []):
            item = HierarchicalMemoryItem.from_json_dict(item_data)
            store._items[item.id] = item
            store._ordered_ids.append(item.id)
            if item.embedding:
                store.vector_index.add(item.id, item.embedding)

        vi_data = data.get("vector_index", {})
        if vi_data:
            store.vector_index = VectorIndex.from_dict(vi_data)

        kg_data = data.get("knowledge_graph", {})
        if kg_data:
            store.knowledge_graph = KnowledgeGraph.from_dict(kg_data)

        return store


# ── MemoryPlugin ───────────────────────────────────────────────────────

class MemoryPlugin:
    """Memory plugin for kernel integration."""

    info = type("Info", (), {
        "name": "memory",
        "version": "0.1",
        "dependencies": [],
        "category": "memory",
        "description": "Memory stub",
    })()

    state: str = "active"

    def __init__(self, **kw):
        self.store = HierarchicalMemoryStore()

    async def on_load(self, kernel) -> bool:
        return True

    async def on_event(self, event):
        """Handle events like message.added → store in memory."""
        if event.type == "message.added":
            content = event.data.get("content", "")
            speaker = event.data.get("role", "unknown")
            ts = event.data.get("timestamp", "")
            self.store.store(HierarchicalHierarchicalMemoryItem(
                content=content[:200],
                source=event.source,
                importance=0.8,
                tags=["conversation"],
            ))
        return True

    def generate_report(self) -> dict:
        return {"name": "memory", "state": "stub"}

"""Memory Hierarchy — hierarchical memory store with persistence (v3.115+)

本文件为 meshctx 开源实现（优雅降级版）：
  - 提供完整的、可工作的内存层级存储 / 向量索引 / 知识图谱 / 持久化功能，
    供开源社区开发、测试与二次开发使用。
  - 商业/完整版（更大规模、分布式、加密存储等增强能力）位于私有仓库
    meshctx-core（pip install meshctx-core，需授权）。
  - 设置环境变量 MESHCTX_STRICT=1 时，未安装 meshctx-core 的导入将抛 ImportError，
    以便在需要完整实现的场景下显式失败而非静默降级。
"""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field
from typing import Optional

_STRICT = os.environ.get("MESHCTX_STRICT") == "1"


class _MeshCtxStubProxy:
    """未导出符号的优雅降级代理: 导入成功, 调用/属性访问时提示需 meshctx-core。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return _MeshCtxStubProxy(f"{self._name}.{attr}")

    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"meshctx-core required (private repo): {self._name}")

    def __repr__(self):
        return f"<meshctx stub {self._name}>"


def __getattr__(name):
    if _STRICT:
        raise ImportError(f"meshctx-core required (private repo): {name}")
    return _MeshCtxStubProxy(name)


class MemoryLevel(Enum):
    SENSORY = "SENSORY"
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4
    WORKING = 2
    SHORT_TERM = 1
    LONG_TERM = 3
    ARCHIVAL = 4


class VectorIndex:
    """Simple in-memory cosine-similarity vector index (open-source fallback)."""

    def __init__(self, dim: int = 384):
        self._dim = int(dim)
        self._vectors: dict[str, list[float]] = {}

    @property
    def dim(self) -> int:
        return self._dim

    def add(self, item_id: str, embedding: list[float]):
        if not embedding:
            return
        self._vectors[item_id] = [float(x) for x in embedding]
        # 自适应维度：以首个实际向量维度为准
        self._dim = len(embedding)

    def count(self) -> int:
        return len(self._vectors)

    def search(self, query: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        if not self._vectors or not query:
            return []
        scored = []
        for item_id, emb in self._vectors.items():
            scored.append((item_id, self._cosine_similarity(query, emb)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            # 维度不一致时按最短维度对齐比较
            n = min(len(a), len(b))
            a, b = a[:n], b[:n]
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    def to_dict(self) -> dict:
        return {
            "dim": self._dim,
            "vectors": [
                {"id": item_id, "embedding": emb}
                for item_id, emb in self._vectors.items()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VectorIndex":
        vi = cls(dim=int(data.get("dim", 384)))
        for entry in data.get("vectors", []):
            vi.add(entry["id"], entry["embedding"])
        # 空时保持文件记录的 dim
        if not data.get("vectors"):
            vi._dim = int(data.get("dim", 384))
        return vi


class KnowledgeGraph:
    """Simple entity-relation knowledge graph (open-source fallback)."""

    def __init__(self):
        self._entities: dict[str, dict] = {}
        self._relations: dict[tuple, float] = {}
        self._entity_memories: dict[str, set] = {}

    def add_entity(self, name: str, etype: str, properties: dict | None = None):
        self._entities[name] = {"type": etype, "properties": dict(properties or {})}

    def add_relation(self, source: str, relation: str, target: str, weight: float = 1.0):
        self._relations[(source, relation, target)] = float(weight)

    def link_memory(self, entity: str, memory_id: str):
        self._entity_memories.setdefault(entity, set()).add(memory_id)

    def search_entities(self, query: str) -> set[str]:
        q = (query or "").lower()
        out = set()
        for name, info in self._entities.items():
            if q in name.lower() or q in str(info.get("type", "")).lower():
                out.add(name)
        return out

    def get_related_memories(self, entity: str) -> set[str]:
        return set(self._entity_memories.get(entity, set()))

    def get_stats(self) -> dict:
        return {
            "entities": len(self._entities),
            "relations": len(self._relations),
            "entity_memory_links": sum(len(v) for v in self._entity_memories.values()),
        }

    def to_dict(self) -> dict:
        return {
            "entities": {
                name: {
                    "type": info["type"],
                    "properties": info["properties"],
                }
                for name, info in self._entities.items()
            },
            "relations": [
                {
                    "source": s,
                    "relation": r,
                    "target": t,
                    "weight": w,
                }
                for (s, r, t), w in self._relations.items()
            ],
            "entity_memories": {
                name: sorted(mems) for name, mems in self._entity_memories.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeGraph":
        kg = cls()
        for name, info in (data.get("entities") or {}).items():
            if isinstance(info, dict):
                kg._entities[name] = {
                    "type": info.get("type", "concept"),
                    "properties": dict(info.get("properties") or {}),
                }
        for rel in data.get("relations") or []:
            kg._relations[(rel["source"], rel["relation"], rel["target"])] = float(
                rel.get("weight", 1.0)
            )
        for name, mems in (data.get("entity_memories") or {}).items():
            kg._entity_memories[name] = set(mems)
        return kg


@dataclass
class MemoryItem:
    """A single memory item with metadata."""

    level: MemoryLevel = None
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
    tags: list[str] = None
    entities: list[str] = None
    confidence: float = 0.5
    is_corrected: bool = False
    correction_history: list[dict] = None
    related_memory_ids: list[str] = None
    embedding: Optional[list[float]] = None
    created_at: float = 0.0
    last_accessed: float = 0.0
    last_reviewed: float = 0.0
    # ── FSRS spaced-repetition state (phase-1) ──
    stability: float = 24.0            # S (hours, kept in hours for backward compat)
    difficulty: float = 5.0            # D in [0, 10]
    ease_factor: float = 2.5           # SM-2 ease factor (legacy)
    next_review: float = 0.0           # unix ts of next scheduled review
    lapses: int = 0                    # times forgotten

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex
        if self.tags is None:
            self.tags = []
        if self.entities is None:
            self.entities = []
        if self.correction_history is None:
            self.correction_history = []
        if self.related_memory_ids is None:
            self.related_memory_ids = []
        if self.content == "" and self.value:
            self.content = self.value
        if self.created_at == 0.0:
            self.created_at = time.time()

    def current_retention(self) -> float:
        """当前保留度（0~1），由 Ebbinghaus 遗忘曲线估算。

        用 per-item FSRS stability（小时）替代固定 24h 衰减。
        R(t) = e^(-t / S)。未复习过（last_reviewed=0）按创建时间起算。
        """
        base = self.last_reviewed if self.last_reviewed else self.created_at
        elapsed = max(0.0, time.time() - base)
        s_seconds = max(1e-6, float(self.stability or 24.0) * 3600.0)  # 小时→秒
        return max(0.05, min(1.0, math.exp(-elapsed / s_seconds)))

    def review_urgency(self) -> float:
        """FSRS 检索紧迫度：importance × (1 - R)。

        到期/即将遗忘的高价值记忆获得更高注入优先级。
        """
        r = self.current_retention()
        return float(self.importance or 0.5) * (1.0 - r)

    def is_due(self, now: float | None = None) -> bool:
        """是否到期（next_review <= now 或从未安排复习）。"""
        now = now or time.time()
        if self.next_review <= 0:
            return True
        return now >= self.next_review

    def to_dict(self) -> dict:
        return self.to_json_dict()

    def to_json_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.value if isinstance(self.level, MemoryLevel) else self.level,
            "key": self.key,
            "value": self.value,
            "content": self.content,
            "summary": self.summary,
            "project_id": self.project_id,
            "conversation_id": self.conversation_id,
            "source": self.source,
            "importance": self.importance,
            "access_count": self.access_count,
            "review_count": self.review_count,
            "tags": list(self.tags or []),
            "entities": list(self.entities or []),
            "confidence": self.confidence,
            "is_corrected": self.is_corrected,
            "correction_history": list(self.correction_history or []),
            "related_memory_ids": list(self.related_memory_ids or []),
            "embedding": list(self.embedding) if self.embedding is not None else None,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "last_reviewed": self.last_reviewed,
            "stability": self.stability,
            "difficulty": self.difficulty,
            "ease_factor": self.ease_factor,
            "next_review": self.next_review,
            "lapses": self.lapses,
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> "MemoryItem":
        level = data.get("level")
        if isinstance(level, str):
            level = MemoryLevel(level)
        elif isinstance(level, (int, float)):
            level = MemoryLevel(int(level))
        else:
            level = MemoryLevel.WORKING
        return cls(
            id=data.get("id", ""),
            level=level,
            key=data.get("key", ""),
            value=data.get("value", ""),
            content=data.get("content", ""),
            summary=data.get("summary", ""),
            project_id=data.get("project_id", ""),
            conversation_id=data.get("conversation_id", ""),
            source=data.get("source", ""),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            review_count=data.get("review_count", 0),
            tags=data.get("tags", []),
            entities=data.get("entities", []),
            confidence=data.get("confidence", 0.5),
            is_corrected=data.get("is_corrected", False),
            correction_history=data.get("correction_history", []),
            related_memory_ids=data.get("related_memory_ids", []),
            embedding=data.get("embedding"),
            created_at=data.get("created_at", 0.0),
            last_accessed=data.get("last_accessed", 0.0),
            last_reviewed=data.get("last_reviewed", 0.0),
            stability=data.get("stability", 24.0),
            difficulty=data.get("difficulty", 5.0),
            ease_factor=data.get("ease_factor", 2.5),
            next_review=data.get("next_review", 0.0),
            lapses=data.get("lapses", 0),
        )


class EbbinghausForgetting:
    """Ebbinghaus forgetting curve model (open-source fallback)."""

    def __init__(self, strength: float = 1.0, stability: float = 24.0):
        self.strength = strength
        self.stability = stability

    def decay(self, elapsed_hours: float = 0.0) -> float:
        """返回经过 elapsed_hours 小时后的记忆保留度（0~1）。"""
        if elapsed_hours <= 0:
            return 1.0
        return max(0.0, math.exp(-float(elapsed_hours) / max(1e-6, self.stability)))


class HierarchicalMemoryStore:
    """Hierarchical memory store with persistence, vector index, and knowledge graph.

    开源降级实现：内存存储 + JSON 文件持久化（原子写入）。
    完整实现（分布式/加密/大规模）见 meshctx-core。
    """

    PERSISTENCE_VERSION = 1

    _LEVEL_DISPLAY = {-1: "SENSORY", 0: "L0", 1: "SHORT_TERM", 2: "WORKING", 3: "LONG_TERM", 4: "ARCHIVAL"}

    def __init__(self):
        self._items: dict[str, MemoryItem] = {}
        self.vector_index = VectorIndex(dim=384)
        self.knowledge_graph = KnowledgeGraph()
        self._auto_save_path: str | None = None
        self._auto_save_threshold: int = 0
        self._pending_writes: int = 0

    @staticmethod
    def _level_key(item: MemoryItem) -> str:
        lv = item.level
        if isinstance(lv, MemoryLevel):
            if lv == MemoryLevel.SENSORY:
                return "SENSORY"
            return HierarchicalMemoryStore._LEVEL_DISPLAY.get(lv.value, str(lv.value))
        return HierarchicalMemoryStore._LEVEL_DISPLAY.get(int(lv), str(lv))

    def store(self, item: MemoryItem):
        if not item.id:
            item.id = uuid.uuid4().hex
        if item.created_at == 0.0:
            item.created_at = time.time()
        self._items[item.id] = item
        if item.embedding:
            self.vector_index.add(item.id, item.embedding)
        # auto-save 计数
        if self._auto_save_path and self._auto_save_threshold > 0:
            self._pending_writes += 1
            if self._pending_writes >= self._auto_save_threshold:
                self.save_to_file(self._auto_save_path)
                self._pending_writes = 0

    def store_with_merge(self, item: MemoryItem, sim_threshold: float = 0.9) -> MemoryItem:
        """M2: 记忆合并去重 — key 相等或相似度≥阈值时合并，importance 累加。

        判定顺序：① key 相等 ② 向量余弦相似度 ③ 文本相似度（difflib 兜底）。
        合并策略：importance 累加（封顶 1.0），value 保留最新，last_reviewed 取最新。
        """
        import difflib
        target = None
        for ex in self._items.values():
            # ① key 相等
            if ex.key and item.key and ex.key == item.key:
                target = ex
                break
            # ② 向量相似度
            if getattr(ex, "embedding", None) and getattr(item, "embedding", None):
                try:
                    ex_emb = list(ex.embedding)
                    it_emb = list(item.embedding)
                    dot = sum(a * b for a, b in zip(ex_emb, it_emb))
                    norm_ex = sum(a * a for a in ex_emb) ** 0.5
                    norm_it = sum(b * b for b in it_emb) ** 0.5
                    if norm_ex and norm_it and (dot / (norm_ex * norm_it)) >= sim_threshold:
                        target = ex
                        break
                except Exception:
                    pass
            # ③ 文本相似度兜底（仅比较 value；key 已在①判定）
            a = (ex.value or ex.content or "").strip()
            b = (item.value or item.content or "").strip()
            if a and b and difflib.SequenceMatcher(None, a, b).ratio() >= sim_threshold:
                target = ex
                break
        if target is not None:
            target.importance = min(1.0, float(getattr(target, "importance", 0) or 0)
                                    + float(getattr(item, "importance", 0) or 0))
            if item.value:
                target.value = item.value
            old_lr = float(getattr(target, "last_reviewed", 0) or 0)
            new_lr = float(getattr(item, "last_reviewed", 0) or 0)
            target.last_reviewed = max(old_lr, new_lr)
            if getattr(item, "embedding", None):
                target.embedding = item.embedding
                self.vector_index.add(target.id, item.embedding)
            return target
        self.store(item)
        return item

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        q = (query or "").lower()
        out = []
        for item in self._items.values():
            haystack = " ".join(
                [item.key, item.value, item.content, item.summary]
            ).lower()
            if q and q in haystack:
                out.append(item)
        # 无词匹配时返回全部（按重要性排序）
        if not out and q == "":
            out = list(self._items.values())
        # M3+FSRS: 按检索价值排序 = importance × (1 - R)（到期紧迫优先）
        out.sort(key=lambda x: x.review_urgency(), reverse=True)
        return out[:top_k] if top_k > 0 else out

    def recall(self, query: str) -> list[MemoryItem]:
        return self.retrieve(query, top_k=0)

    # ── FSRS 复习闭环（phase-1）──────────────────────────────

    def record_recall(
        self,
        item_id: str,
        grade: int | None = None,
        confidence: float | None = None,
    ) -> MemoryItem | None:
        """主动回忆回写：检索命中/复习成功时更新 FSRS 调度状态。

        修复历史缺陷：last_reviewed 只写不更新。
        更新：last_reviewed / review_count / stability / difficulty /
        ease_factor / next_review / confidence。
        """
        item = self._items.get(item_id)
        if item is None:
            return None

        from .fsrs_scheduler import FSRSScheduler, MemoryCard, grade_from_confidence

        if grade is None:
            grade = grade_from_confidence(confidence) if confidence is not None else 4

        # 复用 FSRSScheduler 状态机（S 以天为单位，MemoryItem 存小时 → 转换）
        sched = FSRSScheduler()
        card = MemoryCard(
            item_id=item.id,
            difficulty=item.difficulty,
            stability=item.stability / 24.0,
            interval_days=(
                item.next_review - (item.last_reviewed or item.created_at)
            ) / 86400.0 if item.next_review else 1.0,
            reviews=item.review_count,
            lapses=item.lapses,
            last_review=item.last_reviewed or item.created_at,
            next_review=item.next_review,
        )
        sched.set_card(card)
        sched.review(card, grade=grade)

        now = time.time()
        item.last_reviewed = now
        item.review_count = card.reviews
        item.stability = card.stability * 24.0          # 天 → 小时
        item.difficulty = card.difficulty
        item.next_review = card.next_review
        item.lapses = card.lapses
        if confidence is not None:
            item.confidence = max(0.0, min(1.0, confidence))
        item.last_accessed = now
        return item

    def record_lapse(self, item_id: str) -> MemoryItem | None:
        """遗忘惩罚（主动遗忘）：grade=0 → stability 减半、间隔重置 1 天。"""
        return self.record_recall(item_id, grade=0)

    def get_due_items(self, now: float | None = None) -> list[MemoryItem]:
        """FSRS 到期条目：用于复习调度与预算裁剪（token 节省）。"""
        now = now or time.time()
        return [it for it in self._items.values() if it.is_due(now)]

    def fsrs_stats(self) -> dict:
        """FSRS 闭环统计。"""
        items = list(self._items.values())
        if not items:
            return {"total_items": 0, "due_items": 0}
        return {
            "total_items": len(items),
            "due_items": len(self.get_due_items()),
            "avg_stability_hours": sum(float(i.stability or 24.0) for i in items) / len(items),
            "avg_difficulty": sum(float(i.difficulty or 5.0) for i in items) / len(items),
            "total_reviews": sum(i.review_count for i in items),
            "total_lapses": sum(i.lapses for i in items),
        }

    def compact(self):
        """Deduplicate items by key, keeping the most recent (last stored)."""
        seen: dict[str, MemoryItem] = {}
        for item in self._items.values():
            seen[item.key] = item
        self._items = {item.id: item for item in seen.values()}

    def _all_items(self):
        """Yield (id, item) pairs for all stored items."""
        yield from self._items.items()

    def get_stats(self) -> dict:
        counts = {name: {"count": 0} for name in ["SENSORY", "L0", "SHORT_TERM", "WORKING", "LONG_TERM", "ARCHIVAL"]}
        for item in self._items.values():
            key = self._level_key(item)
            counts.setdefault(key, {"count": 0})
            counts[key]["count"] += 1
        return {
            **counts,
            "total_items": len(self._items),
            "vector_index": {"count": self.vector_index.count()},
            "knowledge_graph": self.knowledge_graph.get_stats(),
        }

    def stats(self) -> dict:
        return self.get_stats()

    def set_auto_save(self, path: str, threshold: int = 0):
        self._auto_save_path = path
        self._auto_save_threshold = int(threshold)
        self._pending_writes = 0

    def save_to_file(self, path: str) -> str:
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
        abs_path = os.path.abspath(path)
        tmp_path = abs_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, abs_path)
        except OSError:
            # 失败时不遗留 .tmp 部分文件
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise
        return abs_path

    @classmethod
    def load_from_file(cls, path: str) -> "HierarchicalMemoryStore":
        if not os.path.exists(path):
            raise FileNotFoundError(f"memory snapshot not found: {path}")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise IOError(f"invalid memory snapshot JSON: {e}")
        version = data.get("version")
        if version != cls.PERSISTENCE_VERSION:
            raise ValueError(
                f"版本不兼容: 文件 version={version}, 当前 PERSISTENCE_VERSION={cls.PERSISTENCE_VERSION}"
            )
        store = cls()
        for entry in data.get("items", []):
            item = MemoryItem.from_json_dict(entry)
            store._items[item.id] = item
            if item.embedding:
                store.vector_index.add(item.id, item.embedding)
        if "vector_index" in data:
            store.vector_index = VectorIndex.from_dict(data["vector_index"])
        if "knowledge_graph" in data:
            store.knowledge_graph = KnowledgeGraph.from_dict(data["knowledge_graph"])
        return store


class MemoryPlugin:
    """Memory plugin for kernel integration (open-source fallback)."""

    info = "meshctx memory plugin (open-source fallback)"

    def __init__(self, **kw):
        self.kernel = None
        self.store = HierarchicalMemoryStore()
        self._config = dict(kw)

    async def on_load(self, kernel) -> bool:
        self.kernel = kernel
        return True

    async def on_event(self, event):
        """Handle events like message.added → store in memory."""
        try:
            etype = getattr(event, "type", None)
            if etype == "message.added":
                payload = getattr(event, "payload", {}) or {}
                text = payload.get("text") or payload.get("content") or ""
                if text:
                    self.store.store(
                        MemoryItem(
                            level=MemoryLevel.WORKING,
                            key=f"msg:{time.time_ns()}",
                            value=text,
                            source=payload.get("source", "user"),
                        )
                    )
        except Exception:
            pass

    def generate_report(self) -> dict:
        return {
            "plugin": "memory",
            "info": self.info,
            "stats": self.store.get_stats(),
        }


__all__ = [
    "MemoryLevel", "VectorIndex", "dim", "add", "count", "search", "to_dict", "from_dict",
    "KnowledgeGraph", "add_entity", "add_relation", "link_memory", "search_entities",
    "get_related_memories", "get_stats",
    "MemoryItem", "current_retention", "to_json_dict", "from_json_dict",
    "EbbinghausForgetting", "decay",
    "HierarchicalMemoryStore", "store", "retrieve", "recall", "compact", "stats",
    "set_auto_save", "save_to_file", "load_from_file",
    "MemoryPlugin", "on_load", "on_event", "generate_report",
]

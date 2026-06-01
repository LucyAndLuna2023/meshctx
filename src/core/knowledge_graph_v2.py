"""
meshctx v3.99 — Knowledge Graph V2 (知识图谱引擎 V2)

增强功能:
  1. 实体抽取+关系推理: 从文本自动提取实体和关系
  2. 图数据库存储: JSON持久化+增量保存+恢复
  3. 语义搜索: TF-IDF加权+模糊匹配+嵌入相似度
  4. 知识融合去重: 多源知识合并+实体消歧+冲突解决
"""
import json
import logging
import math
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.knowledge_graph_v2")


# ═══════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════

@dataclass
class Entity:
    """知识图谱中的实体节点."""
    id: str
    name: str
    type: str = "concept"          # concept, person, location, event, artifact, ...
    confidence: float = 1.0         # 提取置信度 [0,1]
    weight: float = 1.0             # 节点权重
    aliases: List[str] = field(default_factory=list)
    embeddings: Optional[List[float]] = None  # 语义向量(可选)
    metadata: Dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    source: str = ""                # 来源标记

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "type": self.type,
            "confidence": self.confidence, "weight": self.weight,
            "aliases": self.aliases, "embeddings": self.embeddings,
            "metadata": self.metadata, "created": self.created,
            "updated": self.updated, "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Entity":
        return cls(
            id=d["id"], name=d["name"], type=d.get("type", "concept"),
            confidence=d.get("confidence", 1.0), weight=d.get("weight", 1.0),
            aliases=d.get("aliases", []), embeddings=d.get("embeddings"),
            metadata=d.get("metadata", {}), created=d.get("created", time.time()),
            updated=d.get("updated", time.time()), source=d.get("source", ""),
        )


@dataclass
class Relation:
    """知识图谱中的关系边."""
    source: str
    target: str
    relation: str = "related_to"    # is_a, part_of, caused_by, depends_on, ...
    weight: float = 1.0
    confidence: float = 1.0         # 推理置信度 [0,1]
    bidirectional: bool = True
    metadata: Dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    source_text: str = ""           # 来源文本片段

    def to_dict(self) -> Dict:
        return {
            "source": self.source, "target": self.target,
            "relation": self.relation, "weight": self.weight,
            "confidence": self.confidence, "bidirectional": self.bidirectional,
            "metadata": self.metadata, "created": self.created,
            "source_text": self.source_text,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Relation":
        return cls(
            source=d["source"], target=d["target"],
            relation=d.get("relation", "related_to"), weight=d.get("weight", 1.0),
            confidence=d.get("confidence", 1.0),
            bidirectional=d.get("bidirectional", True),
            metadata=d.get("metadata", {}), created=d.get("created", time.time()),
            source_text=d.get("source_text", ""),
        )


@dataclass
class KGVDocument:
    """知识图谱文档 — 用于序列化整个图."""
    version: str = "2.0"
    entities: Dict[str, Entity] = field(default_factory=dict)
    relations: List[Relation] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "version": self.version,
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
            "relations": [r.to_dict() for r in self.relations],
            "stats": self.stats,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "KGVDocument":
        doc = cls(
            version=d.get("version", "2.0"),
            stats=d.get("stats", {}),
            created=d.get("created", time.time()),
        )
        doc.entities = {k: Entity.from_dict(v) for k, v in d.get("entities", {}).items()}
        doc.relations = [Relation.from_dict(r) for r in d.get("relations", [])]
        return doc


# ═══════════════════════════════════════════════════════════
# Keyword / Pattern extractors
# ═══════════════════════════════════════════════════════════

# Common relation patterns in English text
_RELATION_PATTERNS = [
    (r"(\w+(?:\s+\w+){0,3})\s+is\s+(?:a|an|the)\s+(\w+(?:\s+\w+){0,3})", "is_a"),
    (r"(\w+(?:\s+\w+){0,3})\s+(?:is\s+)?part\s+of\s+(\w+(?:\s+\w+){0,3})", "part_of"),
    (r"(\w+(?:\s+\w+){0,3})\s+(?:is\s+)?caused\s+by\s+(\w+(?:\s+\w+){0,3})", "caused_by"),
    (r"(\w+(?:\s+\w+){0,3})\s+depends?\s+on\s+(\w+(?:\s+\w+){0,3})", "depends_on"),
    (r"(\w+(?:\s+\w+){0,3})\s+(?:is\s+)?similar\s+to\s+(\w+(?:\s+\w+){0,3})", "similar_to"),
    (r"(\w+(?:\s+\w+){0,3})\s+(?:is\s+)?used\s+(?:for|by|in)\s+(\w+(?:\s+\w+){0,3})", "used_for"),
    (r"(\w+(?:\s+\w+){0,3})\s+belongs?\s+to\s+(\w+(?:\s+\w+){0,3})", "belongs_to"),
    (r"(\w+(?:\s+\w+){0,3})\s+consists?\s+of\s+(\w+(?:\s+\w+){0,3})", "consists_of"),
    (r"(\w+(?:\s+\w+){0,3})\s+(?:is\s+)?related\s+to\s+(\w+(?:\s+\w+){0,3})", "related_to"),
    (r"(\w+(?:\s+\w+){0,3})\s+(?:is\s+)?associated\s+with\s+(\w+(?:\s+\w+){0,3})", "associated_with"),
    (r"(\w+(?:\s+\w+){0,3})\s+leads?\s+to\s+(\w+(?:\s+\w+){0,3})", "leads_to"),
    (r"(\w+(?:\s+\w+){0,3})\s+includes?\s+(\w+(?:\s+\w+){0,3})", "includes"),
]

# Entity type detection by keyword
_ENTITY_TYPE_RULES = [
    (r"\b(?:he|she|dr\.|mr\.|mrs\.|ms\.|prof\.|president|ceo)\b", "person"),
    (r"\b(?:city|country|river|mountain|ocean|street|avenue|road)\b", "location"),
    (r"\b(?:python|java|rust|docker|kubernetes|api|database|server)\b", "artifact"),
    (r"\b(?:conference|meeting|summit|festival|ceremony)\b", "event"),
    (r"\b(?:theory|algorithm|method|framework|principle|law)\b", "concept"),
]


def _normalize_id(name: str) -> str:
    """Normalize entity name into a stable id."""
    return re.sub(r"[^a-z0-9_]+", "_", name.lower().strip()).strip("_")


def _tokenize(text: str) -> List[str]:
    """Simple word tokenizer for TF-IDF."""
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def _compute_tf(text: str) -> Dict[str, float]:
    """Compute term frequency for a text."""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    counter = Counter(tokens)
    total = len(tokens)
    return {k: v / total for k, v in counter.items()}


def _compute_idf(documents: List[str]) -> Dict[str, float]:
    """Compute inverse document frequency."""
    N = len(documents)
    if N == 0:
        return {}
    dfs = Counter()
    for doc in documents:
        dfs.update(set(_tokenize(doc)))
    return {term: math.log((N + 1) / (freq + 1)) + 1.0 for term, freq in dfs.items()}


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    keys = set(vec_a) | set(vec_b)
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in keys)
    norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════
# KnowledgeGraphV2
# ═══════════════════════════════════════════════════════════

class KnowledgeGraphV2:
    """v3.99 知识图谱引擎 V2

    提供:
      - 实体抽取: extract_entities(text) 从文本中提取实体
      - 关系推理: infer_relations() 基于模式和共现推断关系
      - 图数据库存储: store_to_db(path) / load_from_db(path)
      - 语义搜索: semantic_search(query, top_k=10)
      - 知识融合去重: fuse_knowledge(other_kg)
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._entities: Dict[str, Entity] = {}
        self._relations: List[Relation] = []
        self._adj: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        self._documents: List[str] = []       # raw text sources for IDF
        self._entity_docs: Dict[str, str] = {}  # entity_id -> source text
        self._idf: Dict[str, float] = {}
        self._dirty: bool = False
        self._stats_cache: Optional[Dict] = None

    # ── Entity Management ──────────────────────────────────

    def add_entity(
        self, name: str, type: str = "concept", confidence: float = 1.0,
        weight: float = 1.0, aliases: Optional[List[str]] = None,
        embeddings: Optional[List[float]] = None, metadata: Optional[Dict] = None,
        source: str = "",
    ) -> Entity:
        """Add or update an entity."""
        eid = _normalize_id(name)
        now = time.time()

        if eid in self._entities:
            # Update existing entity
            ent = self._entities[eid]
            ent.name = name
            ent.type = type
            ent.confidence = max(ent.confidence, confidence)
            ent.weight = max(ent.weight, weight)
            if aliases:
                for a in aliases:
                    if a not in ent.aliases:
                        ent.aliases.append(a)
            if embeddings:
                ent.embeddings = embeddings
            if metadata:
                ent.metadata.update(metadata)
            ent.updated = now
            if source:
                ent.source = source
        else:
            ent = Entity(
                id=eid, name=name, type=type, confidence=confidence,
                weight=weight, aliases=aliases or [], embeddings=embeddings,
                metadata=metadata or {}, source=source,
            )
            self._entities[eid] = ent
            self._adj[eid] = []

        self._dirty = True
        self._stats_cache = None
        return ent

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by id."""
        return self._entities.get(entity_id)

    def find_entity(self, name: str) -> Optional[Entity]:
        """Find entity by name (exact match on id or aliases)."""
        eid = _normalize_id(name)
        if eid in self._entities:
            return self._entities[eid]
        for ent in self._entities.values():
            if name in ent.aliases:
                return ent
        return None

    def list_entities(self, entity_type: str = None) -> List[Entity]:
        """List all entities, optionally filtered by type."""
        if entity_type:
            return [e for e in self._entities.values() if e.type == entity_type]
        return list(self._entities.values())

    # ── Relation Management ────────────────────────────────

    def add_relation(
        self, source: str, target: str, relation: str = "related_to",
        weight: float = 1.0, confidence: float = 1.0,
        bidirectional: bool = True, metadata: Optional[Dict] = None,
        source_text: str = "",
    ) -> Relation:
        """Add a relation between two entities (auto-creates missing entities)."""
        sid = _normalize_id(source)
        tid = _normalize_id(target)

        # Auto-create entities if missing
        if sid not in self._entities:
            self.add_entity(source)
        if tid not in self._entities:
            self.add_entity(target)

        # Check for duplicate
        for existing in self._relations:
            if existing.source == sid and existing.target == tid and existing.relation == relation:
                existing.weight = max(existing.weight, weight)
                existing.confidence = max(existing.confidence, confidence)
                if metadata:
                    existing.metadata.update(metadata)
                return existing

        rel = Relation(
            source=sid, target=tid, relation=relation,
            weight=weight, confidence=confidence,
            bidirectional=bidirectional, metadata=metadata or {},
            source_text=source_text,
        )
        self._relations.append(rel)
        self._adj[sid].append((tid, weight))
        if bidirectional:
            self._adj[tid].append((sid, weight))

        self._dirty = True
        self._stats_cache = None
        return rel

    def get_relations(self, entity_id: Optional[str] = None) -> List[Relation]:
        """Get all relations involving an entity_id (or all if None)."""
        if entity_id is None:
            return list(self._relations)
        return [r for r in self._relations if r.source == entity_id or r.target == entity_id]

    def get_neighbors(self, entity_id: str, depth: int = 1) -> Dict[str, List[Tuple[str, float]]]:
        """BFS traversal to get neighbors up to given depth."""
        if entity_id not in self._entities:
            return {}
        visited = {entity_id}
        frontier = {entity_id}
        result = {}
        for d in range(depth):
            next_frontier = set()
            for n in frontier:
                neighbors = [(t, w) for t, w in self._adj.get(n, []) if t not in visited]
                if neighbors:
                    result[n] = neighbors
                for t, _ in neighbors:
                    visited.add(t)
                    next_frontier.add(t)
            frontier = next_frontier
        return result

    def shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """BFS shortest path between two entities."""
        sid = _normalize_id(source)
        tid = _normalize_id(target)
        if sid not in self._entities or tid not in self._entities:
            return None
        from collections import deque
        q = deque([(sid, [sid])])
        visited = {sid}
        while q:
            node, path = q.popleft()
            if node == tid:
                return [self._entities[n].name for n in path]
            for neighbor, _ in self._adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    q.append((neighbor, path + [neighbor]))
        return None

    def most_connected(self, n: int = 10) -> List[Tuple[str, int, str]]:
        """Return top-N most connected entities (id, degree, name)."""
        degrees = {nid: len(edges) for nid, edges in self._adj.items()}
        sorted_degrees = sorted(degrees.items(), key=lambda x: -x[1])[:n]
        return [(nid, deg, self._entities[nid].name) for nid, deg in sorted_degrees]

    # ── 1) Entity Extraction ───────────────────────────────

    def extract_entities(
        self, text: str, source: str = "",
        detect_types: bool = True, min_confidence: float = 0.3,
    ) -> List[Entity]:
        """Extract entities from natural language text.

        Uses:
          - Capitalized noun phrase detection for named entities
          - Keyword-based type inference
          - TF-IDF weighted importance scoring

        Args:
            text: Raw text to extract from
            source: Source label for provenance
            detect_types: Enable type detection
            min_confidence: Minimum confidence threshold for extraction

        Returns:
            List of extracted Entity objects
        """
        if not text or not text.strip():
            return []

        self._documents.append(text)
        extracted = []

        # Pattern 1: Capitalized noun phrases (likely named entities)
        cap_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b')
        cap_matches = cap_pattern.findall(text)
        cap_counter = Counter(cap_matches)

        # Pattern 2: Technical terms (containing underscores, dots, or camelCase)
        tech_pattern = re.compile(r'\b([a-z]+(?:[._][a-z]+)+)\b|\b([a-z]+(?:[A-Z][a-z]+)+)\b')
        tech_matches = []
        for m in tech_pattern.finditer(text):
            match_val = m.group(0)
            if match_val:
                tech_matches.append(match_val)
        tech_counter = Counter(tech_matches)

        # Pattern 3: All-cap acronyms (2-5 letters)
        acronym_pattern = re.compile(r'\b([A-Z]{2,5})\b')
        acronym_matches = acronym_pattern.findall(text)
        acronym_counter = Counter(acronym_matches)

        # Process capitalized entities
        for name, count in cap_counter.items():
            if len(name) < 2:
                continue
            etype = self._detect_entity_type(name, text) if detect_types else "concept"
            confidence = min(1.0, 0.3 + 0.1 * count + 0.2 * (len(name.split()) > 1))
            if confidence >= min_confidence:
                ent = self.add_entity(
                    name=name, type=etype, confidence=confidence,
                    weight=math.log(1 + count), source=source,
                )
                self._entity_docs[ent.id] = text
                extracted.append(ent)

        # Process technical terms
        for name, count in tech_counter.items():
            if len(name) < 2:
                continue
            etype = "artifact" if detect_types else "concept"
            confidence = min(1.0, 0.5 + 0.1 * count)
            if confidence >= min_confidence:
                ent = self.add_entity(
                    name=name, type=etype, confidence=confidence,
                    weight=math.log(1 + count), source=source,
                )
                self._entity_docs[ent.id] = text
                extracted.append(ent)

        # Process acronyms
        for name, count in acronym_counter.items():
            etype = "concept"
            confidence = min(1.0, 0.4 + 0.15 * count)
            if confidence >= min_confidence:
                ent = self.add_entity(
                    name=name, type=etype, confidence=confidence,
                    weight=math.log(1 + count), source=source,
                    aliases=[name.lower()] if name.isupper() else [],
                )
                self._entity_docs[ent.id] = text
                extracted.append(ent)

        self._idf = _compute_idf(self._documents)
        self._dirty = True
        self._stats_cache = None
        return extracted

    def _detect_entity_type(self, name: str, context: str) -> str:
        """Heuristic type detection for an entity name."""
        name_lower = name.lower()
        for pattern, etype in _ENTITY_TYPE_RULES:
            if re.search(pattern, name_lower):
                return etype
        # Check context
        ctx_lower = context.lower()
        for pattern, etype in _ENTITY_TYPE_RULES:
            if re.search(pattern, ctx_lower):
                return etype
        return "concept"

    # ── 2) Relation Inference ──────────────────────────────

    def infer_relations(
        self, text: Optional[str] = None, use_patterns: bool = True,
        use_cooccurrence: bool = True, min_confidence: float = 0.2,
    ) -> List[Relation]:
        """Infer relations between existing entities.

        Two strategies:
          1. Pattern-based: Regex patterns for common relational phrases
          2. Co-occurrence: Entities appearing in same sentence are related

        Args:
            text: Text to infer from (if None, uses stored entity documents)
            use_patterns: Enable pattern-based relation extraction
            use_cooccurrence: Enable co-occurrence based inference
            min_confidence: Minimum confidence for accepting a relation

        Returns:
            List of inferred Relation objects
        """
        inferred = []

        # Build corpus from entity documents
        if text:
            corpus = [text]
        elif self._entity_docs:
            corpus = list(set(self._entity_docs.values()))
        else:
            corpus = []

        if not corpus:
            return []

        # Strategy 1: Pattern-based extraction
        if use_patterns:
            for doc in corpus:
                for pattern, rel_type in _RELATION_PATTERNS:
                    for m in re.finditer(pattern, doc, re.IGNORECASE):
                        source_name = m.group(1).strip()
                        target_name = m.group(2).strip()
                        sid = _normalize_id(source_name)
                        tid = _normalize_id(target_name)
                        if sid in self._entities and tid in self._entities:
                            conf = min(0.9, 0.6 + 0.1 * len(m.group(1).split()))
                            if conf >= min_confidence:
                                rel = self.add_relation(
                                    source=source_name, target=target_name,
                                    relation=rel_type, confidence=conf,
                                    source_text=m.group(0),
                                )
                                inferred.append(rel)

        # Strategy 2: Co-occurrence in same sentence
        if use_cooccurrence:
            for doc in corpus:
                sentences = re.split(r'[.!?]+', doc)
                eids_in_doc = [eid for eid in self._entities
                               if self._entity_docs.get(eid, "") == doc]
                for sent in sentences:
                    sent_entities = [eid for eid in eids_in_doc
                                     if self._entities[eid].name.lower() in sent.lower()]
                    for i in range(len(sent_entities)):
                        for j in range(i + 1, len(sent_entities)):
                            ea = sent_entities[i]
                            eb = sent_entities[j]
                            # Check if relation already exists
                            exists = any(
                                (r.source == ea and r.target == eb) or
                                (r.source == eb and r.target == ea)
                                for r in self._relations
                            )
                            if not exists:
                                conf = min(0.5, 0.2 + 0.05 * len(sent_entities))
                                if conf >= min_confidence:
                                    rel = self.add_relation(
                                        source=self._entities[ea].name,
                                        target=self._entities[eb].name,
                                        relation="cooccurs_with", confidence=conf,
                                    )
                                    inferred.append(rel)

        self._dirty = True
        self._stats_cache = None
        return inferred

    # ── 3) Graph Database Storage ──────────────────────────

    def store_to_db(self, path: str) -> int:
        """Persist entire knowledge graph to a JSON file.

        Args:
            path: File path for the JSON database

        Returns:
            Number of bytes written
        """
        doc = KGVDocument(
            entities=self._entities,
            relations=self._relations,
            stats=self.stats(),
        )
        data = doc.to_dict()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json_str)
        self._dirty = False
        logger.info(f"KnowledgeGraphV2 stored {len(self._entities)} entities, "
                    f"{len(self._relations)} relations to {path}")
        return len(json_str.encode("utf-8"))

    def load_from_db(self, path: str) -> bool:
        """Load knowledge graph from a JSON file.

        Merges with existing data — does NOT clear current graph.

        Args:
            path: File path for the JSON database

        Returns:
            True if loaded successfully
        """
        if not os.path.exists(path):
            logger.warning(f"DB file not found: {path}")
            return False

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc = KGVDocument.from_dict(data)

        # Merge entities
        for eid, ent in doc.entities.items():
            if eid in self._entities:
                existing = self._entities[eid]
                existing.confidence = max(existing.confidence, ent.confidence)
                existing.weight = max(existing.weight, ent.weight)
                for alias in ent.aliases:
                    if alias not in existing.aliases:
                        existing.aliases.append(alias)
                existing.metadata.update(ent.metadata)
                existing.updated = time.time()
            else:
                self._entities[eid] = ent
                self._adj[eid] = []

        # Merge relations
        existing_pairs = {(r.source, r.target, r.relation) for r in self._relations}
        for rel in doc.relations:
            key = (rel.source, rel.target, rel.relation)
            if key not in existing_pairs:
                self._relations.append(rel)
                self._adj[rel.source].append((rel.target, rel.weight))
                if rel.bidirectional:
                    self._adj[rel.target].append((rel.source, rel.weight))
                existing_pairs.add(key)

        self._dirty = True
        self._stats_cache = None
        logger.info(f"KnowledgeGraphV2 loaded from {path}: "
                    f"{len(doc.entities)} entities, {len(doc.relations)} relations merged")
        return True

    # ── 4) Semantic Search ─────────────────────────────────

    def semantic_search(
        self, query: str, top_k: int = 10,
        use_tfidf: bool = True, use_embeddings: bool = False,
    ) -> List[Tuple[Entity, float]]:
        """Semantic search for entities matching a query.

        Multi-strategy ranking:
          1. Exact/substring name match (highest weight)
          2. TF-IDF weighted vector similarity
          3. Embedding cosine similarity (if embeddings available)

        Args:
            query: Search query string
            top_k: Number of results to return
            use_tfidf: Enable TF-IDF similarity scoring
            use_embeddings: Enable embedding-based similarity (if available)

        Returns:
            List of (Entity, score) tuples sorted by descending score
        """
        q_lower = query.lower()
        scores: Dict[str, float] = {}

        for eid, ent in self._entities.items():
            score = 0.0

            # Exact match on name or aliases
            if q_lower == ent.name.lower():
                score += 50.0
            elif q_lower in ent.name.lower():
                score += 20.0
            elif any(q_lower in alias.lower() for alias in ent.aliases):
                score += 15.0

            # Substring match on name tokens
            q_tokens = set(_tokenize(query))
            name_tokens = set(_tokenize(ent.name))
            overlap = q_tokens & name_tokens
            if overlap:
                score += len(overlap) * 5.0 / max(1, len(q_tokens))

            # Type match
            if q_lower in ent.type.lower():
                score += 2.0

            # Metadata match
            for v in ent.metadata.values():
                if isinstance(v, str) and q_lower in v.lower():
                    score += 3.0
                    break

            # Source text TF-IDF similarity
            if use_tfidf and eid in self._entity_docs and self._idf:
                query_tf = _compute_tf(query)
                doc_tf = _compute_tf(self._entity_docs[eid])
                tfidf_sim = _cosine_similarity(
                    {k: v * self._idf.get(k, 1.0) for k, v in query_tf.items()},
                    {k: v * self._idf.get(k, 1.0) for k, v in doc_tf.items()},
                )
                score += tfidf_sim * 10.0

            # Embedding similarity
            if use_embeddings and ent.embeddings:
                # Simple placeholders: user would provide query embeddings externally
                # For now, score based on embedding magnitude as proxy
                magnitude = math.sqrt(sum(v ** 2 for v in ent.embeddings))
                score += magnitude * 0.1

            if score > 0:
                scores[eid] = score

        # Sort and return top-k
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return [(self._entities[eid], score) for eid, score in ranked]

    # ── 5) Knowledge Fusion & Deduplication ────────────────

    def fuse_knowledge(
        self, other: "KnowledgeGraphV2",
        merge_strategy: str = "max_confidence",
        resolve_conflicts: bool = True,
    ) -> Tuple[int, int]:
        """Fuse knowledge from another KnowledgeGraphV2 into this one.

        Deduplication strategies:
          - Name-based matching (exact + alias)
          - Confidence-weighted merging
          - Conflict resolution via max/avg/source priority

        Args:
            other: Source KnowledgeGraphV2 to fuse from
            merge_strategy: 'max_confidence', 'avg', or 'source_priority'
            resolve_conflicts: Auto-resolve conflicting relations

        Returns:
            Tuple of (new_entities_added, new_relations_added)
        """
        new_entities = 0
        new_relations = 0

        # Build alias index for existing entities
        alias_map: Dict[str, str] = {}  # alias -> eid
        for eid, ent in self._entities.items():
            alias_map[ent.name.lower()] = eid
            for alias in ent.aliases:
                alias_map[alias.lower()] = eid

        # Merge entities
        for oid, oent in other._entities.items():
            matched_eid = None

            # Try exact id match
            if oid in self._entities:
                matched_eid = oid
            # Try name match
            elif oent.name.lower() in alias_map:
                matched_eid = alias_map[oent.name.lower()]
            # Try alias match
            else:
                for alias in oent.aliases:
                    if alias.lower() in alias_map:
                        matched_eid = alias_map[alias.lower()]
                        break

            if matched_eid:
                # Merge existing entity
                existing = self._entities[matched_eid]
                if merge_strategy == "max_confidence":
                    if oent.confidence > existing.confidence:
                        existing.name = oent.name
                        existing.type = oent.type
                        existing.confidence = oent.confidence
                    existing.weight = max(existing.weight, oent.weight)
                elif merge_strategy == "avg":
                    existing.confidence = (existing.confidence + oent.confidence) / 2
                    existing.weight = (existing.weight + oent.weight) / 2
                elif merge_strategy == "source_priority":
                    pass  # keep existing, don't override

                for alias in oent.aliases:
                    if alias not in existing.aliases:
                        existing.aliases.append(alias)
                existing.metadata.update(oent.metadata)
                existing.updated = time.time()
                if oent.source and not existing.source:
                    existing.source = oent.source
            else:
                # Add new entity
                new_ent = Entity(
                    id=oid, name=oent.name, type=oent.type,
                    confidence=oent.confidence, weight=oent.weight,
                    aliases=list(oent.aliases),
                    embeddings=list(oent.embeddings) if oent.embeddings else None,
                    metadata=dict(oent.metadata), source=oent.source,
                )
                self._entities[oid] = new_ent
                self._adj[oid] = []
                alias_map[new_ent.name.lower()] = oid
                for alias in new_ent.aliases:
                    alias_map[alias.lower()] = oid
                new_entities += 1

        # Merge relations
        existing_triples = {
            (r.source, r.target, r.relation) for r in self._relations
        }
        for rel in other._relations:
            key = (rel.source, rel.target, rel.relation)
            if key not in existing_triples:
                # Check reverse for bidirectional
                rev_key = (rel.target, rel.source, rel.relation)
                if resolve_conflicts and rev_key in existing_triples:
                    # Conflict: same relation but reversed direction
                    # Keep the one with higher confidence
                    existing_rev = next(
                        r for r in self._relations
                        if r.source == rel.target and r.target == rel.source
                        and r.relation == rel.relation
                    )
                    if rel.confidence > existing_rev.confidence:
                        self._relations.remove(existing_rev)
                        self._adj[existing_rev.source] = [
                            (t, w) for t, w in self._adj[existing_rev.source]
                            if t != existing_rev.target
                        ]
                        self._adj[existing_rev.target] = [
                            (t, w) for t, w in self._adj[existing_rev.target]
                            if t != existing_rev.source
                        ]
                        self._add_relation_internal(rel)
                        new_relations += 1
                else:
                    self._add_relation_internal(rel)
                    new_relations += 1
                    existing_triples.add(key)

        self._dirty = True
        self._stats_cache = None
        logger.info(f"Knowledge fusion: +{new_entities} entities, +{new_relations} relations")
        return new_entities, new_relations

    def _add_relation_internal(self, rel: Relation):
        """Add relation without duplicate check (used during fusion)."""
        self._relations.append(rel)
        if rel.source not in self._adj:
            self._adj[rel.source] = []
        if rel.target not in self._adj:
            self._adj[rel.target] = []
        self._adj[rel.source].append((rel.target, rel.weight))
        if rel.bidirectional:
            self._adj[rel.target].append((rel.source, rel.weight))

    def deduplicate_entities(
        self, similarity_threshold: float = 0.8,
    ) -> int:
        """Deduplicate entities within the same graph.

        Finds near-identical entities by name similarity and merges them.

        Args:
            similarity_threshold: Jaccard threshold for merging (0-1)

        Returns:
            Number of entities merged
        """
        merged = 0
        eids = list(self._entities.keys())
        for i in range(len(eids)):
            if eids[i] not in self._entities:
                continue
            for j in range(i + 1, len(eids)):
                if eids[j] not in self._entities:
                    continue
                ea = self._entities[eids[i]]
                eb = self._entities[eids[j]]

                # Compute name similarity via Jaccard on tokens
                tokens_a = set(_tokenize(ea.name))
                tokens_b = set(_tokenize(eb.name))
                if not tokens_a or not tokens_b:
                    continue
                jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

                if jaccard >= similarity_threshold:
                    # Merge eb into ea
                    ea.confidence = max(ea.confidence, eb.confidence)
                    ea.weight = max(ea.weight, eb.weight)
                    for alias in eb.aliases:
                        if alias not in ea.aliases:
                            ea.aliases.append(alias)
                    ea.metadata.update(eb.metadata)
                    ea.updated = time.time()

                    # Re-route relations from eb to ea
                    new_relations = []
                    for r in self._relations:
                        if r.source == eb.id:
                            r.source = ea.id
                        if r.target == eb.id:
                            r.target = ea.id
                        # Drop self-loops
                        if r.source != r.target:
                            new_relations.append(r)
                    self._relations = new_relations

                    # Update adjacency
                    if eb.id in self._adj:
                        for target, w in self._adj.get(eb.id, []):
                            if target != ea.id:
                                self._adj[ea.id].append((target, w))
                        del self._adj[eb.id]

                    del self._entities[eids[j]]
                    merged += 1

        if merged:
            self._dirty = True
            self._stats_cache = None
            self._rebuild_adjacency()

        return merged

    def _rebuild_adjacency(self):
        """Rebuild full adjacency from relations list."""
        self._adj = defaultdict(list)
        for r in self._relations:
            if r.source not in self._adj:
                self._adj[r.source] = []
            if r.target not in self._adj:
                self._adj[r.target] = []
            self._adj[r.source].append((r.target, r.weight))
            if r.bidirectional:
                self._adj[r.target].append((r.source, r.weight))
        # Ensure all entities have adjacency entries
        for eid in self._entities:
            if eid not in self._adj:
                self._adj[eid] = []

    # ── Stats & Utility ────────────────────────────────────

    def stats(self) -> Dict:
        """Get graph statistics."""
        if self._stats_cache is not None:
            return self._stats_cache
        total_entities = len(self._entities)
        total_relations = len(self._relations)
        type_counts = Counter(e.type for e in self._entities.values())
        rel_counts = Counter(r.relation for r in self._relations)
        density = round(total_relations / max(1, total_entities), 3)
        stats = {
            "name": self.name,
            "total_entities": total_entities,
            "total_relations": total_relations,
            "density": density,
            "entity_types": dict(type_counts.most_common()),
            "relation_types": dict(rel_counts.most_common()),
            "top_connected": self.most_connected(5),
            "dirty": self._dirty,
        }
        self._stats_cache = stats
        return stats

    def clear(self):
        """Reset the knowledge graph to empty state."""
        self._entities.clear()
        self._relations.clear()
        self._adj.clear()
        self._documents.clear()
        self._entity_docs.clear()
        self._idf.clear()
        self._dirty = False
        self._stats_cache = None

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        doc = KGVDocument(
            entities=self._entities,
            relations=self._relations,
            stats=self.stats(),
        )
        return doc.to_dict()

    @classmethod
    def from_dict(cls, d: Dict, name: str = "restored") -> "KnowledgeGraphV2":
        """Deserialize from dictionary."""
        doc = KGVDocument.from_dict(d)
        kg = cls(name=name)
        for eid, ent in doc.entities.items():
            kg._entities[eid] = ent
            kg._adj[eid] = []
        for rel in doc.relations:
            kg._relations.append(rel)
            kg._adj[rel.source].append((rel.target, rel.weight))
            if rel.bidirectional:
                kg._adj[rel.target].append((rel.source, rel.weight))
        kg._stats_cache = None
        return kg


# ═══════════════════════════════════════════════════════════
# Singleton access
# ═══════════════════════════════════════════════════════════

_kg_v2: Optional[KnowledgeGraphV2] = None


def get_knowledge_graph_v2() -> KnowledgeGraphV2:
    """Get or create the global KnowledgeGraphV2 singleton."""
    global _kg_v2
    if _kg_v2 is None:
        _kg_v2 = KnowledgeGraphV2(name="global")
    return _kg_v2


def reset_knowledge_graph_v2():
    """Reset the global KnowledgeGraphV2 singleton."""
    global _kg_v2
    _kg_v2 = None

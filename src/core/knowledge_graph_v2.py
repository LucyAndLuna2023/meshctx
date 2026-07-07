"""meshctx knowledge_graph_v2 — entity extraction, relation inference, storage, search, fusion."""

import json
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.knowledge_graph_v2")


# ═══════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════

@dataclass
class Entity:
    """A knowledge graph entity (node)."""
    id: str
    name: str
    type: str = "entity"
    confidence: float = 0.5
    weight: float = 1.0
    aliases: List[str] = field(default_factory=list)


@dataclass
class Relation:
    """A directed relation (edge) between two entities."""
    source_id: str
    target_id: str
    relation: str = "related_to"
    weight: float = 1.0


@dataclass
class KGVDocument:
    """A document ingested into the knowledge graph."""
    text: str
    entities: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
# KnowledgeGraphV2
# ═══════════════════════════════════════════════════════════

class KnowledgeGraphV2:
    """In-memory knowledge graph with entity extraction, relation inference,
    semantic search, graph traversal, persistence, and fusion."""

    def __init__(self, name: str = "default"):
        self.name = name
        self._entities: Dict[str, Entity] = {}
        self._relations: List[Relation] = []
        self._alias_index: Dict[str, str] = {}   # alias-normalised → entity id
        self._lock = threading.RLock()
        self._documents: List[KGVDocument] = []

    # ── helpers ──────────────────────────────────────────

    @staticmethod
    def _norm(name: str) -> str:
        """Normalise a name to a stable entity id."""
        return re.sub(r'[^a-z0-9_]+', '_', name.lower().strip()).strip('_')

    # ── entity CRUD ──────────────────────────────────────

    def add_entity(
        self,
        name: str,
        type: str = "entity",
        confidence: float = 0.5,
        weight: float = 1.0,
        aliases: Optional[List[str]] = None,
    ) -> Entity:
        """Add or update an entity.  Returns the Entity."""
        eid = self._norm(name)
        with self._lock:
            existing = self._entities.get(eid)
            if existing is not None:
                existing.confidence = confidence
                existing.weight = weight
                existing.type = type
                if aliases:
                    for a in aliases:
                        aid = self._norm(a)
                        self._alias_index[aid] = eid
                    existing.aliases = list(dict.fromkeys(existing.aliases + aliases))
                return existing

            ent = Entity(
                id=eid,
                name=name,
                type=type,
                confidence=confidence,
                weight=weight,
                aliases=list(aliases) if aliases else [],
            )
            self._entities[eid] = ent
            self._alias_index[self._norm(name)] = eid
            for a in (aliases or []):
                self._alias_index[self._norm(a)] = eid
            return ent

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by id.  Returns None if not found."""
        with self._lock:
            return self._entities.get(entity_id)

    def find_entity(self, name: str) -> Optional[Entity]:
        """Find entity by name or alias.  Case-insensitive."""
        lookup = self._norm(name)
        with self._lock:
            eid = self._alias_index.get(lookup)
            if eid is not None:
                return self._entities.get(eid)
            return self._entities.get(lookup)

    def list_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        """List all entities, optionally filtered by type."""
        with self._lock:
            if entity_type is None:
                return list(self._entities.values())
            return [e for e in self._entities.values() if e.type == entity_type]

    # ── relations ────────────────────────────────────────

    def add_relation(
        self,
        source_name: str,
        target_name: str,
        relation: str = "related_to",
        weight: float = 1.0,
    ) -> Optional[Relation]:
        """Add a directed relation.  Returns the Relation or None if entities missing."""
        src = self.find_entity(source_name)
        tgt = self.find_entity(target_name)
        if src is None or tgt is None:
            return None
        r = Relation(source_id=src.id, target_id=tgt.id, relation=relation, weight=weight)
        with self._lock:
            self._relations.append(r)
        return r

    def get_relations(self, entity_name: Optional[str] = None) -> List[Relation]:
        """Get relations, optionally filtered to those involving *entity_name*."""
        with self._lock:
            if entity_name is None:
                return list(self._relations)
            eid = None
            ent = self.find_entity(entity_name)
            if ent is not None:
                eid = ent.id
            if eid is None:
                return []
            return [r for r in self._relations if r.source_id == eid or r.target_id == eid]

    # ── entity extraction ────────────────────────────────

    _CAPITALIZED_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b')
    _ACRONYM_RE = re.compile(r'\b([A-Z]{2,})\b')
    _ANY_CAP_RE = re.compile(r'\b([A-Z][A-Za-z]{2,})\b')

    def extract_entities(
        self,
        text: str,
        min_confidence: float = 0.2,
    ) -> List[Entity]:
        """Extract entity mentions from natural-language text.

        Uses heuristics: capitalized multi-word phrases, acronyms, and frequency.
        """
        if not text or not text.strip():
            return []

        # Count occurrences
        cap_matches = self._CAPITALIZED_RE.findall(text)
        acr_matches = self._ACRONYM_RE.findall(text)
        any_cap_matches = self._ANY_CAP_RE.findall(text)

        cap_counts: Counter = Counter(cap_matches)
        acr_counts: Counter = Counter(acr_matches)
        any_cap_counts: Counter = Counter(any_cap_matches)

        entities: List[Entity] = []
        seen: set = set()

        total_tokens = len(text.split())

        # Add capitalized phrases
        for phrase, count in cap_counts.most_common():
            if phrase in seen:
                continue
            # Confidence based on frequency and length
            freq_conf = min(1.0, count / max(1, total_tokens) * 20)
            len_bonus = 0.1 if len(phrase.split()) > 1 else 0.0
            confidence = round(min(1.0, freq_conf + len_bonus + 0.15), 3)
            if confidence >= min_confidence:
                seen.add(phrase)
                ent = Entity(
                    id=self._norm(phrase),
                    name=phrase,
                    type="entity",
                    confidence=confidence,
                    weight=float(count),
                )
                entities.append(ent)
                # Also auto-add to the graph
                self.add_entity(phrase, type=ent.type, confidence=confidence, weight=float(count))

        # Add acronyms
        for acr, count in acr_counts.most_common():
            if acr in seen:
                continue
            confidence = min(1.0, count / max(1, total_tokens) * 15 + 0.2)
            if confidence >= min_confidence:
                seen.add(acr)
                ent = Entity(
                    id=self._norm(acr),
                    name=acr,
                    type="entity",
                    confidence=round(confidence, 3),
                    weight=float(count),
                )
                entities.append(ent)
                self.add_entity(acr, type=ent.type, confidence=confidence, weight=float(count))

        # Add any-capitalized words (catches PostgreSQL, NoSQL, etc.)
        for word, count in any_cap_counts.most_common():
            if word in seen:
                continue
            confidence = min(1.0, count / max(1, total_tokens) * 12 + 0.15)
            if confidence >= min_confidence:
                seen.add(word)
                ent = Entity(
                    id=self._norm(word),
                    name=word,
                    type="entity",
                    confidence=round(confidence, 3),
                    weight=float(count),
                )
                entities.append(ent)
                self.add_entity(word, type=ent.type, confidence=confidence, weight=float(count))

        return entities

    # ── relation inference ───────────────────────────────

    _PATTERNS = [
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+is\s+(?:a|an)\s+(\w+(?:\s+\w+){0,3})\b'), 'is_a'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+part\s+of\s+(\w+(?:\s+\w+){0,3})\b'), 'part_of'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+supports\s+(\w+(?:\s+\w+){0,3})\b'), 'supports'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+has\s+(\w+(?:\s+\w+){0,3})\b'), 'has'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+related\s+to\s+(\w+(?:\s+\w+){0,3})\b'), 'related_to'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+depends\s+on\s+(\w+(?:\s+\w+){0,3})\b'), 'depends_on'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+uses\s+(\w+(?:\s+\w+){0,3})\b'), 'uses'),
        (re.compile(r'(?i)\b(\w+(?:\s+\w+){0,3})\s+is\s+part\s+of\s+(\w+(?:\s+\w+){0,3})\b'), 'part_of'),
    ]

    def infer_relations(
        self,
        text: Optional[str] = None,
        use_patterns: bool = True,
        use_cooccurrence: bool = True,
    ) -> List[Relation]:
        """Infer relations from text or from co-occurrence of entities."""
        new_relations: List[Relation] = []
        existing_keys: set = set()

        with self._lock:
            for r in self._relations:
                existing_keys.add((r.source_id, r.target_id, r.relation))

        def _add_rel(src_name, tgt_name, rel_type, weight=1.0):
            src = self.find_entity(src_name)
            tgt = self.find_entity(tgt_name)
            if src is None or tgt is None:
                return
            key = (src.id, tgt.id, rel_type)
            if key in existing_keys:
                return
            existing_keys.add(key)
            r = Relation(source_id=src.id, target_id=tgt.id, relation=rel_type, weight=weight)
            with self._lock:
                self._relations.append(r)
            new_relations.append(r)

        # Pattern-based inference
        if use_patterns and text:
            for pattern, rel_type in self._PATTERNS:
                for m in pattern.finditer(text):
                    a_name = m.group(1).strip()
                    b_name = m.group(2).strip()
                    if len(a_name) > 1 and len(b_name) > 1:
                        _add_rel(a_name, b_name, rel_type)

        # Co-occurrence inference
        if use_cooccurrence:
            entity_names = [e.name for e in self.list_entities()]
            all_text = (text or "") + " " + " ".join(e.name for e in self.list_entities())
            with self._lock:
                for doc in self._documents:
                    all_text += " " + doc.text if doc.text else ""
            for i in range(len(entity_names)):
                for j in range(i + 1, len(entity_names)):
                    a_name = entity_names[i]
                    b_name = entity_names[j]
                    if a_name in all_text and b_name in all_text:
                        _add_rel(a_name, b_name, "co_occurs", 0.5)

        return new_relations

    # ── persistence ──────────────────────────────────────

    def store_to_db(self, path: str) -> bool:
        """Persist the graph to a JSON file."""
        try:
            data = self.to_dict()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"store_to_db failed: {e}")
            return False

    def load_from_db(self, path: str) -> bool:
        """Load graph from a JSON file.  Merges into existing data."""
        try:
            if not os.path.exists(path):
                return False
            with open(path, 'r') as f:
                data = json.load(f)
            self._merge_from_dict(data)
            logger.info(f"Loaded KG from {path}: {len(self._entities)} entities, {len(self._relations)} relations")
            return True
        except Exception as e:
            logger.error(f"load_from_db failed: {e}")
            return False

    # ── semantic search ──────────────────────────────────

    def semantic_search(
        self,
        query: str,
        use_tfidf: bool = False,
        limit: int = 20,
        min_score: float = 0.15,
    ) -> List[Tuple[Entity, float]]:
        """Search entities by name/text similarity.  Returns (entity, score) pairs."""
        query_lower = query.lower()
        results: List[Tuple[Entity, float]] = []

        with self._lock:
            for ent in self._entities.values():
                score = 0.0
                name_lower = ent.name.lower()
                # Exact match
                if name_lower == query_lower:
                    score = 1.0
                # Substring
                elif query_lower in name_lower:
                    score = 0.8
                elif name_lower in query_lower:
                    score = 0.7
                # Alias match
                elif any(query_lower in a.lower() or a.lower() in query_lower for a in ent.aliases):
                    score = 0.75
                # TF-IDF-ish: boost for common words in entity name
                elif use_tfidf:
                    query_words = set(query_lower.split())
                    name_words = set(name_lower.split())
                    overlap = query_words & name_words
                    if overlap:
                        score = len(overlap) / max(1, len(query_words)) * 0.8
                # Fuzzy similarity fallback
                else:
                    score = SequenceMatcher(None, query_lower, name_lower).ratio() * 0.5

                if score >= min_score:
                    results.append((ent, round(score, 3)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    # ── knowledge fusion ─────────────────────────────────

    def fuse_knowledge(
        self,
        other: "KnowledgeGraphV2",
        merge_strategy: str = "max_confidence",
    ) -> Tuple[int, int]:
        """Fuse another knowledge graph into this one.

        Returns (new_entities_added, new_relations_added).
        """
        new_ent = 0
        new_rel = 0

        existing_rel_keys: set = set()
        with self._lock:
            for r in self._relations:
                existing_rel_keys.add((r.source_id, r.target_id, r.relation))

        # Merge entities
        for ent in other.list_entities():
            existing = self.find_entity(ent.name)
            if existing is None:
                self.add_entity(
                    name=ent.name,
                    type=ent.type,
                    confidence=ent.confidence,
                    weight=ent.weight,
                    aliases=ent.aliases,
                )
                new_ent += 1
            else:
                # Merge
                with self._lock:
                    if merge_strategy == "max_confidence":
                        existing.confidence = max(existing.confidence, ent.confidence)
                    existing.weight = max(existing.weight, ent.weight)
                    if ent.type and ent.type != "entity":
                        existing.type = ent.type
                    for a in ent.aliases:
                        if a not in existing.aliases:
                            existing.aliases.append(a)
                            self._alias_index[self._norm(a)] = existing.id

        # Merge relations
        for rel in other._relations:
            key = (rel.source_id, rel.target_id, rel.relation)
            if key not in existing_rel_keys:
                existing_rel_keys.add(key)
                with self._lock:
                    self._relations.append(Relation(
                        source_id=rel.source_id,
                        target_id=rel.target_id,
                        relation=rel.relation,
                        weight=rel.weight,
                    ))
                new_rel += 1

        return new_ent, new_rel

    # ── deduplication ────────────────────────────────────

    def deduplicate_entities(self, similarity_threshold: float = 0.5) -> int:
        """Merge similar entities.  Returns number of merges performed."""
        merged = 0
        entities = self.list_entities()
        n = len(entities)
        to_merge: List[Tuple[str, str]] = []  # (victim_id, survivor_id)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = entities[i], entities[j]
                sim = SequenceMatcher(None, a.name.lower(), b.name.lower()).ratio()
                if sim >= similarity_threshold:
                    # Keep the one with higher confidence/weight
                    if a.confidence * a.weight >= b.confidence * b.weight:
                        to_merge.append((b.id, a.id))
                    else:
                        to_merge.append((a.id, b.id))

        for victim_id, survivor_id in set(to_merge):
            with self._lock:
                if victim_id not in self._entities:
                    continue
                victim = self._entities.pop(victim_id)
                survivor = self._entities.get(survivor_id)
                if survivor is None:
                    self._entities[victim_id] = victim
                    continue
                # Merge aliases
                survivor.aliases = list(dict.fromkeys(survivor.aliases + victim.aliases + [victim.name]))
                survivor.weight += victim.weight
                survivor.confidence = max(survivor.confidence, victim.confidence)
                # Update alias index
                for a in survivor.aliases:
                    self._alias_index[self._norm(a)] = survivor_id
                # Rewrite relations
                for r in self._relations:
                    if r.source_id == victim_id:
                        r.source_id = survivor_id
                    if r.target_id == victim_id:
                        r.target_id = survivor_id
                merged += 1

        return merged

    # ── graph traversal ──────────────────────────────────

    def _adjacency(self) -> Dict[str, List[str]]:
        """Build adjacency list."""
        adj: Dict[str, List[str]] = defaultdict(list)
        with self._lock:
            for r in self._relations:
                adj[r.source_id].append(r.target_id)
                adj[r.target_id].append(r.source_id)
        return adj

    def shortest_path(self, source_name: str, target_name: str) -> Optional[List[str]]:
        """BFS shortest path between two entities.  Returns list of entity names or None."""
        src = self.find_entity(source_name)
        tgt = self.find_entity(target_name)
        if src is None or tgt is None:
            return None

        adj = self._adjacency()

        queue = deque([(src.id, [src.id])])
        visited: set = {src.id}

        while queue:
            node_id, path = queue.popleft()
            if node_id == tgt.id:
                # Convert ids back to names
                result: List[str] = []
                for nid in path:
                    ent = self.get_entity(nid)
                    result.append(ent.name if ent else nid)
                return result

            for neighbor in adj.get(node_id, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def most_connected(self, n: int = 10) -> List[Tuple[Entity, int, str]]:
        """Return the *n* most-connected entities.  (entity, degree, name)."""
        adj = self._adjacency()
        scores = [(eid, len(neighbors)) for eid, neighbors in adj.items()]
        scores.sort(key=lambda x: x[1], reverse=True)

        result: List[Tuple[Entity, int, str]] = []
        for eid, degree in scores[:n]:
            ent = self.get_entity(eid)
            name = ent.name if ent else eid
            result.append((ent, degree, name))
        return result

    def get_neighbors(
        self,
        entity_id: str,
        depth: int = 1,
    ) -> Dict[str, List[Tuple[str, float]]]:
        """Get neighbors up to *depth* hops.  Returns {node_id: [(neighbor_id, weight), ...]}."""
        if depth < 1:
            return {}

        ent = self.get_entity(entity_id)
        if ent is None:
            return {}

        adj = self._adjacency()
        result: Dict[str, List[Tuple[str, float]]] = {}

        # Collect weights from relations
        edge_weights: Dict[Tuple[str, str], float] = {}
        with self._lock:
            for r in self._relations:
                edge_weights[(r.source_id, r.target_id)] = r.weight
                edge_weights[(r.target_id, r.source_id)] = r.weight

        visited: set = {entity_id}
        current = {entity_id}
        for d in range(depth):
            next_level: set = set()
            for nid in current:
                neighbors: List[Tuple[str, float]] = []
                for neighbor in adj.get(nid, []):
                    w = edge_weights.get((nid, neighbor), 1.0)
                    neighbors.append((neighbor, w))
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_level.add(neighbor)
                if neighbors:
                    result[nid] = neighbors
            current = next_level

        return result

    # ── serialization ────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to a plain dict."""
        with self._lock:
            return {
                "name": self.name,
                "entities": [
                    {
                        "id": e.id,
                        "name": e.name,
                        "type": e.type,
                        "confidence": e.confidence,
                        "weight": e.weight,
                        "aliases": e.aliases,
                    }
                    for e in self._entities.values()
                ],
                "relations": [
                    {
                        "source_id": r.source_id,
                        "target_id": r.target_id,
                        "relation": r.relation,
                        "weight": r.weight,
                    }
                    for r in self._relations
                ],
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraphV2":
        """Deserialize from a dict."""
        kg = cls(name=data.get("name", "loaded"))
        kg._merge_from_dict(data)
        return kg

    def _merge_from_dict(self, data: Dict[str, Any]):
        """Internal: merge dict data into this instance."""
        for e_data in data.get("entities", []):
            self.add_entity(
                name=e_data["name"],
                type=e_data.get("type", "entity"),
                confidence=e_data.get("confidence", 0.5),
                weight=e_data.get("weight", 1.0),
                aliases=e_data.get("aliases", []),
            )
        for r_data in data.get("relations", []):
            r = Relation(
                source_id=r_data["source_id"],
                target_id=r_data["target_id"],
                relation=r_data.get("relation", "related_to"),
                weight=r_data.get("weight", 1.0),
            )
            with self._lock:
                self._relations.append(r)

    # ── stats & maintenance ──────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return statistics about the graph."""
        with self._lock:
            e_count = len(self._entities)
            r_count = len(self._relations)
            type_counts: Counter = Counter(e.type for e in self._entities.values())
            max_edges = e_count * (e_count - 1)  # directed
            density = r_count / max(1, max_edges)

        # Call outside _lock to avoid re-entrant deadlock
        top = self.most_connected(5)
        return {
            "name": self.name,
            "total_entities": e_count,
            "total_relations": r_count,
            "entity_types": dict(type_counts),
            "top_connected": [(t[2], t[1]) for t in top],
            "density": round(density, 6),
        }

    def clear(self):
        """Remove all entities and relations."""
        with self._lock:
            self._entities.clear()
            self._relations.clear()
            self._alias_index.clear()
            self._documents.clear()


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_kg_v2_instance: Optional[KnowledgeGraphV2] = None
_kg_v2_lock = threading.Lock()


def get_knowledge_graph_v2(name: str = "default") -> KnowledgeGraphV2:
    """Get or create the global KnowledgeGraphV2 singleton."""
    global _kg_v2_instance
    if _kg_v2_instance is None:
        with _kg_v2_lock:
            if _kg_v2_instance is None:
                _kg_v2_instance = KnowledgeGraphV2(name=name)
    return _kg_v2_instance


def reset_knowledge_graph_v2():
    """Reset the global singleton (for testing)."""
    global _kg_v2_instance
    with _kg_v2_lock:
        _kg_v2_instance = None

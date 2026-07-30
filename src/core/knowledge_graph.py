"""Knowledge Graph — 统一知识图谱 (v3.115.49, v1+v2合并)

Backward-compatible: v1 API (KGNode/KGEdge/KnowledgeGraph)
wraps v2 engine (Entity/Relation/KnowledgeGraphV2)."""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.kg")


# ── v1 API (backward compatible) ─────────────────────────────

class KGNode:
    """Knowledge graph node (v1 API)."""
    def __init__(self, node_id: str, label: str = "", type: str = "entity", **kwargs):
        self.id = node_id
        self.label = label or node_id
        self.type = type
        self.props = kwargs

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "type": self.type, **self.props}


class KGEdge:
    """Knowledge graph edge (v1 API)."""
    def __init__(self, source: str, target: str, relation: str = "relates_to", weight: float = 1.0):
        self.source = source
        self.target = target
        self.relation = relation
        self.weight = weight


class KnowledgeGraph:
    """Unified knowledge graph — v1 API wrapping v2 engine."""

    def __init__(self):
        self._nodes: Dict[str, KGNode] = {}
        self._edges: List[KGEdge] = []
        self._v2 = None  # lazy init v2 engine
        self._stats = {"added": 0, "queried": 0, "merged": 0}

    def _init_v2(self):
        if self._v2 is None:
            try:
                from .knowledge_graph_v2 import KnowledgeGraphV2
                self._v2 = KnowledgeGraphV2(name="unified")
            except Exception:
                pass

    # ── CRUD ──

    def add_node(self, node_id: str, label: str = "", type: str = "entity", **kwargs):
        node = KGNode(node_id, label, type, **kwargs)
        self._nodes[node_id] = node
        self._stats["added"] += 1
        # Sync to v2
        self._init_v2()
        if self._v2:
            try:
                self._v2.add_entity(node_id, label, entity_type=type, metadata=kwargs)
            except Exception:
                pass
        return node

    def add_edge(self, source: str, target: str, relation: str = "relates_to", weight: float = 1.0):
        edge = KGEdge(source, target, relation, weight)
        self._edges.append(edge)
        # Sync to v2
        if self._v2:
            try:
                self._v2.add_relation(source, target, relation)
            except Exception:
                pass
        return edge

    def add_fact(self, subject: str, predicate: str, obj: str, confidence: float = 1.0):
        """Add a triple fact."""
        self.add_node(subject, label=subject)
        self.add_node(obj, label=obj)
        self.add_edge(subject, obj, predicate, confidence)

    # ── Query ──

    def query_neighbors(self, node_id: str) -> dict:
        self._stats["queried"] += 1
        incoming = [(e.source, e.relation) for e in self._edges if e.target == node_id]
        outgoing = [(e.target, e.relation) for e in self._edges if e.source == node_id]
        return {
            "node": self._nodes.get(node_id, KGNode(node_id)).to_dict(),
            "incoming": incoming,
            "outgoing": outgoing,
            "degree": len(incoming) + len(outgoing),
        }

    def shortest_path(self, source: str, target: str, max_depth: int = 5) -> List[str]:
        """BFS shortest path."""
        if source == target:
            return [source]
        visited = {source}
        queue = [(source, [source])]
        while queue:
            node, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            neighbors = [e.target for e in self._edges if e.source == node]
            neighbors += [e.source for e in self._edges if e.target == node]
            for nb in neighbors:
                if nb == target:
                    return path + [nb]
                if nb not in visited:
                    visited.add(nb)
                    queue.append((nb, path + [nb]))
        return []

    def most_connected(self, n: int = 10) -> List[Tuple[str, int]]:
        degrees = {}
        for e in self._edges:
            degrees[e.source] = degrees.get(e.source, 0) + 1
            degrees[e.target] = degrees.get(e.target, 0) + 1
        return sorted(degrees.items(), key=lambda x: -x[1])[:n]

    def search(self, query: str) -> List[KGNode]:
        q = query.lower()
        return [n for n in self._nodes.values()
                if q in n.label.lower() or q in n.id.lower()]

    def search_relations(self, relation: str) -> List[KGEdge]:
        return [e for e in self._edges if relation.lower() in e.relation.lower()]

    # ── Merge ──

    def merge_from(self, other: "KnowledgeGraph"):
        """Merge another graph into this one."""
        for node in other._nodes.values():
            self.add_node(node.id, node.label, node.type, **node.props)
        for edge in other._edges:
            self.add_edge(edge.source, edge.target, edge.relation, edge.weight)
        self._stats["merged"] += 1

    # ── Stats ──

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def stats(self) -> dict:
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "density": round(self.edge_count / max(self.node_count, 1), 2),
            **self._stats,
        }

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [{"source": e.source, "target": e.target,
                       "relation": e.relation, "weight": e.weight}
                      for e in self._edges],
        }


# ── Singleton ────────────────────────────────────────────────

_kg: Optional[KnowledgeGraph] = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
    return _kg

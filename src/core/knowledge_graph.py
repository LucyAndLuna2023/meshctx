"""meshctx knowledge_graph — Knowledge Graph module"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KGNode:
    id: str = ""
    label: str = ""
    type: str = "entity"
    properties: dict = field(default_factory=dict)


@dataclass
class KGEdge:
    source: str = ""
    target: str = ""
    relation: str = "relates_to"
    weight: float = 1.0


class KnowledgeGraph:
    """A simple in-memory knowledge graph."""

    def __init__(self):
        self._nodes: dict[str, KGNode] = {}
        self._edges: list[KGEdge] = []
        self._adj: dict[str, list[str]] = defaultdict(list)

    def add_node(self, node_id: str, label: str = "", type: str = "entity", **kwargs):
        self._nodes[node_id] = KGNode(id=node_id, label=label, type=type, properties=kwargs)

    def add_edge(self, source: str, target: str, relation: str = "relates_to", weight: float = 1.0):
        edge = KGEdge(source=source, target=target, relation=relation, weight=weight)
        self._edges.append(edge)
        self._adj[source].append(target)
        if target not in self._adj:
            self._adj[target] = []

    def query_neighbors(self, node_id: str) -> dict:
        """Return adjacency dict: {node_id: [neighbors]}."""
        neighbors = self._adj.get(node_id, [])
        return {node_id: list(neighbors)}

    def shortest_path(self, source: str, target: str) -> list[str]:
        """BFS shortest path."""
        from collections import deque
        explored = set()
        parent = {}
        q = deque([source])
        explored.add(source)
        while q:
            v = q.popleft()
            if v == target:
                path = []
                while v in parent:
                    path.append(v)
                    v = parent[v]
                path.append(source)
                return path[::-1]
            for nb in self._adj.get(v, []):
                if nb not in explored:
                    explored.add(nb)
                    parent[nb] = v
                    q.append(nb)
        return []

    def most_connected(self, n: int = 10) -> list[tuple[str, int]]:
        """Return (node_id, degree) sorted by degree descending."""
        deg = {nid: len(neighbors) for nid, neighbors in self._adj.items()}
        sorted_deg = sorted(deg.items(), key=lambda x: x[1], reverse=True)
        return sorted_deg[:n]

    def search(self, query: str) -> list[KGNode]:
        """Search nodes by id or label substring (case-insensitive)."""
        q = query.lower()
        results = []
        for node in self._nodes.values():
            if q in node.id.lower() or q in node.label.lower():
                results.append(node)
        return results

    def to_dot(self) -> str:
        """Export to Graphviz DOT format."""
        lines = ["digraph G {"]
        for node_id in self._nodes:
            lines.append(f'  "{node_id}";')
        for edge in self._edges:
            lines.append(f'  "{edge.source}" -> "{edge.target}" [label="{edge.relation}"];')
        lines.append("}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeGraph":
        kg = cls()
        for nid, label in data.get("nodes", {}).items():
            kg.add_node(nid, label)
        for src, tgt, rel in data.get("edges", []):
            kg.add_edge(src, tgt, rel)
        return kg

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: node.label for nid, node in self._nodes.items()},
            "edges": [(e.source, e.target, e.relation) for e in self._edges],
        }


_kg_instance: Optional[KnowledgeGraph] = None


def get_knowledge_graph() -> KnowledgeGraph:
    global _kg_instance
    if _kg_instance is None:
        _kg_instance = KnowledgeGraph()
    return _kg_instance

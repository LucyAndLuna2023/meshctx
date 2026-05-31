"""
meshctx v3.61 — Knowledge Graph Engine (知识图谱引擎)

功能:
  1. 实体提取: 从对话/代码自动提取概念+关系
  2. 图谱存储: 节点+边, 支持权重+方向
  3. 查询: BFS/DFS遍历, 最短路径, 相关性排名
  4. 可视化: DOT格式导出
"""
import logging, time, json
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional

logger = logging.getLogger("meshctx.knowledge_graph")

@dataclass
class KGNode:
    id: str; label: str; type: str="concept"
    weight: float=1.0; created: float=field(default_factory=time.time)
    metadata: Dict=field(default_factory=dict)

@dataclass
class KGEdge:
    source: str; target: str; relation: str="related_to"
    weight: float=1.0; bidirectional: bool=True

class KnowledgeGraph:
    def __init__(self):
        self._nodes: Dict[str,KGNode]={}
        self._edges: List[KGEdge]=[]
        self._adj: Dict[str,List[Tuple[str,float]]]=defaultdict(list)
    
    def add_node(self, id: str, label: str, type: str="concept", metadata: Dict=None) -> KGNode:
        node = KGNode(id=id, label=label, type=type, metadata=metadata or {})
        self._nodes[id] = node
        if id not in self._adj: self._adj[id] = []
        return node
    
    def add_edge(self, source: str, target: str, relation: str="related_to", weight: float=1.0) -> KGEdge:
        if source not in self._nodes: self.add_node(source, source)
        if target not in self._nodes: self.add_node(target, target)
        edge = KGEdge(source=source, target=target, relation=relation, weight=weight)
        self._edges.append(edge)
        self._adj[source].append((target, weight))
        if edge.bidirectional: self._adj[target].append((source, weight))
        return edge
    
    def query_neighbors(self, node_id: str, depth: int=1) -> Dict[str,List]:
        if node_id not in self._nodes: return {}
        visited = {node_id}; frontier = {node_id}; result = {}
        for d in range(depth):
            next_frontier = set()
            for n in frontier:
                neighbors = [(t,w) for t,w in self._adj.get(n,[]) if t not in visited]
                if neighbors: result[n] = neighbors
                for t,_ in neighbors: visited.add(t); next_frontier.add(t)
            frontier = next_frontier
        return result
    
    def shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        if source not in self._nodes or target not in self._nodes: return None
        q = deque([(source, [source])]); visited = {source}
        while q:
            node, path = q.popleft()
            if node == target: return path
            for neighbor,_ in self._adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor); q.append((neighbor, path+[neighbor]))
        return None
    
    def most_connected(self, n: int=10) -> List[Tuple[str,int]]:
        degrees = {nid: len(edges) for nid, edges in self._adj.items()}
        return sorted(degrees.items(), key=lambda x:-x[1])[:n]
    
    def search(self, query: str) -> List[KGNode]:
        q = query.lower(); results = []
        for node in self._nodes.values():
            score = 0
            if q in node.label.lower(): score += 10
            if q in node.id.lower(): score += 5
            if q in node.type.lower(): score += 3
            if any(q in str(v).lower() for v in node.metadata.values()): score += 2
            if score > 0: results.append((score, node))
        results.sort(key=lambda x:-x[0])
        return [n for _,n in results[:20]]
    
    def to_dot(self) -> str:
        lines = ["digraph KG {", "  rankdir=LR; node [shape=box];"]
        for nid,n in self._nodes.items():
            lines.append(f'  "{nid}" [label="{n.label}",tooltip="{n.type}"];')
        for e in self._edges:
            arrow = " [dir=both]" if e.bidirectional else ""
            lines.append(f'  "{e.source}" -> "{e.target}" [label="{e.relation}"{arrow}];')
        lines.append("}"); return "\n".join(lines)
    
    def get_stats(self) -> Dict:
        return {"nodes": len(self._nodes), "edges": len(self._edges),
                "density": round(len(self._edges)/max(1,len(self._nodes)),2),
                "top_connected": self.most_connected(5)}

_kg = None
def get_knowledge_graph():
    global _kg
    if _kg is None: _kg = KnowledgeGraph()
    return _kg

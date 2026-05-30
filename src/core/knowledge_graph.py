"""
MeshCtx v3.43 — Knowledge Graph Engine (知识图谱引擎)

BP验证中发现c5(知识图谱)能力待验证 → 现在落地实现
用途: 实体关系抽取 + 图查询 + 推理
"""
import time, json, hashlib
from typing import Optional, List, Dict, Any, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path.home() / ".meshctx" / "knowledge_graph"
DATA_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class Entity:
    """知识实体"""
    name: str
    entity_type: str = "concept"
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    confidence: float = 0.5

@dataclass
class Relation:
    """实体关系"""
    source: str
    target: str
    relation_type: str  # has_part, causes, depends_on, similar_to, ...
    weight: float = 0.5
    evidence: str = ""
    created_at: float = field(default_factory=time.time)

class KnowledgeGraph:
    """轻量级知识图谱"""
    
    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relations: List[Relation] = []
        self._adjacency: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        self._load()
    
    def _load(self):
        f = DATA_DIR / "graph.json"
        if f.exists():
            try:
                with open(f) as fp:
                    data = json.load(fp)
                for e in data.get('entities', []):
                    self.entities[e['name']] = Entity(**e)
                for r in data.get('relations', []):
                    self.relations.append(Relation(**r))
                    self._adjacency[r['source']].append((r['target'], r['weight']))
            except: pass
    
    def _save(self):
        with open(DATA_DIR / "graph.json", 'w') as f:
            json.dump({
                'entities': [e.__dict__ for e in self.entities.values()],
                'relations': [r.__dict__ for r in self.relations],
            }, f, indent=2, ensure_ascii=False, default=str)
    
    def add_entity(self, name: str, entity_type: str = "concept", **props) -> Entity:
        if name in self.entities:
            e = self.entities[name]
            e.properties.update(props)
            e.confidence = min(1.0, e.confidence + 0.1)
        else:
            e = Entity(name=name, entity_type=entity_type, properties=props)
            self.entities[name] = e
        self._save()
        return e
    
    def add_relation(self, source: str, target: str, relation_type: str,
                     weight: float = 0.5, evidence: str = "") -> Relation:
        # Ensure entities exist
        if source not in self.entities:
            self.add_entity(source)
        if target not in self.entities:
            self.add_entity(target)
        
        # Check duplicate
        for r in self.relations:
            if r.source == source and r.target == target and r.relation_type == relation_type:
                r.weight = max(r.weight, weight)
                return r
        
        r = Relation(source=source, target=target, relation_type=relation_type,
                     weight=weight, evidence=evidence)
        self.relations.append(r)
        self._adjacency[source].append((target, weight))
        self._save()
        return r
    
    def query_neighbors(self, entity: str, depth: int = 1) -> Dict[str, Any]:
        """查询邻居"""
        if depth == 0:
            return {'entity': entity, 'neighbors': []}
        
        neighbors = []
        visited = {entity}
        queue = [(entity, 0)]
        
        while queue:
            current, d = queue.pop(0)
            if d >= depth:
                continue
            for target, weight in self._adjacency.get(current, []):
                if target not in visited:
                    visited.add(target)
                    neighbors.append({'entity': target, 'depth': d+1, 'weight': weight})
                    queue.append((target, d+1))
        
        return {'entity': entity, 'neighbors': neighbors, 'total': len(neighbors)}
    
    def find_path(self, source: str, target: str, max_depth: int = 3) -> Optional[List[str]]:
        """BFS最短路径"""
        if source == target:
            return [source]
        
        visited = {source}
        queue = [(source, [source])]
        
        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                continue
            for neighbor, _ in self._adjacency.get(current, []):
                if neighbor == target:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            'entities': len(self.entities),
            'relations': len(self.relations),
            'entity_types': list(set(e.entity_type for e in self.entities.values())),
            'most_connected': sorted(
                [(name, len(adj)) for name, adj in self._adjacency.items()],
                key=lambda x: x[1], reverse=True
            )[:5],
        }

# 单例
_graph: Optional[KnowledgeGraph] = None

def get_knowledge_graph() -> KnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
    return _graph

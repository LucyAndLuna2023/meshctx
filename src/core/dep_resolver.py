"""Plugin Dependency Resolver — v3.20"""
import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set
logger = logging.getLogger(__name__)

class DepResolver:
    def __init__(self): self._deps: Dict[str, Set[str]] = defaultdict(set)
    
    def add(self, name: str, depends_on: List[str] = None):
        if depends_on: self._deps[name].update(depends_on)
        else: self._deps[name]  # ensure exists
    
    def resolve(self, names: List[str]) -> Dict:
        """拓扑排序解决依赖顺序"""
        in_degree = {n: 0 for n in set(names) | set(self._deps.keys()) if n in self._deps or n in names}
        graph = defaultdict(set)
        for pkg in self._deps:
            if pkg not in in_degree: in_degree[pkg] = 0
            for dep in self._deps[pkg]:
                if dep not in in_degree: in_degree[dep] = 0
                graph[dep].add(pkg)
                in_degree[pkg] += 1
        
        queue = deque([n for n, d in in_degree.items() if d == 0 and n in names])
        order = []
        while queue:
            pkg = queue.popleft(); order.append(pkg)
            for dependent in graph.get(pkg, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0 and dependent in names:
                    queue.append(dependent)
        
        missing = [n for n in names if n not in order]
        return {"order": order + missing, "cycles": len(names) - len(order) > 0}
    
    def get_stats(self) -> Dict:
        return {"packages": len(self._deps), "total_deps": sum(len(v) for v in self._deps.values())}

_resolver: Optional[DepResolver] = None
def get_dep_resolver() -> DepResolver:
    global _resolver
    if _resolver is None: _resolver = DepResolver()
    return _resolver

"""Dependency Graph Visualizer — v3.14"""
import ast, logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set
logger = logging.getLogger(__name__)

class DepGraph:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or Path.cwd()
        self._graph: Dict[str, Set[str]] = defaultdict(set)
    
    def build(self) -> Dict:
        for f in self.root.rglob("*.py"):
            try:
                tree = ast.parse(f.read_text())
                fname = str(f.relative_to(self.root))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        self._graph[fname].add(node.module)
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            self._graph[fname].add(alias.name.split(".")[0])
            except: pass
        
        cycles = self._find_cycles()
        most_depended = sorted([(k, sum(1 for v in self._graph.values() if k in v or any(k in x for x in v))) for k in self._graph], key=lambda x: -x[1])[:5]
        
        return {"files": len(self._graph), "edges": sum(len(v) for v in self._graph.values()),
                "cycles": len(cycles), "most_depended": [{"file": f, "used_by": c} for f,c in most_depended]}
    
    def _find_cycles(self) -> List[List[str]]:
        visited = set(); stack = set(); cycles = []
        def dfs(node, path):
            visited.add(node); stack.add(node)
            for neighbor in self._graph.get(node, set()):
                if neighbor in stack: cycles.append(path + [neighbor])
                elif neighbor not in visited: dfs(neighbor, path + [neighbor])
            stack.discard(node)
        for node in self._graph:
            if node not in visited: dfs(node, [node])
        return cycles
    
    def get_stats(self) -> Dict: return self.build()

_graph: Optional[DepGraph] = None
def get_dep_graph() -> DepGraph:
    global _graph
    if _graph is None: _graph = DepGraph()
    return _graph

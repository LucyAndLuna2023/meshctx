"""
meshctx Knowledge Graph — 图知识索引引擎
==========================================

基于有向属性图的知识表示与检索系统。支持节点/边管理、
图遍历(BFS/DFS)、最短路径查找、邻居查询、子图提取。

核心功能:
  1. 数据结构 — Node/Edge/Property, 支持任意属性
  2. 图操作 — add_node/add_edge/remove_node/remove_edge
  3. 图遍历 — BFS (广度优先) / DFS (深度优先)
  4. 路径查找 — 最短路径 (无权 BFS)
  5. 邻居查询 — 出边/入边/双向邻居
  6. 子图提取 — 按节点集合提取诱导子图
  7. 图统计 — 节点数/边数/密度/度数分布
  8. 持久化 — JSON 导入/导出

使用示例:
  kg = get_knowledge_graph()
  kg.add_node("alice", type="person", age=30)
  kg.add_node("bob", type="person", age=25)
  kg.add_edge("alice", "bob", relation="knows", weight=0.8)
  path = kg.shortest_path("alice", "bob")
  neighbors = kg.get_neighbors("alice")

设计原则:
  - 纯内存操作, 无外部依赖
  - JSON 可序列化, 完整导入导出
  - 线程安全: 读写锁保护
  - 适配知识检索场景, 非通用图数据库

代码量: ~500 行
"""

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.knowledge_graph")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class Property:
    """节点或边上的属性"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Property":
        return cls(
            key=d["key"],
            value=d["value"],
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


@dataclass
class Node:
    """知识图谱节点"""
    id: str
    properties: Dict[str, Property] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        """获取属性值"""
        prop = self.properties.get(key)
        return prop.value if prop else default

    def set(self, key: str, value: Any):
        """设置属性"""
        now = time.time()
        if key in self.properties:
            self.properties[key].value = value
            self.properties[key].updated_at = now
        else:
            self.properties[key] = Property(key=key, value=value, created_at=now, updated_at=now)
        self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "properties": {k: v.to_dict() for k, v in self.properties.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Node":
        props = {}
        for k, v in d.get("properties", {}).items():
            props[k] = Property.from_dict(v)
        return cls(
            id=d["id"],
            properties=props,
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


@dataclass
class Edge:
    """知识图谱有向边"""
    source: str
    target: str
    properties: Dict[str, Property] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        prop = self.properties.get(key)
        return prop.value if prop else default

    def set(self, key: str, value: Any):
        now = time.time()
        if key in self.properties:
            self.properties[key].value = value
            self.properties[key].updated_at = now
        else:
            self.properties[key] = Property(key=key, value=value, created_at=now, updated_at=now)
        self.updated_at = now

    @property
    def key(self) -> Tuple[str, str]:
        """返回边的唯一标识 (source, target)"""
        return (self.source, self.target)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "properties": {k: v.to_dict() for k, v in self.properties.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Edge":
        props = {}
        for k, v in d.get("properties", {}).items():
            props[k] = Property.from_dict(v)
        return cls(
            source=d["source"],
            target=d["target"],
            properties=props,
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


# ═══════════════════════════════════════════════════════════
# 知识图谱主类
# ═══════════════════════════════════════════════════════════

class KnowledgeGraph:
    """有向属性知识图谱

    内存图存储, 邻接表实现。支持节点/边的增删查改、
    图遍历、最短路径、子图提取与 JSON 持久化。
    """

    def __init__(self):
        self._nodes: Dict[str, Node] = {}
        # 出边: source -> {target: Edge}
        self._out_edges: Dict[str, Dict[str, Edge]] = {}
        # 入边: target -> {source: Edge}
        self._in_edges: Dict[str, Dict[str, Edge]] = {}
        self._lock = threading.RLock()
        self._stats: Dict[str, int] = {"adds": 0, "removes": 0, "searches": 0}

    # ── 节点操作 ──────────────────────────────────────────

    def add_node(self, node_id: str, **properties) -> Node:
        """添加或更新节点

        Args:
            node_id: 节点唯一标识
            **properties: 节点属性 (key=value)

        Returns:
            创建或更新的 Node 对象
        """
        with self._lock:
            if node_id in self._nodes:
                node = self._nodes[node_id]
                for k, v in properties.items():
                    node.set(k, v)
                logger.debug(f"Updated node: {node_id}")
            else:
                node = Node(id=node_id)
                for k, v in properties.items():
                    node.set(k, v)
                self._nodes[node_id] = node
                self._out_edges[node_id] = {}
                self._in_edges[node_id] = {}
                self._stats["adds"] += 1
                logger.debug(f"Added node: {node_id}")
            return node

    def get_node(self, node_id: str) -> Optional[Node]:
        """获取节点"""
        with self._lock:
            return self._nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        """检查节点是否存在"""
        with self._lock:
            return node_id in self._nodes

    def remove_node(self, node_id: str) -> bool:
        """删除节点及其所有关联边

        Returns:
            是否成功删除
        """
        with self._lock:
            if node_id not in self._nodes:
                return False

            # 删除所有出边
            for target in list(self._out_edges.get(node_id, {}).keys()):
                self._in_edges.get(target, {}).pop(node_id, None)
            del self._out_edges[node_id]

            # 删除所有入边
            for source in list(self._in_edges.get(node_id, {}).keys()):
                self._out_edges.get(source, {}).pop(node_id, None)
            del self._in_edges[node_id]

            del self._nodes[node_id]
            self._stats["removes"] += 1
            logger.debug(f"Removed node: {node_id}")
            return True

    @property
    def node_count(self) -> int:
        """节点总数"""
        with self._lock:
            return len(self._nodes)

    def list_nodes(self) -> List[str]:
        """列出所有节点 ID"""
        with self._lock:
            return list(self._nodes.keys())

    def find_nodes(self, **filters) -> List[str]:
        """按属性过滤查找节点

        Args:
            **filters: 属性过滤条件 (key=value)

        Returns:
            匹配的节点 ID 列表
        """
        with self._lock:
            results = []
            for node_id, node in self._nodes.items():
                match = True
                for k, v in filters.items():
                    if node.get(k) != v:
                        match = False
                        break
                if match:
                    results.append(node_id)
            return results

    # ── 边操作 ────────────────────────────────────────────

    def add_edge(self, source: str, target: str, **properties) -> Edge:
        """添加或更新有向边

        如果端点不存在则自动创建。

        Args:
            source: 源节点 ID
            target: 目标节点 ID
            **properties: 边属性 (e.g. weight=0.5, relation="knows")

        Returns:
            创建或更新的 Edge 对象
        """
        with self._lock:
            # 确保端点存在
            if source not in self._nodes:
                self.add_node(source)
            if target not in self._nodes:
                self.add_node(target)

            edge_key = (source, target)
            existing = self._out_edges[source].get(target)

            if existing:
                for k, v in properties.items():
                    existing.set(k, v)
                logger.debug(f"Updated edge: {source} -> {target}")
                return existing

            edge = Edge(source=source, target=target)
            for k, v in properties.items():
                edge.set(k, v)

            self._out_edges[source][target] = edge
            self._in_edges[target][source] = edge
            self._stats["adds"] += 1
            logger.debug(f"Added edge: {source} -> {target}")
            return edge

    def get_edge(self, source: str, target: str) -> Optional[Edge]:
        """获取边"""
        with self._lock:
            return self._out_edges.get(source, {}).get(target)

    def has_edge(self, source: str, target: str) -> bool:
        """检查边是否存在"""
        with self._lock:
            return target in self._out_edges.get(source, {})

    def remove_edge(self, source: str, target: str) -> bool:
        """删除边

        Returns:
            是否成功删除
        """
        with self._lock:
            if source not in self._out_edges:
                return False
            if target not in self._out_edges[source]:
                return False
            del self._out_edges[source][target]
            del self._in_edges[target][source]
            self._stats["removes"] += 1
            logger.debug(f"Removed edge: {source} -> {target}")
            return True

    @property
    def edge_count(self) -> int:
        """边总数"""
        with self._lock:
            return sum(len(targets) for targets in self._out_edges.values())

    # ── 邻居查询 ──────────────────────────────────────────

    def get_neighbors(self, node_id: str, direction: str = "out") -> List[str]:
        """获取节点的邻居

        Args:
            node_id: 节点 ID
            direction: "out" (出边邻居), "in" (入边邻居), "both" (双向)

        Returns:
            邻居节点 ID 列表
        """
        with self._lock:
            neighbors = set()
            if direction in ("out", "both"):
                neighbors.update(self._out_edges.get(node_id, {}).keys())
            if direction in ("in", "both"):
                neighbors.update(self._in_edges.get(node_id, {}).keys())
            self._stats["searches"] += 1
            return list(neighbors)

    def get_out_degree(self, node_id: str) -> int:
        """获取出度"""
        with self._lock:
            return len(self._out_edges.get(node_id, {}))

    def get_in_degree(self, node_id: str) -> int:
        """获取入度"""
        with self._lock:
            return len(self._in_edges.get(node_id, {}))

    def get_degree(self, node_id: str) -> int:
        """获取总度数 (出度 + 入度)"""
        with self._lock:
            out = len(self._out_edges.get(node_id, {}))
            inp = len(self._in_edges.get(node_id, {}))
            return out + inp

    # ── 图遍历 ────────────────────────────────────────────

    def bfs(self, start: str, max_depth: Optional[int] = None) -> List[str]:
        """广度优先遍历 (BFS)

        Args:
            start: 起始节点 ID
            max_depth: 最大遍历深度, None 表示不限制

        Returns:
            按 BFS 顺序访问的节点 ID 列表
        """
        with self._lock:
            if start not in self._nodes:
                return []

            visited = []
            seen = {start}
            queue = deque([(start, 0)])

            while queue:
                node, depth = queue.popleft()
                visited.append(node)

                if max_depth is not None and depth >= max_depth:
                    continue

                for neighbor in self._out_edges.get(node, {}):
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append((neighbor, depth + 1))

            self._stats["searches"] += 1
            return visited

    def dfs(self, start: str, max_depth: Optional[int] = None) -> List[str]:
        """深度优先遍历 (DFS)

        Args:
            start: 起始节点 ID
            max_depth: 最大遍历深度, None 表示不限制

        Returns:
            按 DFS 顺序访问的节点 ID 列表
        """
        with self._lock:
            if start not in self._nodes:
                return []

            visited = []
            seen = set()

            def _dfs(node: str, depth: int):
                if node in seen:
                    return
                if max_depth is not None and depth > max_depth:
                    return
                seen.add(node)
                visited.append(node)
                for neighbor in self._out_edges.get(node, {}):
                    _dfs(neighbor, depth + 1)

            _dfs(start, 0)
            self._stats["searches"] += 1
            return visited

    # ── 路径查找 ──────────────────────────────────────────

    def shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """无权最短路径 (BFS)

        Args:
            source: 起始节点
            target: 目标节点

        Returns:
            节点 ID 列表表示路径, 不存在则返回 None
        """
        with self._lock:
            if source not in self._nodes or target not in self._nodes:
                return None
            if source == target:
                return [source]

            visited = {source}
            queue = deque([(source, [source])])

            while queue:
                node, path = queue.popleft()
                for neighbor in self._out_edges.get(node, {}):
                    if neighbor == target:
                        self._stats["searches"] += 1
                        return path + [neighbor]
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))

            self._stats["searches"] += 1
            return None

    def find_all_paths(self, source: str, target: str,
                       max_length: int = 10) -> List[List[str]]:
        """查找两个节点间的所有简单路径 (DFS, 有长度限制)

        Args:
            source: 起始节点
            target: 目标节点
            max_length: 最大路径长度

        Returns:
            所有路径的列表
        """
        with self._lock:
            if source not in self._nodes or target not in self._nodes:
                return []

            all_paths = []

            def _dfs(current: str, path: List[str], visited: Set[str]):
                if len(path) > max_length:
                    return
                if current == target:
                    all_paths.append(list(path))
                    return
                for neighbor in self._out_edges.get(current, {}):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        path.append(neighbor)
                        _dfs(neighbor, path, visited)
                        path.pop()
                        visited.discard(neighbor)

            _dfs(source, [source], {source})
            self._stats["searches"] += 1
            return all_paths

    # ── 子图提取 ──────────────────────────────────────────

    def extract_subgraph(self, node_ids: Set[str],
                         include_edges: bool = True) -> "KnowledgeGraph":
        """提取诱导子图

        Args:
            node_ids: 要提取的节点 ID 集合
            include_edges: 是否包含这些节点之间的边

        Returns:
            新的 KnowledgeGraph 实例
        """
        subgraph = KnowledgeGraph()
        with self._lock:
            for nid in node_ids:
                if nid in self._nodes:
                    node = self._nodes[nid]
                    props = {k: v.value for k, v in node.properties.items()}
                    subgraph.add_node(nid, **props)

            if include_edges:
                for source in node_ids:
                    for target, edge in self._out_edges.get(source, {}).items():
                        if target in node_ids:
                            props = {k: v.value for k, v in edge.properties.items()}
                            subgraph.add_edge(source, target, **props)

        return subgraph

    def k_hop_subgraph(self, center: str, k: int = 1) -> "KnowledgeGraph":
        """提取 k-hop 邻域子图

        Args:
            center: 中心节点 ID
            k: 跳数

        Returns:
            包含中心节点及其 k-hop 邻居的 KnowledgeGraph
        """
        with self._lock:
            if center not in self._nodes:
                return KnowledgeGraph()

            nodes_in_scope = {center}
            frontier = {center}

            for _ in range(k):
                next_frontier = set()
                for node in frontier:
                    for neighbor in self._out_edges.get(node, {}):
                        if neighbor not in nodes_in_scope:
                            nodes_in_scope.add(neighbor)
                            next_frontier.add(neighbor)
                    for neighbor in self._in_edges.get(node, {}):
                        if neighbor not in nodes_in_scope:
                            nodes_in_scope.add(neighbor)
                            next_frontier.add(neighbor)
                frontier = next_frontier
                if not frontier:
                    break

        return self.extract_subgraph(nodes_in_scope, include_edges=True)

    # ── 图统计 ────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取图统计信息"""
        with self._lock:
            n = len(self._nodes)
            e = sum(len(targets) for targets in self._out_edges.values())
            max_possible = n * (n - 1) if n > 1 else 0
            density = e / max_possible if max_possible > 0 else 0.0

            # 度分布
            degrees = [self.get_degree(nid) for nid in self._nodes]
            avg_degree = sum(degrees) / n if n > 0 else 0.0
            max_degree = max(degrees) if degrees else 0

            # 连通分量 (弱连通)
            components = self._find_weakly_connected_components()

            return {
                "node_count": n,
                "edge_count": e,
                "density": round(density, 6),
                "avg_degree": round(avg_degree, 2),
                "max_degree": max_degree,
                "connected_components": len(components),
                "largest_component_size": max((len(c) for c in components), default=0),
                "is_dag": self._is_dag(),
                **self._stats,
            }

    def _find_weakly_connected_components(self) -> List[Set[str]]:
        """查找弱连通分量"""
        visited = set()
        components = []

        for node_id in self._nodes:
            if node_id not in visited:
                component = set()
                queue = deque([node_id])
                visited.add(node_id)

                while queue:
                    current = queue.popleft()
                    component.add(current)
                    # 遍历所有邻居 (出边 + 入边, 视为无向)
                    for neighbor in self._out_edges.get(current, {}):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                    for neighbor in self._in_edges.get(current, {}):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

                components.append(component)

        return components

    def _is_dag(self) -> bool:
        """检查图是否为有向无环图 (DAG)"""
        with self._lock:
            # Kahn 算法
            in_degree = {nid: len(self._in_edges.get(nid, {})) for nid in self._nodes}
            queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
            visited_count = 0

            while queue:
                node = queue.popleft()
                visited_count += 1
                for neighbor in self._out_edges.get(node, {}):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            return visited_count == len(self._nodes)

    # ── JSON 持久化 ───────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "nodes": [node.to_dict() for node in self._nodes.values()],
                "edges": [],
                "version": "1.0",
                "exported_at": time.time(),
            }

    def to_dict_full(self) -> Dict[str, Any]:
        """完整序列化 (包含边)"""
        with self._lock:
            edges = []
            for source, targets in self._out_edges.items():
                for edge in targets.values():
                    edges.append(edge.to_dict())

            return {
                "nodes": [node.to_dict() for node in self._nodes.values()],
                "edges": edges,
                "version": "1.0",
                "exported_at": time.time(),
                "stats": self.get_stats(),
            }

    def export_json(self, path: Optional[str] = None, indent: int = 2) -> str:
        """导出为 JSON 字符串或文件

        Args:
            path: 可选的文件路径, 提供则写入文件
            indent: JSON 缩进

        Returns:
            JSON 字符串
        """
        data = self.to_dict_full()
        json_str = json.dumps(data, ensure_ascii=False, indent=indent, default=str)

        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"Knowledge graph exported to {path} ({len(data['nodes'])} nodes, {len(data['edges'])} edges)")

        return json_str

    def import_json(self, data: Union[str, Dict[str, Any], Path]):
        """从 JSON 导入

        Args:
            data: JSON 字符串、字典或文件路径
        """
        if isinstance(data, (str, Path)):
            path = Path(data)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(str(data))

        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data)}")

        with self._lock:
            # 导入节点
            for node_data in data.get("nodes", []):
                node = Node.from_dict(node_data)
                self._nodes[node.id] = node
                if node.id not in self._out_edges:
                    self._out_edges[node.id] = {}
                if node.id not in self._in_edges:
                    self._in_edges[node.id] = {}

            # 导入边
            for edge_data in data.get("edges", []):
                edge = Edge.from_dict(edge_data)
                src, tgt = edge.source, edge.target
                # 确保端点存在
                if src not in self._nodes:
                    self._nodes[src] = Node(id=src)
                    self._out_edges[src] = {}
                    self._in_edges[src] = {}
                if tgt not in self._nodes:
                    self._nodes[tgt] = Node(id=tgt)
                    self._out_edges[tgt] = {}
                    self._in_edges[tgt] = {}
                self._out_edges[src][tgt] = edge
                self._in_edges[tgt][src] = edge

            self._stats["adds"] += len(data.get("nodes", [])) + len(data.get("edges", []))

        logger.info(f"Imported knowledge graph: {len(data.get('nodes', []))} nodes, "
                    f"{len(data.get('edges', []))} edges")

    def clear(self):
        """清空图"""
        with self._lock:
            self._nodes.clear()
            self._out_edges.clear()
            self._in_edges.clear()
            self._stats = {"adds": 0, "removes": 0, "searches": 0}
        logger.info("Knowledge graph cleared")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_kg_instance: Optional[KnowledgeGraph] = None
_kg_lock = threading.Lock()


def get_knowledge_graph() -> KnowledgeGraph:
    """获取 KnowledgeGraph 全局单例 (auto-create)

    Returns:
        KnowledgeGraph 实例
    """
    global _kg_instance
    if _kg_instance is None:
        with _kg_lock:
            if _kg_instance is None:
                _kg_instance = KnowledgeGraph()
    return _kg_instance


def reset_knowledge_graph():
    """重置全局实例 (用于测试)"""
    global _kg_instance
    with _kg_lock:
        _kg_instance = None

"""Topological Memory Structure — v2.78
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
持久同调(Persistent Homology)用于发现记忆拓扑结构

核心: 
- H0(连通分量): 找到记忆簇 — 哪些记忆属于同一主题
- H1(环/洞): 发现知识gap — 记忆空间中缺失的连接
- 持久性条形码: 衡量拓扑特征的重要性
- 降维: 高维记忆→2D可视化

应用:
- 记忆检索: 同簇记忆一起召回
- 知识gap检测: 持久环=需要填补的知识空白
- 冗余检测: 短期存在的连通分量=噪音
"""
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TopologicalFeature:
    """拓扑特征"""
    dim: int = 0             # 0=连通分量, 1=环, 2=空腔
    birth: float = 0.0       # 出现时的距离阈值
    death: float = float('inf')  # 消失时的距离阈值
    persistence: float = 0.0  # death - birth
    members: List[str] = field(default_factory=list)  # 组成此特征的记忆ID


@dataclass
class MemoryCluster:
    """记忆簇"""
    id: str = ""
    members: List[str] = field(default_factory=list)
    centroid: np.ndarray = field(default_factory=lambda: np.zeros(8))
    density: float = 0.0
    coherence: float = 0.0


class TopologicalMemoryAnalyzer:
    """拓扑记忆分析器"""

    def __init__(self, max_memories: int = 500):
        self.max_memories = max_memories
        self._embeddings: Dict[str, np.ndarray] = {}  # memory_id → vector
        self._clusters: List[MemoryCluster] = []
        self._features: List[TopologicalFeature] = []
        self._distance_matrix: Optional[np.ndarray] = None

    # ── Embedding ──────────────────────────────────────

    def add_memory(self, memory_id: str, text: str,
                  importance: float = 0.5):
        """添加记忆到拓扑空间"""
        if len(self._embeddings) >= self.max_memories:
            return

        # 文本→向量 (简化: TF-based embedding)
        vec = self._text_to_vector(text, importance)
        self._embeddings[memory_id] = vec

    def _text_to_vector(self, text: str, importance: float) -> np.ndarray:
        """文本→8维特征向量"""
        vec = np.zeros(8)
        tl = text.lower()

        vec[0] = np.log1p(len(text))
        vec[1] = sum(1 for c in text if c.isdigit()) / max(1, len(text))
        vec[2] = sum(1 for c in text if c.isupper()) / max(1, len(text))
        vec[3] = sum(1 for c in text if not c.isalnum() and c != ' ') / max(1, len(text))

        tech_keywords = ['import','class','def','function','api','data',
                        'model','server','config','error','bug','fix',
                        'test','deploy','memory','agent']
        vec[5] = sum(1 for kw in tech_keywords if kw in tl) / max(1, len(tech_keywords))
        vec[6] = importance
        # 用hash引入区分度
        vec[7] = (hash(text) % 1000) / 1000.0
        
        # 关键词加权: 把前3个主要词的首字母hash加入vec[4]
        words = text.lower().split()[:5]
        keyword_hash = sum(hash(w) for w in words) % 100 / 100.0
        vec[4] = keyword_hash

        return vec

    # ── Distance Matrix ────────────────────────────────

    def compute_distance_matrix(self) -> np.ndarray:
        """计算记忆间的距离矩阵"""
        if len(self._embeddings) < 2:
            return np.array([[]])

        ids = list(self._embeddings.keys())
        n = len(ids)
        matrix = np.zeros((n, n))

        for i in range(n):
            vi = self._embeddings[ids[i]]
            for j in range(i+1, n):
                vj = self._embeddings[ids[j]]
                dist = np.linalg.norm(vi - vj)
                matrix[i][j] = dist
                matrix[j][i] = dist

        self._distance_matrix = matrix
        return matrix

    # ── Persistent Homology (简化实现) ─────────────────

    def compute_persistence(self) -> List[TopologicalFeature]:
        """计算持久同调特征"""
        if self._distance_matrix is None:
            self.compute_distance_matrix()

        ids = list(self._embeddings.keys())
        n = len(ids)
        if n < 2:
            return []

        features = []

        # 1. H0: 连通分量 (单链聚类+持久性)
        # 使用union-find跟踪分量合并
        parent = list(range(n))
        rank = [0] * n

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx == ry: return False
            if rank[rx] < rank[ry]: rx, ry = ry, rx
            parent[ry] = rx
            if rank[rx] == rank[ry]: rank[rx] += 1
            return True

        # 按距离排序的边
        edges = []
        for i in range(n):
            for j in range(i+1, n):
                edges.append((self._distance_matrix[i][j], i, j))
        edges.sort()

        # 连通分量跟踪
        component_birth = {i: 0.0 for i in range(n)}
        component_members = {i: {ids[i]} for i in range(n)}

        for dist, i, j in edges:
            ri, rj = find(i), find(j)
            if ri != rj:
                # 合并两个分量 → 一个"死掉"
                # 保留较大的分量作为"存活"
                if len(component_members[ri]) < len(component_members[rj]):
                    ri, rj = rj, ri

                death_component = rj
                birth = component_birth.get(death_component, 0)
                persistence = dist - birth

                if persistence > 0.05:  # 过滤噪音
                    features.append(TopologicalFeature(
                        dim=0,
                        birth=birth,
                        death=dist,
                        persistence=persistence,
                        members=list(component_members[death_component]),
                    ))

                # 合并
                union(ri, rj)
                new_root = find(ri)
                component_members[new_root] = (
                    component_members[ri] | component_members[rj]
                )
                component_birth[new_root] = min(
                    component_birth.get(ri, 0),
                    component_birth.get(rj, 0),
                )

        # 2. H1: 环检测 (持久环 = 知识gap)
        # 在新距离下不形成三角形的边→潜在的环
        for dist, i, j in edges:
            if dist > 0.3:  # 高距离阈值
                # 检查i和j是否可能形成环
                for k in range(n):
                    if k != i and k != j:
                        dik = self._distance_matrix[i][k] if i < k else self._distance_matrix[k][i]
                        djk = self._distance_matrix[j][k] if j < k else self._distance_matrix[k][j]
                        if dik < dist and djk < dist:
                            # i,j,k形成三角形但又不太紧密→潜在环
                            avg = (dist + dik + djk) / 3
                            if 0.2 < avg < 0.8:
                                features.append(TopologicalFeature(
                                    dim=1,
                                    birth=min(dist, dik, djk),
                                    death=max(dist, dik, djk),
                                    persistence=max(dist, dik, djk) - min(dist, dik, djk),
                                    members=[ids[i], ids[j], ids[k]],
                                ))
                            break  # 每个边只检测一次

        # 按持久性排序
        features.sort(key=lambda f: f.persistence, reverse=True)
        self._features = features[:50]
        return self._features

    # ── Clustering ─────────────────────────────────────

    def cluster(self, n_clusters: int = 5) -> List[MemoryCluster]:
        """基于拓扑的聚类"""
        if self._distance_matrix is None:
            self.compute_distance_matrix()

        ids = list(self._embeddings.keys())
        n = len(ids)
        if n < 2:
            return []

        # 简化: 使用距离阈值聚类
        threshold = np.percentile(self._distance_matrix[self._distance_matrix > 0], 30)

        # Union-find聚类
        parent = list(range(n))
        def find(x):
            while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry: parent[ry] = rx

        for i in range(n):
            for j in range(i+1, n):
                if self._distance_matrix[i][j] < threshold:
                    union(i, j)

        # 收集簇
        cluster_map = defaultdict(list)
        for i in range(n):
            cluster_map[find(i)].append(i)

        clusters = []
        for root, indices in cluster_map.items():
            if len(indices) < 3:
                continue

            member_ids = [ids[i] for i in indices]
            vectors = [self._embeddings[mid] for mid in member_ids]
            centroid = np.mean(vectors, axis=0)

            # 聚合度: 平均内部距离
            internal_dists = []
            for i in range(len(indices)):
                for j in range(i+1, len(indices)):
                    internal_dists.append(
                        self._distance_matrix[indices[i]][indices[j]]
                    )
            coherence = 1.0 - (np.mean(internal_dists) if internal_dists else 0)

            clusters.append(MemoryCluster(
                id=f"cluster-{root}",
                members=member_ids,
                centroid=centroid,
                density=len(member_ids) / n,
                coherence=round(coherence, 3),
            ))

        clusters.sort(key=lambda c: c.density, reverse=True)
        self._clusters = clusters[:n_clusters]
        return self._clusters

    # ── Analysis ───────────────────────────────────────

    def find_knowledge_gaps(self) -> List[str]:
        """发现知识gap (H1持久环)"""
        gaps = []
        for f in self._features:
            if f.dim == 1 and f.persistence > 0.3:
                gaps.append(
                    f"知识gap: {f.members} (持久性={f.persistence:.3f}), "
                    f"建议补充这3个概念之间的联系"
                )
        return gaps[:5]

    def find_memory_clusters(self) -> List[Dict]:
        """返回记忆簇摘要"""
        return [
            {
                "cluster_id": c.id,
                "size": len(c.members),
                "density": round(c.density, 3),
                "coherence": c.coherence,
                "sample_members": c.members[:3],
            }
            for c in self._clusters
        ]

    def get_persistence_barcode(self) -> List[Dict]:
        """持久性条形码数据"""
        return [
            {
                "dim": f.dim,
                "birth": round(f.birth, 3),
                "death": round(f.death, 3) if f.death < float('inf') else float('inf'),
                "persistence": round(f.persistence, 3),
                "n_members": len(f.members),
            }
            for f in self._features[:20]
        ]

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "total_memories": len(self._embeddings),
            "total_clusters": len(self._clusters),
            "total_features": len(self._features),
            "h0_features": sum(1 for f in self._features if f.dim == 0),
            "h1_features": sum(1 for f in self._features if f.dim == 1),
            "knowledge_gaps": len(self.find_knowledge_gaps()),
            "largest_cluster": max((c.density for c in self._clusters), default=0),
            "average_coherence": (
                np.mean([c.coherence for c in self._clusters])
                if self._clusters else 0
            ),
        }


# 单例
_analyzer: Optional[TopologicalMemoryAnalyzer] = None


def get_topology_analyzer() -> TopologicalMemoryAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = TopologicalMemoryAnalyzer()
    return _analyzer

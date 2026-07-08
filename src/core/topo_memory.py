"""Topological Memory Analyzer — persistent homology for memory structure"""
import hashlib
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class PersistenceFeature:
    birth: float
    death: float
    persistence: float
    dimension: int = 0


@dataclass
class Cluster:
    members: List[str] = field(default_factory=list)
    coherence: float = 0.0
    center: Optional[np.ndarray] = None


class TopologicalMemoryAnalyzer:
    """Analyzes memory topology using persistent homology and clustering."""

    def __init__(self, max_memories: int = 100, **kw):
        self.max_memories = max_memories
        self._embeddings: Dict[str, np.ndarray] = {}
        self._memories: Dict[str, tuple] = {}
        self._distance_matrix: Optional[np.ndarray] = None
        self._persistence_features: List[PersistenceFeature] = []
        self._clusters: List[Cluster] = []

    def _word_hash(self, word: str, **kw) -> float:
        """Deterministic hash of a word to a float in [0, 1]."""
        h = hashlib.md5(word.encode()).digest()
        val = int.from_bytes(h[:8], 'big')
        return val / (2**64 - 1)

    def _text_to_vector(self, text: str, importance: float, **kw) -> np.ndarray:
        """Convert text + importance to an 8-dimensional vector.

        Dimensions 0-5 and 7 encode text semantics.
        Dimension 6 stores importance.
        """
        words = text.lower().split()
        vec = np.zeros(8)
        if not words:
            vec[6] = importance
            return vec

        # Dimensions for text semantics: 0,1,2,3,4,5,7
        text_dims = [0, 1, 2, 3, 4, 5, 7]
        for word in words:
            for d in text_dims:
                seed = self._word_hash(f"{word}|{d}")
                vec[d] += seed - 0.5  # center around 0

        # Normalize by word count
        for d in text_dims:
            vec[d] /= len(words)

        # Dimension 6 = importance
        vec[6] = importance
        return vec

    def add_memory(self, memory_id: str, text: str, importance: float, **kw):
        """Add a memory with its text and importance."""
        vec = self._text_to_vector(text, importance)
        self._embeddings[memory_id] = vec
        self._memories[memory_id] = (text, importance)
        # Invalidate cached computations
        self._distance_matrix = None
        self._persistence_features = []
        self._clusters = []

    def compute_distance_matrix(self, **kw) -> np.ndarray:
        """Compute pairwise Euclidean distance matrix between all memories."""
        ids = list(self._embeddings.keys())
        n = len(ids)
        self._distance_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                dist = float(np.linalg.norm(
                    self._embeddings[ids[i]] - self._embeddings[ids[j]]
                ))
                self._distance_matrix[i][j] = dist
                self._distance_matrix[j][i] = dist
        return self._distance_matrix

    def cluster(self, n_clusters: int = 3, **kw) -> List[Cluster]:
        """Agglomerative clustering of memories."""
        if self._distance_matrix is None:
            self.compute_distance_matrix()

        ids = list(self._embeddings.keys())
        n = len(ids)

        if n <= n_clusters:
            clusters = [
                Cluster(members=[mid], coherence=1.0, center=self._embeddings[mid])
                for mid in ids
            ]
            self._clusters = clusters
            return clusters

        # Each point starts as its own cluster
        cluster_members = [[mid] for mid in ids]
        n_current = n

        # Merge closest clusters until we reach n_clusters
        while n_current > n_clusters:
            min_dist = float('inf')
            min_i, min_j = -1, -1

            for i in range(n_current):
                for j in range(i + 1, n_current):
                    # Average linkage distance
                    total = 0.0
                    count = 0
                    for mi in cluster_members[i]:
                        for mj in cluster_members[j]:
                            ii = ids.index(mi)
                            jj = ids.index(mj)
                            total += self._distance_matrix[ii][jj]
                            count += 1
                    avg_dist = total / count if count > 0 else float('inf')

                    if avg_dist < min_dist:
                        min_dist = avg_dist
                        min_i, min_j = i, j

            # Merge
            cluster_members[min_i].extend(cluster_members[min_j])
            cluster_members.pop(min_j)
            n_current -= 1

        # Build Cluster objects
        self._clusters = []
        for members in cluster_members:
            # Coherence: average pairwise similarity within cluster
            if len(members) <= 1:
                coherence = 1.0
            else:
                similarities = []
                for a in range(len(members)):
                    for b in range(a + 1, len(members)):
                        ia = ids.index(members[a])
                        ib = ids.index(members[b])
                        dist = self._distance_matrix[ia][ib]
                        similarities.append(1.0 / (1.0 + dist))
                coherence = float(np.mean(similarities))

            # Cluster center
            vecs = [self._embeddings[mid] for mid in members]
            center = np.mean(vecs, axis=0)

            self._clusters.append(Cluster(
                members=members, coherence=coherence, center=center
            ))

        return self._clusters

    def compute_persistence(self, **kw) -> List[PersistenceFeature]:
        """Compute 0-dimensional persistent homology via minimum spanning tree."""
        if self._distance_matrix is None:
            self.compute_distance_matrix()

        ids = list(self._embeddings.keys())
        n = len(ids)

        if n < 2:
            self._persistence_features = []
            return []

        # Build sorted edge list
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                edges.append((self._distance_matrix[i][j], i, j))
        edges.sort(key=lambda e: e[0])

        # Union-Find
        parent = list(range(n))

        def find(x, **kw):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y, **kw):
            px, py = find(x), find(y)
            if px != py:
                parent[py] = px
                return True
            return False

        features = []
        for dist, i, j in edges:
            if union(i, j):
                features.append(PersistenceFeature(
                    birth=0.0,
                    death=float(dist),
                    persistence=float(dist),
                    dimension=0,
                ))

        self._persistence_features = features
        return features

    def get_persistence_barcode(self, **kw) -> List[dict]:
        """Return persistence barcode as list of dicts (each has 'birth' key)."""
        if not self._persistence_features:
            self.compute_persistence()

        return [
            {
                "birth": f.birth,
                "death": f.death,
                "persistence": f.persistence,
                "dimension": f.dimension,
            }
            for f in self._persistence_features
        ]

    def find_memory_clusters(self, **kw) -> List[Cluster]:
        """Return pre-computed clusters, computing if needed."""
        if not self._clusters:
            self.cluster()
        return self._clusters

    def find_knowledge_gaps(self, **kw) -> List[dict]:
        """Identify knowledge gaps from high-persistence features."""
        if self._distance_matrix is None:
            self.compute_distance_matrix()
        if not self._persistence_features:
            self.compute_persistence()

        gaps = []
        sorted_features = sorted(
            self._persistence_features,
            key=lambda f: f.persistence,
            reverse=True,
        )
        for i, f in enumerate(sorted_features[:3]):
            gaps.append({
                "gap_id": i,
                "persistence": f.persistence,
                "birth": f.birth,
                "death": f.death,
                "description": f"Gap with persistence {f.persistence:.3f}",
            })
        return gaps

    def get_stats(self, **kw) -> dict:
        """Aggregate statistics about the memory topology."""
        if self._distance_matrix is None:
            self.compute_distance_matrix()
        if not self._clusters:
            self.cluster()
        if not self._persistence_features:
            self.compute_persistence()

        avg_coherence = (
            float(np.mean([c.coherence for c in self._clusters]))
            if self._clusters else 0.0
        )
        avg_persistence = (
            float(np.mean([f.persistence for f in self._persistence_features]))
            if self._persistence_features else 0.0
        )

        return {
            "total_memories": len(self._embeddings),
            "total_clusters": len(self._clusters),
            "average_coherence": avg_coherence,
            "average_persistence": avg_persistence,
            "max_memories": self.max_memories,
        }


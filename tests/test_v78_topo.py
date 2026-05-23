"""v2.78 Topological Memory — 测试"""
import sys
from pathlib import Path

import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def tma():
    from src.core.topo_memory import TopologicalMemoryAnalyzer
    a = TopologicalMemoryAnalyzer(max_memories=100)
    # Add diverse memories
    a.add_memory("m1", "Python is a programming language", 0.8)
    a.add_memory("m2", "Python is used for data science", 0.7)
    a.add_memory("m3", "JavaScript runs in browsers", 0.6)
    a.add_memory("m4", "React is a JavaScript framework", 0.5)
    a.add_memory("m5", "Docker containers isolate applications", 0.4)
    a.add_memory("m6", "Kubernetes orchestrates containers", 0.4)
    a.add_memory("m7", "Machine learning uses neural networks", 0.8)
    a.add_memory("m8", "Deep learning is a subset of ML", 0.7)
    a.add_memory("m9", "Rust is a systems programming language", 0.6)
    a.add_memory("m10", "C++ is used for game engines", 0.5)
    return a


class TestEmbedding:
    def test_add_memory(self, tma):
        assert len(tma._embeddings) >= 10

    def test_text_to_vector(self, tma):
        vec = tma._text_to_vector("import numpy as np", 0.8)
        assert len(vec) == 8
        assert vec[6] == 0.8  # importance


class TestDistanceMatrix:
    def test_compute_distance_matrix(self, tma):
        dm = tma.compute_distance_matrix()
        assert dm.shape == (10, 10)
        assert dm[0][1] >= 0  # non-negative

    def test_clustering_basic(self, tma):
        """基本聚类: 10条记忆应分出簇"""
        tma.compute_distance_matrix()
        clusters = tma.cluster(n_clusters=3)
        assert len(clusters) >= 1
        # 至少有一个簇有3+成员
        assert any(len(c.members) >= 3 for c in clusters)


class TestPersistence:
    def test_compute_persistence(self, tma):
        tma.compute_distance_matrix()
        features = tma.compute_persistence()
        assert len(features) > 0
        for f in features:
            assert f.persistence > 0

    def test_persistence_barcode(self, tma):
        tma.compute_distance_matrix()
        tma.compute_persistence()
        barcode = tma.get_persistence_barcode()
        assert len(barcode) > 0
        assert "birth" in barcode[0]


class TestClustering:
    def test_cluster(self, tma):
        tma.compute_distance_matrix()
        clusters = tma.cluster(n_clusters=3)
        assert len(clusters) >= 1
        # Python相关的应该在同一个簇
        for c in clusters:
            assert c.coherence > 0

    def test_find_clusters_summary(self, tma):
        tma.compute_distance_matrix()
        tma.cluster()
        clusters = tma.find_memory_clusters()
        assert len(clusters) >= 1


class TestKnowledgeGaps:
    def test_find_knowledge_gaps(self, tma):
        tma.compute_distance_matrix()
        tma.compute_persistence()
        gaps = tma.find_knowledge_gaps()
        assert isinstance(gaps, list)


class TestStats:
    def test_stats(self, tma):
        tma.compute_distance_matrix()
        tma.compute_persistence()
        tma.cluster()
        stats = tma.get_stats()
        assert stats["total_memories"] >= 10
        assert stats["total_clusters"] >= 1

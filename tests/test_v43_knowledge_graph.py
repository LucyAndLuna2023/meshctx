"""v3.43 Knowledge Graph tests"""
import pytest

class TestKnowledgeGraph:
    def test_add_entity(self):
        from src.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.entities.clear()
        e = kg.add_entity("Python", "language")
        assert e.name == "Python"
        assert "Python" in kg.entities
    
    def test_add_relation(self):
        from src.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.entities.clear()
        kg.relations.clear()
        kg.add_entity("Python", "language")
        kg.add_entity("FastAPI", "framework")
        r = kg.add_relation("Python", "FastAPI", "has_framework", 0.9)
        assert r.relation_type == "has_framework"
        assert len(kg.relations) == 1
    
    def test_query_neighbors(self):
        from src.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.entities.clear()
        kg.relations.clear()
        kg._adjacency.clear()
        kg.add_entity("A")
        kg.add_entity("B")
        kg.add_entity("C")
        kg.add_relation("A", "B", "links_to")
        kg.add_relation("B", "C", "links_to")
        result = kg.query_neighbors("A", depth=2)
        assert result['total'] >= 1
    
    def test_find_path(self):
        from src.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.entities.clear()
        kg.relations.clear()
        kg._adjacency.clear()
        kg.add_relation("A", "B", "to")
        kg.add_relation("B", "C", "to")
        path = kg.find_path("A", "C")
        assert path is not None
        assert path == ["A", "B", "C"]
    
    def test_no_path(self):
        from src.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.entities.clear()
        kg.relations.clear()
        kg._adjacency.clear()
        kg.add_entity("X")
        kg.add_entity("Y")
        path = kg.find_path("X", "Y", max_depth=3)
        assert path is None
    
    def test_stats(self):
        from src.core.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        stats = kg.get_stats()
        assert 'entities' in stats
        assert 'relations' in stats

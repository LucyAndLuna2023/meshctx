"""v3.61 Knowledge Graph — tests"""
import pytest
from src.core.knowledge_graph import KnowledgeGraph, KGNode, KGEdge, get_knowledge_graph

class TestKG:
    def test_add_node(self):
        kg = KnowledgeGraph(); kg.add_node("a","Alpha")
        assert "a" in kg._nodes

    def test_add_edge(self):
        kg = KnowledgeGraph(); kg.add_edge("a","b","uses")
        assert len(kg._edges) == 1

    def test_neighbors(self):
        kg = KnowledgeGraph(); kg.add_edge("a","b"); kg.add_edge("a","c")
        n = kg.query_neighbors("a")
        assert n["node"]["id"] == "a"; assert len(n["outgoing"]) == 2; assert n["degree"] == 2

    def test_shortest_path(self):
        kg = KnowledgeGraph()
        kg.add_edge("a","b"); kg.add_edge("b","c"); kg.add_edge("a","d")
        path = kg.shortest_path("a","c")
        assert path == ["a","b","c"]

    def test_most_connected(self):
        kg = KnowledgeGraph()
        kg.add_edge("hub","a"); kg.add_edge("hub","b"); kg.add_edge("hub","c")
        top = kg.most_connected(3)
        assert top[0][0] == "hub"

    def test_search(self):
        kg = KnowledgeGraph(); kg.add_node("py","Python",type="language")
        results = kg.search("python")
        assert len(results) >= 1

    def test_to_dict(self):
        kg = KnowledgeGraph(); kg.add_edge("x","y")
        d = kg.to_dict()
        assert "nodes" in d; assert "edges" in d

    def test_singleton(self):
        assert get_knowledge_graph() is get_knowledge_graph()

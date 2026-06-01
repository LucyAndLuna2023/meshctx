"""v3.99 Knowledge Graph V2 — entity extraction, relation inference, storage, search, fusion."""
import json
import os
import tempfile
import time

import pytest

from src.core.knowledge_graph_v2 import (
    KnowledgeGraphV2,
    Entity,
    Relation,
    KGVDocument,
    get_knowledge_graph_v2,
    reset_knowledge_graph_v2,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_sample_kg() -> KnowledgeGraphV2:
    """Create a knowledge graph with sample entities and relations."""
    kg = KnowledgeGraphV2(name="sample")
    kg.add_entity("Python", type="artifact", confidence=0.9)
    kg.add_entity("Django", type="artifact", confidence=0.85)
    kg.add_entity("FastAPI", type="artifact", confidence=0.8)
    kg.add_entity("Web Framework", type="concept", confidence=0.7)
    kg.add_entity("REST API", type="concept", confidence=0.75)
    kg.add_entity("Asynchronous", type="concept", confidence=0.6)
    kg.add_relation("Python", "Django", relation="has_framework", weight=2.0)
    kg.add_relation("Python", "FastAPI", relation="has_framework", weight=1.5)
    kg.add_relation("Django", "Web Framework", relation="is_a", weight=1.0)
    kg.add_relation("FastAPI", "Web Framework", relation="is_a", weight=1.0)
    kg.add_relation("FastAPI", "Asynchronous", relation="supports", weight=1.2)
    return kg


# ═══════════════════════════════════════════════════════════
# 1) Entity Management
# ═══════════════════════════════════════════════════════════

class TestEntityManagement:
    """Basic entity CRUD operations."""

    def test_add_and_get_entity(self):
        kg = KnowledgeGraphV2()
        ent = kg.add_entity("Machine Learning", type="concept", confidence=0.95)
        assert ent.name == "Machine Learning"
        assert ent.type == "concept"
        assert ent.confidence == 0.95
        retrieved = kg.get_entity(ent.id)
        assert retrieved is not None
        assert retrieved.name == "Machine Learning"

    def test_add_entity_update(self):
        """Adding same entity again updates confidence/weight."""
        kg = KnowledgeGraphV2()
        kg.add_entity("Test", confidence=0.5, weight=1.0)
        kg.add_entity("Test", confidence=0.9, weight=2.0, aliases=["T"])
        ent = kg.find_entity("Test")
        assert ent.confidence == 0.9
        assert ent.weight == 2.0
        assert "T" in ent.aliases

    def test_find_entity_by_alias(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("Artificial Intelligence", aliases=["AI", "Machine Intelligence"])
        found = kg.find_entity("AI")
        assert found is not None
        assert found.name == "Artificial Intelligence"

    def test_list_entities_filtered(self):
        kg = _make_sample_kg()
        concepts = kg.list_entities(entity_type="concept")
        artifacts = kg.list_entities(entity_type="artifact")
        assert len(concepts) >= 3
        assert len(artifacts) >= 3
        for e in concepts:
            assert e.type == "concept"
        for e in artifacts:
            assert e.type == "artifact"


# ═══════════════════════════════════════════════════════════
# 2) Entity Extraction
# ═══════════════════════════════════════════════════════════

class TestEntityExtraction:
    """Entity extraction from natural language text."""

    def test_extract_capitalized_entities(self):
        kg = KnowledgeGraphV2()
        text = "John Smith works at Google in Mountain View on the Search Engine project."
        extracted = kg.extract_entities(text)
        names = {e.name for e in extracted}
        assert "John Smith" in names
        assert "Google" in names
        assert "Mountain View" in names
        assert "Search Engine" in names

    def test_extract_empty_text(self):
        kg = KnowledgeGraphV2()
        extracted = kg.extract_entities("")
        assert extracted == []
        extracted2 = kg.extract_entities("   ")
        assert extracted2 == []

    def test_extract_acronyms(self):
        kg = KnowledgeGraphV2()
        text = "The API uses JSON over HTTP for REST communications via URL routing."
        extracted = kg.extract_entities(text)
        names = {e.name for e in extracted}
        assert "API" in names
        assert "JSON" in names
        assert "HTTP" in names
        assert "REST" in names

    def test_extract_with_confidence_threshold(self):
        kg = KnowledgeGraphV2()
        text = "Alice and Bob discussed Machine Learning and Deep Learning with Dr. Eve."
        extracted = kg.extract_entities(text, min_confidence=0.3)
        names = {e.name for e in extracted}
        # Single-occurrence items should be above 0.3 threshold
        assert "Alice" in names
        assert "Bob" in names

    def test_extract_respects_min_confidence(self):
        kg = KnowledgeGraphV2()
        text = "X and Y and Z are very obscure. A B C appear once each."
        extracted_high = kg.extract_entities(text, min_confidence=0.9)
        extracted_low = kg.extract_entities(text, min_confidence=0.1)
        # Higher threshold should yield fewer or equal results
        assert len(extracted_high) <= len(extracted_low)


# ═══════════════════════════════════════════════════════════
# 3) Relation Inference
# ═══════════════════════════════════════════════════════════

class TestRelationInference:
    """Relation inference from text patterns and co-occurrence."""

    def test_infer_pattern_based(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("SQLite", type="artifact")
        kg.add_entity("Database", type="concept")
        kg.add_entity("Python", type="artifact")
        text = "SQLite is a Database. SQLite is part of Python."
        kg.infer_relations(text, use_patterns=True, use_cooccurrence=False)
        rels = kg.get_relations()
        # Should infer at least one relation via "is a" or "part of" patterns
        assert len(rels) > 0

    def test_infer_cooccurrence(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("Redis", type="artifact")
        kg.add_entity("Cache", type="concept")
        kg.extract_entities("Redis is used as a Cache for fast lookups.")
        kg.infer_relations(use_patterns=True, use_cooccurrence=True)
        rels = kg.get_relations()
        # Should have at least one relation
        assert len(rels) > 0

    def test_infer_no_duplicate_relations(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("A", type="concept")
        kg.add_entity("B", type="concept")
        text = "A is related to B."
        r1 = kg.infer_relations(text)
        r2 = kg.infer_relations(text)
        # Should not create duplicate relations
        assert len(r2) == 0  # No new relations on second call


# ═══════════════════════════════════════════════════════════
# 4) Graph Database Storage
# ═══════════════════════════════════════════════════════════

class TestGraphDBStorage:
    """JSON-based persistent storage."""

    def test_store_and_load_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "kg_v2.json")

        kg1 = _make_sample_kg()
        kg1.store_to_db(path)

        assert os.path.exists(path)

        kg2 = KnowledgeGraphV2(name="loaded")
        success = kg2.load_from_db(path)
        assert success is True

        stats2 = kg2.stats()
        assert stats2["total_entities"] >= 5
        assert stats2["total_relations"] >= 5

        os.remove(path)
        os.rmdir(tmpdir)

    def test_load_merges_with_existing(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "merge.json")

        kg1 = KnowledgeGraphV2()
        kg1.add_entity("NodeA")
        kg1.store_to_db(path)

        kg2 = KnowledgeGraphV2()
        kg2.add_entity("NodeB")
        kg2.load_from_db(path)

        assert kg2.get_entity("nodea") is not None
        assert kg2.get_entity("nodeb") is not None

        os.remove(path)
        os.rmdir(tmpdir)

    def test_load_nonexistent(self):
        kg = KnowledgeGraphV2()
        ok = kg.load_from_db("/nonexistent/kg.json")
        assert ok is False


# ═══════════════════════════════════════════════════════════
# 5) Semantic Search
# ═══════════════════════════════════════════════════════════

class TestSemanticSearch:
    """Semantic search with TF-IDF and fuzzy matching."""

    def test_exact_match_scores_highest(self):
        kg = _make_sample_kg()
        results = kg.semantic_search("Python")
        assert len(results) > 0
        # Python should be top result
        assert results[0][0].name == "Python"

    def test_partial_match(self):
        kg = _make_sample_kg()
        results = kg.semantic_search("Framework")
        assert len(results) > 0
        names = {r[0].name for r in results}
        assert "Web Framework" in names or "Django" in names

    def test_empty_search(self):
        kg = _make_sample_kg()
        results = kg.semantic_search("zzz_nonexistent_zzz")
        assert results == []

    def test_search_with_tfidf(self):
        kg = KnowledgeGraphV2()
        kg.extract_entities("PostgreSQL is a powerful Database management system.")
        kg.extract_entities("MongoDB is a popular NoSQL document store.")
        # Search for entity that appears in both contexts
        results = kg.semantic_search("PostgreSQL", use_tfidf=True)
        assert len(results) > 0


# ═══════════════════════════════════════════════════════════
# 6) Knowledge Fusion & Deduplication
# ═══════════════════════════════════════════════════════════

class TestKnowledgeFusion:
    """Multi-source knowledge fusion and deduplication."""

    def test_fuse_adds_new_entities(self):
        kg1 = KnowledgeGraphV2()
        kg1.add_entity("Alpha")
        kg2 = KnowledgeGraphV2()
        kg2.add_entity("Beta")
        new_ent, new_rel = kg1.fuse_knowledge(kg2)
        assert new_ent == 1
        assert kg1.find_entity("Beta") is not None

    def test_fuse_merges_duplicates(self):
        kg1 = KnowledgeGraphV2()
        kg1.add_entity("Shared", confidence=0.5, type="concept")
        kg2 = KnowledgeGraphV2()
        kg2.add_entity("Shared", confidence=0.9, type="artifact", aliases=["S"])
        new_ent, new_rel = kg1.fuse_knowledge(kg2, merge_strategy="max_confidence")
        assert new_ent == 0  # No new entity, merged into existing
        ent = kg1.find_entity("Shared")
        assert ent.confidence == 0.9
        assert ent.type == "artifact"
        assert "S" in ent.aliases

    def test_fuse_relates_entities(self):
        kg1 = KnowledgeGraphV2()
        kg1.add_entity("A"); kg1.add_entity("B")
        kg1.add_relation("A", "B", relation="connected")

        kg2 = KnowledgeGraphV2()
        kg2.add_entity("A"); kg2.add_entity("B")
        kg2.add_relation("A", "B", relation="connected")
        kg2.add_relation("A", "B", relation="depends_on")

        new_ent, new_rel = kg1.fuse_knowledge(kg2)
        assert new_ent == 0
        assert new_rel == 1  # Only the new "depends_on" relation added
        rels = kg1.get_relations()
        rel_types = {r.relation for r in rels}
        assert "connected" in rel_types
        assert "depends_on" in rel_types

    def test_deduplicate_similar_entities(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("Machine Learning", type="concept")
        kg.add_entity("Machine Learning Algorithms", type="concept")
        kg.add_entity("Unrelated Topic", type="concept")

        merged = kg.deduplicate_entities(similarity_threshold=0.5)
        assert merged >= 1

    def test_deduplicate_no_merge_dissimilar(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("Python", type="artifact")
        kg.add_entity("JavaScript", type="artifact")
        kg.add_entity("Rust", type="artifact")

        merged = kg.deduplicate_entities(similarity_threshold=0.8)
        assert merged == 0


# ═══════════════════════════════════════════════════════════
# 7) Graph Traversal
# ═══════════════════════════════════════════════════════════

class TestGraphTraversal:
    """BFS, shortest path, and connectivity."""

    def test_shortest_path(self):
        kg = _make_sample_kg()
        path = kg.shortest_path("Python", "Asynchronous")
        assert path is not None
        assert path[0] == "Python"
        assert path[-1] == "Asynchronous"

    def test_shortest_path_no_route(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("Island")
        kg.add_entity("Continent")
        path = kg.shortest_path("Island", "Continent")
        assert path is None

    def test_most_connected(self):
        kg = _make_sample_kg()
        top = kg.most_connected(3)
        assert len(top) <= 3
        # Python should be among most connected (has 2 outgoing relations)
        names = [t[2] for t in top]
        assert "Python" in names

    def test_get_neighbors(self):
        kg = _make_sample_kg()
        py = kg.find_entity("Python")
        neighbors = kg.get_neighbors(py.id, depth=1)
        assert py.id in neighbors
        neighbor_ids = [t[0] for t in neighbors[py.id]]
        assert len(neighbor_ids) >= 2  # Django + FastAPI


# ═══════════════════════════════════════════════════════════
# 8) Serialization & Stats
# ═══════════════════════════════════════════════════════════

class TestSerialization:
    """to_dict / from_dict roundtrip and stats."""

    def test_serialization_roundtrip(self):
        kg1 = _make_sample_kg()
        d = kg1.to_dict()
        kg2 = KnowledgeGraphV2.from_dict(d)
        assert kg2.stats()["total_entities"] == kg1.stats()["total_entities"]
        assert kg2.stats()["total_relations"] == kg1.stats()["total_relations"]

    def test_stats(self):
        kg = _make_sample_kg()
        s = kg.stats()
        assert s["name"] == "sample"
        assert s["total_entities"] >= 5
        assert s["total_relations"] >= 5
        assert "entity_types" in s
        assert "top_connected" in s
        assert isinstance(s["density"], float)

    def test_clear(self):
        kg = _make_sample_kg()
        kg.clear()
        assert kg.stats()["total_entities"] == 0
        assert kg.stats()["total_relations"] == 0

    def test_singleton(self):
        reset_knowledge_graph_v2()
        kg1 = get_knowledge_graph_v2()
        kg2 = get_knowledge_graph_v2()
        assert kg1 is kg2
        kg1.add_entity("SingletonTest")
        assert kg2.find_entity("SingletonTest") is not None


# ═══════════════════════════════════════════════════════════
# 9) Edge Cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Corner cases and error handling."""

    def test_entity_id_normalization(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("My Cool Project!")
        ent = kg.find_entity("My Cool Project!")
        assert ent is not None
        assert "my_cool_project" in ent.id

    def test_get_nonexistent_entity(self):
        kg = KnowledgeGraphV2()
        assert kg.get_entity("no_such_id") is None

    def test_get_neighbors_nonexistent(self):
        kg = KnowledgeGraphV2()
        assert kg.get_neighbors("ghost") == {}

    def test_get_relations_for_nonexistent(self):
        kg = KnowledgeGraphV2()
        rels = kg.get_relations("no_such")
        assert rels == []

    def test_shortest_path_missing_node(self):
        kg = KnowledgeGraphV2()
        kg.add_entity("A")
        assert kg.shortest_path("A", "Z") is None
        assert kg.shortest_path("Z", "A") is None

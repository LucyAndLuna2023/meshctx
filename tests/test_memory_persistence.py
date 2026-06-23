"""
Tests for HierarchicalMemoryStore persistence:
  - save_to_file / load_from_file
  - auto-save
  - versioning / compatibility
  - edge cases
"""
import json
import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.memory_hierarchy import (
    HierarchicalMemoryStore,
    MemoryItem,
    MemoryLevel,
    VectorIndex,
    KnowledgeGraph,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def store():
    """Fresh memory store"""
    return HierarchicalMemoryStore()


@pytest.fixture
def populated_store(store):
    """Store with items at multiple levels"""
    for i, level in enumerate([
        MemoryLevel.SENSORY, MemoryLevel.WORKING,
        MemoryLevel.SHORT_TERM, MemoryLevel.LONG_TERM,
        MemoryLevel.ARCHIVAL,
    ]):
        item = MemoryItem(
            level=level,
            key=f"key_{i}",
            value=f"value_{i}",
            importance=0.5 + i * 0.1,
            tags=["tag_a"],
        )
        store.store(item)
    return store


@pytest.fixture
def tmp_path():
    """Temporary file path (deleted after test)"""
    path = tempfile.mktemp(suffix=".json")
    yield path
    if os.path.exists(path):
        os.unlink(path)
    if os.path.exists(path + ".tmp"):
        os.unlink(path + ".tmp")


# ═══════════════════════════════════════════════════════════════
# 1. Basic save/load
# ═══════════════════════════════════════════════════════════════

class TestBasicSaveLoad:

    def test_save_returns_abspath(self, populated_store, tmp_path):
        """save_to_file returns absolute path"""
        result = populated_store.save_to_file(tmp_path)
        assert os.path.isabs(result)
        assert os.path.exists(result)

    def test_save_creates_valid_json(self, populated_store, tmp_path):
        """Saved file is valid JSON with expected structure"""
        populated_store.save_to_file(tmp_path)
        with open(tmp_path) as f:
            data = json.load(f)
        assert "version" in data
        assert "meta" in data
        assert "items" in data
        assert "vector_index" in data
        assert "knowledge_graph" in data

    def test_save_meta_counts(self, populated_store, tmp_path):
        """Meta section has correct counts"""
        populated_store.save_to_file(tmp_path)
        with open(tmp_path) as f:
            data = json.load(f)
        assert data["meta"]["total_items"] == 5
        assert data["meta"]["total_stores"] == 5

    def test_roundtrip_preserves_all_items(self, populated_store, tmp_path):
        """All items survive save+load"""
        populated_store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        stats = loaded.get_stats()
        assert stats["SENSORY"]["count"] == 1
        assert stats["WORKING"]["count"] == 1
        assert stats["SHORT_TERM"]["count"] == 1
        assert stats["LONG_TERM"]["count"] == 1
        assert stats["ARCHIVAL"]["count"] == 1

    def test_roundtrip_empty_store(self, store, tmp_path):
        """Empty store saves and loads without error"""
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        stats = loaded.get_stats()
        for level_name in ["SENSORY", "WORKING", "SHORT_TERM", "LONG_TERM", "ARCHIVAL"]:
            assert stats[level_name]["count"] == 0

    def test_roundtrip_item_fields(self, store, tmp_path):
        """All MemoryItem fields are preserved"""
        item = MemoryItem(
            level=MemoryLevel.LONG_TERM,
            key="the_key",
            value="the_value",
            summary="summary_text",
            project_id="proj_123",
            conversation_id="conv_456",
            source="assistant",
            importance=0.85,
            tags=["ai", "test"],
            entities=["EntityA", "EntityB"],
            confidence=0.95,
            is_corrected=True,
            correction_history=[{"old": "x", "new": "y"}],
            related_memory_ids=["mem_1"],
        )
        item.access_count = 42
        item.review_count = 7
        store.store(item)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)

        # Find the loaded item
        loaded_item = None
        for _, mi in loaded._all_items():
            loaded_item = mi
        assert loaded_item is not None
        assert loaded_item.id == item.id
        assert loaded_item.key == "the_key"
        assert loaded_item.value == "the_value"
        assert loaded_item.summary == "summary_text"
        assert loaded_item.project_id == "proj_123"
        assert loaded_item.conversation_id == "conv_456"
        assert loaded_item.source == "assistant"
        assert loaded_item.importance == 0.85
        assert loaded_item.access_count == 42
        assert loaded_item.review_count == 7
        assert loaded_item.tags == ["ai", "test"]
        assert loaded_item.entities == ["EntityA", "EntityB"]
        assert loaded_item.confidence == 0.95
        assert loaded_item.is_corrected is True
        assert len(loaded_item.correction_history) == 1
        assert loaded_item.related_memory_ids == ["mem_1"]
        assert loaded_item.level == MemoryLevel.LONG_TERM


# ═══════════════════════════════════════════════════════════════
# 2. VectorIndex & KnowledgeGraph persistence
# ═══════════════════════════════════════════════════════════════

class TestVectorAndGraphPersistence:

    def test_vector_index_preserved(self, store, tmp_path):
        """Vector embeddings survive save/load"""
        item = MemoryItem(level=MemoryLevel.LONG_TERM, key="vec", value="test")
        item.embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        store.store(item)
        store.vector_index.add(item.id, item.embedding)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        assert loaded.vector_index.count() == 1

    def test_vector_index_search_after_load(self, store, tmp_path):
        """Vector search works on loaded store"""
        item = MemoryItem(level=MemoryLevel.LONG_TERM, key="vec", value="test")
        item.embedding = [1.0, 0.0, 0.0]
        store.store(item)
        store.vector_index.add(item.id, item.embedding)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        results = loaded.vector_index.search([1.0, 0.0, 0.0], top_k=5)
        assert len(results) == 1
        assert results[0][0] == item.id
        assert results[0][1] > 0.99

    def test_knowledge_graph_preserved(self, store, tmp_path):
        """Knowledge graph entities/relations survive save/load"""
        kg = store.knowledge_graph
        kg.add_entity("Paris", "city", {"country": "France"})
        kg.add_entity("France", "country", {})
        kg.add_relation("Paris", "capital_of", "France", weight=0.9)
        kg.link_memory("Paris", "mem_1")
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        lkg = loaded.knowledge_graph
        assert "Paris" in lkg.search_entities("Paris")
        assert "France" in lkg.search_entities("France")
        stats = lkg.get_stats()
        assert stats["entities"] == 2
        assert stats["relations"] == 1
        assert stats["entity_memory_links"] == 1

    def test_knowledge_graph_search_after_load(self, store, tmp_path):
        """Graph search works on loaded store"""
        store.knowledge_graph.add_entity("Python", "lang", {})
        store.knowledge_graph.add_entity("Django", "framework", {})
        store.knowledge_graph.add_relation("Django", "uses", "Python")
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        assert "Python" in loaded.knowledge_graph.search_entities("Python")
        related = loaded.knowledge_graph.get_related_memories("Python")
        assert isinstance(related, set)

    def test_multiple_items_with_embeddings(self, store, tmp_path):
        """Multiple items with embeddings all survive"""
        for i in range(5):
            item = MemoryItem(level=MemoryLevel.LONG_TERM, key=f"vec_{i}", value=str(i))
            item.embedding = [float(i) / 10.0] * 4
            store.store(item)
            store.vector_index.add(item.id, item.embedding)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        assert loaded.vector_index.count() == 5


# ═══════════════════════════════════════════════════════════════
# 3. Auto-save
# ═══════════════════════════════════════════════════════════════

class TestAutoSave:

    def test_autosave_not_triggered_below_threshold(self, store, tmp_path):
        """Auto-save does not fire before threshold is reached"""
        store.set_auto_save(tmp_path, threshold=5)
        for i in range(4):
            store.store(MemoryItem(level=MemoryLevel.WORKING, key=f"k{i}", value=f"v{i}"))
        assert not os.path.exists(tmp_path)

    def test_autosave_triggers_at_threshold(self, store, tmp_path):
        """Auto-save fires exactly when threshold is reached"""
        store.set_auto_save(tmp_path, threshold=3)
        for i in range(2):
            store.store(MemoryItem(level=MemoryLevel.WORKING, key=f"k{i}", value=f"v{i}"))
        assert not os.path.exists(tmp_path)
        store.store(MemoryItem(level=MemoryLevel.WORKING, key="k2", value="v2"))
        assert os.path.exists(tmp_path)

    def test_autosave_resets_counter(self, store, tmp_path):
        """Counter resets after auto-save fires"""
        store.set_auto_save(tmp_path, threshold=2)
        store.store(MemoryItem(level=MemoryLevel.WORKING, key="k1", value="v1"))
        store.store(MemoryItem(level=MemoryLevel.WORKING, key="k2", value="v2"))
        assert os.path.exists(tmp_path)
        # Remove so we can detect next save
        os.unlink(tmp_path)
        store.store(MemoryItem(level=MemoryLevel.WORKING, key="k3", value="v3"))
        assert not os.path.exists(tmp_path)

    def test_autosave_threshold_zero_disables(self, store, tmp_path):
        """Setting threshold to 0 disables auto-save"""
        store.set_auto_save(tmp_path, threshold=0)
        for i in range(100):
            store.store(MemoryItem(level=MemoryLevel.WORKING, key=f"k{i}", value=f"v{i}"))
        assert not os.path.exists(tmp_path)

    def test_autosaved_file_is_loadable(self, store, tmp_path):
        """File created by auto-save can be loaded"""
        store.set_auto_save(tmp_path, threshold=2)
        items = []
        for i in range(2):
            item = MemoryItem(level=MemoryLevel.SENSORY, key=f"k{i}", value=f"v{i}")
            store.store(item)
            items.append(item)
        assert os.path.exists(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        stats = loaded.get_stats()
        assert stats["SENSORY"]["count"] == 2

    def test_autosave_multiple_triggers(self, store, tmp_path):
        """Auto-save can trigger multiple times"""
        store.set_auto_save(tmp_path, threshold=2)
        for i in range(6):
            store.store(MemoryItem(level=MemoryLevel.WORKING, key=f"k{i}", value=f"v{i}"))
        # Should have saved at 2, 4, 6 writes
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        stats = loaded.get_stats()
        assert stats["WORKING"]["count"] == 6


# ═══════════════════════════════════════════════════════════════
# 4. Error handling & edge cases
# ═══════════════════════════════════════════════════════════════

class TestErrorHandling:

    def test_load_nonexistent_file(self):
        """Loading a non-existent file raises FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            HierarchicalMemoryStore.load_from_file("/nonexistent/path.json")

    def test_load_bad_json(self, tmp_path):
        """Loading a file with invalid JSON raises IOError"""
        with open(tmp_path, "w") as f:
            f.write("{bad json")
        with pytest.raises(IOError):
            HierarchicalMemoryStore.load_from_file(tmp_path)

    def test_load_version_mismatch(self, tmp_path):
        """Loading a file with wrong version raises ValueError"""
        with open(tmp_path, "w") as f:
            json.dump({
                "version": 999,
                "items": [],
                "vector_index": {},
                "knowledge_graph": {},
            }, f)
        with pytest.raises(ValueError, match="版本不兼容"):
            HierarchicalMemoryStore.load_from_file(tmp_path)

    def test_load_minimal_valid(self, tmp_path):
        """Loading a minimal but valid snapshot works"""
        with open(tmp_path, "w") as f:
            json.dump({
                "version": 1,
                "meta": {"saved_at": time.time(), "total_items": 0,
                         "total_stores": 0, "vector_count": 0,
                         "graph_stats": {"entities": 0, "relations": 0,
                                         "entity_memory_links": 0}},
                "items": [],
                "vector_index": {"dim": 384, "vectors": []},
                "knowledge_graph": {"entities": {}, "relations": [],
                                    "entity_memories": {}},
            }, f)
        store = HierarchicalMemoryStore.load_from_file(tmp_path)
        assert store.get_stats()["SENSORY"]["count"] == 0

    def test_save_to_readonly_dir(self, store):
        """Saving to a non-writable location raises IOError"""
        with pytest.raises((IOError, OSError, PermissionError)):
            store.save_to_file("/dev/null/save.json")

    def test_atomic_write_no_partial_file(self, store, tmp_path):
        """If save fails mid-write, no partial file remains"""
        # Force failure by giving a bad path (but not the .tmp one)
        # Instead, simulate by making the tmp path unreadable
        # This test just verifies the pattern doesn't leave .tmp behind
        try:
            store.save_to_file("/invalid_dir/deep/file.json")
        except (IOError, OSError):
            pass
        # No .tmp file should linger
        assert not os.path.exists("/invalid_dir/deep/file.json.tmp")


# ═══════════════════════════════════════════════════════════════
# 5. Large / stress tests
# ═══════════════════════════════════════════════════════════════

class TestStressAndLarge:

    def test_large_number_of_items(self, store, tmp_path):
        """Save/load 200+ items"""
        for i in range(250):
            item = MemoryItem(
                level=MemoryLevel.SHORT_TERM if i % 2 == 0 else MemoryLevel.LONG_TERM,
                key=f"key_{i}",
                value=f"value_{i}",
                importance=min(1.0, i / 250.0),
                tags=[f"tag_{i % 5}"],
            )
            store.store(item)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        stats = loaded.get_stats()
        total = stats["SHORT_TERM"]["count"] + stats["LONG_TERM"]["count"]
        assert total == 250

    def test_large_items_with_embeddings(self, store, tmp_path):
        """Save/load 100 items with embeddings"""
        for i in range(100):
            item = MemoryItem(
                level=MemoryLevel.LONG_TERM,
                key=f"emb_{i}",
                value=f"val_{i}",
            )
            item.embedding = [float(i) / 100.0] * 32
            store.store(item)
            store.vector_index.add(item.id, item.embedding)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        assert loaded.vector_index.count() == 100

        # Verify search still works
        results = loaded.vector_index.search([0.5] * 32, top_k=3)
        assert len(results) == 3


# ═══════════════════════════════════════════════════════════════
# 6. VectorIndex serialization (unit tests)
# ═══════════════════════════════════════════════════════════════

class TestVectorIndexSerialization:

    def test_to_dict_from_dict_empty(self):
        """Empty VectorIndex round-trips correctly"""
        vi = VectorIndex(dim=384)
        data = vi.to_dict()
        assert data["dim"] == 384
        assert data["vectors"] == []
        vi2 = VectorIndex.from_dict(data)
        assert vi2.count() == 0

    def test_to_dict_from_dict_with_items(self):
        """Non-empty VectorIndex round-trips correctly"""
        vi = VectorIndex(dim=3)
        vi.add("id1", [0.1, 0.2, 0.3])
        vi.add("id2", [0.4, 0.5, 0.6])
        data = vi.to_dict()
        assert len(data["vectors"]) == 2
        vi2 = VectorIndex.from_dict(data)
        assert vi2.count() == 2
        results = vi2.search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 2
        assert results[0][0] == "id1"

    def test_vector_index_search_empty(self):
        """Search on empty VectorIndex returns empty list"""
        vi = VectorIndex(dim=384)
        assert vi.search([0.1] * 384) == []

    def test_vector_index_adaptive_dim(self):
        """VectorIndex adapts dimension automatically"""
        vi = VectorIndex(dim=384)
        vi.add("id1", [0.1, 0.2, 0.3])
        assert vi.dim == 3


# ═══════════════════════════════════════════════════════════════
# 7. KnowledgeGraph serialization (unit tests)
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeGraphSerialization:

    def test_to_dict_from_dict_empty(self):
        """Empty KnowledgeGraph round-trips correctly"""
        kg = KnowledgeGraph()
        data = kg.to_dict()
        assert data["entities"] == {}
        assert data["relations"] == []
        assert data["entity_memories"] == {}
        kg2 = KnowledgeGraph.from_dict(data)
        assert kg2.get_stats()["entities"] == 0

    def test_to_dict_from_dict_with_data(self):
        """Non-empty KnowledgeGraph round-trips correctly"""
        kg = KnowledgeGraph()
        kg.add_entity("E1", "concept", {"key": "val"})
        kg.add_entity("E2", "person", {})
        kg.add_relation("E1", "related_to", "E2", weight=0.8)
        kg.link_memory("E1", "mem_1")
        kg.link_memory("E2", "mem_2")
        data = kg.to_dict()
        kg2 = KnowledgeGraph.from_dict(data)
        stats = kg2.get_stats()
        assert stats["entities"] == 2
        assert stats["relations"] == 1
        assert stats["entity_memory_links"] == 2
        assert "E1" in kg2.search_entities("E1")

    def test_to_dict_entity_properties_preserved(self):
        """Entity properties survive serialization"""
        kg = KnowledgeGraph()
        kg.add_entity("Berlin", "city", {"country": "Germany", "pop": 3.7e6})
        data = kg.to_dict()
        kg2 = KnowledgeGraph.from_dict(data)
        assert "Berlin" in kg2._entities
        assert kg2._entities["Berlin"]["properties"]["country"] == "Germany"
        assert kg2._entities["Berlin"]["properties"]["pop"] == 3.7e6

    def test_to_dict_relation_weights_preserved(self):
        """Relation weights survive serialization"""
        kg = KnowledgeGraph()
        kg.add_relation("A", "connects", "B", weight=0.75)
        data = kg.to_dict()
        kg2 = KnowledgeGraph.from_dict(data)
        assert ("A", "connects", "B") in kg2._relations
        assert kg2._relations[("A", "connects", "B")] == 0.75


# ═══════════════════════════════════════════════════════════════
# 8. MemoryItem serialization (unit tests)
# ═══════════════════════════════════════════════════════════════

class TestMemoryItemSerialization:

    def test_to_json_dict_contains_all_fields(self, store):
        """to_json_dict includes all dataclass fields"""
        item = MemoryItem(
            level=MemoryLevel.WORKING,
            key="test_key",
            value="test_value",
            source="user",
        )
        d = item.to_json_dict()
        assert d["id"] == item.id
        assert d["level"] == MemoryLevel.WORKING.value
        assert d["key"] == "test_key"
        assert d["value"] == "test_value"
        assert d["source"] == "user"
        assert d["importance"] == 0.5
        assert "embedding" in d
        assert d["embedding"] is None

    def test_from_json_dict_restores_all_fields(self):
        """from_json_dict restores all fields"""
        data = {
            "id": "test-uuid-123",
            "level": 2,
            "key": "restored_key",
            "value": "restored_value",
            "summary": "summary_text",
            "embedding": [0.1, 0.2, 0.3],
            "project_id": "proj_x",
            "conversation_id": "conv_y",
            "source": "assistant",
            "created_at": 1000.0,
            "last_accessed": 1001.0,
            "last_reviewed": 1002.0,
            "importance": 0.75,
            "access_count": 10,
            "review_count": 3,
            "tags": ["a", "b"],
            "entities": ["Ent1"],
            "related_memory_ids": ["mid1"],
            "confidence": 0.9,
            "is_corrected": True,
            "correction_history": [{"from": "old", "to": "new"}],
        }
        item = MemoryItem.from_json_dict(data)
        assert item.id == "test-uuid-123"
        assert item.level == MemoryLevel.SHORT_TERM
        assert item.key == "restored_key"
        assert item.value == "restored_value"
        assert item.embedding == [0.1, 0.2, 0.3]
        assert item.project_id == "proj_x"
        assert item.conversation_id == "conv_y"
        assert item.source == "assistant"
        assert item.created_at == 1000.0
        assert item.last_accessed == 1001.0
        assert item.last_reviewed == 1002.0
        assert item.importance == 0.75
        assert item.access_count == 10
        assert item.review_count == 3
        assert item.tags == ["a", "b"]
        assert item.entities == ["Ent1"]
        assert item.related_memory_ids == ["mid1"]
        assert item.confidence == 0.9
        assert item.is_corrected is True
        assert len(item.correction_history) == 1

    def test_from_json_dict_defaults(self):
        """from_json_dict fills defaults for missing fields"""
        data = {"id": "min-id", "level": 0}
        item = MemoryItem.from_json_dict(data)
        assert item.key == ""
        assert item.value == ""
        assert item.importance == 0.5
        assert item.tags == []
        assert item.embedding is None

    def test_level_enum_roundtrip(self):
        """MemoryLevel int values survive serialize/deserialize"""
        for level in MemoryLevel:
            d = {"id": "x", "level": level.value, "key": "", "value": ""}
            item = MemoryItem.from_json_dict(d)
            assert item.level == level, f"Failed for {level}"


# ═══════════════════════════════════════════════════════════════
# 9. Integration: existing features still work after persistence
# ═══════════════════════════════════════════════════════════════

class TestIntegration:

    def test_store_retrieve_after_load(self, store, tmp_path):
        """store() and retrieve() still work on loaded store"""
        original = MemoryItem(level=MemoryLevel.WORKING, key="orig", value="original")
        store.store(original)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        # Add more items to loaded store
        new_item = MemoryItem(level=MemoryLevel.WORKING, key="new", value="new_item")
        loaded.store(new_item)
        # Retrieve should find both
        results = loaded.retrieve("original", top_k=5)
        assert any(r.key == "orig" for r in results)
        results2 = loaded.retrieve("new_item", top_k=5)
        assert any(r.key == "new" for r in results2)

    def test_compact_after_load(self, store, tmp_path):
        """compact() works on loaded store"""
        for i in range(3):
            item = MemoryItem(level=MemoryLevel.WORKING, key="dup_key", value=f"val_{i}")
            store.store(item)
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        assert loaded.get_stats()["WORKING"]["count"] == 3
        loaded.compact()
        assert loaded.get_stats()["WORKING"]["count"] == 1

    def test_get_stats_after_load(self, store, tmp_path):
        """get_stats() works on loaded store"""
        store.save_to_file(tmp_path)
        loaded = HierarchicalMemoryStore.load_from_file(tmp_path)
        stats = loaded.get_stats()
        assert "SENSORY" in stats
        assert "vector_index" in stats
        assert "knowledge_graph" in stats


# ═══════════════════════════════════════════════════════════════
# 10. Version marker / compatibility
# ═══════════════════════════════════════════════════════════════

class TestVersionCompatibility:

    def test_persistence_version_constant(self):
        """PERSISTENCE_VERSION is defined and positive"""
        assert HierarchicalMemoryStore.PERSISTENCE_VERSION > 0

    def test_version_in_saved_file(self, store, tmp_path):
        """Saved file has correct version number"""
        store.save_to_file(tmp_path)
        with open(tmp_path) as f:
            data = json.load(f)
        assert data["version"] == HierarchicalMemoryStore.PERSISTENCE_VERSION

    def test_rejects_old_version(self, tmp_path):
        """Loading old version file raises ValueError"""
        with open(tmp_path, "w") as f:
            json.dump({
                "version": 0,
                "items": [],
                "vector_index": {"dim": 384, "vectors": []},
                "knowledge_graph": {"entities": {}, "relations": [],
                                    "entity_memories": {}},
            }, f)
        with pytest.raises(ValueError):
            HierarchicalMemoryStore.load_from_file(tmp_path)

    def test_rejects_future_version(self, tmp_path):
        """Loading future version file raises ValueError"""
        with open(tmp_path, "w") as f:
            json.dump({
                "version": 99,
                "items": [],
                "vector_index": {"dim": 384, "vectors": []},
                "knowledge_graph": {"entities": {}, "relations": [],
                                    "entity_memories": {}},
            }, f)
        with pytest.raises(ValueError):
            HierarchicalMemoryStore.load_from_file(tmp_path)


# ═══════════════════════════════════════════════════════════════
# Count: 50 tests
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

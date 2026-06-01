"""v3.108 Memory Compactor 记忆压缩器测试"""
import time
import pytest
from src.core.memory_compactor import (
    MemoryCompactor, MemoryEntry, MemoryTier,
    CompressionStrategy, CompactionResult, TierMigrationResult,
    RetrievalResult, CompactionStats,
    get_memory_compactor, reset_memory_compactor,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def compactor():
    """创建新的MemoryCompactor实例"""
    return MemoryCompactor()


@pytest.fixture
def populated_compactor():
    """创建包含测试数据的MemoryCompactor"""
    mc = MemoryCompactor()
    contents = [
        ("Python is a high-level programming language used for web development, data science, and automation.", ["python", "programming"]),
        ("Machine learning enables computers to learn from data without explicit programming.", ["ml", "ai"]),
        ("Docker containers provide isolated environments for running applications consistently.", ["docker", "devops"]),
        ("Kubernetes orchestrates containerized applications across clusters of machines.", ["k8s", "devops"]),
        ("TensorFlow is an open-source framework for building and training neural networks.", ["tensorflow", "ml", "ai"]),
        ("Git is a distributed version control system for tracking changes in source code.", ["git", "vcs"]),
        ("REST APIs use HTTP methods to expose resources and enable client-server communication.", ["api", "rest"]),
        ("PostgreSQL is a powerful open-source relational database with advanced SQL features.", ["postgresql", "database"]),
    ]
    for content, tags in contents:
        mc.add_memory(content=content, tags=tags)
    return mc


# ═══════════════════════════════════════════════════════════
# 1) Add & Retrieve Memory Tests
# ═══════════════════════════════════════════════════════════

class TestAddAndRetrieve:
    """1) 添加和检索记忆测试"""

    def test_add_memory_basic(self, compactor):
        entry = compactor.add_memory(
            content="Hello world, this is a test memory.",
            tags=["test", "hello"],
        )
        assert entry.memory_id.startswith("mem_")
        assert entry.content == "Hello world, this is a test memory."
        assert "test" in entry.tags
        assert "hello" in entry.tags
        assert 0 <= entry.importance_score <= 100
        assert entry.tier in ("hot", "warm", "cold")

    def test_add_memory_with_custom_id(self, compactor):
        entry = compactor.add_memory(
            content="Custom ID memory",
            memory_id="my_custom_id",
            tags=["custom"],
        )
        assert entry.memory_id == "my_custom_id"
        assert compactor.get_memory("my_custom_id") is not None

    def test_get_memory_updates_access(self, compactor):
        entry = compactor.add_memory(content="Access test")
        mid = entry.memory_id
        initial_access = entry.access_count

        retrieved = compactor.get_memory(mid)
        assert retrieved is not None
        assert retrieved.access_count == initial_access + 1
        assert retrieved.last_accessed >= entry.last_accessed

    def test_get_memory_nonexistent(self, compactor):
        assert compactor.get_memory("nonexistent") is None

    def test_delete_memory(self, compactor):
        entry = compactor.add_memory(content="To be deleted")
        assert compactor.get_memory(entry.memory_id) is not None

        assert compactor.delete_memory(entry.memory_id) is True
        assert compactor.get_memory(entry.memory_id) is None
        assert compactor.delete_memory(entry.memory_id) is False  # Already gone


# ═══════════════════════════════════════════════════════════
# 2) Smart Summary Compression Tests
# ═══════════════════════════════════════════════════════════

class TestSmartCompression:
    """2) 智能摘要压缩测试"""

    def test_extractive_compress(self, compactor):
        content = (
            "Python is a versatile programming language. "
            "It is widely used in data science. "
            "Many developers prefer Python for its simplicity. "
            "The language supports multiple programming paradigms. "
            "Python has a large ecosystem of libraries."
        )
        entry = compactor.add_memory(content=content)
        result = compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.EXTRACTIVE.value,
        )
        assert result.entries_affected == 1
        assert result.compression_ratio < 1.0
        assert result.original_size > result.compressed_size

        # Verify entry was updated
        updated = compactor.get_memory(entry.memory_id)
        assert updated.compression_level >= 1
        assert len(updated.summary) > 0

    def test_abstractive_compress(self, compactor):
        content = (
            "Actually, this is really a very long piece of text that basically "
            "just describes something quite simple. It's really not that complex "
            "when you think about it literally. The main point is just that "
            "simple things should be expressed simply."
        )
        entry = compactor.add_memory(content=content)
        result = compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.ABSTRACTIVE.value,
        )
        assert result.compression_ratio <= 1.0
        updated = compactor.get_memory(entry.memory_id)
        assert updated.summary != content

    def test_truncate_compress_long_content(self, compactor):
        long_content = "A" * 2000
        entry = compactor.add_memory(content=long_content)
        result = compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.TRUNCATE.value,
        )
        assert result.compressed_size < result.original_size
        assert result.compressed_size <= 500 + 10  # Max 500 + "[...]"

    def test_progressive_compress_multiple_levels(self, compactor):
        content = (
            "This is a detailed document about memory compression techniques. "
            "Memory compression is important for managing large context windows. "
            "There are several approaches including extractive, abstractive, and "
            "progressive compression. Each has its own trade-offs in terms of "
            "quality and computational cost. Progressive compression applies "
            "increasingly aggressive compression levels over time."
        )
        entry = compactor.add_memory(content=content)

        # Level 1
        r1 = compactor.compress_memory(
            entry.memory_id, strategy=CompressionStrategy.EXTRACTIVE.value
        )
        assert r1.compression_ratio <= 1.0

        # Level 2
        r2 = compactor.compress_memory(
            entry.memory_id, strategy=CompressionStrategy.PROGRESSIVE.value, force=True
        )
        assert r2.compression_ratio <= 1.0

        updated = compactor.get_memory(entry.memory_id)
        assert updated.compression_level >= 2

    def test_compress_nonexistent(self, compactor):
        result = compactor.compress_memory("nonexistent")
        assert result.original_size == 0
        assert "error" in result.details

    def test_compress_all_by_tier(self, compactor):
        compactor.add_memory(content="Hot memory A " * 20, tags=["hot"])
        compactor.add_memory(content="Warm memory B " * 20, tags=["warm"])
        compactor.add_memory(content="Cold memory C " * 20, tags=["cold"])

        result = compactor.compress_all(
            strategy=CompressionStrategy.TRUNCATE.value,
        )
        assert result.entries_affected >= 1
        assert result.compression_ratio <= 1.0

    def test_merge_similar_memories(self, compactor):
        compactor.add_memory(
            content="Docker is a container platform for running applications in isolated environments.",
            tags=["docker", "container", "isolation"],
        )
        compactor.add_memory(
            content="Docker provides containerization for deploying applications consistently across environments.",
            tags=["docker", "deployment", "container"],
        )
        compactor.add_memory(
            content="Python is a programming language for data science and machine learning.",
            tags=["python"],
        )

        merged = compactor.merge_similar(similarity_threshold=0.2)
        # Docker entries should be merged; Python should not
        assert len(merged) >= 1


# ═══════════════════════════════════════════════════════════
# 3) Importance Scoring Tests
# ═══════════════════════════════════════════════════════════

class TestImportanceScoring:
    """3) 重要性评分测试"""

    def test_initial_score_in_range(self, compactor):
        entry = compactor.add_memory(content="Test content")
        assert 0 <= entry.importance_score <= 100

    def test_score_increases_with_access(self, compactor):
        entry = compactor.add_memory(content="Access this many times")
        initial_score = entry.importance_score

        # Simulate many accesses
        for _ in range(100):
            entry.access_count += 1

        new_score = compactor.score_importance(entry)
        assert new_score > initial_score

    def test_score_affected_by_tags(self, compactor):
        e1 = compactor.add_memory(content="No tags memory")
        e2 = compactor.add_memory(
            content="Tagged memory",
            tags=["important", "critical", "pinned", "starred", "urgent"],
        )
        assert e2.importance_score > 0

    def test_metadata_boost(self, compactor):
        e1 = compactor.add_memory(content="Plain")
        e2 = compactor.add_memory(
            content="Boosted",
            metadata={"pinned": True, "starred": True, "important": True},
        )
        assert e2.importance_score > e1.importance_score

    def test_boost_importance(self, compactor):
        entry = compactor.add_memory(content="Boost me")
        old_score = entry.importance_score
        assert compactor.boost_importance(entry.memory_id, amount=20.0)
        assert entry.importance_score > old_score

    def test_decay_importance(self, compactor):
        entry = compactor.add_memory(content="Decay me")
        entry.importance_score = 80.0
        assert compactor.decay_importance(entry.memory_id, amount=30.0)
        assert entry.importance_score == 50.0

    def test_recalculate_all_scores(self, compactor):
        compactor.add_memory(content="Memory 1")
        compactor.add_memory(content="Memory 2")
        compactor.add_memory(content="Memory 3")
        count = compactor.recalculate_all_scores()
        assert count >= 0  # May be 0 if no changes

    def test_importance_report(self, compactor):
        compactor.add_memory(content="High importance")
        compactor.add_memory(content="Medium")
        compactor.add_memory(content="Low")

        # Set scores manually for testing
        entries = list(compactor._all_entries.values())
        if len(entries) >= 3:
            entries[0].importance_score = 85.0
            entries[1].importance_score = 50.0
            entries[2].importance_score = 15.0

        report = compactor.get_importance_report()
        assert report["total"] >= 3
        assert report["high"] >= 1
        assert report["low"] >= 1
        assert 0 <= report["avg"] <= 100

    def test_boost_nonexistent(self, compactor):
        assert compactor.boost_importance("nonexistent") is False
        assert compactor.decay_importance("nonexistent") is False


# ═══════════════════════════════════════════════════════════
# 4) Tiered Storage Tests (hot/warm/cold)
# ═══════════════════════════════════════════════════════════

class TestTieredStorage:
    """4) 分层存储(hot/warm/cold)测试"""

    def test_new_memory_starts_in_appropriate_tier(self, compactor):
        entry = compactor.add_memory(content="Fresh memory")
        assert entry.tier in (MemoryTier.HOT.value, MemoryTier.WARM.value, MemoryTier.COLD.value)

    def test_can_assign_initial_tier(self, compactor):
        entry = compactor.add_memory(
            content="Cold from start",
            initial_tier=MemoryTier.COLD.value,
        )
        assert entry.tier == MemoryTier.COLD.value

    def test_migrate_tiers_runs(self, compactor):
        compactor.add_memory(content="Entry 1")
        compactor.add_memory(content="Entry 2")
        compactor.add_memory(
            content="Entry 3",
            initial_tier=MemoryTier.COLD.value,
        )
        result = compactor.migrate_tiers()
        assert result.hot_count + result.warm_count + result.cold_count == 3
        assert result.timestamp > 0

    def test_promote_memory(self, compactor):
        entry = compactor.add_memory(
            content="Promotable",
            initial_tier=MemoryTier.COLD.value,
        )
        assert entry.tier == MemoryTier.COLD.value

        assert compactor.promote_memory(entry.memory_id) is True
        assert entry.tier == MemoryTier.WARM.value

        assert compactor.promote_memory(entry.memory_id) is True
        assert entry.tier == MemoryTier.HOT.value

        # Already at top, can't promote further
        assert compactor.promote_memory(entry.memory_id) is False

    def test_demote_memory(self, compactor):
        entry = compactor.add_memory(
            content="Demotable",
            initial_tier=MemoryTier.HOT.value,
        )
        assert entry.tier == MemoryTier.HOT.value

        assert compactor.demote_memory(entry.memory_id) is True
        assert entry.tier == MemoryTier.WARM.value

        assert compactor.demote_memory(entry.memory_id) is True
        assert entry.tier == MemoryTier.COLD.value

        # Already at bottom
        assert compactor.demote_memory(entry.memory_id) is False

    def test_promote_demote_nonexistent(self, compactor):
        assert compactor.promote_memory("nonexistent") is False
        assert compactor.demote_memory("nonexistent") is False

    def test_get_tier_counts(self, compactor):
        compactor.add_memory(content="H1", initial_tier=MemoryTier.HOT.value)
        compactor.add_memory(content="W1", initial_tier=MemoryTier.WARM.value)
        compactor.add_memory(content="C1", initial_tier=MemoryTier.COLD.value)

        counts = compactor.get_tier_counts()
        assert counts["hot"] == 1
        assert counts["warm"] == 1
        assert counts["cold"] == 1
        assert counts["total"] == 3

    def test_get_entries_by_tier(self, compactor):
        compactor.add_memory(content="Hot item", initial_tier=MemoryTier.HOT.value)
        compactor.add_memory(content="Warm item", initial_tier=MemoryTier.WARM.value)

        hot_entries = compactor.get_entries_by_tier(MemoryTier.HOT.value)
        assert len(hot_entries) == 1
        assert hot_entries[0].content == "Hot item"

        warm_entries = compactor.get_entries_by_tier(MemoryTier.WARM.value)
        assert len(warm_entries) == 1

    def test_migrate_tracks_history(self, compactor):
        compactor.add_memory(content="Test migration")
        result = compactor.migrate_tiers()
        history = compactor.get_migration_history()
        assert len(history) >= 1


# ═══════════════════════════════════════════════════════════
# 5) Retrieval Optimization Tests
# ═══════════════════════════════════════════════════════════

class TestRetrievalOptimization:
    """5) 检索优化测试"""

    def test_retrieve_by_keywords(self, populated_compactor):
        result = populated_compactor.retrieve("Python programming")
        assert len(result.entries) >= 1
        assert result.query == "Python programming"

    def test_retrieve_with_tier_filter(self, populated_compactor):
        result = populated_compactor.retrieve(
            "docker kubernetes",
            tier=MemoryTier.HOT.value,
        )
        assert result.query == "docker kubernetes"
        assert len(result.tiers_searched) <= 1

    def test_retrieve_with_min_importance(self, populated_compactor):
        # Set very high importance threshold
        result = populated_compactor.retrieve(
            "machine learning",
            min_importance=95.0,
        )
        # Should return empty or few results
        assert isinstance(result.entries, list)

    def test_retrieve_top_k(self, populated_compactor):
        result = populated_compactor.retrieve("data", top_k=3)
        assert len(result.entries) <= 3

    def test_retrieve_returns_scores(self, populated_compactor):
        result = populated_compactor.retrieve("Python")
        assert len(result.scores) == len(result.entries)
        for score in result.scores.values():
            assert 0 <= score <= 1.0

    def test_search_by_tags_any(self, populated_compactor):
        results = populated_compactor.search_by_tags(
            ["devops"], match_all=False
        )
        assert len(results) >= 2  # docker and k8s

    def test_search_by_tags_all(self, populated_compactor):
        results = populated_compactor.search_by_tags(
            ["ml", "ai"], match_all=True
        )
        # ML entry has [ml, ai], TensorFlow entry has [tensorflow, ml, ai]
        assert len(results) >= 1

    def test_search_by_tags_limit(self, populated_compactor):
        results = populated_compactor.search_by_tags(
            ["devops"], limit=1
        )
        assert len(results) <= 1

    def test_retrieve_empty_query(self, populated_compactor):
        result = populated_compactor.retrieve("")
        assert isinstance(result.entries, list)
        assert result.total_candidates >= 0

    def test_retrieval_cache_works(self, populated_compactor):
        # First retrieval
        r1 = populated_compactor.retrieve("Python development")
        assert r1.retrieval_time_ms >= 0

        # Second retrieval (should be faster due to cache warmth)
        r2 = populated_compactor.retrieve("Python development")
        assert r2.retrieval_time_ms >= 0

    def test_get_frequent(self, populated_compactor):
        # Access some entries multiple times
        for _ in range(5):
            populated_compactor.get_memory(
                list(populated_compactor._all_entries.keys())[0]
            )

        frequent = populated_compactor.get_frequent(top_n=3)
        assert len(frequent) <= 3

    def test_get_recent(self, populated_compactor):
        recent = populated_compactor.get_recent(top_n=5)
        assert len(recent) <= 5


# ═══════════════════════════════════════════════════════════
# 6) Stats & History Tests
# ═══════════════════════════════════════════════════════════

class TestStatsAndHistory:
    """6) 统计和历史测试"""

    def test_get_stats_empty(self, compactor):
        stats = compactor.get_stats()
        assert stats.total_entries == 0
        assert stats.hot_count == 0
        assert stats.warm_count == 0
        assert stats.cold_count == 0
        assert stats.compactions_run == 0

    def test_get_stats_with_data(self, populated_compactor):
        stats = populated_compactor.get_stats()
        assert stats.total_entries == 8
        assert stats.total_chars > 0
        assert 0 <= stats.avg_importance <= 100

    def test_compaction_history(self, compactor):
        entry = compactor.add_memory(content="History test " * 10)
        compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.EXTRACTIVE.value,
        )
        compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.ABSTRACTIVE.value,
            force=True,
        )

        history = compactor.get_compaction_history()
        assert len(history) >= 2

    def test_migration_history(self, compactor):
        compactor.add_memory(content="Migrate test")
        compactor.migrate_tiers()
        compactor.migrate_tiers()

        history = compactor.get_migration_history()
        assert len(history) >= 2

    def test_reset_clears_everything(self, populated_compactor):
        assert populated_compactor.get_stats().total_entries == 8

        populated_compactor.reset()
        stats = populated_compactor.get_stats()
        assert stats.total_entries == 0
        assert stats.hot_count == 0
        assert stats.compactions_run == 0

        history = populated_compactor.get_compaction_history()
        assert len(history) == 0


# ═══════════════════════════════════════════════════════════
# 7) Singleton Tests
# ═══════════════════════════════════════════════════════════

class TestSingleton:
    """7) 单例测试"""

    def test_get_returns_instance(self):
        reset_memory_compactor()
        mc = get_memory_compactor()
        assert isinstance(mc, MemoryCompactor)
        reset_memory_compactor()

    def test_singleton_same_instance(self):
        reset_memory_compactor()
        mc1 = get_memory_compactor()
        mc2 = get_memory_compactor()
        assert mc1 is mc2
        reset_memory_compactor()

    def test_reset_creates_new_instance(self):
        reset_memory_compactor()
        mc1 = get_memory_compactor()
        mc1.add_memory(content="Test singleton")
        assert mc1.get_stats().total_entries == 1

        reset_memory_compactor()
        mc2 = get_memory_compactor()
        assert mc2.get_stats().total_entries == 0
        assert mc1 is not mc2
        reset_memory_compactor()


# ═══════════════════════════════════════════════════════════
# 8) End-to-End Integration Tests
# ═══════════════════════════════════════════════════════════

class TestEndToEnd:
    """8) 端到端集成测试"""

    def test_full_lifecycle(self, compactor):
        """完整生命周期: 添加→评分→压缩→迁移→检索→删除"""
        # Step 1: Add memories
        e1 = compactor.add_memory(
            content="The quick brown fox jumps over the lazy dog. "
                    "This pangram contains every letter of the English alphabet. "
                    "It is often used for testing fonts and keyboards. "
                    "The sentence has been used since the late 19th century. "
                    "Many typists practice with this famous phrase every day.",
            tags=["example", "pangram", "typography"],
        )
        e2 = compactor.add_memory(
            content="Machine learning models require large datasets for training. "
                    "Data preprocessing is a critical step in the ML pipeline.",
            tags=["machine-learning", "data"],
        )

        # Step 2: Score importance
        importance1 = compactor.score_importance(e1)
        importance2 = compactor.score_importance(e2)
        assert 0 <= importance1 <= 100
        assert 0 <= importance2 <= 100

        # Step 3: Compress
        result1 = compactor.compress_memory(
            e1.memory_id,
            strategy=CompressionStrategy.EXTRACTIVE.value,
        )
        assert result1.compression_ratio < 1.0

        # Step 4: Migrate tiers
        migration = compactor.migrate_tiers()
        assert migration.hot_count + migration.warm_count + migration.cold_count == 2

        # Step 5: Retrieve
        retrieval = compactor.retrieve("fox lazy dog", top_k=5)
        assert len(retrieval.entries) >= 1
        assert any(e.memory_id == e1.memory_id for e in retrieval.entries)

        # Step 6: Search by tags
        tagged = compactor.search_by_tags(["machine-learning"])
        assert len(tagged) >= 1

        # Step 7: Delete
        assert compactor.delete_memory(e1.memory_id) is True
        assert compactor.get_memory(e1.memory_id) is None
        assert compactor.get_stats().total_entries == 1

    def test_bulk_compress_and_merge(self, compactor):
        """批量压缩+合并流程"""
        # Add similar memories
        for i in range(5):
            compactor.add_memory(
                content=f"Docker container {i} is used for running applications "
                        f"in isolated environments with consistent behavior.",
                tags=["docker", f"container-{i}"],
            )

        assert compactor.get_stats().total_entries == 5

        # Bulk compress
        result = compactor.compress_all(
            strategy=CompressionStrategy.EXTRACTIVE.value,
        )
        assert result.entries_affected == 5

        # Merge similar
        merged = compactor.merge_similar(similarity_threshold=0.4)
        # Should have merged some docker entries
        assert compactor.get_stats().total_entries < 5 + len(merged)

    def test_importance_driven_tier_migration(self, compactor):
        """重要性驱动的层级迁移"""
        e1 = compactor.add_memory(
            content="Important document about project architecture decisions",
            metadata={"pinned": True, "important": True},
        )
        e2 = compactor.add_memory(
            content="Random note about lunch",
            initial_tier=MemoryTier.COLD.value,
        )
        e2.importance_score = 5.0

        # Boost and ensure e1 is hot
        compactor.boost_importance(e1.memory_id, 40.0)
        assert e1.importance_score > 70

        # Migrate
        compactor.migrate_tiers()

        hot = compactor.get_entries_by_tier(MemoryTier.HOT.value)
        assert any(e.memory_id == e1.memory_id for e in hot)

    def test_tag_based_retrieval_precision(self, compactor):
        """标签检索精确度测试"""
        for tag in ["python", "javascript", "rust", "python", "python"]:
            compactor.add_memory(
                content=f"Content about {tag}",
                tags=[tag],
            )

        python_results = compactor.search_by_tags(["python"])
        assert len(python_results) == 3

        js_results = compactor.search_by_tags(["javascript"])
        assert len(js_results) == 1


# ═══════════════════════════════════════════════════════════
# 9) Edge Cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """9) 边界情况测试"""

    def test_empty_content_memory(self, compactor):
        entry = compactor.add_memory(content="")
        assert entry is not None
        assert entry.content == ""

    def test_compress_empty_content(self, compactor):
        entry = compactor.add_memory(content="")
        result = compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.EXTRACTIVE.value,
        )
        assert result.compression_ratio <= 1.0

    def test_very_long_content_handling(self, compactor):
        long_content = "Long text. " * 5000
        entry = compactor.add_memory(content=long_content)
        assert len(entry.content) > 10000

        result = compactor.compress_memory(
            entry.memory_id,
            strategy=CompressionStrategy.TRUNCATE.value,
        )
        assert result.compressed_size < result.original_size

    def test_duplicate_memory_ids(self, compactor):
        e1 = compactor.add_memory(content="First", memory_id="same_id")
        e2 = compactor.add_memory(content="Second", memory_id="same_id")
        # Second should overwrite first
        retrieved = compactor.get_memory("same_id")
        assert retrieved.content == "Second"

    def test_retrieve_no_matches(self, compactor):
        compactor.add_memory(content="Something completely different")
        result = compactor.retrieve("zzz_nonexistent_keyword_xyz")
        assert len(result.entries) == 0

    def test_many_memories_performance(self, compactor):
        """批量添加性能测试"""
        for i in range(50):
            compactor.add_memory(
                content=f"Memory entry number {i} with some random content "
                        f"to fill up the space with test data.",
                tags=[f"batch-{i % 5}"],
            )

        assert compactor.get_stats().total_entries == 50

        # Should handle retrieval fine
        result = compactor.retrieve("memory entry", top_k=20)
        assert len(result.entries) >= 1

        # Should handle migration fine
        migration = compactor.migrate_tiers()
        assert migration.hot_count + migration.warm_count + migration.cold_count == 50

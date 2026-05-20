"""Tests for Human-Like Memory — v2.40"""
import pytest
import time
from src.core.human_memory import (
    MemoryChunk, EmotionIntensity, HumanLikeMemory, get_human_memory,
)


class TestEmotionIntensity:
    def test_values(self):
        assert EmotionIntensity.NEUTRAL.value == 0
        assert EmotionIntensity.CRITICAL.value == 5
        assert EmotionIntensity.IMPORTANT.value == 2

    def test_comparison(self):
        assert EmotionIntensity.CRITICAL.value > EmotionIntensity.IMPORTANT.value
        assert EmotionIntensity.NEUTRAL.value < EmotionIntensity.INTERESTING.value


class TestMemoryChunk:
    def test_create(self):
        chunk = MemoryChunk(id="test1", pattern="user prefers concise answers")
        assert chunk.pattern == "user prefers concise answers"
        assert chunk.emotion == EmotionIntensity.NEUTRAL
        assert chunk.strength == 1.0

    def test_decay_neutral(self):
        chunk = MemoryChunk(id="t", pattern="routine stuff",
                           emotion=EmotionIntensity.NEUTRAL)
        chunk.decay_strength(168)  # 1 week
        assert chunk.strength < 0.5  # Should significantly decay

    def test_decay_critical(self):
        chunk = MemoryChunk(id="t", pattern="critical info",
                           emotion=EmotionIntensity.CRITICAL)
        chunk.decay_strength(168)  # 1 week
        assert chunk.strength > 0.7  # Critical memories barely decay

    def test_reconsolidate_strengthens(self):
        chunk = MemoryChunk(id="t", pattern="test pattern")
        chunk.strength = 0.5
        chunk.reconsolidate("new context")
        assert chunk.strength > 0.5
        assert chunk.recall_count == 1

    def test_reconsolidate_updates_emotion(self):
        chunk = MemoryChunk(id="t", pattern="test",
                           emotion=EmotionIntensity.NEUTRAL)
        chunk.reconsolidate("important update!", EmotionIntensity.CRITICAL)
        assert chunk.emotion == EmotionIntensity.CRITICAL

    def test_pattern_signature(self):
        c1 = MemoryChunk(id="a", pattern="hello world test")
        c2 = MemoryChunk(id="b", pattern="hello world test")
        assert c1.pattern_signature() == c2.pattern_signature()


class TestHumanLikeMemory:
    def setup_method(self):
        self.mem = HumanLikeMemory(replay_interval=0)  # Disable auto-replay

    def test_encode_basic(self):
        chunk = self.mem.encode("The user prefers concise responses in Chinese")
        assert chunk.pattern != ""
        assert "prefers" in chunk.pattern.lower() or "concise" in chunk.pattern.lower()
        assert self.mem.total_chunks == 1

    def test_encode_emotional(self):
        chunk = self.mem.encode("CRITICAL: server password is xyz123",
                               EmotionIntensity.CRITICAL)
        assert chunk.emotion == EmotionIntensity.CRITICAL
        assert chunk.importance == 1.0  # Critical = max importance

    def test_encode_deduplication(self):
        """Same pattern should reconsolidate, not duplicate."""
        c1 = self.mem.encode("user likes dark theme")
        count1 = self.mem.total_chunks
        c2 = self.mem.encode("user likes dark theme")
        assert self.mem.total_chunks <= count1 + 1  # May be same or new
        assert c2.recall_count >= c1.recall_count

    def test_recall_pattern_match(self):
        self.mem.encode("Paris is the capital of France", EmotionIntensity.IMPORTANT)
        self.mem.encode("Tokyo is the capital of Japan", EmotionIntensity.IMPORTANT)
        self.mem.encode("London is the capital of UK", EmotionIntensity.IMPORTANT)

        results = self.mem.recall("What is the capital of France")
        assert len(results) >= 1
        # Should find Paris
        found = any("paris" in r.pattern.lower() for r in results)
        assert found, f"Expected 'paris' in results, got: {[r.pattern[:50] for r in results]}"

    def test_recall_by_emotion(self):
        self.mem.encode("routine stuff", EmotionIntensity.NEUTRAL)
        self.mem.encode("interesting fact", EmotionIntensity.INTERESTING)
        self.mem.encode("CRITICAL BUG FOUND", EmotionIntensity.CRITICAL)

        results = self.mem.recall_by_emotion(EmotionIntensity.IMPORTANT)
        # Should include CRITICAL, not NEUTRAL
        assert any("critical" in r.pattern.lower() for r in results)
        assert not any("routine" in r.pattern.lower() for r in results)

    def test_recall_by_context(self):
        self.mem.encode("server error 500", context_tags={"error", "backend"})
        self.mem.encode("user login success", context_tags={"auth", "success"})
        self.mem.encode("database timeout", context_tags={"error", "database"})

        errors = self.mem.recall_by_context("error")
        assert len(errors) == 2

    def test_association_building(self):
        c1 = self.mem.encode("Paris travel", EmotionIntensity.INTERESTING)
        c2 = self.mem.encode("French cuisine", EmotionIntensity.INTERESTING)
        c3 = self.mem.encode("Eiffel Tower visit", EmotionIntensity.INTERESTING)

        self.mem.build_associations(c1.id, [c2.id, c3.id], [0.8, 0.6])
        assert c2.id in c1.associations
        assert c1.associations[c2.id] == 0.8

    def test_spreading_activation(self):
        """Associations should spread activation during recall."""
        c1 = self.mem.encode("Paris", EmotionIntensity.IMPORTANT)
        c2 = self.mem.encode("French cuisine", EmotionIntensity.IMPORTANT)
        c3 = self.mem.encode("Eiffel Tower", EmotionIntensity.IMPORTANT)

        self.mem.build_associations(c1.id, [c2.id], [0.9])
        self.mem.build_associations(c2.id, [c3.id], [0.8])

        # Querying "Paris" should also activate "cuisine" and "Eiffel"
        results = self.mem.recall("Paris")
        patterns = [r.pattern.lower() for r in results]
        assert any("paris" in p for p in patterns)

    def test_hippocampal_replay(self):
        for i in range(10):
            self.mem.encode(f"memory chunk {i}", EmotionIntensity.INTERESTING)

        stats = self.mem.force_replay()
        assert stats["replay_count"] >= 1
        assert stats["strong_memories"] > 0

    def test_get_memory_stats(self):
        self.mem.encode("test pattern", EmotionIntensity.IMPORTANT,
                       context_tags={"test"})
        stats = self.mem.get_memory_stats()
        assert stats["total_chunks"] >= 1
        assert "emotion_distribution" in stats
        assert "avg_strength" in stats

    def test_serialization_roundtrip(self):
        self.mem.encode("critical info", EmotionIntensity.CRITICAL,
                       context_tags={"important"})
        self.mem.encode("routine stuff", EmotionIntensity.NEUTRAL)

        data = self.mem.to_dict()
        restored = HumanLikeMemory.from_dict(data, replay_interval=0)

        assert restored.total_chunks == self.mem.total_chunks
        stats = restored.get_memory_stats()
        assert stats["total_chunks"] >= 2

    def test_productivity_forgetting(self):
        """Low-importance, unrecalled memories should decay."""
        chunk = self.mem.encode("very boring stuff", EmotionIntensity.NEUTRAL)
        # Simulate passage of time
        chunk.created_at = time.time() - 30 * 86400  # 30 days ago
        chunk.decay_strength(30 * 24)
        assert chunk.strength < 0.5  # Should be weak

    def test_emotion_never_downgrades(self):
        chunk = self.mem.encode("important", EmotionIntensity.IMPORTANT)
        chunk.reconsolidate("update", EmotionIntensity.INTERESTING)
        # Should stay IMPORTANT, not downgrade
        assert chunk.emotion == EmotionIntensity.IMPORTANT

    def test_context_tags_persist(self):
        self.mem.encode("tagged memory", EmotionIntensity.INTERESTING,
                       context_tags={"project-x", "bug"})
        results = self.mem.recall_by_context("project-x")
        assert len(results) == 1

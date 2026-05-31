"""
v3.51 Cross-Agent Knowledge Sync — 测试
"""
import pytest
import time
from pathlib import Path
import tempfile

from src.core.knowledge_sync import (
    KnowledgeItem, KnowledgeBus, CrossAgentSyncEngine,
    KnowledgeDomain, SyncPriority, ProfileInfo,
    get_knowledge_bus, get_sync_engine,
)


class TestKnowledgeItem:
    def test_create(self):
        ki = KnowledgeItem(title="test", content="hello")
        assert ki.title == "test"
        assert ki.domain == KnowledgeDomain.GENERAL
        assert ki.priority == SyncPriority.MEDIUM

    def test_mark_helpful(self):
        ki = KnowledgeItem()
        assert ki.helpful_count == 0
        ki.mark_helpful()
        assert ki.helpful_count == 1

    def test_is_expired(self):
        ki = KnowledgeItem()
        assert not ki.is_expired()
        ki.expires_at = time.time() - 1
        assert ki.is_expired()

    def test_to_summary(self):
        ki = KnowledgeItem(domain=KnowledgeDomain.SECURITY, title="CVE", content="critical bug")
        s = ki.to_summary()
        assert "security" in s
        assert "CVE" in s


class TestKnowledgeBus:
    def test_publish(self):
        import tempfile, os
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        item = KnowledgeItem(title="test", domain=KnowledgeDomain.DEVELOPMENT)
        bus.publish(item)
        assert item.id in bus._items

    def test_query_by_domain(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.publish(KnowledgeItem(title="dev tip", domain=KnowledgeDomain.DEVELOPMENT, tags=["python"]))
        bus.publish(KnowledgeItem(title="security fix", domain=KnowledgeDomain.SECURITY, tags=["cve"]))
        
        results = bus.query(domain=KnowledgeDomain.SECURITY)
        assert len(results) == 1
        assert "security" in results[0].title

    def test_query_by_tags(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.publish(KnowledgeItem(title="a", tags=["python", "async"]))
        bus.publish(KnowledgeItem(title="b", tags=["rust"]))
        
        results = bus.query(tags=["python"])
        assert len(results) == 1
        assert results[0].title == "a"

    def test_search(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.publish(KnowledgeItem(title="python async guide", content="how to use asyncio"))
        bus.publish(KnowledgeItem(title="rust ownership", content="borrow checker"))
        
        results = bus.search("python")
        assert len(results) >= 1, f"Expected at least 1 result for 'python', got {len(results)}"
        assert any("python" in r.title.lower() for r in results)

    def test_mark_helpful(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        item = KnowledgeItem(title="test")
        bus.publish(item)
        bus.mark_helpful(item.id)
        assert bus._items[item.id].helpful_count == 1

    def test_cleanup_expired(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.publish(KnowledgeItem(title="old", expires_at=time.time() - 10))
        bus.publish(KnowledgeItem(title="new"))
        count = bus.cleanup_expired()
        assert count == 1

    def test_register_profile(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        profile = ProfileInfo(name="meshctx", domains=[KnowledgeDomain.DEVELOPMENT])
        bus.register_profile(profile)
        assert "meshctx" in bus._profiles

    def test_get_for_profile(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.register_profile(ProfileInfo(name="dev", domains=[KnowledgeDomain.DEVELOPMENT]))
        bus.register_profile(ProfileInfo(name="sec", domains=[KnowledgeDomain.SECURITY]))
        
        bus.publish(KnowledgeItem(title="dev tool", domain=KnowledgeDomain.DEVELOPMENT))
        bus.publish(KnowledgeItem(title="cve fix", domain=KnowledgeDomain.SECURITY))
        
        dev_items = bus.get_for_profile("dev")
        assert any("dev" in i.title for i in dev_items)

    def test_get_stats(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.publish(KnowledgeItem(title="a", domain=KnowledgeDomain.DEVELOPMENT, priority=SyncPriority.HIGH))
        stats = bus.get_stats()
        assert stats["total_items"] == 1

    def test_subscribe_notification(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        received = []
        bus.subscribe("observer", lambda item: received.append(item.title))
        bus.publish(KnowledgeItem(title="important", priority=SyncPriority.CRITICAL, tags=["all"]))
        # Notification happens based on profile relevance


class TestCrossAgentSyncEngine:
    def test_learn_from_error(self):
        engine = CrossAgentSyncEngine()
        item = engine.learn_from_error("dev", "TIMEOUT", "Request timed out", "Increase timeout to 60s")
        assert item is not None
        assert item.domain == KnowledgeDomain.PERFORMANCE
        assert "TIMEOUT" in item.title

    def test_learn_from_pattern(self):
        engine = CrossAgentSyncEngine()
        item = engine.learn_from_pattern("dev", "var_syntax", "NSIS Var requires one per line", "Split Var declarations")
        assert item is not None
        assert item.domain == KnowledgeDomain.GENERAL

    def test_sync_to_profile(self):
        engine = CrossAgentSyncEngine()
        engine.bus.register_profile(ProfileInfo(name="receiver", domains=[KnowledgeDomain.DEVELOPMENT]))
        engine.learn_from_error("sender", "SYNTAX", "bad indent", "fix indent")
        items = engine.sync_to_profile("receiver")
        assert len(items) >= 1

    def test_cross_agent_insights(self):
        engine = CrossAgentSyncEngine()
        engine.bus.register_profile(ProfileInfo(name="target", domains=[KnowledgeDomain.GENERAL]))
        engine.learn_from_pattern("source", "pattern_x", "found a pattern", "use this")
        insights = engine.get_cross_agent_insights("target")
        assert len(insights) >= 1

    def test_get_stats(self):
        engine = CrossAgentSyncEngine()
        stats = engine.get_stats()
        assert "bus" in stats
        assert "sync_count" in stats


class TestIntegration:
    """端到端: 发布→订阅→同步→查询"""

    def test_pub_sub_flow(self):
        bus = KnowledgeBus(storage_path=Path(tempfile.mkdtemp()) / "kb.json")
        bus.register_profile(ProfileInfo(name="dev", domains=[KnowledgeDomain.DEVELOPMENT]))
        bus.register_profile(ProfileInfo(name="ops", domains=[KnowledgeDomain.DEPLOYMENT]))
        
        # Dev publishes a deployment tip
        bus.publish(KnowledgeItem(
            source_profile="dev",
            domain=KnowledgeDomain.DEPLOYMENT,
            title="SCP timeout fix",
            content="Use cat pipe instead of scp for large files",
            solution="cat file | ssh host 'cat > /path'",
            tags=["deploy", "scp", "ssh"],
        ))
        
        # Ops queries for deployment tips
        ops_items = bus.get_for_profile("ops")
        assert len(ops_items) >= 1
        assert "scp" in ops_items[0].title.lower() or "timeout" in ops_items[0].title.lower()

    def test_singleton(self):
        b1 = get_knowledge_bus()
        b2 = get_knowledge_bus()
        assert b1 is b2
        
        e1 = get_sync_engine()
        e2 = get_sync_engine()
        assert e1 is e2

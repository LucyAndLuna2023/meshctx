"""v2.53 Cross-Agent Knowledge Transfer — 测试套件"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.knowledge_transfer import (
    CrossAgentKnowledgeEngine, KnowledgeNode, KnowledgeSource, get_knowledge_engine
)


@pytest.fixture
def engine():
    return CrossAgentKnowledgeEngine(max_nodes=100)


class TestAgentManagement:
    """Agent管理"""

    def test_register_agent(self, engine):
        result = engine.register_agent("agent-1", ["code", "search"])
        assert result["status"] == "registered"
        assert "agent-1" in engine._agents

    def test_unregister_agent(self, engine):
        engine.register_agent("agent-2")
        engine.unregister_agent("agent-2")
        assert "agent-2" not in engine._agents


class TestKnowledgeCRUD:
    """知识增删查"""

    def test_add_knowledge(self, engine):
        node = engine.add_knowledge("Python 3.12引入了新的类型语法",
                                     category="programming",
                                     source_agent="agent-1",
                                     confidence=0.8)
        assert node.node_id != ""
        assert node.confidence == 0.8
        assert node.strength == 1.0

    def test_get_knowledge(self, engine):
        node = engine.add_knowledge("测试知识")
        retrieved = engine.get_knowledge(node.node_id)
        assert retrieved is not None
        assert retrieved.content == "测试知识"
        assert retrieved.access_count >= 1

    def test_get_nonexistent(self, engine):
        assert engine.get_knowledge("nonexistent") is None

    def test_query_knowledge(self, engine):
        engine.add_knowledge("Python异步编程", category="programming")
        engine.add_knowledge("JavaScript异步编程", category="programming")
        engine.add_knowledge("Docker部署", category="devops")
        results = engine.query_knowledge("异步编程", category="programming")
        assert len(results) >= 1
        assert any("Python" in r.content for r in results)

    def test_query_min_confidence(self, engine):
        engine.add_knowledge("高置信度", confidence=0.9)
        engine.add_knowledge("低置信度", confidence=0.1)
        results = engine.query_knowledge("置信度", min_confidence=0.5)
        assert all(r.confidence >= 0.5 for r in results)

    def test_query_skips_weak_nodes(self, engine):
        node = engine.add_knowledge("弱知识")
        node.strength = 0.05  # 低于阈值
        results = engine.query_knowledge("弱知识")
        assert len(results) == 0


class TestKnowledgeDecay:
    """知识衰减"""

    def test_decay_reduces_strength(self, engine):
        node = engine.add_knowledge("会衰减的知识")
        original = node.strength
        engine.decay_knowledge()
        assert node.strength < original

    def test_decay_removes_weak_nodes(self, engine):
        node = engine.add_knowledge("极弱知识")
        node.strength = 0.01
        engine.decay_knowledge()
        assert engine.get_knowledge(node.node_id) is None

    def test_consolidation_boosts_strong(self, engine):
        node = engine.add_knowledge("高频知识")
        node.access_count = 10
        node.strength = 0.5
        engine.consolidate_knowledge()
        assert node.strength > 0.5  # 巩固后更强


class TestBroadcast:
    """知识广播"""

    def test_broadcast_lesson(self, engine):
        engine.register_agent("teacher")
        result = engine.broadcast_lesson("teacher", "SSH密钥配置方法",
                                          category="devops")
        assert result["broadcast_id"] != ""
        assert engine._stats["total_broadcasts"] >= 1
        # agent贡献应增加
        assert engine._agents["teacher"]["contributions"] >= 1

    def test_broadcast_creates_node(self, engine):
        result = engine.broadcast_lesson("agent-a", "新发现", confidence=0.7)
        node = engine.get_knowledge(result["broadcast_id"])
        assert node is not None
        assert node.source == KnowledgeSource.CROSS_AGENT


class TestConflictResolution:
    """冲突解决"""

    def test_resolve_conflict_higher_confidence_wins(self, engine):
        a = engine.add_knowledge("答案A", confidence=0.9)
        b = engine.add_knowledge("答案B", confidence=0.3)
        result = engine.resolve_conflict(a.node_id, b.node_id)
        assert result["winner_id"] == a.node_id

    def test_resolve_conflict_loser_deprecated(self, engine):
        a = engine.add_knowledge("正确答案", confidence=0.9)
        b = engine.add_knowledge("错误答案", confidence=0.3)
        result = engine.resolve_conflict(a.node_id, b.node_id)
        loser = engine.get_knowledge(result["loser_id"])
        assert loser.strength < 1.0  # 输家被降权

    def test_resolve_conflict_nonexistent(self, engine):
        result = engine.resolve_conflict("no-a", "no-b")
        assert "error" in result


class TestAgentInsights:
    """Agent个性化知识"""

    def test_agent_insights(self, engine):
        engine.register_agent("agent-x")
        engine.add_knowledge("知识1", source_agent="agent-x", confidence=0.8)
        engine.add_knowledge("知识2", source_agent="agent-y", confidence=0.9)
        insights = engine.get_agent_insights("agent-x")
        assert insights["agent_id"] == "agent-x"
        assert len(insights["insights"]) >= 1

    def test_agent_insights_empty(self, engine):
        engine.register_agent("empty-agent")
        insights = engine.get_agent_insights("empty-agent")
        assert len(insights["insights"]) == 0


class TestStats:
    """统计"""

    def test_stats_tracks_all(self, engine):
        engine.register_agent("a1")
        engine.add_knowledge("k1")
        engine.add_knowledge("k2")
        engine.broadcast_lesson("a1", "lesson")
        stats = engine.get_stats()
        assert stats["agent_count"] >= 1
        assert stats["total_broadcasts"] >= 1
        assert stats["active_nodes"] >= 2

    def test_top_categories(self, engine):
        engine.add_knowledge("a", category="cat1")
        engine.add_knowledge("b", category="cat1")
        engine.add_knowledge("c", category="cat2")
        cats = engine._top_categories()
        assert len(cats) >= 1
        assert cats[0][0] == "cat1"


class TestEdgeCases:
    """边界条件"""

    def test_duplicate_content_different_ids(self, engine):
        """相同内容应产生不同ID(时间戳不同)"""
        n1 = engine.add_knowledge("重复内容")
        time.sleep(0.01)
        n2 = engine.add_knowledge("重复内容")
        assert n1.node_id != n2.node_id

    def test_query_empty_graph(self, engine):
        results = engine.query_knowledge("nothing")
        assert len(results) == 0

    def test_max_nodes_pruning(self, engine):
        """节点数超过限制时自动裁剪"""
        small = CrossAgentKnowledgeEngine(max_nodes=5)
        for i in range(10):
            node = small.add_knowledge(f"node-{i}")
            node.strength = 0.01  # 标记为弱
        small.decay_knowledge()
        assert len(small._graph) < 10


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import knowledge_transfer
        knowledge_transfer._engine = None
        e1 = get_knowledge_engine()
        e2 = get_knowledge_engine()
        assert e1 is e2

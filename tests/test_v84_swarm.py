"""v2.84 Swarm Engine — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def swarm():
    from src.core.swarm_engine import SwarmEngine
    return SwarmEngine()


class TestDiscovery:
    def test_self_registered(self, swarm):
        assert len(swarm._members) >= 1

    def test_discover(self, swarm):
        discovered = swarm.discover(["192.168.1.2:3001", "192.168.1.3:3001"])
        assert len(swarm._members) >= 3

    def test_register(self, swarm):
        from src.core.swarm_engine import SwarmMember
        m = SwarmMember(agent_id="test-agent", host="1.2.3.4")
        swarm.register(m)
        assert "test-agent" in swarm._members

    def test_heartbeat(self, swarm):
        hb = swarm.heartbeat()
        assert hb["total"] >= 1


class TestVoting:
    def test_propose(self, swarm):
        swarm.discover(["10.0.0.2:3001"])
        vote = swarm.propose("deploy to production")
        assert vote.proposal == "deploy to production"

    def test_cast_vote(self, swarm):
        swarm.discover(["10.0.0.2:3001", "10.0.0.3:3001"])
        swarm.propose("enable feature X")
        swarm.cast_vote("enable feature X", "meshctx-0", True)
        # Get one of the discovered agents
        for mid in swarm._members:
            if mid != "meshctx-0":
                swarm.cast_vote("enable feature X", mid, True)
                break

        consensus = swarm.get_consensus("enable feature X")
        assert "ratio" in consensus

    def test_vote_duplicate_prevented(self, swarm):
        swarm.propose("test")
        swarm.cast_vote("test", "meshctx-0", True)
        result = swarm.cast_vote("test", "meshctx-0", False)  # 重复投票
        assert result is False


class TestTaskDistribution:
    def test_assign_task(self, swarm):
        swarm.discover(["10.0.0.2:3001"])
        assigned = swarm.assign_task({"type": "code", "content": "write sort"})
        assert assigned is not None

    def test_report_result(self, swarm):
        swarm.discover(["10.0.0.2:3001"])
        mid = list(swarm._members.keys())[0]
        swarm.report_result(mid, "task-1", True, "done")
        member = swarm._members[mid]
        assert member.tasks_completed >= 1
        assert member.trust_score > 0.5


class TestKnowledgeSharing:
    def test_share_and_query(self, swarm):
        swarm.share_knowledge("db_host", "postgres.local")
        result = swarm.query_knowledge("db_host")
        assert result == "postgres.local"

    def test_unknown_key(self, swarm):
        result = swarm.query_knowledge("nonexistent")
        assert result is None


class TestLeaderElection:
    def test_elect_leader(self, swarm):
        swarm.discover(["10.0.0.2:3001"])
        leader = swarm.elect_leader()
        assert leader == "meshctx-0"  # 自己信任度最高


class TestStats:
    def test_swarm_stats(self, swarm):
        swarm.discover(["10.0.0.2:3001"])
        stats = swarm.get_swarm_stats()
        assert stats["members"] >= 2
        assert "leader" in stats
        assert "avg_trust" in stats

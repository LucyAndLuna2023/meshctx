"""v3.65 Agent Governance — tests"""
import pytest
from src.core.agent_governance import AgentGovernance, AgentIdentity, get_governance

class TestGovernance:
    def test_register(self):
        g = AgentGovernance()
        g.register(AgentIdentity(id="a1", name="test", role="worker"))
        assert "a1" in g._agents

    def test_quota(self):
        g = AgentGovernance()
        g.register(AgentIdentity(id="a1", name="test"))
        g.record_usage("a1", tokens=50000)
        assert g.check_quota("a1")

    def test_quota_exceeded(self):
        g = AgentGovernance()
        g.register(AgentIdentity(id="a1", name="test"))
        g.record_usage("a1", tokens=200000)
        assert not g.check_quota("a1")

    def test_audit(self):
        g = AgentGovernance()
        g.audit("a1", "deploy", "ok")
        assert len(g._audit) == 1

    def test_policy(self):
        g = AgentGovernance()
        g.register(AgentIdentity(id="a1", name="test", role="worker"))
        g.add_policy("deploy_policy", {"action":"deploy","roles":["admin"]})
        assert not g.evaluate("a1", "deploy")

    def test_stats(self):
        g = AgentGovernance()
        g.register(AgentIdentity(id="a1", name="test"))
        s = g.get_stats()
        assert s["agents"] == 1

    def test_singleton(self):
        assert get_governance() is get_governance()

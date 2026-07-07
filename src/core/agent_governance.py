"""meshctx agent_governance — agent registration, quota, policy, audit"""

import time
from dataclasses import dataclass, field


@dataclass
class AgentIdentity:
    """Identity for an agent in the governance system."""
    id: str = ""
    name: str = ""
    role: str = "worker"
    agent_id: str = ""

    def __post_init__(self):
        if not self.agent_id:
            self.agent_id = self.id or f"agent_{id(self)}"


class AgentGovernance:
    """Governs agent lifecycle: registration, quota, policy, audit."""

    DEFAULT_QUOTA = 100000  # tokens

    def __init__(self):
        self._agents = {}
        self._quota = {}
        self._audit = []
        self._policies = {}

    def register(self, identity):
        """Register an agent identity."""
        self._agents[identity.id] = identity
        self._quota[identity.id] = 0

    def record_usage(self, agent_id, tokens=0):
        """Record token usage for an agent."""
        if agent_id in self._quota:
            self._quota[agent_id] += tokens

    def check_quota(self, agent_id):
        """Check if agent is under quota. Returns True if under limit."""
        used = self._quota.get(agent_id, 0)
        return used < self.DEFAULT_QUOTA

    def audit(self, agent_id, action, result):
        """Record an audit entry."""
        self._audit.append({
            "agent_id": agent_id,
            "action": action,
            "result": result,
            "timestamp": time.time(),
        })

    def add_policy(self, name, policy):
        """Add an access policy."""
        self._policies[name] = policy

    def evaluate(self, agent_id, action):
        """Evaluate whether an agent is allowed to perform an action."""
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        for policy in self._policies.values():
            if policy.get("action") == action:
                allowed_roles = policy.get("roles", [])
                agent_role = getattr(agent, "role", "")
                return agent_role in allowed_roles
        return True

    def get_stats(self):
        """Return governance statistics."""
        return {
            "agents": len(self._agents),
            "policies": len(self._policies),
            "audit_entries": len(self._audit),
            "total_quota_used": sum(self._quota.values()),
        }


_governance = None


def get_governance():
    """Singleton accessor for AgentGovernance."""
    global _governance
    if _governance is None:
        _governance = AgentGovernance()
    return _governance

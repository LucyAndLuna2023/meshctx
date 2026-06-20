"""Summon Engine — 开源版 (stub)"""
import uuid, time

class _SummonResult:
    def __init__(self, agent_id, description, task, role):
        self.agent_id = agent_id
        self.description = description
        self.task = task
        self.role = role
        self.status = "completed"
        self.result = f"[stub] Task '{task or description}' completed by {role or 'default'} agent"
        self.created_at = time.time()
    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "result": self.result,
            "description": self.description,
            "task": self.task,
            "role": self.role,
            "created_at": self.created_at,
        }

class _SummonEngine:
    def __init__(self):
        self._agents = {}
    def summon(self, description="", task="", timeout=300, role="", async_mode=False):
        agent_id = str(uuid.uuid4())[:8]
        result = _SummonResult(agent_id, description, task, role)
        self._agents[agent_id] = result
        return result
    def active_agents(self):
        return [a.to_dict() for a in self._agents.values()]
    def get_stats(self):
        return {"total_summoned": len(self._agents), "active": len(self._agents)}
    def dismiss(self, agent_id):
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

_engine = _SummonEngine()
def get_summon_engine():
    return _engine

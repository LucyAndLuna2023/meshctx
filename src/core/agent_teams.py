"""meshctx agent_teams"""
import uuid
from dataclasses import dataclass, field
from enum import Enum

class AgentRole(str, Enum):
    LEAD = "lead"
    DEVELOPER = "developer"
    TESTER = "tester"
    REVIEWER = "reviewer"

@dataclass
class AgentProfile:
    name: str = ""
    role: AgentRole = AgentRole.DEVELOPER
    agent_id: str = field(default_factory=lambda: f"agent_{uuid.uuid4().hex[:8]}")

@dataclass
class AgentTask:
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    description: str = ""
    assigned_to: str = ""

BUILTIN_AGENTS = {"code_lead": AgentProfile(name="Code Lead", role=AgentRole.LEAD)}

_teams = None
def get_teams():
    global _teams
    if _teams is None:
        _teams = type("Teams", (), {"agents": [], "tasks": [], "get_team_status": lambda self: {"agents": len(self.agents)}})()
    return _teams

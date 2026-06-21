"""meshctx agent_governance"""
import uuid, time
from dataclasses import dataclass, field
from src.core.agent_swarm import AgentIdentity

_governance = None
def get_governance():
    global _governance
    if _governance is None: _governance = AgentIdentity()
    return _governance

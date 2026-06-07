"""
meshctx v3.65 — Agent Governance (Agent治理)

功能:
  1. Agent注册: 身份/角色/权限
  2. 配额管理: token/API调用/会话/时间限制
  3. 审计日志: 所有Agent操作可追溯
  4. 策略引擎: 规则定义+自动执行
"""
import logging, time, json
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.agent_governance")

@dataclass
class AgentIdentity:
    id: str; name: str; role: str="worker"
    permissions: List[str]=field(default_factory=list)
    active: bool=True; created: float=field(default_factory=time.time)

@dataclass
class Quota:
    max_tokens: int=100000; max_calls: int=1000; max_sessions: int=50
    tokens_used: int=0; calls_used: int=0; sessions_used: int=0

@dataclass
class AuditEntry:
    agent_id: str; action: str; result: str; timestamp: float=field(default_factory=time.time)

class AgentGovernance:
    def __init__(self):
        self._agents: Dict[str,AgentIdentity]={}
        self._quotas: Dict[str,Quota]={}
        self._audit: deque=deque(maxlen=500)
        self._policies: Dict[str,Dict]={}
    
    def register(self, agent: AgentIdentity) -> str:
        self._agents[agent.id] = agent
        self._quotas[agent.id] = Quota()
        return agent.id
    
    def check_quota(self, agent_id: str) -> bool:
        q = self._quotas.get(agent_id)
        if not q: return False
        return (q.tokens_used < q.max_tokens and q.calls_used < q.max_calls 
                and q.sessions_used < q.max_sessions)
    
    def record_usage(self, agent_id: str, tokens: int=0):
        q = self._quotas.get(agent_id)
        if q:
            q.tokens_used += tokens; q.calls_used += 1
    
    def audit(self, agent_id: str, action: str, result: str="ok"):
        self._audit.append(AuditEntry(agent_id=agent_id, action=action, result=result))
    
    def add_policy(self, name: str, rule: Dict):
        self._policies[name] = rule
    
    def evaluate(self, agent_id: str, action: str) -> bool:
        agent = self._agents.get(agent_id)
        if not agent: return False
        for name, rule in self._policies.items():
            if rule.get("action") == action:
                return agent.role in rule.get("roles", [agent.role])
        return True
    
    @property
    def status(self) -> Dict:
        """治理状态 (兼容 /api/governance/status)"""
        return {
            "agents_registered": len(self._agents),
            "agents_active": sum(1 for a in self._agents.values() if a.active),
            "policies": len(self._policies),
            "audit_entries": len(self._audit),
            "quotas": {aid: {"max_tokens": q.max_tokens, "tokens_used": q.tokens_used,
                             "max_calls": q.max_calls, "calls_used": q.calls_used}
                       for aid, q in self._quotas.items()},
        }

    @property
    def rules(self) -> List[Dict]:
        """策略规则列表 (兼容 /api/governance/rules)"""
        return [{"name": name, **rule} for name, rule in self._policies.items()]

    @property
    def error_patterns(self) -> Dict:
        """错误模式分析 (兼容 /api/governance/errors)"""
        patterns = {}
        for entry in self._audit:
            if entry.result != "ok":
                key = f"{entry.action}:{entry.result}"
                patterns[key] = patterns.get(key, 0) + 1
        return {"patterns": patterns, "total_errors": sum(patterns.values())}

    def get_stats(self) -> Dict:
        return {"agents": len(self._agents), "policies": len(self._policies),
                "audit_entries": len(self._audit),
                "active": sum(1 for a in self._agents.values() if a.active)}

_ag = None
def get_governance():
    global _ag
    if _ag is None: _ag = AgentGovernance()
    return _ag

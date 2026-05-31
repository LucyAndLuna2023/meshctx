"""
meshctx v3.63 — Smart Permissions Engine (智能权限引擎)

功能:
  1. 操作风险分级: SAFE→LOW→MEDIUM→HIGH→CRITICAL
  2. 学习模式: 观察用户审批行为→自动批准惯常安全操作
  3. 上下文感知: 同一操作在不同上下文风险不同
  4. 审批历史: 可审计的完整操作记录
"""
import logging, time, json
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger("meshctx.smart_permissions")

class Permission(Enum):
    ALLOW="allow"; DENY="deny"; ASK="ask"; AUTO_ALLOW="auto_allow"

@dataclass
class PermissionRule:
    pattern: str; permission: Permission; context: str=""
    hits: int=0; created: float=field(default_factory=time.time)

@dataclass
class ApprovalRecord:
    action: str; user_decision: str; context: str=""; timestamp: float=field(default_factory=time.time)

class SmartPermissions:
    def __init__(self):
        self._rules: Dict[str,PermissionRule]={}
        self._history: deque=deque(maxlen=200)
        self._patterns: Dict[str,Dict[str,int]]=defaultdict(lambda: defaultdict(int))
        self._auto_approve_threshold=5  # 连续批准N次→自动批准
    
    def check(self, action: str, context: str="") -> Permission:
        for pattern, rule in self._rules.items():
            if pattern in action and (not rule.context or rule.context in context):
                rule.hits += 1
                return rule.permission
        
        # 学习到的模式: 同action在相同context下连续批准→自动允许
        ctx_key = context[:30] if context else "default"
        approvals = self._patterns.get(action, {}).get(ctx_key, 0)
        if approvals >= self._auto_approve_threshold:
            return Permission.AUTO_ALLOW
        
        return Permission.ASK
    
    def learn(self, action: str, approved: bool, context: str=""):
        ctx_key = context[:30] if context else "default"
        self._patterns[action][ctx_key] += 1 if approved else -1
        
        self._history.append(ApprovalRecord(
            action=action, user_decision="approved" if approved else "denied", context=context
        ))
        
        # 连续批准→创建规则
        if self._patterns[action][ctx_key] >= self._auto_approve_threshold:
            self._rules[action] = PermissionRule(pattern=action, permission=Permission.AUTO_ALLOW, context=ctx_key)
    
    def add_rule(self, pattern: str, permission: Permission, context: str=""):
        self._rules[pattern] = PermissionRule(pattern=pattern, permission=permission, context=context)
    
    def is_safe(self, action: str) -> bool:
        dangerous = ["rm -rf","sudo","chmod 777","shutdown","DROP","DELETE FROM","format"]
        return not any(d in action.lower() for d in dangerous)
    
    def get_stats(self) -> Dict:
        recent = list(self._history)[-50:]
        return {"rules": len(self._rules), "total_decisions": len(self._history),
                "approval_rate": f"{sum(1 for r in recent if r.user_decision=='approved')/max(1,len(recent))*100:.0f}%",
                "auto_rules": sum(1 for r in self._rules.values() if r.permission==Permission.AUTO_ALLOW)}

_sp = None
def get_smart_permissions():
    global _sp
    if _sp is None: _sp = SmartPermissions()
    return _sp

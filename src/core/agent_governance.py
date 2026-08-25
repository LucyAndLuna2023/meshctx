"""meshctx agent_governance — agent registration, quota, policy, audit.

真实实现（开源版）: 纯 Python stdlib (threading / dataclasses / time / logging)。
提供 agent 身份注册、令牌配额管理、访问策略评估与操作审计的
进程内（内存）治理服务。不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.agent_governance")


@dataclass
class AgentIdentity:
    """Identity for an agent in the governance system.

    ``id`` 是治理系统的唯一键；``agent_id`` 作为别名，未显式提供时
    回退到 ``id``（保持向后兼容：调用方可能只传 id 或只传 agent_id）。
    """
    id: str = ''
    name: str = ''
    role: str = 'worker'
    agent_id: str = ''

    def __post_init__(self):
        if not self.agent_id:
            self.agent_id = self.id
        if not self.name:
            self.name = self.id
        if not self.role:
            self.role = 'worker'

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "agent_id": self.agent_id,
        }


@dataclass
class Quota:
    """Token 配额状态（per-agent）。"""
    agent_id: str = ''
    limit: int = 100000
    used: int = 0
    last_reset: float = field(default_factory=time.time)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def under_limit(self) -> bool:
        return self.used < self.limit

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "last_reset": self.last_reset,
        }


@dataclass
class AuditEntry:
    """一条操作审计记录。"""
    agent_id: str = ''
    action: str = ''
    result: str = ''
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "action": self.action,
            "result": self.result,
            "timestamp": self.timestamp,
        }


class AgentGovernance:
    """Governs agent lifecycle: registration, quota, policy, audit.

    线程安全：所有可变状态通过 ``self._lock`` 保护，可被多线程 worker 共享。
    """

    DEFAULT_QUOTA = 100000

    def __init__(self):
        self._agents: Dict[str, AgentIdentity] = {}
        self._quotas: Dict[str, Quota] = {}
        self._audit: List[AuditEntry] = []
        self._policies: Dict[str, dict] = {}
        self._error_patterns: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._created_at = time.time()

    # ── 注册 ──────────────────────────────────────────────
    def register(self, identity):
        """Register an agent identity.

        返回注册后的 AgentIdentity。重复注册同一 id 会更新既有记录。
        """
        if not isinstance(identity, AgentIdentity):
            identity = AgentIdentity(id=str(identity))
        with self._lock:
            existing = self._agents.get(identity.id)
            if existing is not None:
                # 合并: 保留既有配额与审计, 更新身份元数据
                existing.name = identity.name or existing.name
                existing.role = identity.role or existing.role
                existing.agent_id = identity.agent_id or existing.agent_id
                self._agents[identity.id] = existing
                self._quotas.setdefault(identity.id, Quota(agent_id=identity.id, limit=self.DEFAULT_QUOTA))
                return existing
            self._agents[identity.id] = identity
            self._quotas.setdefault(identity.id, Quota(agent_id=identity.id, limit=self.DEFAULT_QUOTA))
            logger.info("agent registered: %s (role=%s)", identity.id, identity.role)
            return identity

    def unregister(self, agent_id: str) -> bool:
        """移除一个 agent 及其配额（保留审计记录）。"""
        with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                self._quotas.pop(agent_id, None)
                return True
            return False

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        with self._lock:
            return self._agents.get(agent_id)

    # ── 配额 ──────────────────────────────────────────────
    def record_usage(self, agent_id, tokens=0):
        """Record token usage for an agent.

        未注册的 agent 会被自动注册（宽松模式），配额从 DEFAULT_QUOTA 起算。
        """
        tokens = int(tokens or 0)
        with self._lock:
            if agent_id not in self._agents:
                self.register(AgentIdentity(id=agent_id, name=agent_id, role='worker'))
            quota = self._quotas.setdefault(agent_id, Quota(agent_id=agent_id, limit=self.DEFAULT_QUOTA))
            quota.used += max(0, tokens)
            return quota.used

    def check_quota(self, agent_id):
        """Check if agent is under quota. Returns True if under limit."""
        with self._lock:
            quota = self._quotas.get(agent_id)
            if quota is None:
                return True
            return quota.under_limit()

    def get_quota(self, agent_id: str) -> Optional[Quota]:
        with self._lock:
            return self._quotas.get(agent_id)

    # ── 审计 ──────────────────────────────────────────────
    def audit(self, agent_id, action, result):
        """Record an audit entry."""
        entry = AuditEntry(agent_id=str(agent_id), action=str(action), result=str(result))
        with self._lock:
            self._audit.append(entry)
            # 记录错误模式（用于 /api/governance/errors）
            if str(result).lower() in ("error", "failed", "denied", "fail"):
                key = f"{action}:{result}"
                self._error_patterns[key] = self._error_patterns.get(key, 0) + 1
        return entry

    def audit_log(self, limit: int = 100) -> List[dict]:
        """最近审计记录（倒序）。"""
        with self._lock:
            return [e.to_dict() for e in self._audit[-limit:]][::-1]

    # ── 策略 ──────────────────────────────────────────────
    def add_policy(self, name, policy):
        """Add an access policy.

        policy 形如 {"action": "deploy", "roles": ["admin"]}：
        只有 roles 中列出的角色可以执行该 action。
        """
        if not isinstance(policy, dict):
            raise TypeError("policy must be a dict like {'action': ..., 'roles': [...]}")
        with self._lock:
            self._policies[str(name)] = dict(policy)
        logger.info("policy added: %s -> %s", name, policy)
        return True

    def evaluate(self, agent_id, action):
        """Evaluate whether an agent is allowed to perform an action.

        规则: 未注册的 agent 一律拒绝；存在匹配 action 的策略时,
        只有角色在策略 roles 列表中的 agent 被放行; 无匹配策略时默认放行。
        """
        with self._lock:
            identity = self._agents.get(agent_id)
            if identity is None:
                return False
            role = identity.role or 'worker'
            for policy in self._policies.values():
                if policy.get('action') != action:
                    continue
                allowed = policy.get('roles') or []
                if role not in allowed:
                    return False
            return True

    def rules(self) -> List[dict]:
        """导出全部策略（用于 /api/governance/rules）。"""
        with self._lock:
            return [
                {"name": name, "action": p.get("action", ""), "roles": list(p.get("roles", []) or [])}
                for name, p in self._policies.items()
            ]

    def error_patterns(self) -> List[dict]:
        """错误模式统计（用于 /api/governance/errors）。"""
        with self._lock:
            return [
                {"pattern": k, "count": v}
                for k, v in sorted(self._error_patterns.items(), key=lambda kv: -kv[1])
            ]

    # ── 统计 ──────────────────────────────────────────────
    def get_stats(self):
        """Return governance statistics."""
        with self._lock:
            total_tokens = sum(q.used for q in self._quotas.values())
            over = [aid for aid, q in self._quotas.items() if not q.under_limit()]
            return {
                "agents": len(self._agents),
                "quotas": len(self._quotas),
                "total_tokens": total_tokens,
                "audit_entries": len(self._audit),
                "policies": len(self._policies),
                "over_quota": len(over),
                "created_at": self._created_at,
            }

    def status(self) -> dict:
        """兼容 /api/governance/status 的状态摘要。"""
        stats = self.get_stats()
        stats["status"] = "active"
        return stats

    def to_dict(self) -> dict:
        return self.get_stats()


_governance = None
_governance_lock = threading.Lock()


def get_governance():
    """Singleton accessor for AgentGovernance."""
    global _governance
    if _governance is None:
        with _governance_lock:
            if _governance is None:
                _governance = AgentGovernance()
    return _governance


def reset_governance():
    """测试辅助: 重置全局单例。"""
    global _governance
    with _governance_lock:
        _governance = None


__all__ = [
    "AgentIdentity", "AgentGovernance", "Quota", "AuditEntry",
    "get_governance", "reset_governance",
]

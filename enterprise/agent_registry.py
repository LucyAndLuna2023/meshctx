"""
agent_registry.py — Agent 注册/发现/路由/心跳 (v1.0)

架构:
  AgentRegistry (Singleton)
  ├── register(agent)      → agent_id
  ├── discover(capability)  → List[Agent]
  ├── route(task)          → best Agent
  ├── heartbeat(agent_id)  → ttl refresh
  └── drain(agent_id)      → graceful offboarding
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.registry")

# ═══════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════

class AgentStatus(Enum):
    ONLINE = "online"
    BUSY = "busy"
    IDLE = "idle"
    DRAINING = "draining"
    OFFLINE = "offline"


@dataclass
class AgentCapability:
    name: str          # e.g. "code_review", "security_scan"
    proficiency: float  # 0.0–1.0 (learned from past tasks)
    cost_per_call: float = 0.0


@dataclass
class AgentInfo:
    agent_id: str
    role: str               # e.g. "legal_reviewer"
    status: AgentStatus = AgentStatus.IDLE
    capabilities: List[AgentCapability] = field(default_factory=list)
    endpoint: str = ""       # gRPC/HTTP address
    metadata: Dict[str, str] = field(default_factory=dict)
    last_heartbeat: float = field(default_factory=time.time)
    registered_at: float = field(default_factory=time.time)
    load: float = 0.0        # 0.0–1.0 current utilization

    def is_healthy(self, ttl: float = 30.0) -> bool:
        return (time.time() - self.last_heartbeat) < ttl


# ═══════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════

class AgentRegistry:
    """分布式 Agent 注册中心 (支持 Redis/etcd 后端)."""

    def __init__(self, backend: str = "memory"):
        self._agents: Dict[str, AgentInfo] = {}
        self._backend = backend
        self._lock = asyncio.Lock()
        self._watchers: List[Callable] = []

    # ── Register ────────────────────────────────────────────

    async def register(self, agent: AgentInfo) -> str:
        """注册 Agent，返回 agent_id."""
        if not agent.agent_id:
            agent.agent_id = _gen_id(agent.role)
        async with self._lock:
            existing = self._agents.get(agent.agent_id)
            if existing and existing.status != AgentStatus.OFFLINE:
                logger.warning(f"agent {agent.agent_id} already registered, updating")
            agent.registered_at = time.time()
            agent.last_heartbeat = time.time()
            self._agents[agent.agent_id] = agent
        logger.info(f"✅ registered: {agent.role} ({agent.agent_id})")
        await self._notify("register", agent)
        return agent.agent_id

    # ── Discover ────────────────────────────────────────────

    async def discover(
        self,
        capability: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[AgentStatus] = None,
        min_proficiency: float = 0.0,
    ) -> List[AgentInfo]:
        """按能力/角色/状态发现 Agent."""
        results = []
        async with self._lock:
            for a in self._agents.values():
                if not a.is_healthy():
                    continue
                if status and a.status != status:
                    continue
                if role and a.role != role:
                    continue
                if capability:
                    caps = {c.name for c in a.capabilities if c.proficiency >= min_proficiency}
                    if capability not in caps:
                        continue
                results.append(a)
        return sorted(results, key=lambda a: a.load)  # least loaded first

    # ── Route ───────────────────────────────────────────────

    async def route(self, task: Dict[str, Any]) -> Optional[AgentInfo]:
        """智能路由: 任务 → 最佳 Agent (load + capability + cost)."""
        required_cap = task.get("capability", "")
        candidates = await self.discover(
            capability=required_cap,
            status=AgentStatus.IDLE,
        )
        if not candidates:
            logger.warning(f"no idle agent for cap={required_cap}")
            return None

        # 评分: proficiency * 0.6 + (1-load) * 0.3 - cost * 0.1
        def score(a: AgentInfo) -> float:
            prof = next((c.proficiency for c in a.capabilities if c.name == required_cap), 0.5)
            cost = next((c.cost_per_call for c in a.capabilities if c.name == required_cap), 0.0)
            return prof * 0.6 + (1 - a.load) * 0.3 - min(cost, 0.1) * 10

        best = max(candidates, key=score)
        logger.info(f"🎯 routed {required_cap} → {best.role} ({best.agent_id})")
        return best

    # ── Heartbeat ───────────────────────────────────────────

    async def heartbeat(self, agent_id: str, load: float = 0.0) -> bool:
        """心跳更新, 返回是否成功."""
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return False
            agent.last_heartbeat = time.time()
            agent.load = load
            agent.status = AgentStatus.BUSY if load > 0.8 else AgentStatus.IDLE
        return True

    # ── Drain ───────────────────────────────────────────────

    async def drain(self, agent_id: str):
        """优雅下线: 标记 DRAINING → 等任务完成 → OFFLINE."""
        async with self._lock:
            agent = self._agents.get(agent_id)
            if agent:
                agent.status = AgentStatus.DRAINING
        await self._notify("drain", agent)
        # 等待 current_load → 0 (由外部监控)
        await asyncio.sleep(5)
        async with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].status = AgentStatus.OFFLINE
        logger.info(f"👋 drained: {agent_id}")

    # ── List All ────────────────────────────────────────────

    async def list_all(self) -> List[AgentInfo]:
        """列出所有 Agent (含离线)."""
        async with self._lock:
            return list(self._agents.values())

    # ── Watchers ────────────────────────────────────────────

    def watch(self, callback: Callable):
        """注册事件回调."""
        self._watchers.append(callback)

    async def _notify(self, event: str, agent: AgentInfo):
        for cb in self._watchers:
            try:
                await cb(event, agent) if asyncio.iscoroutinefunction(cb) else cb(event, agent)
            except Exception as e:
                logger.error(f"watcher error: {e}")


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _gen_id(role: str) -> str:
    seed = f"{role}:{time.time()}:{id(role)}"
    return f"{role[:8]}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry

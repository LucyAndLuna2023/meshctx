"""Team orchestration — meshctx open-source agent teams.

TeamCreate / TeamDelete equivalent. Each agent in a team runs as an independent
context with its own tools. Teams share a result queue. Uses threading for
concurrent agent execution.

真实实现（开源版）: 纯 Python stdlib (threading / queue / uuid / time)。
不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import queue as _queue
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.team")


class TeamResult:
    """Single agent result placed on the shared result queue."""

    def __init__(self, team_id: str, agent_name: str, role: str,
                 message: str, response: str, latency_ms: float):
        self.team_id = team_id
        self.agent_name = agent_name
        self.role = role
        self.message = message
        self.response = response
        self.latency_ms = latency_ms
        self.timestamp = time.time()

    def to_dict(self, **kw) -> dict:
        return {
            "team_id": self.team_id,
            "agent_name": self.agent_name,
            "role": self.role,
            "message": self.message,
            "response": self.response,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }

    def __repr__(self, **kw) -> str:
        return (f"<TeamResult agent={self.agent_name} role={self.role} "
                f"latency_ms={self.latency_ms:.1f}>")


class AgentContext:
    """Independent context for one agent inside a team."""

    def __init__(self, name: str, role: str, tools: list[str] | None = None,
                 model: str | None = None,
                 process_fn: Callable[..., str] | None = None):
        if not name:
            raise ValueError("agent name must not be empty")
        self.name = name
        self.role = role or 'worker'
        self.tools = list(tools or [])
        self.model = model
        self.process_fn = process_fn
        self.created_at = time.time()
        self.messages_processed = 0

    def _default_process(self, message: str, **kw) -> str:
        """Default processing — echoes with agent identity."""
        tool_hint = f" tools={self.tools}" if self.tools else ""
        return (f"[{self.name} ({self.role}){tool_hint}] "
                f"received: {message}")

    def run(self, team_id: str, message: str, result_queue: "queue.Queue[TeamResult]") -> None:
        """Entry point executed in a dedicated thread."""
        start = time.perf_counter()
        try:
            if self.process_fn is not None:
                response = self.process_fn(message, agent_name=self.name, role=self.role)
            else:
                response = self._default_process(message)
            latency_ms = (time.perf_counter() - start) * 1000.0
            result = TeamResult(team_id, self.name, self.role, message,
                                str(response), round(latency_ms, 2))
        except Exception as e:  # 显式处理: 错误被封装进结果, 不中断其他 agent
            logger.exception("agent %s failed while processing team message", self.name)
            latency_ms = (time.perf_counter() - start) * 1000.0
            result = TeamResult(team_id, self.name, self.role, message,
                                f"ERROR: {type(e).__name__}: {e}", round(latency_ms, 2))
        self.messages_processed += 1
        result_queue.put(result)


class Team:
    """A named team of agents with a shared result queue."""

    def __init__(self, team_id: str, name: str, agents: list[AgentContext]):
        if not agents:
            raise ValueError("team must contain at least one agent")
        self.team_id = team_id
        self.name = name
        self.agents = list(agents)
        self._messages_sent = 0
        self._created_at = time.time()
        self._lock = threading.Lock()

    def send(self, message: str, **kw) -> list[TeamResult]:
        """Send *message* to every agent concurrently and collect results.

        每个 agent 在自己的线程中运行（process_fn 或默认回显），
        全部完成后按入队顺序返回结果列表。
        """
        result_queue: "queue.Queue[TeamResult]" = _queue.Queue()
        threads = [
            threading.Thread(target=agent.run, args=(self.team_id, message, result_queue),
                             daemon=True, name=f"team-{self.team_id}-{agent.name}")
            for agent in self.agents
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        collected: List[TeamResult] = []
        while not result_queue.empty():
            collected.append(result_queue.get_nowait())
        with self._lock:
            self._messages_sent += 1
        return collected

    def stats(self, **kw) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "agents": len(self.agents),
            "agent_names": [a.name for a in self.agents],
            "messages_sent": self._messages_sent,
            "created_at": self._created_at,
        }


# ── 模块级团队注册表（进程内）────────────────────────────
_registry_lock = threading.Lock()
_registry: Dict[str, Team] = {}


def team_create(name: str, agents: list[dict],
                process_fn: Callable[..., str] | None = None) -> str:
    """Create a new team of agents.

    agents 为字典列表, 每项支持: {"name": ..., "role": ..., "tools": [...], "model": ...}
    返回新团队的 team_id。
    """
    if not name:
        raise ValueError("team name must not be empty")
    if not agents:
        raise ValueError("agents list must not be empty")
    contexts = []
    for i, spec in enumerate(agents):
        if not isinstance(spec, dict):
            raise TypeError(f"agents[{i}] must be a dict, got {type(spec).__name__}")
        agent_name = spec.get("name") or f"agent_{i}"
        contexts.append(AgentContext(
            name=agent_name,
            role=spec.get("role", "worker"),
            tools=spec.get("tools"),
            model=spec.get("model"),
            process_fn=process_fn,
        ))
    team_id = f"team_{uuid.uuid4().hex[:8]}"
    team = Team(team_id=team_id, name=name, agents=contexts)
    with _registry_lock:
        _registry[team_id] = team
    logger.info("team created: %s (%s, %d agents)", team_id, name, len(contexts))
    return team_id


def team_send(team_id: str, message: str) -> list[dict]:
    """Send a message to all agents in the team and return their responses."""
    with _registry_lock:
        team = _registry.get(team_id)
    if team is None:
        raise KeyError(f"team not found: {team_id}")
    return [r.to_dict() for r in team.send(message)]


def team_delete(team_id: str) -> bool:
    """Delete a team by its id."""
    with _registry_lock:
        if team_id in _registry:
            del _registry[team_id]
            logger.info("team deleted: %s", team_id)
            return True
        return False


def team_list() -> list[dict]:
    """List all currently active teams."""
    with _registry_lock:
        return [t.stats() for t in _registry.values()]


def team_get(team_id: str) -> Optional[Team]:
    """直接获取 Team 对象（编程式调用）。"""
    with _registry_lock:
        return _registry.get(team_id)


__all__ = [
    "TeamResult", "AgentContext", "Team",
    "team_create", "team_send", "team_delete", "team_list", "team_get",
]

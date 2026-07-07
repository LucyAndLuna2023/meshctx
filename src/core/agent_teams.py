"""
MeshCtx Agent Teams — Specialized Sub-Agent Orchestration
===========================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Lightweight sub-agent system inspired by Claude Code's agent teams:
- Define specialized agents with custom system prompts and tool sets
- Invoke agents by name with task delegation
- Parallel execution with result aggregation
- Agent-to-agent handoff
- Team coordination patterns (review, brainstorm, divide-and-conquer)

License: Proprietary Core.
"""
import time
import threading
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
from enum import Enum


class AgentRole(Enum):
    CODER = "coder"              # Writes/reviews code
    REVIEWER = "reviewer"        # Security/quality review
    ARCHITECT = "architect"      # System design
    TESTER = "tester"            # Test generation
    RESEARCHER = "researcher"    # Research and analysis
    DEVOPS = "devops"            # Infrastructure
    CUSTOM = "custom"            # User-defined


@dataclass
class AgentProfile:
    name: str
    role: AgentRole = AgentRole.CUSTOM
    model: str = ""              # Override default model
    system_prompt: str = ""      # Specialized instructions
    allowed_tools: List[str] = field(default_factory=list)
    temperature: float = 0.3
    max_turns: int = 10
    priority: int = 0

    def to_dict(self) -> Dict:
        return {
            "name": self.name, "role": self.role.value,
            "model": self.model, "system_prompt": self.system_prompt[:200],
            "allowed_tools": self.allowed_tools,
            "temperature": self.temperature, "max_turns": self.max_turns,
        }


@dataclass
class AgentTask:
    task_id: str
    agent_name: str
    instruction: str
    context: str = ""           # Additional context
    priority: int = 0
    created_at: float = field(default_factory=time.time)

    # Results
    status: str = "pending"     # pending/running/done/failed
    result: str = ""
    error: str = ""
    completed_at: float = 0
    tokens_used: int = 0


@dataclass
class TeamResult:
    team_name: str
    tasks: List[AgentTask]
    aggregated: str = ""
    total_tokens: int = 0
    total_time_s: float = 0
    success_count: int = 0
    failure_count: int = 0


# ── Built-in Agent Profiles ──────────────────────────────

BUILTIN_AGENTS = {
    "coder": AgentProfile(
        name="coder", role=AgentRole.CODER,
        system_prompt="你是一个高级软件工程师。写出清晰、可维护的代码，包含类型注解和文档字符串。",
        temperature=0.2, max_turns=15,
    ),
    "reviewer": AgentProfile(
        name="reviewer", role=AgentRole.REVIEWER,
        system_prompt="你是一个安全代码审查员。审查代码的安全漏洞、bug、性能问题、代码异味。",
        temperature=0.1, max_turns=5,
    ),
    "architect": AgentProfile(
        name="architect", role=AgentRole.ARCHITECT,
        system_prompt="你是一个系统架构师。设计可扩展、可维护的系统架构。给出清晰的组件设计和数据流。",
        temperature=0.3, max_turns=20,
    ),
    "tester": AgentProfile(
        name="tester", role=AgentRole.TESTER,
        system_prompt="你是一个测试工程师。编写全面的测试用例，覆盖正常/边界/异常情况。",
        temperature=0.2, max_turns=10,
    ),
    "researcher": AgentProfile(
        name="researcher", role=AgentRole.RESEARCHER,
        system_prompt="你是一个技术研究员。深入分析问题，提供数据驱动的结论和引用。",
        temperature=0.4, max_turns=20,
    ),
    "devops": AgentProfile(
        name="devops", role=AgentRole.DEVOPS,
        system_prompt="你是一个DevOps工程师。关注部署、监控、CI/CD、容器化。",
        temperature=0.2, max_turns=10,
    ),
}


# ── Agent Team Manager ────────────────────────────────────

class AgentTeamManager:
    """Orchestrate multiple specialized sub-agents.

    Patterns:
    1. REVIEW: coder writes → reviewer checks → coder fixes
    2. BRAINSTORM: researcher + architect → merge insights
    3. DIVIDE_CONQUER: split problem → parallel agents → merge
    4. PIPELINE: agent1 output → agent2 input → agent3
    """

    def __init__(self, storage_dir: str = ""):
        home = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
        self.storage_dir = Path(storage_dir) if storage_dir else home / "agents"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.agents: Dict[str, AgentProfile] = dict(BUILTIN_AGENTS)
        self.tasks: Dict[str, AgentTask] = {}
        self.task_history: List[AgentTask] = []
        self._load_custom()

    # ── Agent Management ──────────────────────────────────

    def register(self, profile: AgentProfile):
        self.agents[profile.name] = profile
        # Save custom agents
        if profile.role == AgentRole.CUSTOM:
            self._save_custom()

    def unregister(self, name: str) -> bool:
        if name in BUILTIN_AGENTS:
            return False  # Cannot delete built-in
        if name in self.agents:
            del self.agents[name]
            self._save_custom()
            return True
        return False

    def list_agents(self) -> List[Dict]:
        return [a.to_dict() for a in self.agents.values()]

    def get_agent(self, name: str) -> Optional[AgentProfile]:
        return self.agents.get(name)

    # ── Task Dispatch ─────────────────────────────────────

    def dispatch(self, agent_name: str, instruction: str,
                context: str = "", priority: int = 0) -> AgentTask:
        """Dispatch a task to an agent. Returns immediately with task_id."""
        agent = self.agents.get(agent_name)
        if not agent:
            raise ValueError(f"Agent '{agent_name}' not found. Available: {list(self.agents.keys())}")

        task_id = f"task_{int(time.time()*1000)}_{len(self.task_history)}_{os.urandom(2).hex()}"
        task = AgentTask(
            task_id=task_id, agent_name=agent_name,
            instruction=instruction, context=context, priority=priority,
        )
        self.tasks[task_id] = task
        return task

    def dispatch_parallel(self, assignments: List[tuple]) -> List[AgentTask]:
        """Dispatch multiple tasks in parallel.

        assignments: [(agent_name, instruction, context), ...]
        Returns list of tasks with task_ids.
        """
        tasks = []
        for agent_name, instruction, context in assignments:
            task = self.dispatch(agent_name, instruction, context)
            tasks.append(task)
        return tasks

    def dispatch_pipeline(self, pipeline: List[tuple]) -> List[AgentTask]:
        """Pipeline: each agent's output becomes next agent's context.

        pipeline: [(agent_name, instruction), ...]
        """
        tasks = []
        prev_context = ""
        for agent_name, instruction in pipeline:
            ctx = prev_context + "\n" + instruction if prev_context else instruction
            task = self.dispatch(agent_name, instruction, ctx)
            tasks.append(task)
            # Mark previous task's result as context? (simplified)
            prev_context = instruction
        return tasks

    # ── Team Patterns ─────────────────────────────────────

    def review_pattern(self, code_description: str) -> Dict:
        """REVIEW: coder writes → reviewer checks → report"""
        tasks = {
            "coder": self.dispatch("coder", f"实现: {code_description}"),
            "reviewer": self.dispatch("reviewer",
                f"审查代码: {code_description}。关注安全、性能、可维护性。"),
        }
        return {"pattern": "review", "tasks": {k: v.task_id for k, v in tasks.items()}}

    def brainstorm_pattern(self, topic: str) -> Dict:
        """BRAINSTORM: researcher + architect analyze independently → merge"""
        tasks = {
            "researcher": self.dispatch("researcher",
                f"研究: {topic}。提供数据驱动的分析和洞察。"),
            "architect": self.dispatch("architect",
                f"架构设计: {topic}。考虑可扩展性和技术选型。"),
        }
        return {"pattern": "brainstorm", "tasks": {k: v.task_id for k, v in tasks.items()}}

    def divide_conquer_pattern(self, problem: str, parts: List[str]) -> Dict:
        """DIVIDE_CONQUER: split into N parts → N coders → merge"""
        tasks = {}
        for i, part in enumerate(parts):
            tasks[f"part_{i}"] = self.dispatch("coder",
                f"实现第{i+1}部分: {part}\n整体问题: {problem}")
        return {"pattern": "divide_conquer", "tasks": {k: v.task_id for k, v in tasks.items()}}

    # ── Task Status ───────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self.tasks.get(task_id)

    def complete_task(self, task_id: str, result: str = "",
                     error: str = "", tokens: int = 0):
        """Mark a task as complete."""
        task = self.tasks.get(task_id)
        if not task:
            return
        task.status = "failed" if error else "done"
        task.result = result
        task.error = error
        task.tokens_used = tokens
        task.completed_at = time.time()
        self.task_history.append(task)
        del self.tasks[task_id]

    def get_active_tasks(self) -> List[AgentTask]:
        return [t for t in self.tasks.values()
               if t.status in ("pending", "running")]

    def get_team_result(self, tasks: List[AgentTask]) -> TeamResult:
        """Aggregate results from multiple tasks."""
        completed = [t for t in tasks if t.status == "done"]
        failed = [t for t in tasks if t.status == "failed"]
        aggregated = "\n\n".join(
            f"[{t.agent_name}] {t.result[:300]}" for t in completed
        )
        total_time = max((t.completed_at - t.created_at) for t in tasks
                        if t.completed_at > 0) if tasks else 0

        return TeamResult(
            team_name="team",
            tasks=tasks,
            aggregated=aggregated,
            total_tokens=sum(t.tokens_used for t in tasks),
            total_time_s=total_time,
            success_count=len(completed),
            failure_count=len(failed),
        )

    def get_stats(self) -> Dict:
        return {
            "total_agents": len(self.agents),
            "builtin_agents": len(BUILTIN_AGENTS),
            "custom_agents": len(self.agents) - len(BUILTIN_AGENTS),
            "active_tasks": len(self.tasks),
            "completed_tasks": len(self.task_history),
            "success_rate": round(
                sum(1 for t in self.task_history if t.status == "done") /
                max(len(self.task_history), 1) * 100, 1
            ),
            "agent_usage": {
                name: sum(1 for t in self.task_history if t.agent_name == name)
                for name in self.agents
            },
        }

    # ── Persistence ────────────────────────────────────────

    def _load_custom(self):
        path = self.storage_dir / "custom_agents.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for ag in data:
                    profile = AgentProfile(
                        name=ag["name"],
                        role=AgentRole(ag.get("role", "custom")),
                        model=ag.get("model", ""),
                        system_prompt=ag.get("system_prompt", ""),
                        allowed_tools=ag.get("allowed_tools", []),
                        temperature=ag.get("temperature", 0.3),
                    )
                    self.agents[profile.name] = profile
            except Exception:
                pass

    def _save_custom(self):
        custom = [a.to_dict() for a in self.agents.values()
                 if a.role == AgentRole.CUSTOM or a.name not in BUILTIN_AGENTS]
        path = self.storage_dir / "custom_agents.json"
        path.write_text(json.dumps(custom, indent=2))


# ── Singleton ───────────────────────────────────────────────

_global_teams: Optional[AgentTeamManager] = None


def get_teams() -> AgentTeamManager:
    global _global_teams
    if _global_teams is None:
        _global_teams = AgentTeamManager()
    return _global_teams

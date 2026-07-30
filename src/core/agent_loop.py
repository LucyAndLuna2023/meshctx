"""Agent Loop — Plan/Act/Reflect cycle plugin with AgentPool delegation"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .agent_swarm import AgentPool, SwarmTask, SwarmTaskStatus, get_agent_pool


class LoopPluginInfo:
    """Plugin identity descriptor (stable API)."""
    def __init__(self, name="agent_loop", version="0.1.0", description=""):
        self.name = name
        self.version = version
        self.description = description


class LoopPhase:
    plan = "plan"
    act = "act"
    reflect = "reflect"


@dataclass
class PlanStep:
    step_id: str = field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    description: str = ""
    agent_id: Optional[str] = None
    status: str = "pending"
    result: str = ""
    error: str = ""


class AgentLoopPlugin:
    """Plan/Act/Reflect agent cycle plugin."""

    def __init__(self, objective: str = "", context: dict | None = None,
                 max_iterations: int = 10, pool_max_slots: int = 5):
        self.info = LoopPluginInfo(
            name="agent_loop", version="0.2.0",
            description="Plan/Act/Reflect agent cycle with AgentPool delegation")
        self.kernel = None
        self._running = False
        self._phase = LoopPhase.plan
        self.objective: str = objective
        self.context: dict = context or {}
        self.steps: list = []
        self._current_step_idx: int = 0
        self._iteration: int = 0
        self._max_iterations: int = max_iterations
        self._started_at: Optional[float] = None
        self._last_step_at: Optional[float] = None
        self._pool: Optional[AgentPool] = None
        self._pool_max_slots: int = pool_max_slots
        self._reflection_log: list = []
        self._outcome: str = ""

    async def on_load(self, kernel) -> bool:
        self.kernel = kernel
        pool = get_agent_pool(max_slots=self._pool_max_slots)
        object.__setattr__(self, '_pool', pool)
        self._log("plan", "AgentLoopPlugin loaded")
        return True

    def start(self):
        self._running = True
        self._started_at = time.time()
        self._iteration = 0
        self._phase = LoopPhase.plan
        self._log("plan", f"Starting loop — objective: {self.objective[:80]}")

    def stop(self):
        self._running = False
        self._log("reflect", "Loop stopped")
        self._release_pool()

    def step(self) -> dict:
        if not self._running:
            return {"phase": "idle", "iteration": self._iteration, "outcome": "stopped"}
        self._iteration += 1
        self._last_step_at = time.time()
        self._phase = LoopPhase.plan
        plan_result = self.plan()
        self._log("plan", plan_result.get("summary", "planning done"))
        self._phase = LoopPhase.act
        act_result = self.act()
        self._log("act", act_result.get("summary", "action done"))
        self._phase = LoopPhase.reflect
        reflect_result = self.reflect(act_result)
        self._outcome = reflect_result.get("outcome", "continue")
        self._log("reflect", f"outcome: {self._outcome}")
        if self._iteration >= self._max_iterations:
            self._outcome = "max_iterations"
        if self._outcome in ("done", "failed", "max_iterations"):
            self._running = False
        return {
            "phase": self._phase, "iteration": self._iteration,
            "outcome": self._outcome, "steps_remaining": self._pending_steps(),
            "pool_status": self._pool.status() if self._pool else {},
            "plan": plan_result, "act": act_result, "reflect": reflect_result,
        }

    def plan(self) -> dict:
        if not self.steps and self.objective:
            self.steps = self._decompose_objective(self.objective)
            self._current_step_idx = 0
            return {"summary": f"Generated {len(self.steps)} steps",
                    "steps": [s.description for s in self.steps],
                    "total_steps": len(self.steps)}
        pending = [s for s in self.steps if s.status == "pending"]
        failed = [s for s in self.steps if s.status == "failed"]
        if failed and self._outcome == "replan":
            for s in failed:
                s.status = "pending"
                s.error = ""
            pending = [s for s in self.steps if s.status == "pending"]
            return {"summary": f"Replan — reset {len(failed)} failed, {len(pending)} pending",
                    "steps": [s.description for s in pending],
                    "total_steps": len(pending)}
        return {"summary": f"{len(pending)} steps pending",
                "steps": [s.description for s in pending],
                "total_steps": len(pending)}

    def act(self) -> dict:
        pending = [s for s in self.steps if s.status == "pending"]
        if not pending:
            return {"summary": "no pending steps", "action": "idle"}
        step = pending[0]
        step.status = "running"
        use_pool = self._should_delegate(step)
        if use_pool and self._pool and self._pool.available_slots() > 0:
            task = SwarmTask(description=step.description,
                             task_type=self._infer_task_type(step.description))
            agent_id = self._pool.spawn(task)
            step.agent_id = agent_id
            return {"summary": f"Dispatched to pool agent {agent_id}",
                    "action": "pool_spawn", "step": step.description,
                    "agent_id": agent_id}
        step.result = f"Completed: {step.description}"
        step.status = "done"
        return {"summary": f"Executed inline: {step.description[:60]}",
                "action": "inline", "step": step.description, "result": step.result}

    def reflect(self, act_result: dict) -> dict:
        if self._pool:
            for s in self.steps:
                if s.status == "running" and s.agent_id:
                    task = self._pool.wait(s.agent_id, timeout=0.001)
                    if task and task.status == SwarmTaskStatus.done:
                        s.status = "done"
                        s.result = task.result or "done via pool"
                    elif task and task.status == SwarmTaskStatus.failed:
                        s.status = "failed"
                        s.error = task.error or "pool failure"
        done = sum(1 for s in self.steps if s.status == "done")
        failed = sum(1 for s in self.steps if s.status == "failed")
        pending = sum(1 for s in self.steps if s.status == "pending")
        running = sum(1 for s in self.steps if s.status == "running")
        total = len(self.steps)
        if total > 0 and done == total:
            return {"outcome": "done", "reason": f"All {total} steps completed",
                    "done": done, "failed": failed}
        if total > 0 and failed > 0 and done + failed == total:
            return {"outcome": "failed", "reason": f"{failed} step(s) failed",
                    "done": done, "failed": failed}
        if running:
            return {"outcome": "wait_pool", "reason": f"{running} agent(s) running",
                    "done": done, "pending": pending}
        return {"outcome": "continue", "reason": f"{pending} step(s) remaining",
                "done": done, "pending": pending}

    def stats(self) -> dict:
        now = time.time()
        done = sum(1 for s in self.steps if s.status == "done")
        failed = sum(1 for s in self.steps if s.status == "failed")
        pending = sum(1 for s in self.steps if s.status == "pending")
        running = sum(1 for s in self.steps if s.status == "running")
        return {
            "running": self._running, "phase": self._phase,
            "iteration": self._iteration, "max_iterations": self._max_iterations,
            "objective": self.objective[:120] if self.objective else "",
            "steps_total": len(self.steps), "steps_done": done,
            "steps_failed": failed, "steps_pending": pending,
            "steps_running": running, "outcome": self._outcome,
            "elapsed": round(now - self._started_at, 3) if self._started_at else 0,
            "last_step_elapsed": round(now - self._last_step_at, 3) if self._last_step_at else 0,
            "pool": self._pool.status() if self._pool else {},
            "reflection_log_len": len(self._reflection_log),
        }

    def _decompose_objective(self, objective: str) -> list:
        keywords = {
            "search": "Search and gather information",
            "analyze": "Analyze collected data",
            "design": "Design solution approach",
            "code": "Write implementation code",
            "review": "Review and validate results",
            "write": "Compose output document",
            "test": "Run tests and verify",
            "deploy": "Deploy or publish results",
        }
        obj_lower = objective.lower()
        matched = [desc for kw, desc in keywords.items() if kw in obj_lower]
        if not matched:
            matched = ["Research and gather context", "Analyze requirements",
                       "Produce deliverable", "Review and finalize"]
        steps = []
        for desc in matched:
            steps.append(PlanStep(description=f"{desc}: {objective[:50]}"))
        return steps

    def _should_delegate(self, step: PlanStep) -> bool:
        heavy = {"code", "analyze", "research", "deploy", "test", "write"}
        return any(kw in step.description.lower() for kw in heavy)

    def _infer_task_type(self, description: str) -> str:
        mapping = {"search": "research", "research": "research",
                   "analyze": "code", "code": "code",
                   "write": "research", "review": "code",
                   "test": "code", "deploy": "code"}
        desc = description.lower()
        for kw, tt in mapping.items():
            if kw in desc:
                return tt
        return "general"

    def _pending_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == "pending")

    def _release_pool(self):
        if self._pool:
            for s in self.steps:
                if s.agent_id:
                    self._pool.close(s.agent_id)

    def _log(self, phase: str, msg: str):
        entry = {"phase": phase, "message": msg, "ts": time.time()}
        self._reflection_log.append(entry)
        if len(self._reflection_log) > 100:
            self._reflection_log = self._reflection_log[-50:]



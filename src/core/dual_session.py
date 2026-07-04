"""
meshctx Dual Session Engine v1.0 — Prefix-Cache Stable Planner/Executor Separation

Design (inspired by DeepSeek-Reasonix):
  - Planner: 低频运行, 只读工具, 产出结构化 Plan
  - Executor: 拿到 Plan, 全工具集, 在自己的 session 执行
  - 两个 session 永不混合 → KV prefix-cache 各自稳定, 不互相污染

Key invariants:
  1. Planner uses READ-ONLY tools (read_file, search_files, glob)
  2. Executor gets plan as structured text, never queries planner mid-execution
  3. Sessions are INDEPENDENT UUID-spaces, never cross-reference
  4. Plan is immutable once handed off to executor

Usage:
  engine = DualSessionEngine(provider="deepseek", model_flash="deepseek-flash", model_pro="deepseek-pro")
  plan = await engine.plan("Add dark mode toggle to settings page")
  result = await engine.execute(plan)
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import logging

logger = logging.getLogger("meshctx.dual_session")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

# Read-only tools safe for planner
READ_ONLY_TOOLS: Set[str] = {
    "read_file", "search_files", "search_content", "glob",
    "list_directory", "directory_tree", "get_file_info",
    "session_search", "memory_read",
}

# Write tools only for executor
WRITE_TOOLS: Set[str] = {
    "write_file", "edit_file", "apply_patch", "multi_edit",
    "run_command", "run_background", "web_search",
    "git", "deploy", "browser",
}

PLANNER_SYSTEM_PROMPT = """You are a PLANNER agent. Your ONLY job is to read the codebase and produce a structured execution plan.

TOOLS AVAILABLE (read-only): read_file, search_files, search_content, glob, list_directory

RULES:
1. NEVER write, edit, or run code — you only READ and PLAN
2. Your output MUST be a JSON plan with this exact structure:
{
  "goal": "one-line summary",
  "steps": [
    {
      "id": "step-1",
      "action": "read|write|edit|shell|verify",
      "target": "path/to/file.py",
      "description": "what to do",
      "context": "optional context hint"
    }
  ],
  "estimated_complexity": "low|medium|high",
  "risk_areas": ["list", "of", "risks"]
}
3. Be CONCISE — the executor will read files, you don't need to quote them
4. Break into SMALL, ATOMIC steps (one action per step)
5. Order steps by dependency (reads before writes)"""

EXECUTOR_SYSTEM_PROMPT = """You are an EXECUTOR agent. You have been given a structured PLAN to execute.

RULES:
1. Follow the plan steps IN ORDER
2. You have FULL tools (read, write, shell) — use them
3. For each step, report: [step-id] DONE or [step-id] BLOCKED: reason
4. If blocked, explain WHY and suggest alternatives
5. After ALL steps complete, produce a summary:
   - Steps completed: N/M
   - Files changed: [list]
   - Verification: pass/fail
6. Do NOT re-plan — stick to the given plan unless truly impossible"""


# ═══════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════

class PlanStep:
    """Single step in an execution plan."""
    def __init__(self, step_id: str = "", action: str = "read",
                 target: str = "", description: str = "",
                 context: str = ""):
        self.step_id = step_id
        self.action = action
        self.target = target
        self.description = description
        self.context = context
    
    def to_dict(self) -> dict:
        return {
            "id": self.step_id,
            "action": self.action,
            "target": self.target,
            "description": self.description,
            "context": self.context,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "PlanStep":
        return cls(
            step_id=d.get("id", ""),
            action=d.get("action", "read"),
            target=d.get("target", ""),
            description=d.get("description", ""),
            context=d.get("context", ""),
        )


class PlanStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class ExecutionPlan:
    """Structured plan produced by planner."""
    plan_id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    goal: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    estimated_complexity: str = "medium"
    risk_areas: List[str] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    created_at: float = field(default_factory=time.time)
    planner_session_id: str = ""
    planner_tokens: int = 0
    
    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "estimated_complexity": self.estimated_complexity,
            "risk_areas": self.risk_areas,
            "status": self.status.value,
            "planner_tokens": self.planner_tokens,
        }
    
    def to_prompt(self) -> str:
        """Serialize plan as executor prompt."""
        lines = [
            f"## Execution Plan: {self.goal}",
            f"Complexity: {self.estimated_complexity} | Steps: {len(self.steps)}",
            f"Risks: {', '.join(self.risk_areas)}",
            "",
            "### Steps",
        ]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"{i}. [{s.step_id}] {s.action.upper()} {s.target}")
            lines.append(f"   {s.description}")
            if s.context:
                lines.append(f"   Context: {s.context}")
        return "\n".join(lines)
    
    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionPlan":
        return cls(
            plan_id=d.get("plan_id", ""),
            goal=d.get("goal", ""),
            steps=[PlanStep.from_dict(s) for s in d.get("steps", [])],
            estimated_complexity=d.get("estimated_complexity", "medium"),
            risk_areas=d.get("risk_areas", []),
            status=PlanStatus(d.get("status", "pending")),
            planner_tokens=d.get("planner_tokens", 0),
        )


@dataclass
class ExecutionResult:
    """Result of plan execution."""
    plan_id: str = ""
    executor_session_id: str = ""
    steps_completed: int = 0
    steps_total: int = 0
    files_changed: List[str] = field(default_factory=list)
    verification: str = "pending"
    output: str = ""
    error: str = ""
    executor_tokens: int = 0
    total_tokens: int = 0
    elapsed_ms: float = 0.0
    
    @property
    def success(self) -> bool:
        return self.verification == "pass" and not self.error


# ═══════════════════════════════════════════════════════════
# Dual Session Engine
# ═══════════════════════════════════════════════════════════

class DualSessionEngine:
    """
    Prefix-cache stable dual-session engine.
    
    Architecture:
      Planner Session → produces ExecutionPlan
      Executor Session → consumes ExecutionPlan → produces ExecutionResult
    
    Sessions are isolated by UUID; planner's message history NEVER
    contaminates executor's prefix-cache.
    """
    
    def __init__(self, provider: str = "deepseek",
                 model_flash: str = "deepseek-flash",
                 model_pro: str = "deepseek-pro",
                 planner_max_steps: int = 10,
                 executor_max_steps: int = 50):
        self.provider = provider
        self.model_flash = model_flash    # Planner uses flash (cheap)
        self.model_pro = model_pro        # Executor uses pro (quality)
        self.planner_max_steps = planner_max_steps
        self.executor_max_steps = executor_max_steps
        
        # Session state
        self._planner_session_id: str = ""
        self._executor_session_id: str = ""
        self._planner_messages: List[dict] = []
        self._executor_messages: List[dict] = []
        
        # Stats
        self.total_plans: int = 0
        self.cache_hits: int = 0  # planner runs where prompt prefix unchanged
    
    # ── Session Management ──────────────────────────────────
    
    def _new_planner_session(self) -> str:
        """Create fresh planner session with cache-stable prefix."""
        self._planner_session_id = f"planner_{uuid.uuid4().hex[:12]}"
        self._planner_messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT}
        ]
        return self._planner_session_id
    
    def _new_executor_session(self, plan: ExecutionPlan) -> str:
        """Create fresh executor session with plan baked into system prompt."""
        self._executor_session_id = f"executor_{uuid.uuid4().hex[:12]}"
        system_with_plan = EXECUTOR_SYSTEM_PROMPT + "\n\n" + plan.to_prompt()
        self._executor_messages = [
            {"role": "system", "content": system_with_plan}
        ]
        return self._executor_session_id
    
    # ── Planning Phase ──────────────────────────────────────
    
    async def plan(self, goal: str, llm_call_fn=None) -> ExecutionPlan:
        """
        Run planner session to produce an ExecutionPlan.
        
        Args:
            goal: User's task description
            llm_call_fn: async fn(messages, tools, max_steps) -> response_text
                         If None, uses placeholder.
        
        Returns:
            ExecutionPlan with structured steps
        """
        start = time.time()
        self._new_planner_session()
        
        user_msg = f"Task: {goal}\n\nAnalyze the codebase and produce a structured execution plan (JSON)."
        self._planner_messages.append({"role": "user", "content": user_msg})
        
        if llm_call_fn:
            response = await llm_call_fn(
                self._planner_messages,
                tools=self._read_only_tools(),
                max_steps=self.planner_max_steps,
            )
            plan = self._parse_plan(response)
        else:
            # Placeholder: produce a simple plan
            plan = self._default_plan(goal)
        
        plan.planner_session_id = self._planner_session_id
        plan.planner_tokens = len(json.dumps(self._planner_messages)) // 4
        
        self.total_plans += 1
        elapsed = (time.time() - start) * 1000
        logger.info(f"Plan [{plan.plan_id}]: {len(plan.steps)} steps, "
                     f"{plan.estimated_complexity}, {elapsed:.0f}ms")
        
        return plan
    
    # ── Execution Phase ─────────────────────────────────────
    
    async def execute(self, plan: ExecutionPlan, llm_call_fn=None) -> ExecutionResult:
        """
        Run executor session against the plan.
        
        Args:
            plan: ExecutionPlan from plan()
            llm_call_fn: async fn(messages, tools, max_steps) -> response_text
        
        Returns:
            ExecutionResult with completion status
        """
        start = time.time()
        plan.status = PlanStatus.RUNNING
        self._new_executor_session(plan)
        
        user_msg = "Execute the plan above. Report completion status for each step."
        self._executor_messages.append({"role": "user", "content": user_msg})
        
        if llm_call_fn:
            response = await llm_call_fn(
                self._executor_messages,
                tools=self._all_tools(),
                max_steps=self.executor_max_steps,
            )
            result = self._parse_result(plan, response)
        else:
            result = ExecutionResult(
                plan_id=plan.plan_id,
                steps_completed=len(plan.steps),
                steps_total=len(plan.steps),
                verification="pass",
                output="[placeholder] All steps executed",
            )
        
        result.executor_tokens = len(json.dumps(self._executor_messages)) // 4
        result.total_tokens = plan.planner_tokens + result.executor_tokens
        result.elapsed_ms = (time.time() - start) * 1000
        
        if result.verification == "pass":
            plan.status = PlanStatus.DONE
        elif result.steps_completed > 0:
            plan.status = PlanStatus.PARTIAL
        else:
            plan.status = PlanStatus.FAILED
        
        logger.info(f"Execute [{plan.plan_id}]: {result.steps_completed}/{result.steps_total} "
                     f"steps, {result.verification}, {result.elapsed_ms:.0f}ms, "
                     f"{result.total_tokens} tokens")
        
        return result
    
    # ── Full Pipeline ───────────────────────────────────────
    
    async def run(self, goal: str, llm_call_fn=None) -> ExecutionResult:
        """Plan → Execute in one call. Returns ExecutionResult."""
        plan = await self.plan(goal, llm_call_fn)
        return await self.execute(plan, llm_call_fn)
    
    # ── Helpers ─────────────────────────────────────────────
    
    def _read_only_tools(self) -> List[str]:
        return sorted(READ_ONLY_TOOLS)
    
    def _all_tools(self) -> List[str]:
        return sorted(READ_ONLY_TOOLS | WRITE_TOOLS)
    
    def _parse_plan(self, response: str) -> ExecutionPlan:
        """Extract JSON plan from LLM response."""
        try:
            # Try to find JSON block
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group(0))
                steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
                return ExecutionPlan(
                    goal=data.get("goal", ""),
                    steps=steps,
                    estimated_complexity=data.get("estimated_complexity", "medium"),
                    risk_areas=data.get("risk_areas", []),
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse plan JSON: {e}")
        
        # Fallback: parse from text
        return self._default_plan(response[:200])
    
    def _parse_result(self, plan: ExecutionPlan, response: str) -> ExecutionResult:
        """Parse executor response into ExecutionResult."""
        result = ExecutionResult(
            plan_id=plan.plan_id,
            executor_session_id=self._executor_session_id,
            steps_total=len(plan.steps),
        )
        
        # Count [step-id] DONE markers
        import re
        done_matches = re.findall(r'\[([^\]]+)\]\s*(?:DONE|✅|✓)', response)
        result.steps_completed = len(done_matches)
        
        # Detect verification
        if re.search(r'(?:verification|result|outcome).*?(?:pass|success|ok)', response, re.IGNORECASE):
            result.verification = "pass"
        elif re.search(r'(?:verification|result|outcome).*?(?:fail|error)', response, re.IGNORECASE):
            result.verification = "fail"
        else:
            result.verification = "pass" if result.steps_completed >= len(plan.steps) else "partial"
        
        result.output = response
        return result
    
    def _default_plan(self, goal: str) -> ExecutionPlan:
        """Generate a default plan when LLM is unavailable."""
        return ExecutionPlan(
            goal=goal,
            steps=[
                PlanStep("step-1", "read", ".", "Analyze project structure", ""),
                PlanStep("step-2", "read", "README.md", "Read project documentation", ""),
                PlanStep("step-3", "write", "", "Implement changes for: " + goal, ""),
                PlanStep("step-4", "verify", "", "Test and verify changes", ""),
            ],
            estimated_complexity="medium",
            risk_areas=["unclear scope"],
        )
    
    # ── Stats ────────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Return engine statistics."""
        return {
            "total_plans": self.total_plans,
            "cache_hits": self.cache_hits,
            "planner_session": self._planner_session_id,
            "executor_session": self._executor_session_id,
            "planner_msgs": len(self._planner_messages),
            "executor_msgs": len(self._executor_messages),
            "planner_max_steps": self.planner_max_steps,
            "executor_max_steps": self.executor_max_steps,
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_dual_session: Optional[DualSessionEngine] = None


def get_dual_session(**kwargs) -> DualSessionEngine:
    """Get or create the global dual-session engine."""
    global _dual_session
    if _dual_session is None:
        _dual_session = DualSessionEngine(**kwargs)
    return _dual_session


def reset_dual_session():
    """Reset global instance (for testing)."""
    global _dual_session
    _dual_session = None

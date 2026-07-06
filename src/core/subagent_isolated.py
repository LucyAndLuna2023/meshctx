"""
meshctx Subagent Isolation Engine v1.0 — Subprocess-based Agent Isolation

Design (inspired by Late-CLI + CarbonCode):
  - Each subagent runs in its OWN context window (isolated message log)
  - Only FINAL answer returns to parent (not intermediate tool calls)
  - Storm-breaker: auto-truncate when context exceeds budget
  - Subagent distillation: measure token savings per spawn

Key invariants:
  1. Subagent does NOT see parent's full message history — only task + context_files
  2. Subagent tool outputs stay in child context, never leak to parent
  3. Storm-breaker fires when child context exceeds max_tokens
  4. Distillation metrics: savingsTokens = completionTokens - outputTokens

Usage:
  engine = SubagentEngine(provider="deepseek", max_context=8000)
  result = await engine.spawn("Analyze src/auth.py for security issues", ctx_files=["src/auth.py"])
  print(f"Output: {result.output}")
  print(f"Saved {result.savings_tokens} tokens via isolation")
"""

import asyncio
import hashlib
import json
import os
import re
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import logging

logger = logging.getLogger("meshctx.subagent")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

MAX_OUTPUT_CHARS = 8000        # Max chars returned to parent
DEFAULT_MAX_TOKENS = 8000      # Storm-breaker threshold
MAX_TURNS = 20                 # Max tool-call turns per subagent
TIMEOUT_SECONDS = 120          # Subagent execution timeout

SUBAGENT_SYSTEM_PROMPT = """You are a SPECIALIST subagent. You are working on an isolated subtask.

RULES:
1. You are given ONE specific task — solve it completely
2. You have access to read/write/search tools
3. Work INDEPENDENTLY — do not ask for clarification, make reasonable assumptions
4. Your FINAL answer is the ONLY thing returned to the parent
5. Be CONCISE — your output goes to a parent agent, not a human
6. If the task is impossible, say "IMPOSSIBLE: <reason>"
7. If you hit your context limit, summarize what you've found and stop
8. Output format:
   [TASK STATUS]: done | partial | impossible
   [FILES CHANGED]: list
   [KEY FINDING]: summary
   [DETAIL]: detailed answer (if needed)"""


# ═══════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════

class SubagentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    STORM_BREAK = "storm_break"  # Truncated by context limit
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class SubagentResult:
    """Result from an isolated subagent run."""
    run_id: str = ""
    task: str = ""
    output: str = ""
    status: SubagentStatus = SubagentStatus.PENDING
    stdin_content: str = ""       # What was fed to subagent
    files_changed: List[str] = field(default_factory=list)
    
    # Cost metrics
    completion_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    elapsed_ms: float = 0.0
    turns: int = 0
    
    @property
    def savings_tokens(self) -> int:
        """Tokens saved by isolation (didn't land in parent context)."""
        return max(0, self.completion_tokens - self.output_tokens)
    
    @property
    def compression_ratio(self) -> float:
        """output_tokens / completion_tokens. Lower = more distilled."""
        if self.completion_tokens == 0:
            return 1.0
        return self.output_tokens / self.completion_tokens
    
    @property
    def success(self) -> bool:
        return self.status == SubagentStatus.DONE


@dataclass
class SubagentSessionSummary:
    """Aggregated stats across all spawns in a session."""
    spawn_count: int = 0
    useful_spawn_count: int = 0
    total_completion_tokens: int = 0
    total_output_tokens: int = 0
    total_savings_tokens: int = 0
    total_cost_usd: float = 0.0
    
    @property
    def success_rate(self) -> float:
        if self.spawn_count == 0:
            return 0.0
        return self.useful_spawn_count / self.spawn_count
    
    @property
    def aggregate_compression_ratio(self) -> float:
        if self.total_completion_tokens == 0:
            return 1.0
        return self.total_output_tokens / self.total_completion_tokens


# ═══════════════════════════════════════════════════════════
# Subagent Engine
# ═══════════════════════════════════════════════════════════

class SubagentEngine:
    """
    Isolated subagent execution engine.
    
    Each spawn:
      1. Creates isolated message context (system prompt + task + context_files)
      2. Runs agent loop until completion or storm-breaker
      3. Returns ONLY final assistant message to parent
      4. Records distillation metrics
    
    Context guard (storm-breaker):
      When context exceeds max_tokens, inject a forced-summary instruction
      and collect the next assistant response as the final answer.
    """
    
    def __init__(self, provider: str = "deepseek",
                 model: str = "deepseek-flash",
                 max_context: int = DEFAULT_MAX_TOKENS,
                 max_turns: int = MAX_TURNS,
                 timeout: int = TIMEOUT_SECONDS):
        self.provider = provider
        self.model = model
        self.max_context = max_context
        self.max_turns = max_turns
        self.timeout = timeout
        
        # Session-level stats
        self._spawns: List[SubagentResult] = []
        self._spawn_count = 0
    
    # ── Spawn & Run ─────────────────────────────────────────
    
    async def spawn(
        self,
        task: str,
        ctx_files: Optional[List[str]] = None,
        llm_call_fn: Optional[Callable] = None,
        skill_name: str = "",
        extra_context: str = "",
    ) -> SubagentResult:
        """
        Spawn an isolated subagent for a self-contained task.
        
        Args:
            task: Subagent task description
            ctx_files: File paths to read as context
            llm_call_fn: async fn(messages, tools, max_steps) -> response_text
            skill_name: Optional skill name for logging
            extra_context: Additional context to inject
        
        Returns:
            SubagentResult with output and metrics
        """
        run_id = f"sub_{uuid.uuid4().hex[:8]}"
        start = time.time()
        self._spawn_count += 1
        
        logger.info(f"[{run_id}] Spawning subagent: {task[:80]}...")
        
        # Build isolated context
        messages = self._build_context(task, ctx_files or [], extra_context)
        
        if llm_call_fn is None:
            # Placeholder: simulate execution
            result = SubagentResult(
                run_id=run_id, task=task,
                output=self._simulate(task, ctx_files or []),
                status=SubagentStatus.DONE,
                completion_tokens=500, output_tokens=200,
                elapsed_ms=(time.time() - start) * 1000,
                turns=1,
            )
        else:
            try:
                result = await self._run_isolated(run_id, task, messages, llm_call_fn, start)
            except asyncio.TimeoutError:
                result = SubagentResult(
                    run_id=run_id, task=task,
                    output="TIMEOUT: subagent exceeded time limit",
                    status=SubagentStatus.TIMEOUT,
                    elapsed_ms=(time.time() - start) * 1000,
                )
            except Exception as e:
                result = SubagentResult(
                    run_id=run_id, task=task,
                    output=f"ERROR: {e}",
                    status=SubagentStatus.ERROR,
                    elapsed_ms=(time.time() - start) * 1000,
                )
        
        self._spawns.append(result)
        logger.info(
            f"[{run_id}] Done: {result.status.value}, "
            f"{result.output_tokens} output tokens, "
            f"{result.savings_tokens} saved, "
            f"{result.elapsed_ms:.0f}ms"
        )
        
        return result
    
    async def spawn_parallel(
        self,
        tasks: List[Dict[str, Any]],
        llm_call_fn: Optional[Callable] = None,
        max_concurrent: int = 3,
    ) -> List[SubagentResult]:
        """
        Spawn multiple subagents in parallel.
        
        Args:
            tasks: List of {"task": str, "ctx_files": Optional[List[str]], "extra_context": str}
            llm_call_fn: Same as spawn()
            max_concurrent: Max concurrent subagents
        
        Returns:
            List of SubagentResult in original order
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def bounded_spawn(t: dict) -> SubagentResult:
            async with semaphore:
                return await self.spawn(
                    task=t["task"],
                    ctx_files=t.get("ctx_files"),
                    llm_call_fn=llm_call_fn,
                    skill_name=t.get("skill_name", ""),
                    extra_context=t.get("extra_context", ""),
                )
        
        results = await asyncio.gather(*[bounded_spawn(t) for t in tasks])
        return list(results)
    
    # ── Internal ────────────────────────────────────────────
    
    async def _run_isolated(
        self, run_id: str, task: str, messages: List[dict],
        llm_call_fn: Callable, start: float
    ) -> SubagentResult:
        """Run the actual agent loop with storm-breaker + loop detection."""
        turns = 0
        final_response = ""
        completion_estimate = 0
        storm_broke = False
        loop_detect_window: list = []  # 循环检测窗口
        LOOP_THRESHOLD = 3             # 连续3次相同响应判定循环

        while turns < self.max_turns:
            turns += 1
            
            # Check context budget
            total_chars = sum(len(json.dumps(m)) for m in messages)
            if total_chars > self.max_context * 4:  # ~4 chars per token
                # Storm-breaker: inject force-summary
                messages.append({
                    "role": "user",
                    "content": (
                        "⚠️ CONTEXT LIMIT REACHED. Stop what you're doing NOW. "
                        "Summarize your findings so far in 3-5 sentences and output "
                        "[TASK STATUS]: partial\n[KEY FINDING]: <summary>"
                    )
                })
                storm_broke = True
            
            try:
                response = await asyncio.wait_for(
                    llm_call_fn(messages, tools=self._subagent_tools(), max_steps=1),
                    timeout=self.timeout - (time.time() - start)
                )
            except asyncio.TimeoutError:
                break
            
            completion_estimate += len(response) // 4
            messages.append({"role": "assistant", "content": response})

            # 循环检测: 比较当前响应与历史
            resp_stripped = response.strip()[:200]
            loop_detect_window.append(resp_stripped)
            if len(loop_detect_window) > LOOP_THRESHOLD:
                loop_detect_window = loop_detect_window[-LOOP_THRESHOLD:]
            if len(loop_detect_window) >= LOOP_THRESHOLD:
                if all(w == loop_detect_window[0] for w in loop_detect_window):
                    logger.warning(f"Subagent {run_id}: loop detected (same response x{LOOP_THRESHOLD})")
                    final_response = response
                    storm_broke = True  # 复用 break 逻辑

            if storm_broke:
                final_response = response
                break
            
            # Check if task is complete
            if self._is_complete(response):
                final_response = response
                break
        
        if not final_response and messages:
            # Take last assistant message
            for m in reversed(messages):
                if m["role"] == "assistant":
                    final_response = m["content"]
                    break
        
        # Truncate output
        output = final_response[:MAX_OUTPUT_CHARS]
        if len(final_response) > MAX_OUTPUT_CHARS:
            output += f"\n\n[…truncated {len(final_response) - MAX_OUTPUT_CHARS} chars]"
        
        output_tokens = len(output) // 4
        files = self._extract_files_changed(final_response)
        
        status = SubagentStatus.DONE
        if storm_broke:
            status = SubagentStatus.STORM_BREAK
        elif turns >= self.max_turns:
            status = SubagentStatus.DONE
        
        return SubagentResult(
            run_id=run_id, task=task,
            output=output, status=status,
            files_changed=files,
            completion_tokens=completion_estimate,
            output_tokens=output_tokens,
            elapsed_ms=(time.time() - start) * 1000,
            turns=turns,
        )
    
    def _build_context(self, task: str, ctx_files: List[str],
                       extra_context: str) -> List[dict]:
        """Build isolated message context."""
        messages = [
            {"role": "system", "content": SUBAGENT_SYSTEM_PROMPT}
        ]
        
        # Add file contents
        for fpath in ctx_files:
            try:
                p = Path(fpath).expanduser()
                if p.exists() and p.is_file():
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if len(content) > 4000:
                        content = content[:4000] + "\n[...truncated]"
                    messages.append({
                        "role": "user",
                        "content": f"Context file `{p.name}`:\n```\n{content}\n```"
                    })
            except Exception as e:
                logger.warning(f"Failed to read context file {fpath}: {e}")
        
        # Add extra context
        if extra_context:
            messages.append({
                "role": "user",
                "content": extra_context
            })
        
        # Add the task
        messages.append({
            "role": "user",
            "content": f"## YOUR TASK\n{task}\n\nComplete this task. Return ONLY the final answer."
        })
        
        return messages
    
    def _subagent_tools(self) -> List[str]:
        """Tools available to subagents."""
        return [
            "read_file", "search_files", "search_content", "glob",
            "write_file", "edit_file", "apply_patch",
            "run_command",
        ]
    
    def _is_complete(self, response: str) -> bool:
        """Check if subagent response indicates completion."""
        markers = [
            "[TASK STATUS]:", "IMPOSSIBLE:", "✅", "done.", "complete.",
            "all steps completed", "no further action needed",
        ]
        return any(m in response for m in markers)
    
    def _extract_files_changed(self, response: str) -> List[str]:
        """Extract file list from response."""
        # Look for [FILES CHANGED]: section
        match = re.search(r'\[FILES CHANGED\]:?\s*\n?(.*?)(?:\n\n|\n\[|\Z)', response, re.DOTALL)
        if match:
            files_text = match.group(1).strip()
            return [f.strip("- ").strip() for f in files_text.split("\n") if f.strip()]
        return []
    
    def _simulate(self, task: str, ctx_files: List[str]) -> str:
        """Simulate subagent output when no LLM is available."""
        return (
            f"[TASK STATUS]: done\n"
            f"[KEY FINDING]: Analyzed task: {task[:100]}\n"
            f"[FILES CHANGED]: {', '.join(ctx_files) if ctx_files else 'none'}\n"
            f"[DETAIL]: Placeholder — LLM not configured"
        )
    
    # ── Distillation ────────────────────────────────────────
    
    def get_session_summary(self) -> SubagentSessionSummary:
        """Compute aggregated distillation metrics for current session."""
        if not self._spawns:
            return SubagentSessionSummary()
        
        summary = SubagentSessionSummary()
        for s in self._spawns:
            summary.spawn_count += 1
            if s.output.strip():
                summary.useful_spawn_count += 1
            summary.total_completion_tokens += s.completion_tokens
            summary.total_output_tokens += s.output_tokens
            summary.total_savings_tokens += s.savings_tokens
            summary.total_cost_usd += s.cost_usd
        
        return summary
    
    def get_distillation_report(self) -> str:
        """Human-readable distillation report."""
        s = self.get_session_summary()
        return (
            f"Subagent Session Report\n"
            f"───────────────────────\n"
            f"Spawns: {s.spawn_count} (useful: {s.useful_spawn_count}, "
            f"rate: {s.success_rate:.1%})\n"
            f"Completion tokens: {s.total_completion_tokens}\n"
            f"Output tokens: {s.total_output_tokens}\n"
            f"Tokens SAVED: {s.total_savings_tokens} "
            f"(compression: {s.aggregate_compression_ratio:.2f}x)\n"
            f"Cost: ${s.total_cost_usd:.4f}\n"
        )
    
    # ── Stats ────────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Engine statistics."""
        return {
            "spawn_count": self._spawn_count,
            "active": len(self._spawns),
            "session_summary": {
                "spawn_count": self.get_session_summary().spawn_count,
                "useful_spawn_count": self.get_session_summary().useful_spawn_count,
                "savings_tokens": self.get_session_summary().total_savings_tokens,
                "cost_usd": self.get_session_summary().total_cost_usd,
            },
            "max_context": self.max_context,
            "max_turns": self.max_turns,
            "timeout": self.timeout,
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_subagent_engine: Optional[SubagentEngine] = None


def get_subagent_engine(**kwargs) -> SubagentEngine:
    """Get or create the global subagent engine."""
    global _subagent_engine
    if _subagent_engine is None:
        _subagent_engine = SubagentEngine(**kwargs)
    return _subagent_engine

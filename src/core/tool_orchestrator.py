"""Tool Orchestrator — 工具编排引擎 (v3.115.43)

Solves: "工具能选不能编排" — adds chaining, dependencies, fallback.
Routes tasks to optimal tool combinations, not just single tools."""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.observability import get_trace_logger

logger = logging.getLogger("meshctx.orchestrator")


# ── Tool registry ────────────────────────────────────────────

TOOL_CAPABILITIES = {
    "web_search": {"category": "search", "cost": "low", "tags": ["web", "info", "news"]},
    "web_extract": {"category": "search", "cost": "low", "tags": ["web", "extract", "read"]},
    "browser_navigate": {"category": "browser", "cost": "medium", "tags": ["web", "render"]},
    "read_file": {"category": "io", "cost": "low", "tags": ["file", "read", "local"]},
    "write_file": {"category": "io", "cost": "low", "tags": ["file", "write", "local"]},
    "search_files": {"category": "io", "cost": "low", "tags": ["file", "search", "local"]},
    "terminal": {"category": "exec", "cost": "high", "tags": ["shell", "exec", "dangerous"]},
    "remote_exec": {"category": "exec", "cost": "high", "tags": ["ssh", "remote", "dangerous"]},
    "remote_read": {"category": "io", "cost": "medium", "tags": ["ssh", "remote", "read"]},
    "remote_write": {"category": "io", "cost": "medium", "tags": ["ssh", "remote", "write"]},
}

# ── Orchestration patterns ────────────────────────────────────

ORCHESTRATION_PATTERNS = {
    # Pattern: (trigger_keywords, tool_sequence, description)
    "research_then_summarize": (
        ["research", "find", "search for", "look up", "查", "搜索"],
        ["web_search", "web_extract", "write_file"],
        "Search web → extract content → save results"
    ),
    "read_then_analyze": (
        ["read", "analyze file", "check file", "查看文件", "读"],
        ["read_file", "search_files"],
        "Read file → search for patterns"
    ),
    "code_then_test": (
        ["write code", "implement", "create script", "写代码", "实现"],
        ["write_file", "terminal"],
        "Write code → execute and test"
    ),
    "remote_deploy": (
        ["deploy", "upload", "push to server", "部署", "上传"],
        ["read_file", "remote_write", "remote_exec"],
        "Read local → upload → execute remotely"
    ),
    "info_gathering": (
        ["what is", "how to", "tell me about", "explain", "什么是", "怎么"],
        ["web_search", "web_extract"],
        "Search web → extract details"
    ),
}


class ToolOrchestrator:
    """Intelligent tool orchestration — chains tools for complex tasks."""

    def __init__(self):
        self._patterns = dict(ORCHESTRATION_PATTERNS)
        self._stats = {"orchestrated": 0, "single_tool": 0, "errors": 0}
        self._fallback_map: Dict[str, str] = {
            "web_search": "web_extract",
            "web_extract": "browser_navigate",
            "browser_navigate": "web_search",
        }
        self._trace = get_trace_logger()

    def plan(self, task: str, available_tools: List[str] = None) -> Dict[str, Any]:
        """Plan tool sequence for a task.

        Returns: {tools: [...], pattern: str, confidence: float, reasoning: str}
        """
        task_lower = task.lower()

        # Match orchestration patterns
        for pattern_name, (keywords, tools, desc) in self._patterns.items():
            if any(kw in task_lower for kw in keywords):
                # Filter to available tools
                plan_tools = [t for t in tools
                             if available_tools is None or t in available_tools]
                if len(plan_tools) >= 2:
                    self._stats["orchestrated"] += 1
                    return {
                        "tools": plan_tools,
                        "pattern": pattern_name,
                        "description": desc,
                        "confidence": 0.85,
                        "reasoning": f"Matched pattern '{pattern_name}': {desc}",
                    }

        # Single tool fallback
        self._stats["single_tool"] += 1
        # Pick best single tool by keyword match
        tool_scores = {}
        for tool, info in TOOL_CAPABILITIES.items():
            score = sum(1 for tag in info["tags"] if tag in task_lower)
            if score > 0:
                tool_scores[tool] = score

        if tool_scores:
            best = max(tool_scores, key=tool_scores.get)
            return {
                "tools": [best],
                "pattern": "single",
                "description": f"Use {best} directly",
                "confidence": 0.5,
                "reasoning": f"No pattern match, best single tool: {best}",
            }

        return {
            "tools": ["web_search"],
            "pattern": "default",
            "description": "Default web search",
            "confidence": 0.3,
            "reasoning": "No tool match found, defaulting to web_search",
        }

    def execute_plan(self, plan: Dict, tool_executor: Callable,
                     task: str) -> List[Dict]:
        """Execute a tool plan sequentially, with fallback."""
        results = []
        plan_span = self._trace.start_span(
            "chain", "ToolOrchestrator.execute_plan",
            inputs={"task": task[:200], "tools": plan.get("tools", [])})
        for tool_name in plan.get("tools", []):
            tool_span = self._trace.start_span(
                "tool", f"tool:{tool_name}",
                inputs={"task": task[:200]},
                parent_id=plan_span.span_id,
                trace_id=plan_span.trace_id)
            result = {"tool": tool_name, "output": "", "error": "", "fallback_used": False}
            try:
                output = tool_executor(tool_name, task)
                result["output"] = str(output)[:2000]
            except Exception as e:
                # Try fallback
                fallback = self._fallback_map.get(tool_name)
                if fallback:
                    try:
                        output = tool_executor(fallback, task)
                        result["output"] = str(output)[:2000]
                        result["fallback_used"] = True
                        result["fallback_tool"] = fallback
                    except Exception as e2:
                        result["error"] = str(e2)
                        self._stats["errors"] += 1
                        self._trace.error_span(tool_span, e2)
                        continue
                else:
                    result["error"] = str(e)
                    self._stats["errors"] += 1
                    self._trace.error_span(tool_span, e)
                    continue
            self._trace.end_span(tool_span, outputs=result)
            results.append(result)
        self._trace.end_span(plan_span,
                             outputs={"n_results": len(results)})
        return results

    def suggest_tools(self, task: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """Suggest best tools for a task (without chaining)."""
        task_lower = task.lower()
        scores = []
        for tool, info in TOOL_CAPABILITIES.items():
            score = sum(1 for tag in info["tags"] if tag in task_lower)
            score += sum(2 for kw, tools, _ in self._patterns.values()
                        if any(k in task_lower for k in kw) and tool in tools)
            if score > 0:
                scores.append((tool, min(score / 5.0, 1.0)))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    def stats(self) -> Dict:
        return dict(self._stats)

    def add_pattern(self, name: str, keywords: List[str],
                    tools: List[str], description: str = ""):
        """Register a new orchestration pattern."""
        self._patterns[name] = (keywords, tools, description)


# Singleton
_orchestrator: Optional[ToolOrchestrator] = None


def get_tool_orchestrator() -> ToolOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ToolOrchestrator()
    return _orchestrator

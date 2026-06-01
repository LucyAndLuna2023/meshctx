"""
MeshCtx Hooks System — Event-Driven Automation
================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Inspired by Claude Code's 8-event hook system:
- PreToolUse: block dangerous commands before execution
- PostToolUse: auto-format, lint, notify after tool use
- UserPromptSubmit: validate/transform user input
- Stop: trigger on agent response completion
- SessionStart: load project context on session begin
- PreCompact: backup before memory compaction
- Notification: desktop alerts on important events
- SubagentStop: orchestrate subagent results

License: Proprietary Core.
"""
import json
import ast
import os
import subprocess
import time
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
from enum import Enum


class HookEvent(Enum):
    USER_PROMPT = "user_prompt"        # Before processing user input
    PRE_TOOL = "pre_tool"              # Before tool execution
    POST_TOOL = "post_tool"            # After tool completes
    STOP = "stop"                      # Agent finishes response
    SESSION_START = "session_start"    # Session begins
    PRE_COMPACT = "pre_compact"        # Before memory compaction
    NOTIFICATION = "notification"      # Important event alert
    SUBAGENT_STOP = "subagent_stop"    # Subagent completes


@dataclass
class HookRule:
    event: HookEvent
    matcher: str = ""          # Pattern to match (tool name, keyword, regex)
    action: str = ""           # Shell command or Python callable name
    action_type: str = "command"  # command | python | notify
    enabled: bool = True
    priority: int = 0
    cooldown_s: float = 0      # Minimum seconds between triggers
    last_triggered: float = 0


@dataclass
class HookContext:
    event: HookEvent
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_output: str = ""
    user_message: str = ""
    agent_response: str = ""
    session_id: str = ""
    project_dir: str = ""
    timestamp: float = field(default_factory=time.time)
    env: dict = field(default_factory=dict)


class HooksEngine:
    """Event-driven automation engine with 8 hook types.

    Configure hooks via JSON file or API. Each hook has:
    - event: when to fire
    - matcher: pattern to filter (tool name, regex, keyword)
    - action: shell command or Python function
    - cooldown: prevent spam
    """

    def __init__(self, config_path: str = ""):
        home = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
        self.config_path = Path(config_path) if config_path else home / "hooks.json"
        self.rules: List[HookRule] = []
        self.execution_log: List[Dict] = []
        self.total_fired = 0
        self.total_blocked = 0
        self._load()

    # ── Rule Management ──────────────────────────────────

    def add_rule(self, event: HookEvent, matcher: str, action: str,
                 action_type: str = "command", priority: int = 0,
                 cooldown_s: float = 0) -> HookRule:
        rule = HookRule(event=event, matcher=matcher, action=action,
                       action_type=action_type, priority=priority,
                       cooldown_s=cooldown_s)
        self.rules.append(rule)
        self._save()
        return rule

    def remove_rule(self, index: int) -> bool:
        if 0 <= index < len(self.rules):
            self.rules.pop(index)
            self._save()
            return True
        return False

    def list_rules(self) -> List[Dict]:
        return [
            {"index": i, "event": r.event.value, "matcher": r.matcher,
             "action": r.action[:80], "enabled": r.enabled,
             "last_triggered": r.last_triggered}
            for i, r in enumerate(self.rules)
        ]

    # ── Event Fire ───────────────────────────────────────

    def fire(self, event: HookEvent, context: HookContext) -> Dict:
        """Fire all matching hooks for an event.

        Returns: {"fired": N, "blocked": N, "results": [...]}
        """
        context.event = event
        results = []
        fired = 0
        blocked = 0

        matching = [r for r in self.rules
                   if r.event == event and r.enabled]

        # Sort by priority (higher = first)
        matching.sort(key=lambda r: -r.priority)

        for rule in matching:
            if not self._matches(rule, context):
                continue

            # Cooldown check
            if rule.cooldown_s > 0:
                if time.time() - rule.last_triggered < rule.cooldown_s:
                    continue

            rule.last_triggered = time.time()
            self.total_fired += 1
            fired += 1

            # Execute action
            try:
                result = self._execute(rule, context)
                results.append({"rule_index": self.rules.index(rule),
                              "action": rule.action[:80], "result": result})
                if result == "BLOCKED":
                    blocked += 1
                    self.total_blocked += 1
            except Exception as e:
                results.append({"rule_index": self.rules.index(rule),
                              "action": rule.action[:80], "error": str(e)})

        self._log_execution(event, context, fired, blocked)
        return {"fired": fired, "blocked": blocked, "results": results}

    def _matches(self, rule: HookRule, context: HookContext) -> bool:
        """Check if rule matches the context."""
        if not rule.matcher:
            return True

        matcher = rule.matcher.lower()

        # Exact match
        if context.tool_name and matcher == context.tool_name.lower():
            return True

        # Substring match: "Bash" matches "Bash(git status)"
        if context.tool_name and matcher in context.tool_name.lower():
            return True

        # Wildcard match: Bash(git *) -> pattern Bash\(git .*\)
        if "*" in matcher:
            pattern = matcher.replace("(", "\\(").replace(")", "\\)")
            pattern = pattern.replace("*", ".*")
            pattern = "^" + pattern + "$"
            target = context.tool_name or ""
            if re.search(pattern, target, re.IGNORECASE):
                return True
            # Also try matching against user_message
            if context.user_message and re.search(pattern.replace("^","").replace("$",""),
                                                    context.user_message, re.IGNORECASE):
                return True

        # Content match in tool_input or user_message
        text_to_check = ""
        if context.tool_input:
            text_to_check = json.dumps(context.tool_input)
        if context.user_message:
            text_to_check += " " + context.user_message

        if text_to_check and matcher in text_to_check.lower():
            return True

        return False

    def _execute(self, rule: HookRule, context: HookContext) -> str:
        """Execute hook action. Return "BLOCKED" to prevent tool execution."""
        env = os.environ.copy()
        env["MESHCTX_TOOL_NAME"] = context.tool_name
        env["MESHCTX_TOOL_INPUT"] = json.dumps(context.tool_input)[:1000]
        env["MESHCTX_USER_MESSAGE"] = context.user_message[:500]
        env["MESHCTX_SESSION_ID"] = context.session_id
        env["MESHCTX_PROJECT_DIR"] = context.project_dir

        if rule.action_type == "command":
            try:
                proc = subprocess.run(
                    rule.action, shell=True, capture_output=True,
                    text=True, timeout=10, env=env,
                    cwd=context.project_dir or None
                )
                if proc.returncode == 2:  # Convention: exit 2 = BLOCK
                    return "BLOCKED"
                return proc.stdout[:500] or "OK"
            except subprocess.TimeoutExpired:
                return "TIMEOUT"
            except Exception as e:
                return f"ERROR: {e}"

        elif rule.action_type == "notify":
            print(f"🔔 [HOOK] {rule.action}")
            return "NOTIFIED"

        elif rule.action_type == "python":
            # Execute simple Python expression
            try:
                result = ast.literal_eval(rule.action) if hasattr(ast, 'literal_eval') else json.loads(rule.action)
                return str(result)[:500]
            except Exception as e:
                return f"ERROR: {e}"

        return "UNKNOWN_ACTION_TYPE"

    # ── Built-in Security Rules ───────────────────────────

    def enable_security_defaults(self):
        """Enable recommended security hooks."""
        defaults = [
            (HookEvent.PRE_TOOL, "Bash(*rm -rf *)",
             'echo "$MESHCTX_TOOL_INPUT" | grep -q "rm -rf" && exit 2 || exit 0',
             "command", 100),
            (HookEvent.PRE_TOOL, "Bash(*git push*--force*)",
             'echo "$MESHCTX_TOOL_INPUT" | grep -q "force" && exit 2 || exit 0',
             "command", 100),
            (HookEvent.PRE_TOOL, "Bash(*curl*|*bash*)",
             'echo "$MESHCTX_TOOL_INPUT" | grep -qE "(curl|wget).*\\|.*(bash|sh)" && exit 2 || exit 0',
             "command", 100),
            (HookEvent.POST_TOOL, "Write(*.py)",
             "ruff check --fix $MESHCTX_PROJECT_DIR 2>/dev/null || true",
             "command", 10, 5.0),
            (HookEvent.SESSION_START, "",
             'echo "Session started: $(date)"',
             "command", 0),
        ]
        for event, matcher, action, atype, pri, *cd in defaults:
            cd_val = cd[0] if cd else 0
            self.add_rule(event, matcher, action, atype, pri, cd_val)
        self._save()

    # ── Persistence ───────────────────────────────────────

    def _load(self):
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text())
                for r in data.get("rules", []):
                    self.rules.append(HookRule(
                        event=HookEvent(r["event"]),
                        matcher=r.get("matcher", ""),
                        action=r.get("action", ""),
                        action_type=r.get("action_type", "command"),
                        enabled=r.get("enabled", True),
                        priority=r.get("priority", 0),
                        cooldown_s=r.get("cooldown_s", 0),
                    ))
            except Exception:
                pass

    def _save(self):
        data = {
            "version": 1,
            "rules": [
                {"event": r.event.value, "matcher": r.matcher,
                 "action": r.action, "action_type": r.action_type,
                 "enabled": r.enabled, "priority": r.priority,
                 "cooldown_s": r.cooldown_s}
                for r in self.rules
            ]
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, indent=2))

    def _log_execution(self, event, context, fired, blocked):
        self.execution_log.append({
            "timestamp": time.time(),
            "event": event.value,
            "fired": fired,
            "blocked": blocked,
            "tool": context.tool_name,
        })
        if len(self.execution_log) > 500:
            self.execution_log = self.execution_log[-200:]

    def get_stats(self) -> Dict:
        return {
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules if r.enabled),
            "total_fired": self.total_fired,
            "total_blocked": self.total_blocked,
            "rules_by_event": {
                e.value: sum(1 for r in self.rules if r.event == e)
                for e in HookEvent
            },
            "recent_executions": self.execution_log[-10:],
        }


# ── Singleton ───────────────────────────────────────────────

_global_hooks: Optional[HooksEngine] = None


def get_hooks() -> HooksEngine:
    global _global_hooks
    if _global_hooks is None:
        _global_hooks = HooksEngine()
    return _global_hooks

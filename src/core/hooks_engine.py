"""meshctx hooks_engine — full HookSystem + HooksEngine implementation"""
import uuid
import time
import re
import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List, Callable


# ═══════════════════════════════════════════════════════════
# HookEvent — 7 unique events (+ aliases for v42 compat)
# ═══════════════════════════════════════════════════════════

class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    PRE_TOOL = "pre_tool_use"       # alias — won't iterate
    PRE_DECISION = "pre_decision"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL = "post_tool_use"     # alias
    STOP = "stop"
    SESSION_START = "session_start"
    USER_PROMPT = "user_prompt"
    SUBAGENT_STOP = "subagent_stop"


# ═══════════════════════════════════════════════════════════
# HookContext — context passed to hook callbacks
# ═══════════════════════════════════════════════════════════

@dataclass
class HookContext:
    event: HookEvent = HookEvent.SESSION_START
    tool_name: str = ""
    user_message: str = ""
    session_id: str = ""
    tool_input: Optional[Dict] = None
    hook_id: str = ""
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# HookRule — individual rule for HooksEngine (v42 compat)
# ═══════════════════════════════════════════════════════════

@dataclass
class HookRule:
    event: HookEvent
    matcher: str = ""
    action: str = "echo"
    priority: int = 0
    last_triggered: float = 0.0
    cooldown_s: float = 0.0


# ═══════════════════════════════════════════════════════════
# HookResult — returned by HookSystem.fire_event
# ═══════════════════════════════════════════════════════════

@dataclass
class HookResult:
    allowed: bool = True
    blocked_by: Optional[str] = None
    modified_context: dict = field(default_factory=dict)
    hooks_fired: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # legacy fields kept for compatibility
    modified: bool = False
    reason: str = ""
    modified_payload: Any = None

    def to_dict(self):
        return {
            "allowed": self.allowed,
            "blocked_by": self.blocked_by,
            "modified_context": self.modified_context,
            "hooks_fired": self.hooks_fired,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════
# HookSystem — singleton, thread-safe hook registry + fire
# ═══════════════════════════════════════════════════════════

class HookSystem:
    """Singleton hook system used by modern test suite (test_hooks_engine.py)."""

    _instance: Optional["HookSystem"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._hooks: Dict[str, dict] = {}
        self._data_lock = threading.Lock()
        self.reset_stats()

    # ── event validation ──────────────────────────────────

    @staticmethod
    def _validate_event(event):
        if isinstance(event, HookEvent):
            return event
        try:
            return HookEvent(event)
        except (ValueError, KeyError):
            raise ValueError("无效的事件类型")

    # ── CRUD ──────────────────────────────────────────────

    def register_hook(self, event, callback, priority=0, name=""):
        event = self._validate_event(event)
        hook_id = str(uuid.uuid4())
        with self._data_lock:
            self._hooks[hook_id] = {
                "hook_id": hook_id,
                "event": event,
                "callback": callback,
                "priority": priority,
                "name": name,
                "enabled": True,
            }
            ev_key = event.value
            if ev_key not in self._stats["hooks_by_event"]:
                self._stats["hooks_by_event"][ev_key] = []
            self._stats["hooks_by_event"][ev_key].append(hook_id)
        return hook_id

    def unregister_hook(self, hook_id):
        with self._data_lock:
            if hook_id not in self._hooks:
                return False
            hook = self._hooks.pop(hook_id)
            ev_key = hook["event"].value
            lst = self._stats["hooks_by_event"].get(ev_key, [])
            if hook_id in lst:
                lst.remove(hook_id)
            return True

    def get_hook(self, hook_id):
        return self._hooks.get(hook_id, None)

    def list_hooks(self, event=None):
        if event is not None:
            event = self._validate_event(event)
            return sorted(
                [h.copy() for h in self._hooks.values() if h["event"] == event],
                key=lambda h: h["priority"], reverse=True,
            )
        return list(self._hooks.values())

    def enable_hook(self, hook_id):
        if hook_id in self._hooks:
            self._hooks[hook_id]["enabled"] = True

    def disable_hook(self, hook_id):
        if hook_id in self._hooks:
            self._hooks[hook_id]["enabled"] = False

    # ── fire ──────────────────────────────────────────────

    def fire_event(self, event, payload):
        event = self._validate_event(event)

        result = HookResult(
            modified_context=payload.copy() if isinstance(payload, dict) else {}
        )

        with self._data_lock:
            self._stats["total_events_fired"] += 1
            hooks = sorted(
                [h for h in self._hooks.values()
                 if h["event"] == event and h["enabled"]],
                key=lambda h: h["priority"], reverse=True,
            )

        context = payload.copy() if isinstance(payload, dict) else payload

        for hook in hooks:
            result.hooks_fired.append(hook["hook_id"])
            with self._data_lock:
                self._stats["total_hooks_triggered"] += 1
            try:
                hook_result = hook["callback"](context)
            except Exception:
                result.warnings.append(
                    f"Hook '{hook['name']}' threw an exception"
                )
                continue

            # hook returned None → skip
            if hook_result is None:
                continue

            # hook returned dict → process allow / warning / modified_context
            if isinstance(hook_result, dict):
                if hook_result.get("allow") is False:
                    result.allowed = False
                    result.blocked_by = hook["name"]
                    reason = hook_result.get("reason", "")
                    if reason:
                        result.warnings.append(reason)
                    with self._data_lock:
                        self._stats["total_blocks"] += 1
                    break  # block chain — stop processing lower-priority hooks

                warning = hook_result.get("warning")
                if warning is not None:
                    result.warnings.append(warning)

                mc = hook_result.get("modified_context")
                if mc:
                    result.modified_context.update(mc)

            # hook returned HookResult object
            elif isinstance(hook_result, HookResult):
                if not hook_result.allowed:
                    result.allowed = False
                    result.blocked_by = hook["name"]
                    if hook_result.reason:
                        result.warnings.append(hook_result.reason)
                    with self._data_lock:
                        self._stats["total_blocks"] += 1
                    break
                result.modified_context.update(hook_result.modified_context)
                result.warnings.extend(hook_result.warnings)

        return result

    # ── stats ─────────────────────────────────────────────

    def reset_stats(self):
        self._stats = {
            "total_events_fired": 0,
            "total_hooks_triggered": 0,
            "total_blocks": 0,
            "hooks_by_event": {},
        }

    def get_stats(self):
        return dict(self._stats)


# ═══════════════════════════════════════════════════════════
# HooksEngine — legacy engine for v42 test suite
# ═══════════════════════════════════════════════════════════

class HooksEngine:
    """Legacy hooks engine used by v42 tests (test_v42_hooks.py)."""

    def __init__(self, config_path=None, **kw):
        self.config_path = config_path
        self.rules: List[HookRule] = []
        self._loaded = False
        self._load()

    # ── rules management ──────────────────────────────────

    def add_rule(self, event, matcher, action, rule_type="command", priority=0,
                 cooldown_s=0):
        r = HookRule(
            event=event,
            matcher=matcher,
            action=action,
            priority=priority,
            cooldown_s=cooldown_s,
        )
        self.rules.append(r)
        return r

    def remove_rule(self, index):
        if 0 <= index < len(self.rules):
            self.rules.pop(index)
            return True
        return False

    def list_rules(self):
        return [
            {
                "index": i,
                "event": r.event.value,
                "matcher": r.matcher,
                "action": r.action,
                "priority": r.priority,
            }
            for i, r in enumerate(self.rules)
        ]

    # ── fire ──────────────────────────────────────────────

    def fire(self, event, context):
        result = {"fired": 0, "blocked": 0}
        tool_name = getattr(context, 'tool_name', '')

        for rule in self.rules:
            if rule.event != event:
                continue

            # cooldown check
            if rule.cooldown_s > 0 and rule.last_triggered > 0:
                if time.time() - rule.last_triggered < rule.cooldown_s:
                    continue

            # match matcher against tool_name (glob-style *)
            if not self._match_tool(rule.matcher, tool_name):
                continue

            rule.last_triggered = time.time()
            result["fired"] += 1

            # "exit N" action means block
            if isinstance(rule.action, str) and rule.action.startswith("exit "):
                result["blocked"] += 1

        return result

    @staticmethod
    def _match_tool(matcher, tool_name):
        if not matcher:
            return True
        # escape regex special chars, then convert \* back to .*
        escaped = re.escape(matcher).replace(r"\*", ".*")
        return bool(re.search(escaped, tool_name))

    # ── security defaults ─────────────────────────────────

    def enable_security_defaults(self):
        self.add_rule(HookEvent.PRE_TOOL, "Bash(*rm -rf *)", "exit 2",
                       "command", 100)
        self.add_rule(HookEvent.PRE_TOOL, "Bash(*format *)", "exit 2",
                       "command", 100)
        self.add_rule(HookEvent.PRE_TOOL, "Bash(*dd if=*)", "exit 2",
                       "command", 90)
        self.add_rule(HookEvent.PRE_TOOL, "Bash(*curl*|*bash*)", "exit 2",
                       "command", 90)
        self.add_rule(HookEvent.PRE_TOOL, "Bash(*git push*force*)", "exit 2",
                       "command", 90)

    # ── persistence ───────────────────────────────────────

    def _save(self):
        if not self.config_path:
            return
        data = []
        for r in self.rules:
            data.append({
                "event": r.event.value,
                "matcher": r.matcher,
                "action": r.action,
                "priority": r.priority,
            })
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(data, f)

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not self.config_path or not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path) as f:
                data = json.load(f)
            for item in data:
                self.rules.append(HookRule(
                    event=HookEvent(item["event"]),
                    matcher=item.get("matcher", ""),
                    action=item.get("action", ""),
                    priority=item.get("priority", 0),
                ))
        except Exception:
            pass

    # ── stats ─────────────────────────────────────────────

    def get_stats(self):
        by_event: Dict[str, int] = {}
        for r in self.rules:
            ev = r.event.value
            by_event[ev] = by_event.get(ev, 0) + 1
        return {"total_rules": len(self.rules), "rules_by_event": by_event}


# ═══════════════════════════════════════════════════════════
# Module-level singletons + helpers
# ═══════════════════════════════════════════════════════════

_hook_system: Optional[HookSystem] = None
_hooks_engine: Optional[HooksEngine] = None


def get_hook_system() -> HookSystem:
    global _hook_system
    if _hook_system is None:
        _hook_system = HookSystem()
    return _hook_system


def get_hooks() -> HooksEngine:
    global _hooks_engine
    if _hooks_engine is None:
        _hooks_engine = HooksEngine()
    return _hooks_engine


def reset_hook_system():
    global _hook_system, _hooks_engine
    HookSystem._instance = None  # reset the class-level singleton
    _hook_system = None
    _hooks_engine = None


# ═══════════════════════════════════════════════════════════
# Built-in security hooks (functions, not classes)
# ═══════════════════════════════════════════════════════════

_rated: Dict[str, int] = {}


def _reset_rate_limit_state():
    global _rated
    _rated.clear()


def _builtin_block_destructive_commands(context):
    """Return {"allow": False, "reason": ...} for dangerous commands."""
    text = ""
    if isinstance(context, dict):
        text = (str(context.get("command", "")) + " " +
                str(context.get("tool_name", "")))
    else:
        text = str(context)

    tlower = text.lower()

    if "rm -rf" in text:
        return {"allow": False, "reason": "Blocked: rm command"}
    if "format" in tlower:
        return {"allow": False, "reason": "Blocked: format command"}
    if "curl" in text and "|" in text and ("bash" in tlower or "sh" in tlower):
        return {"allow": False, "reason": "Blocked: curl | bash"}
    if "git" in text and "push" in text and "force" in text:
        return {"allow": False, "reason": "Blocked: git push --force"}

    return {"allow": True}


def _builtin_prevent_credential_leak(context):
    """Return {"allow": True, "warning": ...} for credential leaks."""
    text = ""
    if isinstance(context, dict):
        text = (str(context.get("output", "")) + " " +
                str(context.get("result", "")) + " " +
                str(context.get("tool_name", "")))
    else:
        text = str(context)

    sensitive = ["api_key", "API_KEY", "sk-", "eyJ", "Bearer",
                 "token", "secret", "password"]

    for s in sensitive:
        if s in text:
            return {"allow": True, "warning": "凭证泄露检测"}

    return {"allow": True, "warning": None}


def _builtin_rate_limit_guard(context):
    """Return {"allow": False, "reason": ..., "metadata": ...} over limit."""
    global _rated
    tool_name = "unknown"
    event_name = "unknown"
    if isinstance(context, dict):
        tool_name = context.get("tool_name", "unknown")
        event_name = context.get("_event", "unknown")
    key = f"{tool_name}:{event_name}"

    _rated[key] = _rated.get(key, 0) + 1
    current = _rated[key]

    if current > 10:
        return {
            "allow": False,
            "reason": "速率限制",
            "metadata": {"current_rate": current},
        }
    return {
        "allow": True,
        "metadata": {"current_rate": current},
    }


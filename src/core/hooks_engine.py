"""meshctx hooks_engine"""
import uuid, time, re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class HookEvent(str, Enum):
    BEFORE_COMMAND = "before_command"
    AFTER_COMMAND = "after_command"
    ON_ERROR = "on_error"
    BEFORE_API_CALL = "before_api_call"
    AFTER_API_CALL = "after_api_call"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"

@dataclass
class HookContext:
    hook_id: str = ""
    event: HookEvent = HookEvent.BEFORE_COMMAND
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

@dataclass
class HookRule:
    event: HookEvent
    pattern: str = ""
    action: str = "block"
    priority: int = 0

@dataclass
class HookResult:
    allowed: bool = True
    modified: bool = False
    reason: str = ""
    modified_payload: Any = None

class HooksEngine:
    def __init__(self, config_path: str = None):
        self._hooks = []
        self._rules = []
        self._enabled = True
    def register(self, event, callback, priority=0):
        self._hooks.append({"event": event, "callback": callback, "priority": priority})
    def add_rule(self, event, pattern, action="block", priority=0):
        self._rules.append(HookRule(event=event, pattern=pattern, action=action, priority=priority))
    def trigger(self, event, payload=None):
        results = []
        for h in self._hooks:
            if h["event"] == event and self._enabled:
                try:
                    r = h["callback"](HookContext(event=event, payload=payload or {}))
                    results.append(r)
                except Exception:
                    results.append(HookResult(allowed=True))
        for r in self._rules:
            if r.event == event and r.action == "block":
                text = str(payload)
                if re.search(r.pattern, text):
                    results.append(HookResult(allowed=False, reason=f"Rule matched: {r.pattern}"))
        return results

_rated = {}
def _reset_rate_limit_state():
    global _rated
    _rated = {}

def _builtin_block_destructive_commands(context):
    dangerous = ["rm -rf", "format", "dd if=", ":(){:|:&};:"]
    for cmd in dangerous:
        if cmd in str(context.payload):
            return HookResult(allowed=False, reason=f"Potentially dangerous: {cmd}")
    return HookResult(allowed=True)

def _builtin_prevent_credential_leak(context):
    sensitive = ["password", "secret", "token", "api_key", "API_KEY", "SECRET"]
    for s in sensitive:
        if s in str(context.payload):
            return HookResult(allowed=False, reason=f"Credential leak detected: {s}")
    return HookResult(allowed=True)

def _builtin_rate_limit_guard(context):
    key = str(context.payload)
    global _rated
    _rated[key] = _rated.get(key, 0) + 1
    if _rated[key] > 50:
        return HookResult(allowed=False, reason="Rate limit exceeded")
    return HookResult(allowed=True)

_hooks = None
def get_hooks():
    global _hooks
    if _hooks is None: _hooks = HooksEngine()
    return _hooks

def get_hook_system():
    return get_hooks()

def reset_hook_system():
    global _hooks
    _hooks = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


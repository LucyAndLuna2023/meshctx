"""meshctx smart_permissions — ML-driven permission learning"""

import fnmatch
from enum import Enum


class Permission(Enum):
    """Permission decision levels."""
    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"
    AUTO_ALLOW = "auto_allow"


class SmartPermissions:
    """Learns permission patterns from user decisions.

    Tracks action approvals/denials and auto-approves
    actions that pass a configurable confidence threshold.
    """

    UNSAFE_PATTERNS = [
        "rm -rf *",
        "rm -rf /*",
        "rm -rf /",
        "sudo rm*",
        "dd if=*",
        "mkfs.*",
        ":(){ :|:& };:",
        "chmod 777 /*",
        "> /dev/sda*",
    ]

    def __init__(self):
        self._action_history = {}  # action -> [True/False, ...]
        self._rules = {}  # pattern -> Permission
        self._auto_approve_threshold = 3
        self._total_decisions = 0

    def check(self, action):
        """Check what permission level an action deserves."""
        for pattern, perm in self._rules.items():
            if fnmatch.fnmatch(action, pattern):
                return perm
        history = self._action_history.get(action, [])
        if len(history) >= self._auto_approve_threshold and all(history):
            return Permission.AUTO_ALLOW
        return Permission.ASK

    def learn(self, action, approved):
        """Learn from a user's decision on an action."""
        if action not in self._action_history:
            self._action_history[action] = []
        self._action_history[action].append(approved)
        self._total_decisions += 1

    def add_rule(self, pattern, permission):
        """Add an explicit permission rule (glob pattern)."""
        self._rules[pattern] = permission

    def is_safe(self, action):
        """Heuristic safety check for a command/action."""
        for pattern in self.UNSAFE_PATTERNS:
            if fnmatch.fnmatch(action, pattern):
                return False
        return True

    def get_stats(self):
        """Return permission learning statistics."""
        return {
            "total_decisions": self._total_decisions,
            "tracked_actions": len(self._action_history),
            "explicit_rules": len(self._rules),
            "auto_approve_threshold": self._auto_approve_threshold,
        }


_sp = None


def get_smart_permissions():
    """Singleton accessor for SmartPermissions."""
    global _sp
    if _sp is None:
        _sp = SmartPermissions()
    return _sp

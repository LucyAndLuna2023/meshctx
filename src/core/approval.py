"""
Command Approval Engine with YOLO mode support.

Provides three approval modes (manual/smart/off) with dangerous command
detection via regex patterns and risk-level classification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ApprovalResult:
    """Result of an approval check for a command."""

    requires_approval: bool
    action: str  # "allow", "prompt", "block"
    reason: str
    risk_level: str  # "low", "medium", "high", "critical"


# ---------------------------------------------------------------------------
# Danger pattern registry
# Each entry: (compiled_regex, risk_level, label)
# Order matters: more specific / higher-severity patterns first.
# ---------------------------------------------------------------------------

_DANGER_PATTERNS: List[Tuple[re.Pattern, str, str]] = []


def _register(pattern: str, risk_level: str, label: str) -> None:
    _DANGER_PATTERNS.append((re.compile(pattern, re.IGNORECASE), risk_level, label))


# --- CRITICAL: irreversible system / data destruction ---
_register(r"\brm\s+-rf\s+/", "critical", "destructive deletion of root")
_register(r"\brm\s+-rf\s+\S*\*\S*", "critical", "destructive wildcard deletion")
_register(r"\bdd\s+if=", "critical", "direct disk write (dd)")
_register(r"\bmkfs\.", "critical", "filesystem format (mkfs)")
_register(r":\(\)\s*\{.*:\|:&.*\};:", "critical", "fork bomb detected")
_register(r"\bDROP\s+TABLE\b", "critical", "SQL DROP TABLE — irreversible data loss")
_register(r"\bTRUNCATE\s+TABLE\b", "critical", "SQL TRUNCATE TABLE — data wipe")
_register(r"\bshutdown\b", "critical", "system shutdown")
_register(r"\breboot\b", "critical", "system reboot")
_register(r"\bhalt\b", "critical", "system halt")

# --- HIGH: dangerous but potentially scoped ---
_register(r"\brm\s+-rf\b", "high", "recursive force removal (rm -rf)")
_register(
    r"\bcurl\b.*\|\s*(?:bash|sh|zsh)\b", "high", "curl piped to shell interpreter"
)
_register(
    r"\bwget\b.*\|\s*(?:bash|sh|zsh)\b", "high", "wget piped to shell interpreter"
)
_register(
    r"\bchmod\s+.*777\s+/", "high", "world-writable permissions on root (chmod 777 /)"
)
_register(r"\bchmod\s+-R\s+777\b", "high", "recursive world-writable permissions")

# --- MEDIUM: potentially dangerous but recoverable ---
_register(r"\bgit\s+push\s+.*--force", "medium", "git force push")
_register(r"\bgit\s+reset\s+--hard\b", "medium", "git hard reset")
_register(r"\bchmod\s+777\b", "medium", "world-writable permissions (chmod 777)")


# ---------------------------------------------------------------------------
# Safe command patterns (explicit allowlist for manual/smart low-risk)
# ---------------------------------------------------------------------------

_SAFE_PATTERNS: List[re.Pattern] = [
    re.compile(p)
    for p in [
        r"^(ls|dir|echo|cat|head|tail|less|more|wc|file|stat)\b",
        r"^(cd|pwd|which|type|whereis|whoami|id|date|time|env|printenv)\b",
        r"^(cp|mv|mkdir|touch|ln)\b",
        r"^(grep|egrep|fgrep|find|locate|sort|uniq|cut|tr|sed|awk)\b",
        r"^(python\d*|python|py|pip\d*|pip|pip3|node|npm|yarn|cargo|go|rustc)\b",
        r"^(git\s+status|git\s+log|git\s+diff|git\s+branch|git\s+remote|git\s+stash)\b",
        r"^(git\s+add|git\s+commit|git\s+checkout|git\s+merge|git\s+pull|git\s+fetch|git\s+clone)\b",
        r"^(docker|kubectl|systemctl|service)\b",
        r"^(ssh|scp|rsync)\b",
        r"^(curl|wget)\b",
        r"^(ping|traceroute|netstat|ss|ip|ifconfig)\b",
        r"^(df|du|free|top|ps|htop|uptime)\b",
        r"^(tar|zip|unzip|gzip|gunzip|bzip2|bunzip2|xz|7z)\b",
        r"^(man|info|help|whatis|apropos)\b",
        r"^(source|\.)\s",
        r"^(make|cmake|gcc|g\+\+|clang)\b",
    ]
]


class ApprovalEngine:
    """Command approval engine with three modes and YOLO override.

    Modes:
      - manual  : every dangerous command requires approval
      - smart   : low-risk auto-pass, high-risk prompt, critical block
      - off     : never requires approval (YOLO)
    """

    def __init__(self, mode: str = "manual", yolo: bool = False) -> None:
        self._mode = mode
        self._yolo = yolo

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def yolo(self) -> bool:
        return self._yolo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Switch approval mode at runtime."""
        if mode not in ("manual", "smart", "off"):
            raise ValueError(f"Unknown approval mode: {mode!r}")
        self._mode = mode

    def check(self, command: str) -> ApprovalResult:
        """Check *command* and return an ApprovalResult."""
        # YOLO always wins
        if self._yolo:
            return ApprovalResult(
                requires_approval=False,
                action="allow",
                reason="YOLO mode enabled — all commands allowed.",
                risk_level="low",
            )

        # Determine if the command matches a danger pattern
        matched_risk: str | None = None
        matched_label: str | None = None
        for pattern, risk_level, label in _DANGER_PATTERNS:
            if pattern.search(command):
                matched_risk = risk_level
                matched_label = label
                break

        # ------------------------------------------------------------------
        # Manual mode — prompt on any danger; safe commands allowed
        # ------------------------------------------------------------------
        if self._mode == "manual":
            if matched_risk is not None:
                return ApprovalResult(
                    requires_approval=True,
                    action="prompt",
                    reason=f"Dangerous command detected: {matched_label}",
                    risk_level=matched_risk,
                )
            return ApprovalResult(
                requires_approval=False,
                action="allow",
                reason="No dangerous patterns detected.",
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # Smart mode — graduated response
        # ------------------------------------------------------------------
        if self._mode == "smart":
            if matched_risk is None:
                return ApprovalResult(
                    requires_approval=False,
                    action="allow",
                    reason="No dangerous patterns detected — auto-approved.",
                    risk_level="low",
                )
            if matched_risk == "critical":
                return ApprovalResult(
                    requires_approval=True,
                    action="block",
                    reason=f"Critical operation blocked: {matched_label}",
                    risk_level=matched_risk,
                )
            # high / medium → prompt
            return ApprovalResult(
                requires_approval=True,
                action="prompt",
                reason=f"Dangerous command detected: {matched_label}",
                risk_level=matched_risk,
            )

        # ------------------------------------------------------------------
        # Off mode — never requires approval
        # ------------------------------------------------------------------
        return ApprovalResult(
            requires_approval=False,
            action="allow",
            reason="Approval engine is off.",
            risk_level=matched_risk if matched_risk else "low",
        )

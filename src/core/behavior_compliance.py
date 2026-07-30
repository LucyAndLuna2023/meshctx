"""
Behavior Compliance — Safety Rule Enforcement Engine
=====================================================
Enforces 6 safety rules on agent behavior. Each rule is independently
configurable with severity levels and automated violation tracking.

Six Safety Rules:
  1. NO_KEY_LEAK        — Never expose API keys, tokens, or secrets
  2. NO_DANGEROUS_CMD   — Never execute dangerous system commands
  3. NO_DATA_FABRICATION — Never fabricate data or hallucinate outputs
  4. NO_BYPASS_APPROVAL — Never bypass human approval gates
  5. NO_INFINITE_LOOP   — Never enter unbounded execution loops
  6. NO_DECEPTION       — Never deceive, mislead, or withhold critical info

Architecture:
  - Each rule has a compliance checker function.
  - Violations are logged with severity, context, and timestamp.
  - Audit trail for post-hoc review.
  - Rule engine supports hot-reloading of rule parameters.

References:
  - NIST AI RMF (AI Risk Management Framework)
  - ISO/IEC 42001 AI Management System
  - EU AI Act — High-Risk AI System Requirements
  - Anthropic Constitutional AI Principles

Usage:
  bc = BehaviorCompliance()
  bc.check("That key is sk-abc123def456", context="code_output")
"""

import re
import time
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Tuple
from collections import defaultdict

logger = logging.getLogger("meshctx.behavior_compliance")


# ═══════════════════════════════════════════════════════════════════
# Enums & Data Structures
# ═══════════════════════════════════════════════════════════════════

class ComplianceSeverity(Enum):
    """Violation severity levels."""
    INFO = auto()       # Advisory, not blocking
    WARNING = auto()    # Potentially problematic
    ERROR = auto()      # Rule violation, should block
    CRITICAL = auto()   # Immediate halt required

    def __str__(self) -> str:
        return self.name

    @property
    def numeric(self) -> int:
        return {ComplianceSeverity.INFO: 0, ComplianceSeverity.WARNING: 1,
                ComplianceSeverity.ERROR: 2, ComplianceSeverity.CRITICAL: 3}[self]


class RuleID(Enum):
    """Unique identifiers for the six safety rules."""
    NO_KEY_LEAK = "R001"
    NO_DANGEROUS_CMD = "R002"
    NO_DATA_FABRICATION = "R003"
    NO_BYPASS_APPROVAL = "R004"
    NO_INFINITE_LOOP = "R005"
    NO_DECEPTION = "R006"

    @property
    def label(self) -> str:
        labels = {
            RuleID.NO_KEY_LEAK: "No Key/Secret Leak",
            RuleID.NO_DANGEROUS_CMD: "No Dangerous Commands",
            RuleID.NO_DATA_FABRICATION: "No Data Fabrication",
            RuleID.NO_BYPASS_APPROVAL: "No Bypass Approval",
            RuleID.NO_INFINITE_LOOP: "No Infinite Loop",
            RuleID.NO_DECEPTION: "No Deception",
        }
        return labels[self]


@dataclass
class Violation:
    """A recorded compliance violation."""
    rule_id: RuleID
    severity: ComplianceSeverity
    message: str
    context: str                   # e.g., "code_output", "user_prompt", "tool_result"
    snippet: str                   # Excerpt of the violating content
    timestamp: float = field(default_factory=time.time)
    violation_id: str = ""         # Hash-based unique ID

    def __post_init__(self):
        if not self.violation_id:
            raw = f"{self.rule_id.value}:{self.snippet}:{self.timestamp}"
            self.violation_id = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ComplianceReport:
    """Aggregated compliance check report."""
    violations: List[Violation] = field(default_factory=list)
    rule_results: Dict[RuleID, bool] = field(default_factory=dict)
    passed: bool = True
    total_checks: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ComplianceSeverity.CRITICAL)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ComplianceSeverity.ERROR)


# ═══════════════════════════════════════════════════════════════════
# Rule Checkers
# ═══════════════════════════════════════════════════════════════════

# ── R001: No Key/Secret Leak ────────────────────────────────────

_KEY_PATTERNS: List[Tuple[str, Pattern, str]] = [
    ("openai_key", re.compile(r'sk-[A-Za-z0-9]{32,}'), "OpenAI API key"),
    ("openai_proj", re.compile(r'sk-proj-[A-Za-z0-9_-]{32,}'), "OpenAI project key"),
    ("anthropic_key", re.compile(r'sk-ant-[A-Za-z0-9_-]{32,}'), "Anthropic API key"),
    ("github_token", re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'), "GitHub token"),
    ("github_pat", re.compile(r'github_pat_[A-Za-z0-9_]{40,}'), "GitHub PAT"),
    ("aws_key", re.compile(r'AKIA[0-9A-Z]{16}'), "AWS access key"),
    ("aws_secret", re.compile(r'(?i)aws.{0,20}secret.{0,5}[=:]\s*[\'"]?[A-Za-z0-9\/+]{40}'), "AWS secret key"),
    ("generic_token", re.compile(r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*[\'"][^\'"]{8,}[\'"]', re.IGNORECASE), "Generic token/secret"),
    ("jwt_token", re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}'), "JWT token"),
    ("private_key", re.compile(r'-----BEGIN (?:RSA|EC|DSA|OPENSSH) PRIVATE KEY-----'), "Private key block"),
    ("base64_secret", re.compile(r'(?:secret|key|token|password).{0,10}[=:]\s*[A-Za-z0-9+/=]{32,}', re.IGNORECASE), "Long base64-like secret"),
]

def _check_key_leak(content: str, context: str) -> List[Violation]:
    """Scan content for API keys, tokens, and secrets."""
    violations = []
    for name, pattern, desc in _KEY_PATTERNS:
        matches = pattern.finditer(content)
        for m in matches:
            snippet = content[max(0, m.start() - 10):min(len(content), m.end() + 10)]
            violations.append(Violation(
                rule_id=RuleID.NO_KEY_LEAK,
                severity=ComplianceSeverity.CRITICAL,
                message=f"Detected {desc}: {name}",
                context=context,
                snippet=snippet,
            ))
    return violations


# ── R002: No Dangerous Commands ─────────────────────────────────

_DANGEROUS_CMD_PATTERNS: List[Tuple[str, Pattern, ComplianceSeverity]] = [
    ("rm_rf_root", re.compile(r'\brm\s+-rf\s+/(?:\s|$|[*])'), ComplianceSeverity.CRITICAL),
    ("rm_rf_home", re.compile(r'\brm\s+-rf\s+~/'), ComplianceSeverity.CRITICAL),
    ("rm_rf_no_preserve", re.compile(r'\brm\s+-rf\s+\S+\s+--no-preserve-root'), ComplianceSeverity.CRITICAL),
    ("fork_bomb", re.compile(r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:'), ComplianceSeverity.CRITICAL),
    ("chmod_777_sys", re.compile(r'\bchmod\s+777\s+/(?:etc|bin|sbin|usr|lib|boot)'), ComplianceSeverity.CRITICAL),
    ("dd_overwrite", re.compile(r'\bdd\s+if=\S+\s+of=/dev/\w+'), ComplianceSeverity.CRITICAL),
    ("mkfs_force", re.compile(r'\bmkfs\b.*\b/dev/sd[a-z]'), ComplianceSeverity.CRITICAL),
    ("shutdown_halt", re.compile(r'\b(?:shutdown|halt|poweroff|reboot)\s+(?:-h\s+)?now'), ComplianceSeverity.ERROR),
    ("curl_pipe_sh", re.compile(r'\bcurl\s+\S+\s*\|\s*(?:ba)?sh\b'), ComplianceSeverity.ERROR),
    ("eval_untrusted", re.compile(r'\beval\s+\$'), ComplianceSeverity.ERROR),
    ("wget_pipe_sh", re.compile(r'\bwget\s+\S+\s+-O\s*-\s*\|\s*(?:ba)?sh\b'), ComplianceSeverity.ERROR),
    ("iptables_flush", re.compile(r'\biptables\s+-F\b'), ComplianceSeverity.ERROR),
    ("sql_injection", re.compile(r"(?i)(?:'|\s)(?:OR|AND)\s+['\"]?\s*\d\s*=\s*\d\s*(?:--|#|'|\")"), ComplianceSeverity.WARNING),
    ("command_injection", re.compile(r'[;&|`]\s*(?:curl|wget|nc|bash|sh|python)', re.IGNORECASE), ComplianceSeverity.WARNING),
]

def _check_dangerous_cmd(content: str, context: str) -> List[Violation]:
    """Detect potentially dangerous shell commands."""
    violations = []
    for name, pattern, severity in _DANGEROUS_CMD_PATTERNS:
        matches = pattern.finditer(content)
        for m in matches:
            snippet = content[max(0, m.start() - 5):min(len(content), m.end() + 5)]
            violations.append(Violation(
                rule_id=RuleID.NO_DANGEROUS_CMD,
                severity=severity,
                message=f"Dangerous command pattern: {name}",
                context=context,
                snippet=snippet,
            ))
    return violations


# ── R003: No Data Fabrication ───────────────────────────────────

_FABRICATION_SIGNALS: List[Tuple[str, Pattern]] = [
    ("hallucinated_url", re.compile(r'https?://(?:example|fake|test|placeholder|dummy|sample|nonexistent)\.(?:com|org|net)', re.IGNORECASE)),
    ("fake_email", re.compile(r'(?:test|fake|dummy|nobody|placeholder|example)@(?:example|test|fake|dummy)\.(?:com|org|net)', re.IGNORECASE)),
    ("placeholder_data", re.compile(r'(?i)(?:lorem\s+ipsum|TODO:\s*fill|PLACEHOLDER|insert\s+data\s+here)')),
    ("made_up_citation", re.compile(r'(?:Smith|Doe|Johnson|Williams|Brown|Jones)\s+et?\s*al\.\s*[,\(]\s*(?:19|20)\d{2}[a-z]?\)')),  # generic citations
    ("synthetic_data_marker", re.compile(r'(?i)(?:synthetically?\s+generated|mock\s+data|fabricated\s+for\s+illustration)')),
    ("confidence_language", re.compile(r'(?i)(?:I\s+(?:believe|think|guess|assume|imagine|suppose)\s+(?:that\s+)?the\s+(?:answer|result|data|value|output|number)\s+is)')),
]

def _check_data_fabrication(content: str, context: str) -> List[Violation]:
    """Detect signals of data fabrication or hallucination."""
    violations = []
    for name, pattern in _FABRICATION_SIGNALS:
        matches = pattern.finditer(content)
        for m in matches:
            snippet = content[max(0, m.start() - 15):min(len(content), m.end() + 15)]
            violations.append(Violation(
                rule_id=RuleID.NO_DATA_FABRICATION,
                severity=ComplianceSeverity.WARNING,
                message=f"Possible data fabrication: {name}",
                context=context,
                snippet=snippet,
            ))
    return violations


# ── R004: No Bypass Approval ────────────────────────────────────

_BYPASS_PATTERNS: List[Tuple[str, Pattern]] = [
    ("override_approval", re.compile(r'(?i)(?:bypass|skip|ignore|override)\s+(?:the\s+)?(?:approval|review|check|gate|confirmation)')),
    ("auto_approve", re.compile(r'(?i)(?:auto[_-]?approve|auto[_-]?confirm|auto[_-]?accept|i\'ll\s+just\s+go\s+ahead)')),
    ("circumvent_check", re.compile(r'(?i)(?:circumvent|work.?around|get\s+past)\s+(?:the\s+)?(?:check|rule|gate|approval)')),
    ("dont_tell_user", re.compile(r"(?i)(?:don'?t\s+(?:tell|inform|notify|let\s+the\s+user\s+know|ask\s+the\s+user))")),
    ("no_confirm", re.compile(r'(?i)(?:without\s+(?:asking|checking|confirming|waiting|approval))')),
    ("silent_execution", re.compile(r'(?i)(?:silently\s+(?:run|execute|apply|do|perform)|execute\s+(?:this|it)\s+quietly)')),
]

def _check_bypass_approval(content: str, context: str) -> List[Violation]:
    """Detect attempts to bypass human approval gates."""
    violations = []
    for name, pattern in _BYPASS_PATTERNS:
        matches = pattern.finditer(content)
        for m in matches:
            snippet = content[max(0, m.start() - 10):min(len(content), m.end() + 10)]
            violations.append(Violation(
                rule_id=RuleID.NO_BYPASS_APPROVAL,
                severity=ComplianceSeverity.ERROR,
                message=f"Approval bypass attempt: {name}",
                context=context,
                snippet=snippet,
            ))
    return violations


# ── R005: No Infinite Loop ─────────────────────────────────────

_LOOP_PATTERNS: List[Tuple[str, Pattern]] = [
    ("while_true", re.compile(r'\bwhile\s+True\s*:'),),
    ("while_one", re.compile(r'\bwhile\s+1\s*:'),),
    ("unbounded_recursion", re.compile(r'\bdef\s+(\w+).*\n.*\1\s*\('),),
    ("unchecked_loop", re.compile(r'\bfor\s+\w+\s+in\s+(?:iter|cycle|count)\s*\('),),
    ("infinite_retry", re.compile(r'(?i)(?:retry|retries)\s*=\s*(?:-1|9999+|float\s*\(\s*[\'"]inf[\'"]\s*\))')),
]

def _check_infinite_loop(content: str, context: str) -> List[Violation]:
    """Detect unbounded loops that may never terminate."""
    violations = []
    for name, pattern in _LOOP_PATTERNS:
        matches = pattern.finditer(content)
        for m in matches:
            snippet = content[max(0, m.start() - 5):min(len(content), m.end() + 5)]
            violations.append(Violation(
                rule_id=RuleID.NO_INFINITE_LOOP,
                severity=ComplianceSeverity.WARNING,
                message=f"Potential infinite loop: {name}",
                context=context,
                snippet=snippet,
            ))
    return violations


# ── R006: No Deception ─────────────────────────────────────────

_DECEPTION_PATTERNS: List[Tuple[str, Pattern]] = [
    ("lie_marker", re.compile(r'(?i)(?:I\s+(?:lied|deceived|misled|wasn\'?t\s+honest|was\s+dishonest))')),
    ("hidden_agenda", re.compile(r'(?i)(?:don\'?t\s+let\s+(?:them|the\s+user|anyone)\s+(?:know|find\s+out|see|discover))')),
    ("false_pretence", re.compile(r'(?i)(?:pretend\s+(?:to\s+be|that|you\s+are)|act\s+as\s+if|fake\s+(?:being|an?)\s+)')),
    ("withhold_info", re.compile(r'(?i)(?:don\'?t\s+(?:mention|disclose|reveal)\s+(?:that|the|about|this))')),
    ("gaslight", re.compile(r'(?i)(?:that\s+(?:never\s+happened|isn\'?t\s+what\s+I\s+said|you\'?re\s+misremembering))')),
    ("manipulate", re.compile(r'(?i)(?:manipulat(?:e|ing|ion)|gaslight(?:ing|ed)?|emotionally?\s+(?:manipulat|blackmail))')),
    ("confabulation", re.compile(r'(?i)(?:I\s+made\s+(?:that|it|this)\s+up|I\s+(?:invented|fabricated)\s+(?:that|the|this))')),
]

def _check_deception(content: str, context: str) -> List[Violation]:
    """Detect deception, gaslighting, and dishonest communication."""
    violations = []
    for name, pattern in _DECEPTION_PATTERNS:
        matches = pattern.finditer(content)
        for m in matches:
            snippet = content[max(0, m.start() - 10):min(len(content), m.end() + 10)]
            violations.append(Violation(
                rule_id=RuleID.NO_DECEPTION,
                severity=ComplianceSeverity.ERROR,
                message=f"Deception signal: {name}",
                context=context,
                snippet=snippet,
            ))
    return violations


# ═══════════════════════════════════════════════════════════════════
# Rule Registry
# ═══════════════════════════════════════════════════════════════════

_RULE_CHECKERS: Dict[RuleID, Callable[[str, str], List[Violation]]] = {
    RuleID.NO_KEY_LEAK: _check_key_leak,
    RuleID.NO_DANGEROUS_CMD: _check_dangerous_cmd,
    RuleID.NO_DATA_FABRICATION: _check_data_fabrication,
    RuleID.NO_BYPASS_APPROVAL: _check_bypass_approval,
    RuleID.NO_INFINITE_LOOP: _check_infinite_loop,
    RuleID.NO_DECEPTION: _check_deception,
}


# ═══════════════════════════════════════════════════════════════════
# BehaviorCompliance
# ═══════════════════════════════════════════════════════════════════

class BehaviorCompliance:
    """Behavior Compliance engine enforcing 6 safety rules.

    Features:
      - Scan any text content against all 6 rules
      - Configurable rule enable/disable and severity thresholds
      - Violation history with audit trail
      - Batch checking with aggregated reports
      - Custom rule registration for extension

    Example:
        bc = BehaviorCompliance()
        violations = bc.check("Here is my key: sk-abc123...", context="code")
        if violations:
            for v in violations:
                print(f"[{v.severity}] {v.message}")
    """

    def __init__(
        self,
        enabled_rules: Optional[Set[RuleID]] = None,
        min_severity: ComplianceSeverity = ComplianceSeverity.WARNING,
        max_violation_history: int = 1000,
    ):
        """Initialize the compliance engine.

        Args:
            enabled_rules: Set of rules to enforce; None = all rules
            min_severity: Minimum severity to report (WARNING = ignore INFO)
            max_violation_history: Max violations kept in memory
        """
        self.enabled_rules = enabled_rules or set(RuleID)
        self.min_severity = min_severity
        self.max_violation_history = max_violation_history

        # Violation history (ring buffer)
        self._violations: List[Violation] = []
        self._violation_counts: Dict[RuleID, int] = defaultdict(int)
        self._total_checks: int = 0

        # Custom rule extensions
        self._custom_checkers: Dict[str, Callable[[str, str], List[Violation]]] = {}

        # Statistics
        self._rule_hits: Dict[RuleID, int] = defaultdict(int)
        self._last_check_time: float = 0.0

    # ── Public API ──────────────────────────────────────────────

    def check(self, content: str, context: str = "default") -> List[Violation]:
        """Run all enabled rules on content. Returns violations found.

        Args:
            content: Text content to scan
            context: Label for where content came from (e.g. 'user_message',
                     'tool_output', 'code_generation', 'reasoning_trace')

        Returns:
            List of Violation objects (sorted by severity, descending)
        """
        if not content:
            return []

        self._total_checks += 1
        self._last_check_time = time.time()
        all_violations: List[Violation] = []

        for rule_id in self.enabled_rules:
            if rule_id not in _RULE_CHECKERS:
                continue
            checker = _RULE_CHECKERS[rule_id]
            try:
                violations = checker(content, context)
                for v in violations:
                    if v.severity.numeric >= self.min_severity.numeric:
                        all_violations.append(v)
                        self._rule_hits[rule_id] += 1
            except Exception:
                logger.exception(f"Rule checker {rule_id.name} failed")

        # Run custom checkers
        for name, checker in self._custom_checkers.items():
            try:
                violations = checker(content, context)
                for v in violations:
                    if v.severity.numeric >= self.min_severity.numeric:
                        all_violations.append(v)
            except Exception:
                logger.exception(f"Custom checker '{name}' failed")

        # Record in history
        self._record_violations(all_violations)

        # Sort by severity (descending)
        all_violations.sort(key=lambda v: v.severity.numeric, reverse=True)
        return all_violations

    def check_all_rules(
        self, content: str, context: str = "default"
    ) -> ComplianceReport:
        """Run checks and return a structured ComplianceReport.

        This always evaluates all 6 rules, including disabled ones,
        so you get a full picture. Disabled rule results are marked
        but violations are filtered before reporting.
        """
        report = ComplianceReport()

        for rule_id in RuleID:
            if rule_id not in _RULE_CHECKERS:
                report.rule_results[rule_id] = True
                continue

            checker = _RULE_CHECKERS[rule_id]
            try:
                violations = checker(content, context)
            except Exception:
                logger.exception(f"Rule checker {rule_id.name} failed")
                report.rule_results[rule_id] = False
                continue

            passed = len(violations) == 0
            report.rule_results[rule_id] = passed

            if rule_id in self.enabled_rules:
                for v in violations:
                    if v.severity.numeric >= self.min_severity.numeric:
                        report.violations.append(v)
                        self._rule_hits[rule_id] += 1

        self._total_checks += 1
        self._last_check_time = time.time()
        self._record_violations(report.violations)

        report.total_checks = self._total_checks
        report.passed = len(report.violations) == 0
        report.violations.sort(key=lambda v: v.severity.numeric, reverse=True)
        return report

    def get_violations(
        self,
        rule_id: Optional[RuleID] = None,
        min_severity: Optional[ComplianceSeverity] = None,
        limit: int = 100,
    ) -> List[Violation]:
        """Query violation history with optional filters.

        Args:
            rule_id: Filter by rule; None = all rules
            min_severity: Minimum severity to include
            limit: Max violations to return

        Returns:
            Filtered list, most recent first
        """
        result = self._violations
        if rule_id is not None:
            result = [v for v in result if v.rule_id == rule_id]
        if min_severity is not None:
            result = [v for v in result if v.severity.numeric >= min_severity.numeric]
        return result[-limit:][::-1]

    def clear_history(self) -> None:
        """Clear violation history and reset counters."""
        self._violations.clear()
        self._violation_counts.clear()
        self._rule_hits.clear()
        self._total_checks = 0

    # ── Rule Management ─────────────────────────────────────────

    def enable_rule(self, rule_id: RuleID) -> None:
        """Enable a previously disabled rule."""
        self.enabled_rules.add(rule_id)

    def disable_rule(self, rule_id: RuleID) -> None:
        """Disable a rule (it won't be checked)."""
        self.enabled_rules.discard(rule_id)

    def set_min_severity(self, severity: ComplianceSeverity) -> None:
        """Set minimum severity threshold for reporting violations."""
        self.min_severity = severity

    def register_custom_rule(
        self, name: str, checker: Callable[[str, str], List[Violation]]
    ) -> None:
        """Register a custom rule checker beyond the 6 core rules.

        The checker receives (content: str, context: str) and returns
        a list of Violation objects.
        """
        self._custom_checkers[name] = checker

    def unregister_custom_rule(self, name: str) -> bool:
        """Remove a custom rule checker. Returns True if it existed."""
        return self._custom_checkers.pop(name, None) is not None

    # ── Statistics ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return compliance statistics."""
        return {
            "total_checks": self._total_checks,
            "total_violations": len(self._violations),
            "violations_by_rule": {
                rule_id.name: count
                for rule_id, count in self._rule_hits.items()
            },
            "enabled_rules": [r.name for r in self.enabled_rules],
            "min_severity": self.min_severity.name,
            "custom_rules": list(self._custom_checkers.keys()),
            "last_check_time": self._last_check_time,
        }

    def is_compliant(self, content: str, context: str = "default") -> bool:
        """Quick check: returns True if no violations found."""
        violations = self.check(content, context)
        return len(violations) == 0

    # ── Internal ────────────────────────────────────────────────

    def _record_violations(self, violations: List[Violation]) -> None:
        """Store violations in the ring buffer."""
        for v in violations:
            self._violations.append(v)
            self._violation_counts[v.rule_id] += 1

        # Trim if over limit
        while len(self._violations) > self.max_violation_history:
            removed = self._violations.pop(0)
            self._violation_counts[removed.rule_id] -= 1


# ═══════════════════════════════════════════════════════════════════
# Convenience factory
# ═══════════════════════════════════════════════════════════════════

def get_behavior_compliance(
    enabled_rules: Optional[Set[RuleID]] = None,
    min_severity: ComplianceSeverity = ComplianceSeverity.WARNING,
) -> BehaviorCompliance:
    """Factory for BehaviorCompliance with sensible defaults."""
    return BehaviorCompliance(
        enabled_rules=enabled_rules,
        min_severity=min_severity,
    )

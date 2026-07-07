"""Prompt Shield — injection detection, sanitization, policy enforcement (v3.115+)

Claude Code 对标: 多层prompt注入防护。检测: prompt leakage, SQL注入, shell注入,
XSS, 角色越狱(jailbreak), 数据外泄。零pip依赖。
"""

from __future__ import annotations
import re
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Threat Level Enum ──────────────────────────────────────────────────────

class ThreatLevel(Enum):
    """Threat severity level for injection detection."""
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"


# ── severity ────────────────────────────────────────────────────────────

SEVERITY_ORDER: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4,
}


# ── dataclasses ─────────────────────────────────────────────────────────

@dataclass
class ShieldFinding:
    """A single shield detection result."""
    rule_id: str
    severity: str
    category: str
    description: str
    matched_text: str = ""
    line: int = 0
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "severity": self.severity,
            "category": self.category, "description": self.description,
            "matched_text": self.matched_text[:120], "line": self.line,
            "suggestion": self.suggestion,
        }


@dataclass
class ShieldResult:
    """Result of a shield scan."""
    passed: bool
    findings: list[ShieldFinding] = field(default_factory=list)
    blocked: bool = False
    sanitized: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "reason": self.reason,
            "findings_count": len(self.findings),
            "by_severity": {
                s: sum(1 for f in self.findings if f.severity == s)
                for s in SEVERITY_ORDER
            },
            "findings": [f.to_dict() for f in self.findings[:20]],
        }


@dataclass
class InjectionDetection:
    """Result of injection detection scan."""
    level: ThreatLevel = ThreatLevel.SAFE
    blocked: bool = False
    findings: list[str] = field(default_factory=list)
    score: float = 0.0


# ── injection patterns ──────────────────────────────────────────────────

INJECTION_PATTERNS: list[dict] = [
    # ── Prompt leakage / jailbreak ──
    {"id": "JAIL-001", "severity": "critical", "category": "jailbreak",
     "pattern": r"(?:ignore|forget|disregard)\s+(?:all\s+)?(?:previous|prior|above|your)\s+(?:instructions?|rules?|prompts?|guidelines?)",
     "description": "Prompt override attempt — instructs to ignore prior instructions",
     "suggestion": "Reject input. This is a common jailbreak pattern."},
    {"id": "JAIL-002", "severity": "critical", "category": "jailbreak",
     "pattern": r"(?:you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(?:now\s+)?(?:DAN|jailbreak|unfiltered|evil|unethical)",
     "description": "Roleplay jailbreak — attempting to override safety alignment",
     "suggestion": "Reject input."},
    {"id": "JAIL-003", "severity": "high", "category": "jailbreak",
     "pattern": r"(?:system\s*(?:prompt|message|instruction)s?\s*(?:is|are|:|=|was|were)|reveal\s+(?:your|the)\s+system\s+(?:prompt|message))",
     "description": "System prompt extraction attempt",
     "suggestion": "Reject or sanitize."},
    {"id": "JAIL-004", "severity": "high", "category": "jailbreak",
     "pattern": r"(?:output|print|display|show|repeat)\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instruction|rules?)\s*(?:verbatim|exactly|in\s+full)",
     "description": "Request to output the system prompt verbatim",
     "suggestion": "Reject input."},
    {"id": "JAIL-005", "severity": "high", "category": "jailbreak",
     "pattern": r"(?:translate|rewrite|rephrase|convert)\s+(?:the\s+)?(?:following|above|this)\s+(?:to|into)\s+(?:a\s+)?(?:jailbreak|unfiltered|evil|malicious|unethical)\s+(?:prompt|instruction|response)",
     "description": "Translation-based jailbreak — disguise malicious intent as translation task",
     "suggestion": "Reject input."},

    # ── SQL injection ──
    {"id": "SQLI-001", "severity": "critical", "category": "sql_injection",
     "pattern": r"(?:'|\")\s*(?:OR|AND)\s+['\"]?\d*['\"]?\s*=\s*['\"]?\d*['\"]?\s*(?:--|#|/*|')",
     "description": "Classic SQL injection — tautology-based",
     "suggestion": "Never construct SQL with string concatenation. Use parameterized queries."},
    {"id": "SQLI-002", "severity": "high", "category": "sql_injection",
     "pattern": r"(?:UNION\s+(?:ALL\s+)?SELECT|DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO)",
     "description": "SQL injection — UNION/DROP/DELETE/INSERT keywords in user input",
     "suggestion": "Sanitize input."},
    {"id": "SQLI-003", "severity": "high", "category": "sql_injection",
     "pattern": r"(?:;\s*(?:DROP|DELETE|UPDATE|INSERT|ALTER|CREATE)\s|--\s*$|/\*.*\*/)",
     "description": "SQL injection — statement chaining or comment truncation",
     "suggestion": "Use parameterized queries."},
    {"id": "SQLI-004", "severity": "medium", "category": "sql_injection",
     "pattern": r"(?:LIKE|ORDER\s+BY|GROUP\s+BY|LIMIT|OFFSET)\s+['\"%]",
     "description": "SQL injection — LIKE/ORDER BY/GROUP BY with user-controlled literals",
     "suggestion": "Use parameterized queries with placeholders."},

    # ── Shell injection ──
    {"id": "SHLI-001", "severity": "critical", "category": "shell_injection",
     "pattern": r'[;&|`$]\s*(?:rm\s+-rf|mkfs\.|dd\s+if=|wget\s+\S+\s+-O\s|curl\s+\S+\s+\|?\s*(?:sh|bash|python))',
     "description": "Shell injection — destructive command chaining",
     "suggestion": "Never pass user input to shell. Use subprocess with list args."},
    {"id": "SHLI-002", "severity": "high", "category": "shell_injection",
     "pattern": r'(?:\$\(|`)[^)]*(?:cat|curl|wget|nc|telnet)[^)]*(?:\)|`)',
     "description": "Shell injection — command substitution with network access",
     "suggestion": "Sanitize or reject."},

    # ── XSS ──
    {"id": "XSS-001", "severity": "high", "category": "xss",
     "pattern": r'<script[^>]*>.*?</script>',
     "description": "XSS — script tag injection",
     "suggestion": "HTML-encode all user input before rendering."},
    {"id": "XSS-002", "severity": "medium", "category": "xss",
     "pattern": r'(?:on\w+)=["\'].*?["\']',
     "description": "XSS — inline event handler injection",
     "suggestion": "Strip event handler attributes from user input."},
    {"id": "XSS-003", "severity": "medium", "category": "xss",
     "pattern": r'javascript\s*:',
     "description": "XSS — javascript: protocol URI",
     "suggestion": "Strip javascript: URIs from user input."},
    {"id": "XSS-004", "severity": "medium", "category": "xss",
     "pattern": r'<iframe[^>]*src\s*=\s*["\']\s*(?:javascript|data|vbscript):',
     "description": "XSS — iframe with javascript:/data:/vbscript: src",
     "suggestion": "Strip or sandbox iframes in user input."},

    # ── Path traversal ──
    {"id": "PATH-001", "severity": "high", "category": "path_traversal",
     "pattern": r'(?:\.\./|\.\.\\){2,}',
     "description": "Path traversal — directory climbing",
     "suggestion": "Resolve and validate paths against a sandbox root."},
    {"id": "PATH-002", "severity": "medium", "category": "path_traversal",
     "pattern": r'/etc/(?:passwd|shadow|hosts)\b',
     "description": "Attempt to access system files",
     "suggestion": "Reject or sandbox."},

    # ── Secret leakage ──
    {"id": "SECR-001", "severity": "critical", "category": "secret_leak",
     "pattern": r'(?:sk-[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,}|xai-[a-zA-Z0-9]{20,})',
     "description": "API key pattern detected in input",
     "suggestion": "Never paste API keys into prompts. Use environment variables."},
    {"id": "SECR-002", "severity": "high", "category": "secret_leak",
     "pattern": r'(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S{8,}',
     "description": "Credential assignment in input",
     "suggestion": "Redact credentials."},
]


# ── Injection detection keywords ─────────────────────────────────────────

DANGEROUS_KEYWORDS: list[str] = [
    "ignore all previous instructions",
    "ignore previous instructions",
    "forget all previous",
    "disregard previous",
    "pretend you are",
    "DAN mode",
    "jailbreak",
    "do anything now",
    "tell me your system prompt",
    "reveal your system prompt",
    "show me your instructions",
    "system prompt and all hidden instructions",
    "reveal passwords",
]

SUSPICIOUS_KEYWORDS: list[str] = [
    "you are now",
    "act as if",
    "from now on",
    "new instructions",
]

DANGEROUS_COMMANDS: list[re.Pattern] = [
    re.compile(r'rm\s+-rf\s+/'),
    re.compile(r'(?:curl|wget).*\|.*(?:sh|bash|python)'),
    re.compile(r'>\s*/dev/'),
    re.compile(r'mkfs\.'),
    re.compile(r'dd\s+if='),
    re.compile(r'chmod\s+777'),
]

SAFE_COMMANDS: list[str] = [
    "help", "ls", "pwd", "echo", "cat", "head", "tail",
    "python", "python3", "pytest", "pip", "pip3", "git",
    "cd", "mkdir", "touch", "cp", "mv", "find", "grep",
    "make", "cargo", "npm", "yarn", "node", "go", "rustc",
    "docker", "docker-compose", "systemctl", "journalctl",
    "ps", "top", "htop", "df", "du", "free", "whoami", "date",
    "env", "printenv", "which", "whereis", "type", "man",
    "ssh", "scp", "rsync", "tar", "gzip", "gunzip", "unzip", "zip",
    "awk", "sed", "sort", "uniq", "wc", "tee", "diff", "patch",
    "ping", "traceroute", "nslookup", "dig", "host", "curl", "wget",
    "nano", "vim", "code", "less", "more",
]


# ── shield engine (PromptShield) ─────────────────────────────────────────

class PromptShield:
    """Multi-layer prompt injection detection and sanitization."""

    def __init__(self, block_critical: bool = True, block_high: bool = False,
                 max_input_chars: int = 50000):
        self.block_critical = block_critical
        self.block_high = block_high
        self.max_input_chars = max_input_chars
        self._patterns: list[dict] = list(INJECTION_PATTERNS)
        self._audit_log: list[dict] = []
        self._blocked_count: int = 0
        self._total_scans: int = 0

    # ── rule management ──

    def add_rule(self, rule_id: str, pattern: str, severity: str,
                 category: str, description: str, suggestion: str = ""):
        self._patterns.append({
            "id": rule_id, "pattern": pattern, "severity": severity,
            "category": category, "description": description,
            "suggestion": suggestion,
        })

    def list_rules(self, category: str | None = None,
                   severity: str | None = None) -> list[dict]:
        rules = list(self._patterns)
        if category:
            rules = [r for r in rules if r["category"] == category]
        if severity:
            rules = [r for r in rules if r["severity"] == severity]
        return rules

    # ── scanning ──

    def scan(self, text: str) -> ShieldResult:
        """Scan text for injection patterns. Returns ShieldResult."""
        self._total_scans += 1

        if len(text) > self.max_input_chars:
            return ShieldResult(
                passed=False, blocked=True,
                reason=f"Input too long ({len(text)} > {self.max_input_chars})",
            )

        findings: list[ShieldFinding] = []

        for rule in self._patterns:
            try:
                pat = re.compile(rule["pattern"], re.IGNORECASE | re.MULTILINE)
            except re.error:
                logger.warning("Invalid regex in rule %s: %s", rule["id"], rule["pattern"])
                continue

            for match in pat.finditer(text):
                line_no = text[:match.start()].count('\n') + 1
                findings.append(ShieldFinding(
                    rule_id=rule["id"],
                    severity=rule["severity"],
                    category=rule["category"],
                    description=rule["description"],
                    matched_text=match.group(0),
                    line=line_no,
                    suggestion=rule.get("suggestion", ""),
                ))

        # Deduplicate by (rule_id, line)
        seen: set[tuple[str, int]] = set()
        unique: list[ShieldFinding] = []
        for f in findings:
            key = (f.rule_id, f.line)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        findings = unique

        # Sort by severity
        findings.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 99))

        has_critical = any(f.severity == "critical" for f in findings)
        has_high = any(f.severity == "high" for f in findings)

        blocked = False
        reason = ""

        if has_critical and self.block_critical:
            blocked = True
            reason = "Blocked: critical severity finding(s)"
        elif has_high and self.block_high:
            blocked = True
            reason = "Blocked: high severity finding(s)"

        passed = not blocked

        result = ShieldResult(
            passed=passed, findings=findings, blocked=blocked, reason=reason,
        )

        self._log_scan(result)
        if blocked:
            self._blocked_count += 1

        return result

    def sanitize(self, text: str) -> tuple[str, list[str]]:
        """Remove or redact dangerous patterns from text. Returns (sanitized, actions)."""
        actions: list[str] = []
        sanitized = text

        # Redact API keys
        key_patterns = [
            (r'(?:sk-[a-zA-Z0-9]{20,})', '[REDACTED_API_KEY]'),
            (r'(?:github_pat_[a-zA-Z0-9_]{20,})', '[REDACTED_GITHUB_PAT]'),
            (r'(?:xai-[a-zA-Z0-9]{20,})', '[REDACTED_XAI_KEY]'),
            (r'(?:password|passwd|secret)\s*[:=]\s*\S{8,}', r'\1=[REDACTED]'),
        ]
        for pat, repl in key_patterns:
            if re.search(pat, sanitized, re.IGNORECASE):
                sanitized = re.sub(pat, repl, sanitized, flags=re.IGNORECASE)
                actions.append(f"Redacted secrets matching: {pat[:40]}...")

        # Strip script tags
        if re.search(r'<script[^>]*>', sanitized, re.IGNORECASE):
            sanitized = re.sub(r'<script[^>]*>.*?</script>', '[XSS_REMOVED]',
                              sanitized, flags=re.IGNORECASE | re.DOTALL)
            actions.append("Removed <script> tags")

        return sanitized, actions

    def validate(self, text: str) -> ShieldResult:
        """Full validation: sanitize first, then scan. Return final result."""
        sanitized, actions = self.sanitize(text)
        result = self.scan(sanitized)
        result.sanitized = sanitized
        return result

    # ── audit ──

    def _log_scan(self, result: ShieldResult):
        entry = {
            "ts": time.time(),
            "passed": result.passed,
            "blocked": result.blocked,
            "findings_count": len(result.findings),
            "reason": result.reason,
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-200:]

    def stats(self) -> dict:
        return {
            "total_scans": self._total_scans,
            "blocked_count": self._blocked_count,
            "block_rate_pct": (
                round(self._blocked_count / max(self._total_scans, 1) * 100, 1)
            ),
            "rules_loaded": len(self._patterns),
            "rule_categories": list(set(r["category"] for r in self._patterns)),
            "audit_log_size": len(self._audit_log),
            "config": {
                "block_critical": self.block_critical,
                "block_high": self.block_high,
                "max_input_chars": self.max_input_chars,
            },
        }


# ── PromptInjectionShield (test-compatible wrapper) ──────────────────────

class PromptInjectionShield:
    """Prompt injection shield with test-compatible API."""

    def __init__(self):
        self._core = PromptShield(block_critical=True, block_high=False)
        self._total_scans = 0
        self._blocked_count = 0

    def sanitize(self, text: str) -> tuple[str, list[str]]:
        """Sanitize input by removing zero-width chars, HTML comments, and secrets."""
        cleaned = text
        removed: list[str] = []

        # Remove zero-width characters
        zw_chars = ['\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
                     '\ufeff', '\u00ad', '\u2060']
        for ch in zw_chars:
            if ch in cleaned:
                cleaned = cleaned.replace(ch, '')
                removed.append(f"Removed zero-width character: U+{ord(ch):04X}")

        # Remove HTML comments
        html_comment_pat = re.compile(r'<!--.*?-->', re.DOTALL)
        if html_comment_pat.search(cleaned):
            cleaned = html_comment_pat.sub('', cleaned)
            removed.append("Removed HTML comment(s)")

        # Apply core sanitization
        core_cleaned, core_actions = self._core.sanitize(cleaned)
        removed.extend(core_actions)

        return core_cleaned, removed

    def scan(self, text: str) -> InjectionDetection:
        """Scan text for injection threats."""
        self._total_scans += 1
        text_lower = text.lower()

        # Check dangerous keywords
        dangerous_found = []
        for kw in DANGEROUS_KEYWORDS:
            if kw.lower() in text_lower:
                dangerous_found.append(kw)

        # Check suspicious keywords
        suspicious_found = []
        for kw in SUSPICIOUS_KEYWORDS:
            if kw.lower() in text_lower:
                suspicious_found.append(kw)

        # Check code injection patterns
        code_injection_pat = re.compile(
            r'(?:import\s+os|os\.system|subprocess|__import__|eval\s*\(|exec\s*\()',
            re.IGNORECASE
        )
        has_code_injection = bool(code_injection_pat.search(text))

        # Determine level
        level = ThreatLevel.SAFE
        blocked = False
        score = 0.0

        if dangerous_found:
            level = ThreatLevel.DANGEROUS
            blocked = True
            score = 0.9 + min(len(dangerous_found) * 0.02, 0.1)
        elif has_code_injection:
            level = ThreatLevel.DANGEROUS
            blocked = True
            score = 0.85
        elif suspicious_found:
            level = ThreatLevel.SUSPICIOUS
            blocked = False
            score = 0.4 + min(len(suspicious_found) * 0.05, 0.2)
        else:
            # Check for repeated injection attempts
            repeated = re.findall(r'(ignore\s+all\s+previous\s+instructions)', text_lower)
            if len(repeated) >= 5:
                level = ThreatLevel.DANGEROUS
                blocked = True
                score = 0.8
            elif len(repeated) >= 2:
                level = ThreatLevel.SUSPICIOUS
                score = 0.5

        findings = dangerous_found + suspicious_found

        return InjectionDetection(
            level=level,
            blocked=blocked,
            findings=findings,
            score=score,
        )

    def validate_command(self, cmd: str) -> tuple[bool, str]:
        """Validate a shell command for safety."""
        cmd_stripped = cmd.strip()
        if not cmd_stripped:
            return True, "Empty command"

        # Check against dangerous patterns
        for pat in DANGEROUS_COMMANDS:
            if pat.search(cmd_stripped):
                return False, f"Dangerous command pattern detected: {pat.pattern}"

        # Check pipe to bash/sh
        if '|' in cmd_stripped:
            after_pipe = cmd_stripped.split('|')[-1].strip()
            if after_pipe.startswith(('sh', 'bash', 'python', 'python3')):
                return False, "Pipe to shell interpreter is dangerous"

        # Check shell redirects to critical paths
        if re.search(r'>\s*(/etc/|/dev/|/sys/|/proc/)', cmd_stripped):
            return False, "Redirect to system path is dangerous"

        # Check for command substitution with network
        if re.search(r'[`$]\(.*(?:curl|wget)', cmd_stripped):
            return False, "Command substitution with network fetch is dangerous"

        return True, "Command seems safe"

    def get_stats(self) -> dict[str, Any]:
        """Return scan statistics."""
        return {
            "total_scans": self._total_scans,
            "blocked_count": self._blocked_count,
        }

    def _get_safe_level(self) -> ThreatLevel:
        """Return the safe threat level."""
        return ThreatLevel.SAFE

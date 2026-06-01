"""
v3.112 Security Scanner — 安全扫描器

四大核心能力:
1) 代码漏洞扫描 (Code Vulnerability Scanning) — AST模式匹配检测危险代码模式
2) 依赖CVE检测 (Dependency CVE Detection) — 检查依赖库已知漏洞
3) 配置审计 (Configuration Audit) — 检测不安全配置项
4) 安全评分报告 (Security Score Report) — 综合安全评分与修复建议

Design: Thread-safe, pluggable scanner modules, regex + AST hybrid detection.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.security_scanner")

# ══════════════════════════════════════════════════════════════════════════════
# Enums & Data Classes
# ══════════════════════════════════════════════════════════════════════════════


class Severity(Enum):
    """漏洞严重程度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ScanModule(Enum):
    """扫描模块类型"""
    CODE_VULN = "code_vulnerability"
    DEPENDENCY_CVE = "dependency_cve"
    CONFIG_AUDIT = "config_audit"
    SCORE_REPORT = "score_report"


@dataclass
class Finding:
    """安全发现"""
    module: ScanModule
    severity: Severity
    title: str
    description: str
    file_path: str = ""
    line_number: int = 0
    code_snippet: str = ""
    cve_id: str = ""
    recommendation: str = ""
    cvss_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "cve_id": self.cve_id,
            "recommendation": self.recommendation,
            "cvss_score": self.cvss_score,
        }


@dataclass
class ScanResult:
    """扫描结果"""
    module: ScanModule
    findings: List[Finding] = field(default_factory=list)
    files_scanned: int = 0
    duration_ms: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.LOW)


@dataclass
class SecurityReport:
    """综合安全报告"""
    score: int = 100  # 0-100, 100 = perfect
    grade: str = "A"
    results: Dict[str, ScanResult] = field(default_factory=dict)
    total_findings: int = 0
    total_files_scanned: int = 0
    total_duration_ms: float = 0.0
    summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "total_findings": self.total_findings,
            "total_files_scanned": self.total_files_scanned,
            "total_duration_ms": self.total_duration_ms,
            "summary": self.summary,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp,
            "modules": {
                name: {
                    "findings_count": len(r.findings),
                    "critical": r.critical_count,
                    "high": r.high_count,
                    "medium": r.medium_count,
                    "low": r.low_count,
                    "files_scanned": r.files_scanned,
                }
                for name, r in self.results.items()
            },
            "all_findings": [
                f.to_dict()
                for r in self.results.values()
                for f in r.findings
            ],
        }


# ══════════════════════════════════════════════════════════════════════════════
# Vulnerability Patterns (Code Scanning)
# ══════════════════════════════════════════════════════════════════════════════

# Regex-based patterns for quick scanning
CODE_VULN_PATTERNS: List[Tuple[str, re.Pattern, Severity, str, str]] = [
    (
        "eval_usage",
        re.compile(r"\beval\s*\(", re.IGNORECASE),
        Severity.HIGH,
        "Use of eval() detected",
        "eval() can execute arbitrary code. Replace with safer alternatives like ast.literal_eval() or custom parsers.",
    ),
    (
        "exec_usage",
        re.compile(r"\bexec\s*\(", re.IGNORECASE),
        Severity.CRITICAL,
        "Use of exec() detected",
        "exec() can execute arbitrary code dynamically. Remove or replace with safe alternatives.",
    ),
    (
        "hardcoded_secret",
        re.compile(
            r"(?i)(password|secret|api_key|api_secret|token|auth_token|private_key)\s*[:=]\s*['\"][^'\"]+['\"]",
        ),
        Severity.HIGH,
        "Hardcoded secret detected",
        "Secrets should be stored in environment variables or a secure vault, not hardcoded in source.",
    ),
    (
        "sql_injection_fstring",
        re.compile(
            r"(?i)(execute|cursor\.execute|\.execute\s*\(|\.raw\s*\()\s*[fF]['\"]",
        ),
        Severity.CRITICAL,
        "Potential SQL injection via f-string",
        "Use parameterized queries or an ORM instead of string interpolation in SQL statements.",
    ),
    (
        "os_system_injection",
        re.compile(r"\bos\.system\s*\(\s*[fF]['\"]", re.IGNORECASE),
        Severity.HIGH,
        "Potential command injection via os.system() f-string",
        "Use subprocess.run() with a list of arguments instead of string concatenation.",
    ),
    (
        "pickle_load",
        re.compile(r"\bpickle\.(loads?|Unpickler)\s*\(", re.IGNORECASE),
        Severity.HIGH,
        "Unsafe pickle deserialization",
        "pickle can execute arbitrary code during deserialization. Use JSON or a safer serialization format.",
    ),
    (
        "yaml_unsafe_load",
        re.compile(r"\byaml\.load\s*\([^)]*(?!.*Loader\s*=\s*yaml\.(Safe|CSafe|Base)Loader)", re.IGNORECASE),
        Severity.HIGH,
        "Unsafe YAML loading (no SafeLoader)",
        "Always use yaml.safe_load() or yaml.load(..., Loader=yaml.SafeLoader) to avoid code execution.",
    ),
    (
        "subprocess_shell_true",
        re.compile(r"\bsubprocess\.\w+\s*\([^)]*\bshell\s*=\s*True", re.IGNORECASE),
        Severity.HIGH,
        "subprocess with shell=True detected",
        "shell=True can lead to command injection. Use shell=False with a list of arguments instead.",
    ),
    (
        "hardcoded_ip_credential",
        re.compile(
            r"(?i)(mongodb|mysql|postgresql|redis)://[^:@]+:[^@]+@",
        ),
        Severity.CRITICAL,
        "Hardcoded database credentials in URL",
        "Database connection strings with embedded credentials should come from environment variables.",
    ),
    (
        "unsafe_deserialization",
        re.compile(r"\bmarshal\.loads?\(", re.IGNORECASE),
        Severity.MEDIUM,
        "Potentially unsafe marshal.loads() usage",
        "marshal is not secure against erroneous or malicious data. Use JSON or pickle with SafeUnpickler.",
    ),
    (
        "open_redirect",
        re.compile(
            r"(?i)redirect\s*\(\s*request\.(args|GET)\s*\[",
        ),
        Severity.MEDIUM,
        "Potential open redirect vulnerability",
        "Validate and sanitize redirect URLs against a whitelist of allowed destinations.",
    ),
    (
        "debug_true",
        re.compile(r"(?i)\bDEBUG\s*=\s*True\b"),
        Severity.LOW,
        "DEBUG mode enabled",
        "DEBUG=True in production exposes stack traces and sensitive information. Set DEBUG=False.",
    ),
]

# AST-based vulnerability visitors
class _VulnerabilityVisitor(ast.NodeVisitor):
    """AST visitor to detect dangerous code patterns."""

    def __init__(self, file_path: str = ""):
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_Call(self, node: ast.Call) -> None:
        # Detect eval() calls
        if isinstance(node.func, ast.Name) and node.func.id == "eval":
            self.findings.append(Finding(
                module=ScanModule.CODE_VULN,
                severity=Severity.HIGH,
                title="Use of eval() detected (AST)",
                description="eval() can execute arbitrary code. Replace with ast.literal_eval() or custom parsers.",
                file_path=self.file_path,
                line_number=node.lineno,
                recommendation="Use ast.literal_eval() for safe evaluation of literals.",
            ))

        # Detect exec() calls
        if isinstance(node.func, ast.Name) and node.func.id == "exec":
            self.findings.append(Finding(
                module=ScanModule.CODE_VULN,
                severity=Severity.CRITICAL,
                title="Use of exec() detected (AST)",
                description="exec() executes arbitrary Python code dynamically. Remove or use safe sandbox.",
                file_path=self.file_path,
                line_number=node.lineno,
                recommendation="Replace exec() with safe alternatives or sandboxed execution.",
            ))

        # Detect __import__() calls
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            self.findings.append(Finding(
                module=ScanModule.CODE_VULN,
                severity=Severity.MEDIUM,
                title="Use of __import__() detected",
                description="Dynamic importing via __import__() can import arbitrary modules. Use importlib instead.",
                file_path=self.file_path,
                line_number=node.lineno,
                recommendation="Use importlib.import_module() with an explicit allowlist.",
            ))

        # Detect getattr with dynamic attribute names
        if isinstance(node.func, ast.Attribute) and node.func.attr == "loads":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "pickle":
                self.findings.append(Finding(
                    module=ScanModule.CODE_VULN,
                    severity=Severity.HIGH,
                    title="Pickle deserialization detected (AST)",
                    description="Pickle can execute arbitrary code during deserialization.",
                    file_path=self.file_path,
                    line_number=node.lineno,
                    recommendation="Use JSON or a safer serialization format instead.",
                ))

        self.generic_visit(node)


# ══════════════════════════════════════════════════════════════════════════════
# CVE Knowledge Base (simplified embedded database)
# ══════════════════════════════════════════════════════════════════════════════

# Known vulnerable packages with CVEs (curated list)
KNOWN_CVE_DATABASE: List[Dict[str, Any]] = [
    {
        "package": "django",
        "cve_id": "CVE-2024-53907",
        "vulnerable_versions": "<3.2.25",
        "patched_versions": ">=3.2.25",
        "severity": Severity.HIGH,
        "cvss_score": 7.5,
        "title": "Django SQL injection in Oracle backend",
        "description": "A SQL injection vulnerability exists in the Oracle backend of Django.",
    },
    {
        "package": "flask",
        "cve_id": "CVE-2023-30861",
        "vulnerable_versions": "<2.3.2",
        "patched_versions": ">=2.3.2",
        "severity": Severity.HIGH,
        "cvss_score": 7.5,
        "title": "Flask session cookie exposure",
        "description": "Flask response can expose session cookie when a 304 Not Modified response is returned.",
    },
    {
        "package": "requests",
        "cve_id": "CVE-2024-35195",
        "vulnerable_versions": "<2.32.0",
        "patched_versions": ">=2.32.0",
        "severity": Severity.MEDIUM,
        "cvss_score": 5.3,
        "title": "Requests Session object proxy bypass",
        "description": "When making requests through a Requests Session, headers may leak between requests.",
    },
    {
        "package": "pyyaml",
        "cve_id": "CVE-2020-14343",
        "vulnerable_versions": "<5.4",
        "patched_versions": ">=5.4",
        "severity": Severity.CRITICAL,
        "cvss_score": 9.8,
        "title": "PyYAML arbitrary code execution via FullLoader",
        "description": "PyYAML FullLoader allows arbitrary code execution when processing untrusted YAML.",
    },
    {
        "package": "pillow",
        "cve_id": "CVE-2024-28219",
        "vulnerable_versions": "<10.3.0",
        "patched_versions": ">=10.3.0",
        "severity": Severity.HIGH,
        "cvss_score": 7.8,
        "title": "Pillow buffer overflow in _imagingcms.c",
        "description": "A buffer overflow in _imagingcms.c could lead to remote code execution.",
    },
    {
        "package": "cryptography",
        "cve_id": "CVE-2024-26130",
        "vulnerable_versions": "<42.0.4",
        "patched_versions": ">=42.0.4",
        "severity": Severity.HIGH,
        "cvss_score": 7.4,
        "title": "Cryptography null pointer dereference",
        "description": "A null pointer dereference in ECDH could cause denial of service.",
    },
    {
        "package": "aiohttp",
        "cve_id": "CVE-2024-23334",
        "vulnerable_versions": "<3.9.2",
        "patched_versions": ">=3.9.2",
        "severity": Severity.HIGH,
        "cvss_score": 7.5,
        "title": "aiohttp directory traversal vulnerability",
        "description": "Improper path validation in aiohttp static file serving leads to directory traversal.",
    },
    {
        "package": "sqlalchemy",
        "cve_id": "CVE-2024-25102",
        "vulnerable_versions": "<2.0.27",
        "patched_versions": ">=2.0.27",
        "severity": Severity.MEDIUM,
        "cvss_score": 5.0,
        "title": "SQLAlchemy regular expression denial of service",
        "description": "A regex in SQLAlchemy's MySQL dialect could cause ReDoS attacks.",
    },
    {
        "package": "jinja2",
        "cve_id": "CVE-2024-34064",
        "vulnerable_versions": "<3.1.4",
        "patched_versions": ">=3.1.4",
        "severity": Severity.MEDIUM,
        "cvss_score": 5.4,
        "title": "Jinja2 XSS via xmlattr filter",
        "description": "The xmlattr filter in Jinja2 accepts keys with spaces and is vulnerable to XSS.",
    },
    {
        "package": "urllib3",
        "cve_id": "CVE-2024-37891",
        "vulnerable_versions": "<1.26.19",
        "patched_versions": ">=1.26.19",
        "severity": Severity.MEDIUM,
        "cvss_score": 4.4,
        "title": "urllib3 proxy-authorization header leak",
        "description": "urllib3 does not strip the proxy-authorization header on cross-origin redirects.",
    },
]


def _parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse a version string into a comparable tuple, stripping non-numeric suffixes."""
    clean = re.sub(r"[^0-9.]", "", version_str)
    try:
        return tuple(int(x) for x in clean.split(".") if x)
    except ValueError:
        return (0,)


def _version_in_range(version: str, range_spec: str) -> bool:
    """Check if a version falls within a range specification like '<2.3.2' or '>=3.2.25'."""
    version_tuple = _parse_version(version)
    if not version_tuple:
        return False

    # Parse range: e.g., "<2.3.2" -> (operator, version)
    match = re.match(r"([<>=!]+)\s*(\d[\d.]*)", range_spec)
    if not match:
        return False
    op, target = match.group(1), match.group(2)
    target_tuple = _parse_version(target)

    if op == "<":
        return version_tuple < target_tuple
    elif op == "<=":
        return version_tuple <= target_tuple
    elif op == ">":
        return version_tuple > target_tuple
    elif op == ">=":
        return version_tuple >= target_tuple
    elif op == "==":
        return version_tuple == target_tuple
    elif op == "!=":
        return version_tuple != target_tuple
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Configuration Audit Rules
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_AUDIT_RULES: List[Dict[str, Any]] = [
    {
        "name": "debug_mode_enabled",
        "file_pattern": re.compile(r"(settings|config|\.env|\.ini|\.toml|\.yaml|\.yml)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(debug|DEBUG)\s*[:=]\s*(true|True|1|yes|on)\b"),
        "severity": Severity.HIGH,
        "title": "Debug mode enabled in configuration",
        "recommendation": "Disable debug mode in production environments.",
    },
    {
        "name": "weak_secret_key",
        "file_pattern": re.compile(r"(settings|config|\.env|\.ini|\.toml|\.yaml|\.yml)", re.IGNORECASE),
        "pattern": re.compile(
            r"(?i)(SECRET_KEY|secret_key|SECRET|secret)\s*[:=]\s*['\"]"
            r"(secret|changeme|password|test|default|12345|abcdef|your[-_]?secret)[\"']",
        ),
        "severity": Severity.CRITICAL,
        "title": "Weak or default secret key detected",
        "recommendation": "Generate a strong random secret key (at least 50 characters, mixed case + digits + symbols).",
    },
    {
        "name": "allow_all_hosts",
        "file_pattern": re.compile(r"(settings|config|\.env|\.ini|\.toml|\.yaml|\.yml)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(ALLOWED_HOSTS)\s*[:=]\s*\[(['\"]\*['\"])\]"),
        "severity": Severity.HIGH,
        "title": "ALLOWED_HOSTS set to wildcard '*'",
        "recommendation": "Restrict ALLOWED_HOSTS to specific domain names in production.",
    },
    {
        "name": "csrf_disabled",
        "file_pattern": re.compile(r"(settings|config|\.py|\.env|\.ini|\.toml)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(CSRF_COOKIE_SECURE|CSRF_USE_SESSIONS)\s*[:=]\s*(false|False|0|no|off)\b"),
        "severity": Severity.MEDIUM,
        "title": "CSRF protection disabled or weakened",
        "recommendation": "Ensure CSRF protection is enabled and CSRF_COOKIE_SECURE=True in production.",
    },
    {
        "name": "ssl_disabled",
        "file_pattern": re.compile(r"(settings|config|\.env|\.py|\.ini|\.toml|\.yaml|\.yml)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(SECURE_SSL_REDIRECT|ssl|tls)\s*[:=]\s*(false|False|0|no|off|disable)\b"),
        "severity": Severity.HIGH,
        "title": "SSL/TLS disabled or not enforced",
        "recommendation": "Enable SSL redirection and enforce HTTPS in production environments.",
    },
    {
        "name": "cookie_not_secure",
        "file_pattern": re.compile(r"(settings|config|\.py)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(SESSION_COOKIE_SECURE)\s*[:=]\s*(false|False|0)\b"),
        "severity": Severity.MEDIUM,
        "title": "Secure cookie flag disabled",
        "recommendation": "Set SESSION_COOKIE_SECURE=True and SESSION_COOKIE_HTTPONLY=True.",
    },
    {
        "name": "cors_wildcard",
        "file_pattern": re.compile(r"(settings|config|\.py|\.env|\.ini|\.toml|\.yaml|\.yml)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(CORS_ALLOW_ALL_ORIGINS|CORS_ORIGIN_ALLOW_ALL)\s*[:=]\s*(true|True|1)\b"),
        "severity": Severity.MEDIUM,
        "title": "CORS allows all origins",
        "recommendation": "Restrict CORS to specific trusted origin domains instead of '*'.",
    },
    {
        "name": "password_in_config",
        "file_pattern": re.compile(r"(settings|config|\.env|\.ini|\.toml|\.yaml|\.yml|\.json)", re.IGNORECASE),
        "pattern": re.compile(
            r"(?i)(DATABASE_URL|DB_URL|MONGO_URI|REDIS_URL)\s*[:=]\s*['\"]?"
            r"\w+://[^:@]+:[^@]+@",
        ),
        "severity": Severity.CRITICAL,
        "title": "Database credentials hardcoded in config file",
        "recommendation": "Use environment variables or a secrets manager for database credentials.",
    },
    {
        "name": "log_level_info_or_below",
        "file_pattern": re.compile(r"(settings|config|\.env|\.ini|\.toml|\.py)", re.IGNORECASE),
        "pattern": re.compile(r"(?i)(LOG_LEVEL|log_level|loglevel)\s*[:=]\s*['\"]?(DEBUG|INFO)['\"]?"),
        "severity": Severity.LOW,
        "title": "Verbose logging level may leak sensitive data",
        "recommendation": "Set log level to WARNING or ERROR in production. Never log at DEBUG level in prod.",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# Security Scanner
# ══════════════════════════════════════════════════════════════════════════════


class SecurityScanner:
    """
    v3.112 Security Scanner — 多引擎安全扫描器.

    Provides:
    - scan_code(): Code vulnerability scanning via regex + AST
    - scan_dependencies(): CVE detection for Python dependencies
    - audit_config(): Configuration security audit
    - generate_report(): Combined security score report with grading
    """

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self._lock = threading.Lock()
        self._results_cache: Dict[str, ScanResult] = {}
        self._last_scan_time: float = 0.0

    # ── Module 1: Code Vulnerability Scanning ──────────────────────────────────

    def scan_code(
        self,
        paths: Optional[List[str]] = None,
        file_glob: str = "*.py",
        exclude_patterns: Optional[List[str]] = None,
    ) -> ScanResult:
        """
        Scan Python source code for security vulnerabilities.

        Uses both regex pattern matching and AST analysis to detect:
        - eval/exec usage
        - Hardcoded secrets
        - SQL/command injection patterns
        - Unsafe deserialization (pickle, yaml, marshal)
        - Debug mode leaks

        Args:
            paths: List of paths to scan (dirs or files). Defaults to [project_root].
            file_glob: Glob pattern for files to scan.
            exclude_patterns: Patterns to exclude (e.g., ['__pycache__', '.git']).

        Returns:
            ScanResult with all findings.
        """
        start = time.time()
        findings: List[Finding] = []
        files_scanned = 0

        if paths is None:
            paths = [str(self.project_root)]

        if exclude_patterns is None:
            exclude_patterns = ["__pycache__", ".git", ".tox", "node_modules", "venv", ".venv", "env", "dist", "build", "egg-info"]

        # Collect all target files
        target_files: List[Path] = []
        for path_str in paths:
            p = Path(path_str)
            if not p.exists():
                continue
            if p.is_file():
                if p.match(file_glob):
                    target_files.append(p)
            elif p.is_dir():
                for root, dirs, files in os.walk(p):
                    # Filter excluded directories
                    dirs[:] = [d for d in dirs if not any(ex in d for ex in exclude_patterns)]
                    for fname in files:
                        fpath = Path(root) / fname
                        if fpath.match(file_glob):
                            target_files.append(fpath)

        files_scanned = len(target_files)

        # Scan each file
        for fpath in target_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Cannot read {fpath}: {e}")
                continue

            rel_path = str(fpath.relative_to(self.project_root)) if self.project_root in fpath.parents else str(fpath)

            # Regex-based scanning
            for name, pattern, severity, title, recommendation in CODE_VULN_PATTERNS:
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    # Extract context (the matched line)
                    lines = content.split("\n")
                    snippet = lines[line_num - 1].strip() if line_num <= len(lines) else match.group(0)
                    findings.append(Finding(
                        module=ScanModule.CODE_VULN,
                        severity=severity,
                        title=f"{title} (regex: {name})",
                        description=title,
                        file_path=rel_path,
                        line_number=line_num,
                        code_snippet=snippet[:200],
                        recommendation=recommendation,
                    ))

            # AST-based scanning (Python files only)
            if fpath.suffix == ".py":
                try:
                    tree = ast.parse(content, filename=str(fpath))
                    visitor = _VulnerabilityVisitor(file_path=rel_path)
                    visitor.visit(tree)
                    findings.extend(visitor.findings)
                except SyntaxError as e:
                    logger.debug(f"AST parse error in {fpath}: {e}")

        duration_ms = (time.time() - start) * 1000
        result = ScanResult(
            module=ScanModule.CODE_VULN,
            findings=findings,
            files_scanned=files_scanned,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._results_cache["code_vuln"] = result
        return result

    # ── Module 2: Dependency CVE Detection ─────────────────────────────────────

    def scan_dependencies(
        self,
        requirements_files: Optional[List[str]] = None,
        check_installed: bool = True,
    ) -> ScanResult:
        """
        Scan Python dependencies for known CVEs.

        Checks:
        - requirements.txt / pyproject.toml / setup.cfg parsed dependencies
        - Installed packages via pip freeze (if check_installed=True)
        - Matches against embedded CVE knowledge base

        Args:
            requirements_files: Explicit list of requirements files to parse.
            check_installed: Also check currently installed packages.

        Returns:
            ScanResult with CVE findings.
        """
        start = time.time()
        findings: List[Finding] = []
        files_scanned = 0

        # Discover requirement files
        if requirements_files is None:
            requirements_files = []
            for pattern in ["requirements*.txt", "requirements/*.txt", "pyproject.toml", "setup.cfg", "setup.py"]:
                for fpath in self.project_root.rglob(pattern):
                    if any(ex in str(fpath) for ex in ["__pycache__", ".git", "node_modules", "venv"]):
                        continue
                    requirements_files.append(str(fpath))

        # Normalize to set to avoid duplicates
        requirements_files = list(set(requirements_files))
        files_scanned = len(requirements_files)

        # Parse detected packages from requirement files
        detected_packages: Dict[str, str] = {}  # name -> version

        for req_file in requirements_files:
            try:
                with open(req_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                # Parse pip-style requirements
                for line in content.split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Handle package==version and package>=version etc.
                    match = re.match(r"([a-zA-Z0-9_.-]+)\s*([><=!~]+)\s*([\d.]+)", line)
                    if match:
                        pkg_name = match.group(1).lower()
                        pkg_version = match.group(3)
                        if pkg_name not in detected_packages:
                            detected_packages[pkg_name] = pkg_version
                    else:
                        # Just package name, no version
                        match2 = re.match(r"([a-zA-Z0-9_.-]+)", line)
                        if match2:
                            pkg_name = match2.group(1).lower()
                            if pkg_name not in detected_packages:
                                detected_packages[pkg_name] = "0.0.0"
            except Exception as e:
                logger.debug(f"Error parsing {req_file}: {e}")

        # Check installed packages
        if check_installed:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "freeze"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        line = line.strip()
                        match = re.match(r"([a-zA-Z0-9_.-]+)==([\d.]+)", line)
                        if match:
                            pkg_name = match.group(1).lower()
                            pkg_version = match.group(2)
                            if pkg_name not in detected_packages or detected_packages[pkg_name] == "0.0.0":
                                detected_packages[pkg_name] = pkg_version
            except Exception as e:
                logger.debug(f"pip freeze failed: {e}")

        # Match against CVE database
        for pkg_name, pkg_version in detected_packages.items():
            for cve_entry in KNOWN_CVE_DATABASE:
                if cve_entry["package"].lower() == pkg_name:
                    if _version_in_range(pkg_version, cve_entry["vulnerable_versions"]):
                        findings.append(Finding(
                            module=ScanModule.DEPENDENCY_CVE,
                            severity=cve_entry["severity"],
                            title=f"{cve_entry['title']} ({cve_entry['cve_id']})",
                            description=f"{cve_entry['description']} Installed: {pkg_name}=={pkg_version}, Vulnerable: {cve_entry['vulnerable_versions']}",
                            cve_id=cve_entry["cve_id"],
                            cvss_score=cve_entry["cvss_score"],
                            recommendation=f"Upgrade {pkg_name} to {cve_entry['patched_versions']}.",
                        ))

        duration_ms = (time.time() - start) * 1000
        result = ScanResult(
            module=ScanModule.DEPENDENCY_CVE,
            findings=findings,
            files_scanned=files_scanned,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._results_cache["dependency_cve"] = result
        return result

    # ── Module 3: Configuration Audit ──────────────────────────────────────────

    def audit_config(
        self,
        config_paths: Optional[List[str]] = None,
    ) -> ScanResult:
        """
        Audit configuration files for security issues.

        Checks:
        - Debug mode enabled
        - Weak/blank secret keys
        - ALLOWED_HOSTS wildcard
        - Disabled CSRF/SSL protections
        - Insecure cookie settings
        - Hardcoded credentials

        Args:
            config_paths: List of config file paths or directories to scan.
                          Defaults to scanning project_root recursively.

        Returns:
            ScanResult with config audit findings.
        """
        start = time.time()
        findings: List[Finding] = []
        files_scanned = 0

        if config_paths is None:
            config_paths = [str(self.project_root)]

        # Collect config files
        config_files: List[Path] = []
        config_extensions = {".py", ".env", ".ini", ".toml", ".yaml", ".yml", ".json", ".cfg", ".conf"}
        config_dotfiles = {".env", ".editorconfig", ".gitignore", ".hgrc", ".npmrc", ".dockerignore"}
        exclude_patterns = ["__pycache__", ".git", ".tox", "node_modules", "venv", ".venv", "env", "dist", "build", "egg-info"]

        for path_str in config_paths:
            p = Path(path_str)
            if not p.exists():
                continue
            if p.is_file() and (p.suffix in config_extensions or p.name in config_dotfiles):
                config_files.append(p)
            elif p.is_dir():
                for root, dirs, files in os.walk(p):
                    dirs[:] = [d for d in dirs if not any(ex in d for ex in exclude_patterns)]
                    for fname in files:
                        fpath = Path(root) / fname
                        if fpath.suffix in config_extensions or fpath.name in config_dotfiles:
                            config_files.append(fpath)

        files_scanned = len(config_files)

        for fpath in config_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Cannot read config {fpath}: {e}")
                continue

            rel_path = str(fpath.relative_to(self.project_root)) if self.project_root in fpath.parents else str(fpath)

            for rule in CONFIG_AUDIT_RULES:
                file_pattern = rule["file_pattern"]
                if not file_pattern.search(fpath.name):
                    continue

                for match in rule["pattern"].finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    lines = content.split("\n")
                    snippet = lines[line_num - 1].strip() if line_num <= len(lines) else match.group(0)
                    findings.append(Finding(
                        module=ScanModule.CONFIG_AUDIT,
                        severity=rule["severity"],
                        title=rule["title"],
                        description=f"Found in {rule['name']}: {snippet[:150]}",
                        file_path=rel_path,
                        line_number=line_num,
                        code_snippet=snippet[:200],
                        recommendation=rule["recommendation"],
                    ))

        duration_ms = (time.time() - start) * 1000
        result = ScanResult(
            module=ScanModule.CONFIG_AUDIT,
            findings=findings,
            files_scanned=files_scanned,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._results_cache["config_audit"] = result
        return result

    # ── Module 4: Security Score Report ────────────────────────────────────────

    def generate_report(
        self,
        run_all: bool = True,
        code_paths: Optional[List[str]] = None,
        requirements_files: Optional[List[str]] = None,
        config_paths: Optional[List[str]] = None,
    ) -> SecurityReport:
        """
        Generate a comprehensive security score report.

        If run_all=True (default), executes all three scanners:
        code vulnerability scan, dependency CVE check, and config audit.
        Then produces a weighted security score (0-100) with letter grade.

        Scoring weights:
        - Code vulnerabilities: 40%
        - Dependency CVEs: 35%
        - Configuration audit: 25%

        Grade scale:
        A: 90-100  B: 80-89  C: 70-79  D: 60-69  F: <60

        Args:
            run_all: Run all scanners (True) or use cached results (False).
            code_paths: Paths for code scan.
            requirements_files: Requirements files for CVE scan.
            config_paths: Config paths for audit.

        Returns:
            SecurityReport with overall score, grade, findings, and recommendations.
        """
        start = time.time()

        if run_all:
            with self._lock:
                self._results_cache.clear()

            result_code = self.scan_code(paths=code_paths)
            result_cve = self.scan_dependencies(requirements_files=requirements_files)
            result_config = self.audit_config(config_paths=config_paths)
        else:
            result_code = self._results_cache.get("code_vuln", ScanResult(module=ScanModule.CODE_VULN))
            result_cve = self._results_cache.get("dependency_cve", ScanResult(module=ScanModule.DEPENDENCY_CVE))
            result_config = self._results_cache.get("config_audit", ScanResult(module=ScanModule.CONFIG_AUDIT))

        # ═══ Weighted Scoring ══════════════════════════════════════════════════
        total_files = result_code.files_scanned + result_cve.files_scanned + result_config.files_scanned

        # Code vulnerability scoring (40% weight)
        code_penalty = (
            result_code.critical_count * 20 +
            result_code.high_count * 10 +
            result_code.medium_count * 5 +
            result_code.low_count * 2
        )
        code_score = max(0, 100 - min(100, code_penalty))
        weighted_code = code_score * 0.40

        # Dependency CVE scoring (35% weight)
        cve_penalty = (
            result_cve.critical_count * 25 +
            result_cve.high_count * 15 +
            result_cve.medium_count * 8 +
            result_cve.low_count * 3
        )
        cve_score = max(0, 100 - min(100, cve_penalty))
        weighted_cve = cve_score * 0.35

        # Configuration audit scoring (25% weight)
        config_penalty = (
            result_config.critical_count * 25 +
            result_config.high_count * 12 +
            result_config.medium_count * 6 +
            result_config.low_count * 2
        )
        config_score = max(0, 100 - min(100, config_penalty))
        weighted_config = config_score * 0.25

        overall_score = round(weighted_code + weighted_cve + weighted_config)

        # Grade
        if overall_score >= 90:
            grade = "A"
        elif overall_score >= 80:
            grade = "B"
        elif overall_score >= 70:
            grade = "C"
        elif overall_score >= 60:
            grade = "D"
        else:
            grade = "F"

        # Collect all findings
        total_findings = len(result_code.findings) + len(result_cve.findings) + len(result_config.findings)

        # Generate recommendations
        recommendations: List[str] = []
        all_findings = result_code.findings + result_cve.findings + result_config.findings
        critical_findings = [f for f in all_findings if f.severity == Severity.CRITICAL]
        high_findings = [f for f in all_findings if f.severity == Severity.HIGH]

        if critical_findings:
            recommendations.append(f"CRITICAL: Fix {len(critical_findings)} critical issues immediately")
            for f in critical_findings[:5]:
                recommendations.append(f"  - {f.title}: {f.recommendation}")
        if high_findings:
            recommendations.append(f"HIGH: Address {len(high_findings)} high-severity issues")
        if not all_findings:
            recommendations.append("No security issues found. Maintain good security practices.")

        # Build summary
        summary_parts = [
            f"Security Score: {overall_score}/100 (Grade: {grade})",
            f"Total Findings: {total_findings} "
            f"(C:{sum(1 for f in all_findings if f.severity == Severity.CRITICAL)} "
            f"H:{sum(1 for f in all_findings if f.severity == Severity.HIGH)} "
            f"M:{sum(1 for f in all_findings if f.severity == Severity.MEDIUM)} "
            f"L:{sum(1 for f in all_findings if f.severity == Severity.LOW)})",
            f"Files Scanned: {total_files}",
        ]
        summary = "\n".join(summary_parts)

        duration_ms = (time.time() - start) * 1000

        report = SecurityReport(
            score=overall_score,
            grade=grade,
            results={
                "code_vulnerability": result_code,
                "dependency_cve": result_cve,
                "config_audit": result_config,
            },
            total_findings=total_findings,
            total_files_scanned=total_files,
            total_duration_ms=duration_ms,
            summary=summary,
            recommendations=recommendations,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        self._last_scan_time = time.time()
        return report

    # ── Quick Scan ─────────────────────────────────────────────────────────────

    def quick_scan(self) -> SecurityReport:
        """Run all scans and return the report. Convenience alias for generate_report()."""
        return self.generate_report(run_all=True)


# ══════════════════════════════════════════════════════════════════════════════
# Singleton access
# ══════════════════════════════════════════════════════════════════════════════

_scanner_instance: Optional[SecurityScanner] = None
_scanner_lock = threading.Lock()


def get_security_scanner(project_root: str = ".") -> SecurityScanner:
    """Get or create the singleton SecurityScanner instance."""
    global _scanner_instance
    if _scanner_instance is None:
        with _scanner_lock:
            if _scanner_instance is None:
                _scanner_instance = SecurityScanner(project_root=project_root)
    return _scanner_instance


def reset_security_scanner() -> None:
    """Reset the singleton SecurityScanner instance."""
    global _scanner_instance
    with _scanner_lock:
        _scanner_instance = None

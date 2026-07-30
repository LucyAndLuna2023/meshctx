"""meshctx security_scanner — code vulnerability scanning, CVE detection, config audit"""
from __future__ import annotations
import re
import os
import ast
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SecScannerSeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ScanModule(Enum):
    CODE_VULN = "code_vuln"
    DEPENDENCIES = "dependencies"
    CONFIG = "config"


@dataclass
class Finding:
    module: ScanModule = ScanModule.CODE_VULN
    severity: SecScannerSeverity = SecScannerSeverity.INFO
    title: str = ""
    description: str = ""
    file_path: str = ""
    line_number: int = 0
    code_snippet: str = ""
    recommendation: str = ""
    cve_id: str = ""
    cvss_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "module": self.module.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "recommendation": self.recommendation,
            "cve_id": self.cve_id,
            "cvss_score": self.cvss_score,
        }


@dataclass
class ScanResult:
    module: ScanModule = ScanModule.CODE_VULN
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecScannerSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecScannerSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecScannerSeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecScannerSeverity.LOW)

    def to_dict(self) -> dict:
        return {
            "module": self.module.value,
            "findings": [f.to_dict() for f in self.findings],
            "files_scanned": self.files_scanned,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
        }


class SecurityReport:
    def __init__(self):
        self.score: int = 100
        self.grade: str = "A"
        self.results: list[ScanResult] = []
        self.recommendations: list[str] = []
        self.all_findings: list[Finding] = []

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "modules": [r.to_dict() for r in self.results],
            "all_findings": [f.to_dict() for f in self.all_findings],
            "recommendations": self.recommendations,
        }


# ── AST Visitor ────────────────────────────────────────────────

class _VulnerabilityVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str = ""):
        self.file_path = file_path
        self.findings: list[Finding] = []

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name == 'eval':
                self.findings.append(Finding(
                    module=ScanModule.CODE_VULN, severity=SecScannerSeverity.CRITICAL,
                    title="eval() 调用",
                    description="eval() has code injection risk",
                    file_path=self.file_path, line_number=node.lineno,
                    recommendation="Avoid using eval()",
                ))
            elif name == 'exec':
                self.findings.append(Finding(
                    module=ScanModule.CODE_VULN, severity=SecScannerSeverity.CRITICAL,
                    title="exec() 调用",
                    description="exec() has code injection risk",
                    file_path=self.file_path, line_number=node.lineno,
                    recommendation="Avoid using exec()",
                ))
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id == 'pickle' and node.func.attr in ('load', 'loads'):
                    self.findings.append(Finding(
                        module=ScanModule.CODE_VULN, severity=SecScannerSeverity.HIGH,
                        title="pickle deserialization",
                        description="Unsafe pickle deserialization",
                        file_path=self.file_path, line_number=node.lineno,
                        recommendation="Avoid pickle for untrusted data",
                    ))
        self.generic_visit(node)


# ── Version helpers ────────────────────────────────────────────

def _parse_version(version_str: str) -> tuple:
    import re as _vre
    num_parts = []
    for m in _vre.finditer(r'\d+', version_str):
        num_parts.append(int(m.group()))
    return tuple(num_parts)


def _version_in_range(version: str, range_spec: str) -> bool:
    ver = _parse_version(version)
    spec = range_spec.strip()
    if spec.startswith("<="):
        return ver <= _parse_version(spec[2:].strip())
    elif spec.startswith(">="):
        return ver >= _parse_version(spec[2:].strip())
    elif spec.startswith("=="):
        return ver == _parse_version(spec[2:].strip())
    elif spec.startswith("<"):
        return ver < _parse_version(spec[1:].strip())
    elif spec.startswith(">"):
        return ver > _parse_version(spec[1:].strip())
    return False


# ── CVE database ───────────────────────────────────────────────

CVE_DATABASE = {
    "django": [
        ("<3.2.25", "CVE-2024-27306"),
        ("<4.2.11", "CVE-2024-27306"),
        ("<5.0.3", "CVE-2024-27306"),
    ],
    "pyyaml": [
        ("<5.4", "CVE-2020-14343"),
    ],
    "requests": [
        ("<2.32.0", "CVE-2024-35195"),
    ],
    "flask": [
        ("<2.3.3", "CVE-2023-30861"),
    ],
    "pillow": [
        ("<10.3.0", "CVE-2024-28219"),
    ],
}

# ── Code vulnerability patterns ───────────────────────────────

CODE_PATTERNS = [
    (re.compile(r'\beval\s*\('), "eval() usage", SecScannerSeverity.CRITICAL,
     "Avoid eval(); use safe alternatives"),
    (re.compile(r'\bexec\s*\('), "exec() usage", SecScannerSeverity.CRITICAL,
     "Avoid exec()"),
    (re.compile(r'PASSWORD\s*=\s*["\']', re.IGNORECASE), "Hardcoded secret",
     SecScannerSeverity.HIGH, "Use environment variables for secrets"),
    (re.compile(r'API_KEY\s*=\s*["\']', re.IGNORECASE), "Hardcoded secret",
     SecScannerSeverity.HIGH, "Use environment variables for API keys"),
    (re.compile(r'SECRET_KEY\s*=\s*["\']', re.IGNORECASE), "Hardcoded secret",
     SecScannerSeverity.HIGH, "Use environment variables for secret keys"),
    (re.compile(r'\bpickle\.(load|loads)\s*\('), "pickle deserialization",
     SecScannerSeverity.HIGH, "Avoid pickle for untrusted data"),
    (re.compile(r'yaml\.load\s*\([^)]*\)'), "Unsafe YAML loading",
     SecScannerSeverity.HIGH, "Use yaml.safe_load() instead"),
    (re.compile(r'\bos\.system\s*\(.*f["\']'), "os.system() with f-string",
     SecScannerSeverity.HIGH, "Use subprocess.run() with shell=False"),
]

# ── Config audit patterns ─────────────────────────────────────

CONFIG_PATTERNS = [
    (re.compile(r'(?i)DEBUG\s*=\s*(?:1|True|true|yes|on)'), "DEBUG enabled",
     SecScannerSeverity.HIGH, "Disable DEBUG in production"),
    (re.compile(r'(?i)SECRET_KEY\s*=\s*["\'][^"\']{1,20}["\']'), "Weak SECRET_KEY",
     SecScannerSeverity.HIGH, "Use a strong random SECRET_KEY"),
    (re.compile(r'(?i)ALLOWED_HOSTS\s*=\s*\[.*\*.*\]'), "Wildcard ALLOWED_HOSTS",
     SecScannerSeverity.MEDIUM, "Restrict ALLOWED_HOSTS"),
    (re.compile(r'(?i)CORS_ALLOW_ALL_ORIGINS\s*=\s*(?:1|True|true)'), "CORS wildcard",
     SecScannerSeverity.MEDIUM, "Restrict CORS origins"),
    (re.compile(r'(?i)DATABASE_URL\s*=\s*["\']?[^"\']*://[^:]+:[^@]+@'), "Hardcoded DB credentials",
     SecScannerSeverity.HIGH, "Use environment variables for database credentials"),
    (re.compile(r'(?i)CSRF_COOKIE_SECURE\s*=\s*False'), "Insecure CSRF cookie",
     SecScannerSeverity.MEDIUM, "Set CSRF_COOKIE_SECURE=True"),
    (re.compile(r'(?i)SESSION_COOKIE_SECURE\s*=\s*False'), "Insecure session cookie",
     SecScannerSeverity.MEDIUM, "Set SESSION_COOKIE_SECURE=True"),
    (re.compile(r'(?i)LOG_LEVEL\s*=\s*["\']?DEBUG["\']?'), "DEBUG log level",
     SecScannerSeverity.LOW, "Set LOG_LEVEL above DEBUG in production"),
]


# ── SecurityScanner ───────────────────────────────────────────

class SecurityScanner:
    def __init__(self, project_root: str = ""):
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._report: SecurityReport | None = None

    # ── scan_code ──

    def scan_code(self, paths: list[str] | None = None) -> ScanResult:
        findings: list[Finding] = []
        files_scanned = 0
        if paths:
            target_files = [Path(p) for p in paths]
        else:
            target_files = list(self.project_root.rglob("*.py"))
        for fpath in target_files:
            try:
                with open(fpath, "r", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue
            files_scanned += 1
            fp_str = str(fpath)
            for line_no, line in enumerate(content.split("\n"), 1):
                for pat, title, severity, suggestion in CODE_PATTERNS:
                    if pat.search(line):
                        findings.append(Finding(
                            module=ScanModule.CODE_VULN, severity=severity,
                            title=title,
                            description=f"Line {line_no}: {line.strip()[:80]}",
                            file_path=fp_str, line_number=line_no,
                            code_snippet=line.strip()[:200],
                            recommendation=suggestion,
                        ))
            # AST deep scan
            try:
                tree = ast.parse(content)
                visitor = _VulnerabilityVisitor(file_path=fp_str)
                visitor.visit(tree)
                for f in visitor.findings:
                    if not any(ex.file_path == f.file_path and ex.line_number == f.line_number and ex.title == f.title for ex in findings):
                        findings.append(f)
            except SyntaxError:
                pass
        return ScanResult(module=ScanModule.CODE_VULN, findings=findings, files_scanned=files_scanned)

    # ── scan_dependencies ──

    def scan_dependencies(self, check_installed: bool = False) -> ScanResult:
        findings: list[Finding] = []
        req_file = self.project_root / "requirements.txt"
        if not req_file.exists():
            return ScanResult(module=ScanModule.DEPENDENCIES)
        try:
            with open(req_file, "r") as f:
                content = f.read()
        except Exception:
            return ScanResult(module=ScanModule.DEPENDENCIES)
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Parse: package==version
            m = re.match(r'^([a-zA-Z0-9_.-]+)\s*==\s*([\d.]+(?:\+[^\s]*|-[^\s]*)?)', line)
            if not m:
                m = re.match(r'^([a-zA-Z0-9_.-]+)\s*>=\s*([\d.]+)', line)
                if not m:
                    continue
            pkg = m.group(1).lower()
            ver = m.group(2)
            if pkg in CVE_DATABASE:
                for range_spec, cve_id in CVE_DATABASE[pkg]:
                    if _version_in_range(ver, range_spec):
                        title = f"{pkg.capitalize()} {ver} (CVE: {cve_id})"
                        findings.append(Finding(
                            module=ScanModule.DEPENDENCIES, severity=SecScannerSeverity.HIGH,
                            title=title,
                            description=f"{pkg}=={ver} is affected by {cve_id} (affected: {range_spec})",
                            cve_id=cve_id,
                            recommendation=f"Upgrade {pkg} to a patched version",
                        ))
        return ScanResult(module=ScanModule.DEPENDENCIES, findings=findings)

    # ── audit_config ──

    def audit_config(self) -> ScanResult:
        findings: list[Finding] = []
        config_files = list(self.project_root.rglob("*.py")) + list(self.project_root.rglob(".env"))
        for fpath in config_files:
            try:
                with open(fpath, "r", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue
            fp_str = str(fpath)
            for line_no, line in enumerate(content.split("\n"), 1):
                for pat, title, severity, suggestion in CONFIG_PATTERNS:
                    if pat.search(line):
                        findings.append(Finding(
                            module=ScanModule.CONFIG, severity=severity,
                            title=f"Config: {title}",
                            description=f"Line {line_no}: {line.strip()[:80]}",
                            file_path=fp_str, line_number=line_no,
                            recommendation=suggestion,
                        ))
        return ScanResult(module=ScanModule.CONFIG, findings=findings)

    # ── generate_report ──

    def generate_report(self, run_all: bool = True) -> SecurityReport:
        report = SecurityReport()
        if run_all:
            report.results.append(self.scan_code())
            report.results.append(self.scan_dependencies())
            report.results.append(self.audit_config())
        # Collect all findings
        for r in report.results:
            report.all_findings.extend(r.findings)
        # Score calculation
        penalty_map = {SecScannerSeverity.CRITICAL: 15, SecScannerSeverity.HIGH: 8, SecScannerSeverity.MEDIUM: 3, SecScannerSeverity.LOW: 1, SecScannerSeverity.INFO: 0}
        penalty = sum(penalty_map.get(f.severity, 0) for f in report.all_findings)
        report.score = max(0, 100 - penalty)
        if report.score >= 90:
            report.grade = "A"
        elif report.score >= 80:
            report.grade = "B"
        elif report.score >= 70:
            report.grade = "C"
        elif report.score >= 60:
            report.grade = "D"
        else:
            report.grade = "F"
        # Recommendations
        recs: set[str] = set()
        for f in report.all_findings:
            if f.recommendation:
                recs.add(f.recommendation)
        report.recommendations = list(recs)
        self._report = report
        return report

    # ── quick_scan ──

    def quick_scan(self) -> SecurityReport:
        return self.generate_report(run_all=True)


# ── Singleton ─────────────────────────────────────────────────

_scanner_instance: SecurityScanner | None = None


def get_security_scanner(project_root: str = "") -> SecurityScanner:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = SecurityScanner(project_root=project_root)
    return _scanner_instance


def reset_security_scanner():
    global _scanner_instance
    _scanner_instance = None

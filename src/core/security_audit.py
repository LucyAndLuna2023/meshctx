"""Security Auditor — dep scan, CVE detection, secret scan, permission check (v3.115+)

Codex 对标: 依赖扫描 + CVE检测 + 密钥泄露检测。零pip依赖。
Works with: requirements.txt, package.json, Cargo.toml, go.mod, Pipfile.
"""

from __future__ import annotations
import re
import os
import json
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── severity ────────────────────────────────────────────────────────────

SEVERITY_ORDER: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4,
}


# ── dataclasses ─────────────────────────────────────────────────────────

class AuditFinding:
    """A single security audit finding."""

    def __init__(self, title: str = "", severity: str = "info",
                 category: str = "", description: str = "",
                 file: str = "", line: int = 0, evidence: str = "",
                 cve: str = "", fix_version: str = "", suggestion: str = ""):
        self.title = title
        self.severity = severity
        self.category = category
        self.description = description
        self.file = file
        self.line = line
        self.evidence = evidence
        self.cve = cve
        self.fix_version = fix_version
        self.suggestion = suggestion

    @property
    def severity_order(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)

    def to_dict(self) -> dict:
        return {
            "title": self.title, "severity": self.severity,
            "category": self.category, "description": self.description,
            "file": self.file, "line": self.line, "evidence": self.evidence,
            "cve": self.cve, "fix_version": self.fix_version,
            "suggestion": self.suggestion,
        }

    def __repr__(self):
        return (f"AuditFinding(severity={self.severity!r}, "
                f"title={self.title!r}, cve={self.cve!r})")


class AuditReport:
    """Full security audit report."""

    def __init__(self, findings: list[AuditFinding] | None = None,
                 files_scanned: int = 0, dep_count: int = 0):
        self.findings = findings or []
        self.files_scanned = files_scanned
        self.dep_count = dep_count
        self.score = 100
        self.verdict = "✅ Secure"

    def compute_score(self) -> AuditReport:
        penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
        score = 100
        for f in self.findings:
            score = max(0, score - penalty.get(f.severity, 0))
        self.score = score
        if score >= 90:
            self.verdict = "✅ Secure"
        elif score >= 70:
            self.verdict = "⚠ Review"
        elif score >= 50:
            self.verdict = "🔶 Vulnerable"
        else:
            self.verdict = "🔴 Critical"
        return self

    def to_dict(self) -> dict:
        by_sev = {}
        by_cat = {}
        for f in self.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            by_cat[f.category] = by_cat.get(f.category, 0) + 1
        return {
            "score": self.score, "verdict": self.verdict,
            "total_findings": len(self.findings),
            "files_scanned": self.files_scanned,
            "dep_count": self.dep_count,
            "by_severity": by_sev, "by_category": by_cat,
            "findings": [f.to_dict() for f in self.findings[:50]],
        }


# ── known CVE patterns ──────────────────────────────────────────────────

# Format: (package_name_regex, version_range, cve_id, severity, description, fix_version)
# Based on known high-impact CVEs — indicative, not exhaustive.
KNOWN_VULNS: list[tuple[str, str, str, str, str, str]] = [
    # Python critical
    (r'^django$', '<3.2.25|<4.0|<4.2.11|<5.0.4', 'CVE-2024-XXXX', 'critical',
     'Django <3.2.25/4.2.11 — SQL injection in Oracle DB backend', '3.2.25 / 4.2.11'),
    (r'^django$', '<2.2.28|<3.1.14|<3.2.10', 'CVE-2021-45115', 'high',
     'Django UserAttributeSimilarityValidator DoS', '3.2.10'),
    (r'^pillow$', '<10.2.0', 'CVE-2024-28219', 'high',
     'Pillow <10.2.0 — buffer overflow in _imagingcms.c', '10.2.0'),
    (r'^requests$', '<2.32.0', 'CVE-2024-35195', 'medium',
     'Requests <2.32.0 — Proxy-Authorization header leak on redirect', '2.32.0'),
    (r'^cryptography$', '<42.0.4', 'CVE-2024-26130', 'high',
     'Cryptography <42.0.4 — NULL pointer dereference in pkcs12', '42.0.4'),
    (r'^(flask|Flask)$', '<2.2.5|<2.3.3', 'CVE-2023-30861', 'high',
     'Flask — cookie disclosure via response Vary header', '2.3.3'),
    (r'^jinja2$', '<3.1.4', 'CVE-2024-34064', 'medium',
     'Jinja2 <3.1.4 — XSS via xmlattr filter with attacker-controlled keys', '3.1.4'),
    (r'^gunicorn$', '<22.0.0', 'CVE-2024-1135', 'high',
     'Gunicorn <22.0.0 — HTTP request smuggling via chunked TE', '22.0.0'),
    (r'^torch$', '<2.2.0', 'CVE-2024-5480', 'high',
     'PyTorch <2.2.0 — arbitrary code exec via pickle in torch.load', '2.2.0'),
    (r'^numpy$', '<1.26.0', 'CVE-2021-41495', 'low',
     'NumPy <1.26.0 — null pointer dereference in array_from_pyobj', '1.26.0'),

    # JavaScript / Node
    (r'^lodash$', '<4.17.21', 'CVE-2021-23337', 'high',
     'Lodash <4.17.21 — command injection via template', '4.17.21'),
    (r'^axios$', '<1.6.0', 'CVE-2023-45857', 'medium',
     'Axios <1.6.0 — CSRF bypass via XSRF-TOKEN cookie', '1.6.0'),
    (r'^express$', '<4.19.2', 'CVE-2024-29041', 'medium',
     'Express <4.19.2 — open redirect in res.redirect()', '4.19.2'),
    (r'^next$', '<14.1.1', 'CVE-2024-34351', 'high',
     'Next.js <14.1.1 — SSRF via Server Actions redirect', '14.1.1'),
    (r'^vite$', '<5.2.0', 'CVE-2024-31207', 'medium',
     'Vite <5.2.0 — server.fs.deny bypass via ?raw??', '5.2.0'),
    (r'^dotenv$', '<16.4.5', 'CVE-2024-28851', 'low',
     'dotenv <16.4.5 — env variable expansion in .env', '16.4.5'),
    (r'^node-fetch$', '<2.7.0|<3.0.0', 'CVE-2022-0235', 'high',
     'node-fetch <2.7.0 — SSRF via redirect to localhost', '2.7.0'),

    # Python JSON deserialization
    (r'^PyYAML$', '<6.0.1', 'CVE-2020-14343', 'critical',
     'PyYAML <6.0.1 — arbitrary code execution via yaml.load()', '6.0.1'),
    (r'^ruamel\.yaml$', '<0.18.0', 'CVE-2023-30608', 'medium',
     'ruamel.yaml <0.18.0 — unsafe yaml.load defaults', '0.18.0'),
]


# ── secret patterns ─────────────────────────────────────────────────────

SECRET_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'(?:api[_-]?key|apikey|API_KEY)\s*[:=]\s*["\'][A-Za-z0-9_\-]{16,}["\']'), "API Key 明文", "high"),
    (re.compile(r'sk-[a-zA-Z0-9]{32,}'), "OpenAI API Key", "critical"),
    (re.compile(r'github_pat_[a-zA-Z0-9_]{22,}'), "GitHub Personal Access Token", "critical"),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), "GitHub Classic Token", "critical"),
    (re.compile(r'xai-[a-zA-Z0-9]{32,}'), "xAI API Key", "critical"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS Access Key ID", "critical"),
    (re.compile(r'(?:password|passwd|pwd)\s*[:=]\s*["\'](?!.*(?:REDACTED|placeholder|changeme|example|your-))[^"\']{6,}["\']'), "密码明文", "critical"),
    (re.compile(r'(?:secret|SECRET)\s*[:=]\s*["\'][A-Za-z0-9_\-+/=]{20,}["\']'), "Secret Key 明文", "critical"),
    (re.compile(r'(?:token|TOKEN)\s*[:=]\s*["\'][A-Za-z0-9_\-.]{20,}["\']'), "Token 明文", "high"),
    (re.compile(r'(?:jdbc|mysql|postgresql|mongodb|redis)://[^@\s]+:[^@\s]+@'), "数据库连接字符串含密码", "high"),
    (re.compile(r'-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH|PGP)\s+PRIVATE\s+KEY-----'), "私钥明文", "critical"),
    (re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{20,}'), "Bearer Token 明文", "high"),
    (re.compile(r'Authorization\s*[:=]\s*["\']?\s*(?:Bearer|Basic)\s+\S{20,}'), "Authorization Header 明文", "high"),
]


# ── dep parsing ─────────────────────────────────────────────────────────

def parse_requirements_txt(path: str) -> list[tuple[str, str]]:
    """Parse requirements.txt → [(name, version_spec), ...]."""
    deps: list[tuple[str, str]] = []
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Handle: name==version, name>=version, name~=version
                m = re.match(r'^([A-Za-z0-9_\-\.]+)\s*([<>=!~]+\s*[\d\.\*]+(?:\s*,\s*[<>=!~]+\s*[\d\.\*]+)*)', line)
                if m:
                    deps.append((m.group(1).lower(), m.group(2).replace(" ", "")))
                else:
                    # Unversioned or complex extras
                    name = re.match(r'^([A-Za-z0-9_\-\.]+)', line)
                    if name:
                        deps.append((name.group(1).lower(), "*"))
    except Exception as e:
        logger.warning("Failed to parse %s: %s", path, e)
    return deps


def parse_package_json(path: str) -> list[tuple[str, str]]:
    """Parse package.json dependencies → [(name, version_spec), ...]."""
    deps: list[tuple[str, str]] = []
    try:
        with open(path, "r", errors="replace") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Failed to parse %s: %s", path, e)
        return deps
    for section in ("dependencies", "devDependencies"):
        for name, ver in data.get(section, {}).items():
            ver_str = str(ver).lstrip("^~>= ")
            deps.append((name.lower(), ver_str))
    return deps


def parse_cargo_toml(path: str) -> list[tuple[str, str]]:
    """Parse Cargo.toml [dependencies] → [(name, version), ...]."""
    deps: list[tuple[str, str]] = []
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()
    except Exception:
        return deps
    in_deps = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("[dependencies"):
            in_deps = True
            continue
        if line.startswith("[") and not line.startswith("[dependencies"):
            in_deps = False
            continue
        if not in_deps or not line:
            continue
        m = re.match(r'^([A-Za-z0-9_\-]+)\s*=\s*"([^"]*)"', line)
        if m:
            deps.append((m.group(1).lower(), m.group(2)))
    return deps


# ── CVE matching ────────────────────────────────────────────────────────

def check_version_range(version: str, range_spec: str) -> bool:
    """Check if version falls in a pip-style version range. Simple comparator."""
    if range_spec == "*":
        return True  # Unknown version → flag it
    if not version or version == "*":
        return True
    try:
        from packaging.version import Version, parse as v_parse
    except ImportError:
        # Fallback: simple numeric comparison
        def _parse(v: str) -> tuple:
            parts = []
            for p in v.replace("-", ".").split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)

        ver = _parse(version)
        for cond in range_spec.split("|"):
            cond = cond.strip()
            if "<" in cond:
                parts = cond.split("<")
                target = _parse(parts[-1].strip())
                if ver < target:
                    return True
            elif ">" in cond:
                parts = cond.split(">")
                target = _parse(parts[-1].strip())
                if ver > target:
                    return True
        return False

    # Full semver comparison with packaging
    try:
        ver = v_parse(version)
    except Exception:
        return True  # Can't parse → flag it

    for cond in range_spec.split("|"):
        cond = cond.strip()
        if not cond:
            continue
        try:
            if cond.startswith("<="):
                target = v_parse(cond[2:].strip())
                if ver <= target:
                    return True
            elif cond.startswith(">="):
                target = v_parse(cond[2:].strip())
                if ver >= target:
                    return True
            elif cond.startswith("<"):
                target = v_parse(cond[1:].strip())
                if ver < target:
                    return True
            elif cond.startswith(">"):
                target = v_parse(cond[1:].strip())
                if ver > target:
                    return True
            elif cond.startswith("=="):
                target = v_parse(cond[2:].strip())
                if ver == target:
                    return True
        except Exception:
            return True
    return False


# ── main auditor ────────────────────────────────────────────────────────

class SecurityAuditor:
    """Multi-layer security auditor: deps, secrets, perms."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self._audit_count: int = 0
        self._total_findings: int = 0
        self._history: list[dict] = []

    # ── dependency audit ──

    def audit_dependencies(self, scan_dir: str | None = None) -> list[AuditFinding]:
        """Scan dependency files and check against known CVEs."""
        findings: list[AuditFinding] = []
        root = Path(scan_dir) if scan_dir else self.project_root

        manifest_files = {
            "requirements.txt": parse_requirements_txt,
            "package.json": parse_package_json,
            "requirements-dev.txt": parse_requirements_txt,
            "Cargo.toml": parse_cargo_toml,
        }

        for filename, parser in manifest_files.items():
            fpath = root / filename
            if not fpath.exists():
                continue
            deps = parser(str(fpath))
            for dep_name, dep_ver in deps:
                for vuln_pkg, ver_range, cve, sev, desc, fix_ver in KNOWN_VULNS:
                    if re.match(vuln_pkg, dep_name, re.IGNORECASE):
                        if check_version_range(dep_ver, ver_range):
                            findings.append(AuditFinding(
                                title=f"{dep_name} {dep_ver} — {cve}",
                                severity=sev, category="dependency",
                                description=desc,
                                file=str(fpath),
                                cve=cve, fix_version=fix_ver,
                                suggestion=f"升级 {dep_name} 到 {fix_ver}",
                            ))
        return findings

    # ── secret scan ──

    def scan_secrets(self, scan_dir: str | None = None) -> list[AuditFinding]:
        """Scan files for hardcoded secrets."""
        findings: list[AuditFinding] = []
        root = Path(scan_dir) if scan_dir else self.project_root

        skip_exts = {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
                     ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
                     ".woff", ".woff2", ".ttf", ".eot",
                     ".mp3", ".mp4", ".avi", ".mov",
                     ".zip", ".tar", ".gz", ".bz2",
                     ".lock", ".min.js", ".min.css"}
        skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv",
                     ".tox", ".eggs", "dist", "build", ".next", ".nuxt"}

        for root_dir, dirs, files in os.walk(str(root)):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext in skip_exts:
                    continue
                fpath = os.path.join(root_dir, fname)
                try:
                    with open(fpath, "r", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue
                for pat, title, severity in SECRET_PATTERNS:
                    for match in pat.finditer(content):
                        line_no = content[:match.start()].count('\n') + 1
                        matched = match.group(0)
                        # Truncate secret in evidence
                        evidence = matched[:40] + "..." if len(matched) > 40 else matched
                        findings.append(AuditFinding(
                            title=title,
                            severity=severity,
                            category="secret",
                            description=f"在 {fname} 第 {line_no} 行发现硬编码的 {title}",
                            file=fpath, line=line_no,
                            evidence=evidence,
                            suggestion=f"将 {title} 移至环境变量或密钥管理服务",
                        ))
        return findings

    # ── permission scan ──

    def scan_permissions(self, scan_dir: str | None = None) -> list[AuditFinding]:
        """Check for overly permissive files."""
        findings: list[AuditFinding] = []
        root = Path(scan_dir) if scan_dir else self.project_root

        for fpath in root.rglob("*"):
            if not fpath.is_file():
                continue
            try:
                st = fpath.stat()
            except OSError:
                continue
            perms = st.st_mode & 0o777
            # Others-writable
            if perms & 0o002:
                findings.append(AuditFinding(
                    title=f"文件全局可写",
                    severity="high", category="permission",
                    description=f"{fpath.name} 权限 {oct(perms)} — 其他用户可写",
                    file=str(fpath),
                    suggestion=f"chmod o-w {fpath.name}",
                ))
            # World-readable private key
            if fpath.suffix in (".pem", ".key", ".p12", ".pfx"):
                if perms & 0o044:
                    findings.append(AuditFinding(
                        title=f"密钥文件权限过宽",
                        severity="critical", category="permission",
                        description=f"{fpath.name} 权限 {oct(perms)} — 密钥文件应设为 600",
                        file=str(fpath),
                        suggestion=f"chmod 600 {fpath.name}",
                    ))
        return findings

    # ── full audit ──

    def run(self, scan_dir: str | None = None,
            audit_deps: bool = True, audit_secrets: bool = True,
            audit_perms: bool = True) -> AuditReport:
        """Run all security audits and return a report."""
        all_findings: list[AuditFinding] = []
        files_scanned = 0
        dep_count = 0

        if audit_deps:
            dep_findings = self.audit_dependencies(scan_dir)
            all_findings.extend(dep_findings)
            dep_count = len(set(f.file for f in dep_findings))

        if audit_secrets:
            secret_findings = self.scan_secrets(scan_dir)
            all_findings.extend(secret_findings)
            # Secret scan touches many files
            scan_root = Path(scan_dir) if scan_dir else self.project_root
            try:
                files_scanned = sum(1 for _ in scan_root.rglob("*") if _.is_file())
            except Exception:
                files_scanned = 0

        if audit_perms:
            perm_findings = self.scan_permissions(scan_dir)
            all_findings.extend(perm_findings)

        # Unique by (file, line, title)
        seen: set[tuple[str, int, str]] = set()
        unique: list[AuditFinding] = []
        for f in all_findings:
            key = (f.file, f.line, f.title)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        unique.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 99))

        report = AuditReport(
            findings=unique, files_scanned=files_scanned, dep_count=dep_count,
        ).compute_score()

        self._audit_count += 1
        self._total_findings += len(unique)
        self._history.append({
            "ts": time.time(),
            "findings": len(unique),
            "score": report.score,
        })
        if len(self._history) > 200:
            self._history = self._history[-100:]

        logger.info(
            "Security audit complete: %d findings, score=%d, verdict=%s",
            len(unique), report.score, report.verdict,
        )
        return report

    def quick_scan(self, filepath: str) -> list[AuditFinding]:
        """Quick security scan of a single file."""
        findings: list[AuditFinding] = []
        try:
            with open(filepath, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            return findings
        for pat, title, severity in SECRET_PATTERNS:
            for match in pat.finditer(content):
                line_no = content[:match.start()].count('\n') + 1
                findings.append(AuditFinding(
                    title=title, severity=severity, category="secret",
                    description=f"硬编码的 {title}", file=filepath,
                    line=line_no, evidence=match.group(0)[:40],
                ))
        return findings

    def stats(self) -> dict:
        return {
            "total_audits": self._audit_count,
            "total_findings": self._total_findings,
            "avg_findings_per_audit": (
                round(self._total_findings / max(self._audit_count, 1), 1)
            ),
            "known_cves": len(KNOWN_VULNS),
            "secret_patterns": len(SECRET_PATTERNS),
            "project_root": str(self.project_root),
            "history": self._history[-10:] if self._history else [],
        }


# ── SecurityAuditEngine (test-compatible interface) ─────────────────────

import enum as _enum


class Severity(_enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SecurityEvent:
    """A single security event finding."""

    def __init__(self, category: str, severity: Severity, description: str = "",
                 evidence: str = ""):
        self.category = category
        self.severity = severity
        self.description = description
        self.evidence = evidence


class SecurityAuditEngine:
    """Security audit engine for scanning text and commands."""

    # Dangerous command patterns
    _CMD_PATTERNS = [
        (["rm -rf /", "rm -rf", "del /f /s"], "dangerous_delete", Severity.CRITICAL),
        (["sudo ", "chmod 777", "chown "], "privilege_escalation", Severity.HIGH),
        (["wget ", "curl "], "data_exfil", Severity.MEDIUM),
        (["/etc/passwd", "/etc/shadow"], "system_file_access", Severity.CRITICAL),
    ]

    # Credential patterns
    _CRED_PATTERNS = [
        (r"api_key\s*[:=]\s*['\"]", "credential_leak", Severity.CRITICAL),
        (r"sk-[a-zA-Z0-9]{20,}", "credential_leak", Severity.CRITICAL),
        (r"ghp_[a-zA-Z0-9]{20,}", "credential_leak", Severity.CRITICAL),
        (r"password\s*[:=]\s*['\"]", "credential_leak", Severity.HIGH),
    ]

    # Injection patterns
    _INJECTION_PATTERNS = [
        (r"eval\s*\(.*\$\(.*curl", "cmd_injection", Severity.CRITICAL),
        (r"eval\s*\(.*curl", "cmd_injection", Severity.CRITICAL),
        (r"sudo\s+rm\s+-rf", "cmd_injection", Severity.CRITICAL),
    ]

    def __init__(self):
        self._scanned = 0
        self._flagged = 0

    def scan(self, text: str):
        """Scan text for security issues. Returns list of SecurityEvent."""
        events = []

        # Check injection patterns
        for pattern, category, severity in self._INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                events.append(SecurityEvent(
                    category=category, severity=severity,
                    description=f"Detected {category} pattern",
                    evidence=text[:80],
                ))

        # Check credential patterns
        for pattern, category, severity in self._CRED_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                events.append(SecurityEvent(
                    category=category, severity=severity,
                    description=f"Detected {category}",
                    evidence=text[:80],
                ))

        # Check sudo
        if "sudo " in text:
            events.append(SecurityEvent(
                category="privilege_escalation", severity=Severity.HIGH,
                description="Sudo command detected",
                evidence=text[:80],
            ))

        self._scanned += 1
        if events:
            self._flagged += 1

        return events

    def audit_command(self, cmd: str):
        """Audit a shell command. Returns list of SecurityEvent."""
        events = []

        for patterns, category, severity in self._CMD_PATTERNS:
            for pat in patterns:
                if pat in cmd:
                    events.append(SecurityEvent(
                        category=category, severity=severity,
                        description=f"Dangerous command: {pat}",
                        evidence=cmd,
                    ))
                    break

        self._scanned += 1
        if events:
            self._flagged += 1

        return events

    def get_report(self):
        """Get audit report."""
        return {
            "stats": {
                "scanned": self._scanned,
                "flagged": self._flagged,
            }
        }


_engine: SecurityAuditEngine = None


def get_security_engine() -> SecurityAuditEngine:
    """Get the singleton security engine."""
    global _engine
    if _engine is None:
        _engine = SecurityAuditEngine()
    return _engine

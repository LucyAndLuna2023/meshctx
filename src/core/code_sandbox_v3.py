"""meshctx code_sandbox_v3 — v3.115.17: Docker isolation + subprocess hardening"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import tempfile
import time
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SandboxLanguage(Enum):
    PYTHON = "python"
    BASH = "bash"
    JAVASCRIPT = "javascript"
    GO = "go"


class SandboxStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class SandboxRiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AuditEntry:
    language: SandboxLanguage = SandboxLanguage.PYTHON
    code_hash: str = ""
    status: SandboxStatus = SandboxStatus.SUCCESS
    risk_level: SandboxRiskLevel = SandboxRiskLevel.LOW
    timestamp: str = ""
    execution_id: str = ""


@dataclass
class CodeSandboxResult:
    output: str = ""
    error: str = ""
    exit_code: int = 0
    status: SandboxStatus = SandboxStatus.SUCCESS
    language: SandboxLanguage = SandboxLanguage.PYTHON
    execution_id: str = ""
    truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "status": self.status.value,
            "language": self.language.value,
            "execution_id": self.execution_id,
            "truncated": self.truncated,
        }


CRITICAL_PATTERNS = [
    r'rm\s+-rf\s+/',
    r'>\s*/dev/sda',
    r'mkfs\.',
    r'dd\s+if=',
    r'fork\s*bomb',
    r':\(\)\s*\{\s*:\|:&\s*\};:',
]


HIGH_RISK_PATTERNS = [
    r'os\.system\s*\(',
    r'subprocess\.',
    r'__import__\s*\(',
    r'eval\s*\(',
    r'exec\s*\(',
    r'open\s*\(.*[\'\"][wWa]',
    r'socket\.',
    r'requests\.',
]

# Docker sandbox constants
_DOCKER_IMAGE = "meshctx-sandbox:latest"
_DOCKER_MEMORY_LIMIT = "512m"
_DOCKER_CPU_LIMIT = 1.0
_DOCKER_TIMEOUT_EXTRA = 5  # extra seconds for Docker overhead


def _security_scan(code: str, language: SandboxLanguage) -> SandboxRiskLevel:
    import re
    for pat in CRITICAL_PATTERNS:
        if re.search(pat, code):
            return SandboxRiskLevel.CRITICAL
    for pat in HIGH_RISK_PATTERNS:
        if re.search(pat, code):
            return SandboxRiskLevel.HIGH
    return SandboxRiskLevel.LOW


def _set_resource_limits():
    """Set resource limits for subprocess hardening (Unix only)."""
    try:
        import resource
        # CPU time: 30s soft, 35s hard
        resource.setrlimit(resource.RLIMIT_CPU, (30, 35))
        # Address space: 512MB
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 1024 * 1024 * 1024))
        # File size: 100MB
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 200 * 1024 * 1024))
        # NPROC: prevent fork bombs (max 50 processes)
        resource.setrlimit(resource.RLIMIT_NPROC, (50, 100))
        # NOFILE: limit open files
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 512))
    except Exception:
        pass  # resource module not available (e.g. Windows)


class CodeSandboxV3:
    def __init__(self, use_docker: bool | None = None, timeout: int = 30,
                 max_output: int = 100000, enable_security_scan: bool = True):
        if use_docker is None:
            use_docker = self._detect_docker()
        self._docker_available = bool(use_docker) if use_docker is not None else False
        self._timeout = timeout
        self._max_output = max_output
        self._enable_security_scan = enable_security_scan
        self._audit_entries: list[AuditEntry] = []
        self._exec_counter = 0

    def _detect_docker(self) -> bool:
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def _gen_execution_id(self) -> str:
        self._exec_counter += 1
        return f"exec_{int(time.time() * 1000)}_{self._exec_counter}"

    def _truncate(self, text: str) -> tuple[str, bool]:
        if len(text) > self._max_output:
            return text[:self._max_output], True
        return text, False

    def _add_audit(self, code: str, language: SandboxLanguage, status: SandboxStatus,
                   risk_level: SandboxRiskLevel, execution_id: str):
        code_hash = hashlib.sha256(code.encode("utf-8", errors="replace")).hexdigest()
        entry = AuditEntry(
            language=language, code_hash=code_hash, status=status,
            risk_level=risk_level, timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            execution_id=execution_id,
        )
        self._audit_entries.append(entry)

    # ── Docker execution ───────────────────────────────────

    def _run_in_docker(self, code: str, language: SandboxLanguage,
                       timeout: int, exec_id: str,
                       risk_level: SandboxRiskLevel) -> CodeSandboxResult:
        """Execute code in an isolated Docker container."""
        ext_map = {
            SandboxLanguage.PYTHON: ".py",
            SandboxLanguage.BASH: ".sh",
            SandboxLanguage.JAVASCRIPT: ".js",
            SandboxLanguage.GO: ".go",
        }
        cmd_map = {
            SandboxLanguage.PYTHON: ["python3"],
            SandboxLanguage.BASH: ["bash"],
            SandboxLanguage.JAVASCRIPT: ["node"],
            SandboxLanguage.GO: ["go", "run"],
        }
        ext = ext_map.get(language, ".txt")
        cmd = cmd_map.get(language, ["cat"])

        tmpdir = tempfile.mkdtemp(prefix="sandbox_")
        code_path = os.path.join(tmpdir, f"code{ext}")
        try:
            with open(code_path, "w") as f:
                f.write(code)

            docker_cmd = [
                "docker", "run", "--rm",
                "--network=none",
                f"--memory={_DOCKER_MEMORY_LIMIT}",
                f"--cpus={_DOCKER_CPU_LIMIT}",
                "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
                "--security-opt=no-new-privileges",
                "--cap-drop=ALL",
                "--pids-limit=100",
                "-v", f"{code_path}:/sandbox/code{ext}:ro",
                "-w", "/sandbox",
                _DOCKER_IMAGE,
            ] + cmd + [f"/sandbox/code{ext}"]

            result = subprocess.run(
                docker_cmd,
                capture_output=True, text=True,
                timeout=timeout + _DOCKER_TIMEOUT_EXTRA,
            )
            output, truncated = self._truncate(result.stdout)
            status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
            self._add_audit(code, language, status, risk_level, exec_id)
            return CodeSandboxResult(
                output=output, error=result.stderr, exit_code=result.returncode,
                status=status, language=language, execution_id=exec_id,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            self._add_audit(code, language, SandboxStatus.TIMEOUT, risk_level, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT: execution exceeded time limit",
                status=SandboxStatus.TIMEOUT, language=language,
                execution_id=exec_id,
            )
        except FileNotFoundError:
            # Docker not found — fall through to subprocess
            return self._run_subprocess(code, language, timeout, exec_id, risk_level)
        except Exception as e:
            self._add_audit(code, language, SandboxStatus.ERROR, risk_level, exec_id)
            return CodeSandboxResult(
                error=str(e), status=SandboxStatus.ERROR,
                language=language, execution_id=exec_id,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── Subprocess execution (hardened) ────────────────────

    def _run_subprocess(self, code: str, language: SandboxLanguage,
                        timeout: int, exec_id: str,
                        risk_level: SandboxRiskLevel) -> CodeSandboxResult:
        """Execute code via subprocess with resource limits (fallback when no Docker)."""
        try:
            result = subprocess.run(
                self._build_cmd(code, language),
                capture_output=True, text=True, timeout=timeout,
                preexec_fn=_set_resource_limits if os.name != "nt" else None,
            )
            output, truncated = self._truncate(result.stdout)
            status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
            self._add_audit(code, language, status, risk_level, exec_id)
            return CodeSandboxResult(
                output=output, error=result.stderr, exit_code=result.returncode,
                status=status, language=language,
                execution_id=exec_id, truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            self._add_audit(code, language, SandboxStatus.TIMEOUT, risk_level, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT: execution exceeded time limit",
                status=SandboxStatus.TIMEOUT, language=language,
                execution_id=exec_id,
            )
        except Exception as e:
            self._add_audit(code, language, SandboxStatus.ERROR, risk_level, exec_id)
            return CodeSandboxResult(
                error=str(e), status=SandboxStatus.ERROR,
                language=language, execution_id=exec_id,
            )

    def _build_cmd(self, code: str, language: SandboxLanguage) -> list:
        """Build the appropriate command for each language."""
        if language == SandboxLanguage.PYTHON:
            return ["python3", "-c", code]
        elif language == SandboxLanguage.BASH:
            return ["bash", "-c", code]
        elif language == SandboxLanguage.JAVASCRIPT:
            return ["node", "-e", code]
        elif language == SandboxLanguage.GO:
            # Go needs temp file — handled separately
            raise NotImplementedError("Go in subprocess not supported, use Docker")
        else:
            raise ValueError(f"Unsupported language: {language}")

    # ── Main execution entry ───────────────────────────────

    def run(self, code: str, language: SandboxLanguage | None = None,
            timeout: int | None = None) -> CodeSandboxResult:
        exec_id = self._gen_execution_id()
        lang = language or SandboxLanguage.PYTHON
        risk_level = SandboxRiskLevel.LOW

        if self._enable_security_scan:
            risk = _security_scan(code, lang)
            risk_level = risk
            if risk in (SandboxRiskLevel.CRITICAL, SandboxRiskLevel.HIGH):
                self._add_audit(code, lang, SandboxStatus.REJECTED, risk, exec_id)
                return CodeSandboxResult(
                    error="Code rejected by security scan",
                    status=SandboxStatus.REJECTED, language=lang,
                    execution_id=exec_id,
                )

        effective_timeout = timeout if timeout is not None else self._timeout

        # Prefer Docker when available
        if self._docker_available:
            return self._run_in_docker(code, lang, effective_timeout, exec_id, risk_level)

        # Fallback: hardened subprocess
        if lang == SandboxLanguage.GO:
            return self._run_go_impl(code, effective_timeout, exec_id, risk_level)
        return self._run_subprocess(code, lang, effective_timeout, exec_id, risk_level)

    # ── Convenience methods ────────────────────────────────

    def run_python(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.PYTHON)

    def run_bash(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.BASH)

    def run_javascript(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.JAVASCRIPT)

    # ── Go implementation (tempfile + subprocess) ──────────

    def _run_go_impl(self, code: str, timeout: int, exec_id: str,
                     risk_level: SandboxRiskLevel = SandboxRiskLevel.LOW) -> CodeSandboxResult:
        try:
            with tempfile.NamedTemporaryFile(suffix=".go", mode="w", delete=False) as f:
                f.write(code)
                go_path = f.name
            exe_path = go_path + ".out"
            try:
                compile_result = subprocess.run(
                    ["go", "build", "-o", exe_path, go_path],
                    capture_output=True, text=True, timeout=timeout,
                    preexec_fn=_set_resource_limits if os.name != "nt" else None,
                )
                if compile_result.returncode != 0:
                    self._add_audit(code, SandboxLanguage.GO, SandboxStatus.ERROR, risk_level, exec_id)
                    return CodeSandboxResult(
                        error=compile_result.stderr, exit_code=compile_result.returncode,
                        status=SandboxStatus.ERROR, language=SandboxLanguage.GO,
                        execution_id=exec_id,
                    )
                result = subprocess.run(
                    [exe_path],
                    capture_output=True, text=True, timeout=timeout,
                    preexec_fn=_set_resource_limits if os.name != "nt" else None,
                )
                output, truncated = self._truncate(result.stdout)
                status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
                self._add_audit(code, SandboxLanguage.GO, status, risk_level, exec_id)
                return CodeSandboxResult(
                    output=output, error=result.stderr, exit_code=result.returncode,
                    status=status, language=SandboxLanguage.GO,
                    execution_id=exec_id, truncated=truncated,
                )
            finally:
                for p in [go_path, exe_path]:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
        except subprocess.TimeoutExpired:
            self._add_audit(code, SandboxLanguage.GO, SandboxStatus.TIMEOUT, risk_level, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT", status=SandboxStatus.TIMEOUT,
                language=SandboxLanguage.GO, execution_id=exec_id,
            )

    def run_go(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.GO)

    # ── Audit ──────────────────────────────────────────────

    def get_audit_entries(self) -> list[AuditEntry]:
        return list(self._audit_entries)

    def export_audit_log(self, path: str) -> str:
        with open(path, "w") as f:
            json.dump([{
                "language": e.language.value,
                "code_hash": e.code_hash,
                "status": e.status.value,
                "risk_level": e.risk_level.value,
                "timestamp": e.timestamp,
                "execution_id": e.execution_id,
            } for e in self._audit_entries], f)
        return path

    def clear_audit_log(self):
        self._audit_entries.clear()

    def available_runtimes(self) -> list[SandboxLanguage]:
        runtimes = [SandboxLanguage.PYTHON, SandboxLanguage.BASH]
        import shutil as _shutil
        if _shutil.which("node"):
            runtimes.append(SandboxLanguage.JAVASCRIPT)
        if _shutil.which("go"):
            runtimes.append(SandboxLanguage.GO)
        return runtimes


# ── Singleton ──────────────────────────────────────────────

_code_sandbox_v3_instance: CodeSandboxV3 | None = None


def get_code_sandbox_v3(**kwargs) -> CodeSandboxV3:
    global _code_sandbox_v3_instance
    if _code_sandbox_v3_instance is None:
        _code_sandbox_v3_instance = CodeSandboxV3(**kwargs)
    return _code_sandbox_v3_instance


def reset_code_sandbox_v3():
    global _code_sandbox_v3_instance
    _code_sandbox_v3_instance = None

"""
meshctx v3.97 — Code Sandbox V3 (增强版代码沙箱)

升级特性 vs v3.74 CodeSandboxV2:
1) Docker隔离执行 (可选, 默认自动检测)
2) 多语言支持 (Python / Bash / JavaScript-Node / Go)
3) 资源限制 (CPU shares / Memory limit / Timeout)
4) 安全审计日志 (完整执行记录+hash+风险评分)

Design: Docker优先 → 子进程fallback, 单例模式, 审计日志持久化.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("meshctx.code_sandbox_v3")

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

DEFAULT_TIMEOUT = 30          # seconds
DEFAULT_MAX_OUTPUT = 100_000  # bytes
DEFAULT_CPU_SHARES = 512      # Docker CPU shares (1024 = 1 core)
DEFAULT_MEMORY_MB = 256       # MB
AUDIT_LOG_KEY = "code_sandbox_v3_audit"
SAFE_PYTHON_BLACKLIST = [
    "import os", "import subprocess", "import shutil", "import sys",
    "import ctypes", "import socket", "import urllib", "import http",
    "import ftplib", "import smtplib", "import telnetlib",
    "__import__", "exec(", "eval(", "compile(", "open(", "breakpoint(",
    "globals()", "locals()", "getattr(", "setattr(", "delattr(",
    "execfile", "input(", "raw_input(",
]


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class SandboxLanguage(str, Enum):
    """Supported execution languages."""
    PYTHON = "python"
    BASH = "bash"
    JAVASCRIPT = "javascript"
    GO = "go"


class SandboxRiskLevel(str, Enum):
    """Security risk assessment levels."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SandboxStatus(str, Enum):
    """Execution status."""
    SUCCESS = "success"
    TIMEOUT = "timeout"
    OOM = "oom"              # Out of memory
    ERROR = "error"
    REJECTED = "rejected"    # Code blocked by security check


# ═══════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════

@dataclass
class CodeSandboxResult:
    """Result of a sandbox execution."""
    output: str = ""
    error: str = ""
    exit_code: int = -1
    duration_ms: float = 0.0
    truncated: bool = False
    status: SandboxStatus = SandboxStatus.ERROR
    language: Optional[SandboxLanguage] = None
    execution_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "status": self.status.value,
            "language": self.language.value if self.language else None,
            "execution_id": self.execution_id,
        }


@dataclass
class AuditEntry:
    """Security audit log entry."""
    execution_id: str
    timestamp: float = field(default_factory=time.time)
    language: SandboxLanguage = SandboxLanguage.PYTHON
    code_hash: str = ""         # SHA256 of source code
    code_snippet: str = ""      # first 200 chars
    risk_level: SandboxRiskLevel = SandboxRiskLevel.SAFE
    risk_reasons: List[str] = field(default_factory=list)
    resource_limits: Dict[str, Any] = field(default_factory=dict)
    status: SandboxStatus = SandboxStatus.ERROR
    exit_code: int = -1
    duration_ms: float = 0.0
    docker_used: bool = False
    hostname: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "timestamp": self.timestamp,
            "language": self.language.value,
            "code_hash": self.code_hash,
            "code_snippet": self.code_snippet,
            "risk_level": self.risk_level.value,
            "risk_reasons": self.risk_reasons,
            "resource_limits": self.resource_limits,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "docker_used": self.docker_used,
            "hostname": self.hostname,
        }


# ═══════════════════════════════════════════════════════════════
# Main Class: CodeSandboxV3
# ═══════════════════════════════════════════════════════════════

class CodeSandboxV3:
    """
    增强版代码沙箱 — Docker隔离 + 多语言 + 资源限制 + 审计日志.

    使用方式:
        sandbox = CodeSandboxV3()
        result = sandbox.run("print('hello')", language=SandboxLanguage.PYTHON)
        # 或快捷方法:
        result = sandbox.run_python("print('hello')")
        result = sandbox.run_bash("echo hi")
        result = sandbox.run_javascript("console.log('hi')")
        result = sandbox.run_go('package main; import "fmt"; func main() {fmt.Println("hi")}')
    """

    # ── Constructor ──────────────────────────────────────────

    def __init__(
        self,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_output: int = DEFAULT_MAX_OUTPUT,
        cpu_shares: int = DEFAULT_CPU_SHARES,
        memory_mb: int = DEFAULT_MEMORY_MB,
        use_docker: Optional[bool] = None,
        audit_log_path: Optional[str] = None,
        enable_security_scan: bool = True,
    ):
        """
        Args:
            timeout: Execution timeout in seconds.
            max_output: Max output bytes before truncation.
            cpu_shares: Docker CPU shares (1024 = 1 vCPU).
            memory_mb: Memory limit in MB.
            use_docker: If None, auto-detect Docker availability.
            audit_log_path: Path to audit log JSON file. If None, log to logger only.
            enable_security_scan: Whether to scan code for dangerous patterns.
        """
        self.timeout = timeout
        self.max_output = max_output
        self.cpu_shares = cpu_shares
        self.memory_mb = memory_mb
        self.enable_security_scan = enable_security_scan

        # Docker auto-detection
        if use_docker is None:
            self._docker_available = self._detect_docker()
        else:
            self._docker_available = use_docker and self._detect_docker()

        self.audit_log_path = audit_log_path
        self._audit_entries: List[AuditEntry] = []
        self._audit_lock = threading.Lock()
        self._hostname = os.uname().nodename if hasattr(os, "uname") else "unknown"

        if self._docker_available:
            logger.info("CodeSandboxV3: Docker detected — using container isolation")
        else:
            logger.info("CodeSandboxV3: Docker unavailable — using subprocess fallback")

    # ── Public API ───────────────────────────────────────────

    def run(
        self,
        code: str,
        language: SandboxLanguage = SandboxLanguage.PYTHON,
        *,
        stdin: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> CodeSandboxResult:
        """Execute code in the sandboxed environment.

        Args:
            code: Source code to execute.
            language: Target language.
            stdin: Optional stdin input.
            timeout: Override default timeout.

        Returns:
            CodeSandboxResult with output/error/status.
        """
        execution_id = str(uuid.uuid4())
        t0 = time.perf_counter()
        effective_timeout = timeout if timeout is not None else self.timeout

        # Step 1: Security scan
        risk = SandboxRiskLevel.SAFE
        risk_reasons: List[str] = []
        if self.enable_security_scan:
            risk, risk_reasons = self._scan_code(code, language)
            if risk == SandboxRiskLevel.CRITICAL:
                audit = self._make_audit(
                    execution_id, code, language, risk, risk_reasons,
                    SandboxStatus.REJECTED, -1, t0,
                )
                self._log_audit(audit)
                return CodeSandboxResult(
                    error=f"Code rejected by security scan: {'; '.join(risk_reasons)}",
                    status=SandboxStatus.REJECTED,
                    language=language,
                    execution_id=execution_id,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

        # Step 2: Execute
        if self._docker_available:
            result = self._run_in_docker(code, language, execution_id,
                                         effective_timeout, stdin)
        else:
            result = self._run_subprocess(code, language, execution_id,
                                          effective_timeout, stdin)

        # Step 3: Audit log
        audit = self._make_audit(
            execution_id, code, language, risk, risk_reasons,
            result.status, result.exit_code, t0,
        )
        self._log_audit(audit)

        return result

    def run_python(self, code: str, *, timeout: Optional[int] = None) -> CodeSandboxResult:
        """Shortcut: run Python code."""
        return self.run(code, SandboxLanguage.PYTHON, timeout=timeout)

    def run_bash(self, code: str, *, timeout: Optional[int] = None) -> CodeSandboxResult:
        """Shortcut: run Bash script."""
        return self.run(code, SandboxLanguage.BASH, timeout=timeout)

    def run_javascript(self, code: str, *, timeout: Optional[int] = None) -> CodeSandboxResult:
        """Shortcut: run JavaScript (Node.js)."""
        return self.run(code, SandboxLanguage.JAVASCRIPT, timeout=timeout)

    def run_go(self, code: str, *, timeout: Optional[int] = None) -> CodeSandboxResult:
        """Shortcut: run Go code."""
        return self.run(code, SandboxLanguage.GO, timeout=timeout)

    # ── Audit API ────────────────────────────────────────────

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent audit entries as dicts."""
        with self._audit_lock:
            return [e.to_dict() for e in self._audit_entries[-limit:]]

    def get_audit_entries(self, limit: int = 100) -> List[AuditEntry]:
        """Return recent raw audit entries."""
        with self._audit_lock:
            return list(self._audit_entries[-limit:])

    def clear_audit_log(self) -> None:
        """Clear in-memory audit log."""
        with self._audit_lock:
            self._audit_entries.clear()

    def export_audit_log(self, path: Optional[str] = None) -> str:
        """Export audit log to JSON file. Returns path."""
        target = path or self.audit_log_path or "code_sandbox_v3_audit.json"
        with self._audit_lock:
            entries = [e.to_dict() for e in self._audit_entries]
        with open(target, "w") as f:
            json.dump(entries, f, indent=2, default=str)
        logger.info(f"Audit log exported to {target} ({len(entries)} entries)")
        return target

    # ── Internal: Docker Detection ───────────────────────────

    @staticmethod
    def _detect_docker() -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            return False

    # ── Internal: Security Scanner ───────────────────────────

    def _scan_code(
        self, code: str, language: SandboxLanguage
    ) -> Tuple[SandboxRiskLevel, List[str]]:
        """Scan code for dangerous patterns. Returns (risk_level, reasons)."""
        reasons: List[str] = []
        risk = SandboxRiskLevel.SAFE

        if language == SandboxLanguage.PYTHON:
            code_lower = code.lower()
            for pattern in SAFE_PYTHON_BLACKLIST:
                if pattern.lower() in code_lower:
                    reasons.append(f"Dangerous pattern: {pattern}")
                    risk = SandboxRiskLevel.HIGH

            # Critical patterns
            critical = ["rm -rf", "dd if=", "mkfs.", "fdisk", "shutdown",
                        "reboot", ":(){ :|:& };:", "fork bomb"]
            for pat in critical:
                if pat.lower() in code_lower:
                    reasons.append(f"CRITICAL pattern: {pat}")
                    risk = SandboxRiskLevel.CRITICAL

        elif language == SandboxLanguage.BASH:
            critical_bash = ["rm -rf /", "mkfs.", "fdisk", "shutdown",
                             "reboot", "dd if=/dev/zero", ":(){ :|:& };:",
                             "fork bomb", "chmod 777 /", "> /dev/sda"]
            for pat in critical_bash:
                if pat.lower() in code.lower():
                    reasons.append(f"CRITICAL pattern: {pat}")
                    risk = SandboxRiskLevel.CRITICAL

        elif language == SandboxLanguage.JAVASCRIPT:
            critical_js = ["require('child_process')", "process.exit",
                           "require('fs')", "fetch(", "XMLHttpRequest",
                           "WebSocket", "eval("]
            for pat in critical_js:
                if pat.lower() in code.lower():
                    reasons.append(f"Suspicious JS pattern: {pat}")
                    if risk.value < SandboxRiskLevel.MEDIUM.value:
                        risk = SandboxRiskLevel.MEDIUM

        elif language == SandboxLanguage.GO:
            critical_go = ["os/exec", "os.RemoveAll", "syscall", "unsafe",
                           "net.Dial", "net/http"]
            for pat in critical_go:
                if pat.lower() in code.lower():
                    reasons.append(f"Suspicious Go pattern: {pat}")
                    if risk.value < SandboxRiskLevel.MEDIUM.value:
                        risk = SandboxRiskLevel.MEDIUM

        return risk, reasons

    # ── Internal: Docker Execution ───────────────────────────

    def _run_in_docker(
        self,
        code: str,
        language: SandboxLanguage,
        execution_id: str,
        timeout: int,
        stdin: Optional[str],
    ) -> CodeSandboxResult:
        """Execute code inside a Docker container."""
        t0 = time.perf_counter()
        docker_image = self._docker_image_for(language)
        cmd = self._docker_command_for(code, language)

        docker_args = [
            "docker", "run", "--rm",
            "--name", f"sandbox_{execution_id[:12]}",
            "--network", "none",                     # no network
            "--cpus", f"{self.cpu_shares / 1024:.2f}",
            "--memory", f"{self.memory_mb}m",
            "--memory-swap", f"{self.memory_mb}m",    # no swap
            "--pids-limit", "64",
            "--read-only",                            # read-only rootfs
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--user", "1000:1000",                    # non-root
            docker_image,
        ] + cmd

        try:
            proc = subprocess.run(
                docker_args,
                capture_output=True, text=True,
                timeout=timeout + 5,   # extra 5s for container overhead
                input=stdin,
            )
            duration = (time.perf_counter() - t0) * 1000

            output = proc.stdout[:self.max_output] if proc.stdout else ""
            error = proc.stderr[:self.max_output] if proc.stderr else ""
            truncated = len(proc.stdout) > self.max_output

            if proc.returncode == 137:
                # Killed by OOM
                return CodeSandboxResult(
                    output=output, error="OOM_KILLED",
                    exit_code=137, duration_ms=duration,
                    truncated=truncated, status=SandboxStatus.OOM,
                    language=language, execution_id=execution_id,
                )

            return CodeSandboxResult(
                output=output, error=error,
                exit_code=proc.returncode, duration_ms=duration,
                truncated=truncated,
                status=SandboxStatus.SUCCESS if proc.returncode == 0 else SandboxStatus.ERROR,
                language=language, execution_id=execution_id,
            )

        except subprocess.TimeoutExpired:
            self._cleanup_container(execution_id)
            return CodeSandboxResult(
                error="TIMEOUT",
                status=SandboxStatus.TIMEOUT,
                language=language, execution_id=execution_id,
                duration_ms=timeout * 1000,
            )
        except Exception as e:
            return CodeSandboxResult(
                error=str(e),
                status=SandboxStatus.ERROR,
                language=language, execution_id=execution_id,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

    @staticmethod
    def _docker_image_for(language: SandboxLanguage) -> str:
        """Return the Docker image for a language."""
        images = {
            SandboxLanguage.PYTHON: "python:3.12-slim",
            SandboxLanguage.BASH: "alpine:3.19",
            SandboxLanguage.JAVASCRIPT: "node:20-slim",
            SandboxLanguage.GO: "golang:1.22-alpine",
        }
        return images[language]

    @staticmethod
    def _docker_command_for(code: str, language: SandboxLanguage) -> List[str]:
        """Build the Docker command for the given language."""
        if language == SandboxLanguage.PYTHON:
            return ["python3", "-c", code]
        elif language == SandboxLanguage.BASH:
            return ["sh", "-c", code]
        elif language == SandboxLanguage.JAVASCRIPT:
            return ["node", "-e", code]
        elif language == SandboxLanguage.GO:
            # Write to temp file, compile and run
            return ["sh", "-c", f"echo '{code}' > /tmp/main.go && go run /tmp/main.go"]
        else:
            raise ValueError(f"Unknown language: {language}")

    @staticmethod
    def _cleanup_container(execution_id: str) -> None:
        """Force-remove a container by name prefix."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", f"sandbox_{execution_id[:12]}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    # ── Internal: Subprocess Fallback ────────────────────────

    def _run_subprocess(
        self,
        code: str,
        language: SandboxLanguage,
        execution_id: str,
        timeout: int,
        stdin: Optional[str],
    ) -> CodeSandboxResult:
        """Execute code via subprocess (fallback when Docker unavailable)."""
        t0 = time.perf_counter()

        try:
            if language == SandboxLanguage.PYTHON:
                result = self._run_python_subprocess(code, timeout, stdin)
            elif language == SandboxLanguage.BASH:
                result = self._run_bash_subprocess(code, timeout, stdin)
            elif language == SandboxLanguage.JAVASCRIPT:
                result = self._run_js_subprocess(code, timeout, stdin)
            elif language == SandboxLanguage.GO:
                result = self._run_go_subprocess(code, timeout, stdin)
            else:
                return CodeSandboxResult(
                    error=f"Unknown language: {language}",
                    status=SandboxStatus.ERROR,
                    language=language, execution_id=execution_id,
                )

            result.language = language
            result.execution_id = execution_id
            return result

        except subprocess.TimeoutExpired:
            return CodeSandboxResult(
                error="TIMEOUT",
                status=SandboxStatus.TIMEOUT,
                language=language, execution_id=execution_id,
                duration_ms=timeout * 1000,
            )
        except Exception as e:
            return CodeSandboxResult(
                error=str(e),
                status=SandboxStatus.ERROR,
                language=language, execution_id=execution_id,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

    def _run_python_subprocess(
        self, code: str, timeout: int, stdin: Optional[str]
    ) -> CodeSandboxResult:
        t0 = time.perf_counter()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            path = f.name
        try:
            proc = subprocess.run(
                ["python3", path],
                capture_output=True, text=True,
                timeout=timeout,
                input=stdin,
                env={**os.environ, "PYTHONPATH": ""},
                preexec_fn=self._set_subprocess_limits if hasattr(os, "setpgrp") else None,
            )
            dur = (time.perf_counter() - t0) * 1000
            out = (proc.stdout or "")[:self.max_output]
            err = (proc.stderr or "")[:self.max_output]
            return CodeSandboxResult(
                output=out, error=err,
                exit_code=proc.returncode, duration_ms=dur,
                truncated=len(proc.stdout or "") > self.max_output,
                status=SandboxStatus.SUCCESS if proc.returncode == 0 else SandboxStatus.ERROR,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _run_bash_subprocess(
        self, code: str, timeout: int, stdin: Optional[str]
    ) -> CodeSandboxResult:
        t0 = time.perf_counter()
        proc = subprocess.run(
            ["bash", "-c", code],
            capture_output=True, text=True,
            timeout=timeout,
            input=stdin,
            env={"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": "/tmp"},
            preexec_fn=self._set_subprocess_limits if hasattr(os, "setpgrp") else None,
        )
        dur = (time.perf_counter() - t0) * 1000
        out = (proc.stdout or "")[:self.max_output]
        err = (proc.stderr or "")[:self.max_output]
        return CodeSandboxResult(
            output=out, error=err,
            exit_code=proc.returncode, duration_ms=dur,
            truncated=len(proc.stdout or "") > self.max_output,
            status=SandboxStatus.SUCCESS if proc.returncode == 0 else SandboxStatus.ERROR,
        )

    def _run_js_subprocess(
        self, code: str, timeout: int, stdin: Optional[str]
    ) -> CodeSandboxResult:
        t0 = time.perf_counter()
        node_bin = shutil.which("node") or "node"
        proc = subprocess.run(
            [node_bin, "-e", code],
            capture_output=True, text=True,
            timeout=timeout,
            input=stdin,
            env={**os.environ, "NODE_PATH": ""},
        )
        dur = (time.perf_counter() - t0) * 1000
        out = (proc.stdout or "")[:self.max_output]
        err = (proc.stderr or "")[:self.max_output]
        return CodeSandboxResult(
            output=out, error=err,
            exit_code=proc.returncode, duration_ms=dur,
            truncated=len(proc.stdout or "") > self.max_output,
            status=SandboxStatus.SUCCESS if proc.returncode == 0 else SandboxStatus.ERROR,
        )

    def _run_go_subprocess(
        self, code: str, timeout: int, stdin: Optional[str]
    ) -> CodeSandboxResult:
        t0 = time.perf_counter()
        go_bin = shutil.which("go") or "go"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".go", delete=False
        ) as f:
            f.write(code)
            path = f.name
        try:
            proc = subprocess.run(
                [go_bin, "run", path],
                capture_output=True, text=True,
                timeout=timeout,
                input=stdin,
                env={**os.environ, "GOPATH": "/tmp/gopath", "GOCACHE": "/tmp/gocache"},
                preexec_fn=self._set_subprocess_limits if hasattr(os, "setpgrp") else None,
            )
            dur = (time.perf_counter() - t0) * 1000
            out = (proc.stdout or "")[:self.max_output]
            err = (proc.stderr or "")[:self.max_output]
            return CodeSandboxResult(
                output=out, error=err,
                exit_code=proc.returncode, duration_ms=dur,
                truncated=len(proc.stdout or "") > self.max_output,
                status=SandboxStatus.SUCCESS if proc.returncode == 0 else SandboxStatus.ERROR,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _set_subprocess_limits() -> None:
        """Set resource limits for subprocess (Unix only)."""
        try:
            import resource
            # Limit CPU time (soft limit)
            resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
            # Limit address space
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            # Limit number of processes
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            # Limit file size
            resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
        except (ImportError, ValueError):
            pass

    # ── Internal: Audit ──────────────────────────────────────

    def _make_audit(
        self,
        execution_id: str,
        code: str,
        language: SandboxLanguage,
        risk: SandboxRiskLevel,
        risk_reasons: List[str],
        status: SandboxStatus,
        exit_code: int,
        t0: float,
    ) -> AuditEntry:
        """Create an audit entry."""
        return AuditEntry(
            execution_id=execution_id,
            language=language,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            code_snippet=code[:200],
            risk_level=risk,
            risk_reasons=risk_reasons,
            resource_limits={
                "timeout": self.timeout,
                "cpu_shares": self.cpu_shares,
                "memory_mb": self.memory_mb,
                "max_output": self.max_output,
            },
            status=status,
            exit_code=exit_code,
            duration_ms=(time.perf_counter() - t0) * 1000,
            docker_used=self._docker_available,
            hostname=self._hostname,
        )

    def _log_audit(self, entry: AuditEntry) -> None:
        """Log audit entry to memory and optionally to file."""
        with self._audit_lock:
            self._audit_entries.append(entry)

        # Log to logger
        log_msg = (
            f"Audit [{entry.execution_id[:8]}]: lang={entry.language.value} "
            f"risk={entry.risk_level.value} status={entry.status.value} "
            f"docker={entry.docker_used} dur={entry.duration_ms:.0f}ms"
        )
        if entry.risk_level in (SandboxRiskLevel.HIGH, SandboxRiskLevel.CRITICAL):
            logger.warning(f"{log_msg} reasons={entry.risk_reasons}")
        else:
            logger.info(log_msg)

        # Persist to file if path configured
        if self.audit_log_path:
            try:
                with open(self.audit_log_path, "a") as f:
                    f.write(json.dumps(entry.to_dict(), default=str) + "\n")
            except Exception:
                logger.exception("Failed to persist audit entry")

    # ── Convenience: detect available runtimes ───────────────

    def available_runtimes(self) -> List[SandboxLanguage]:
        """Return list of available runtimes on this host."""
        runtimes = [SandboxLanguage.PYTHON, SandboxLanguage.BASH]
        if shutil.which("node"):
            runtimes.append(SandboxLanguage.JAVASCRIPT)
        if shutil.which("go"):
            runtimes.append(SandboxLanguage.GO)
        return runtimes


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_code_sandbox_v3: Optional[CodeSandboxV3] = None
_code_sandbox_v3_lock = threading.Lock()


def get_code_sandbox_v3(
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_output: int = DEFAULT_MAX_OUTPUT,
    cpu_shares: int = DEFAULT_CPU_SHARES,
    memory_mb: int = DEFAULT_MEMORY_MB,
    use_docker: Optional[bool] = None,
    audit_log_path: Optional[str] = None,
    enable_security_scan: bool = True,
) -> CodeSandboxV3:
    """Get or create the singleton CodeSandboxV3 instance."""
    global _code_sandbox_v3
    if _code_sandbox_v3 is None:
        with _code_sandbox_v3_lock:
            if _code_sandbox_v3 is None:
                _code_sandbox_v3 = CodeSandboxV3(
                    timeout=timeout,
                    max_output=max_output,
                    cpu_shares=cpu_shares,
                    memory_mb=memory_mb,
                    use_docker=use_docker,
                    audit_log_path=audit_log_path,
                    enable_security_scan=enable_security_scan,
                )
    return _code_sandbox_v3


def reset_code_sandbox_v3() -> None:
    """Reset the singleton (useful for testing)."""
    global _code_sandbox_v3
    with _code_sandbox_v3_lock:
        if _code_sandbox_v3 is not None:
            _code_sandbox_v3.clear_audit_log()
        _code_sandbox_v3 = None

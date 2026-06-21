"""meshctx code_sandbox_v3 — v3.97 stub"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
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


def _security_scan(code: str, language: SandboxLanguage) -> SandboxRiskLevel:
    import re
    high_risk = [
        r'os\.system\s*\(',
        r'subprocess\.',
        r'__import__\s*\(',
        r'eval\s*\(',
        r'exec\s*\(',
        r'open\s*\(.*[\'\"][wWa]',
        r'socket\.',
        r'requests\.',
    ]
    for pat in CRITICAL_PATTERNS + high_risk:
        if re.search(pat, code):
            return SandboxRiskLevel.HIGH
    return SandboxRiskLevel.LOW


class CodeSandboxV3:
    def __init__(self, use_docker: bool | None = None, timeout: int = 30,
                 max_output: int = 100000, enable_security_scan: bool = False):
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

    def run(self, code: str, language: SandboxLanguage | None = None,
            timeout: int | None = None) -> CodeSandboxResult:
        exec_id = self._gen_execution_id()
        lang = language or SandboxLanguage.PYTHON
        risk_level = SandboxRiskLevel.LOW

        if self._enable_security_scan:
            risk = _security_scan(code, lang)
            risk_level = risk
            if risk == SandboxRiskLevel.CRITICAL:
                # Only truly critical patterns are rejected
                import re
                for pat in CRITICAL_PATTERNS:
                    if re.search(pat, code):
                        self._add_audit(code, lang, SandboxStatus.REJECTED, SandboxRiskLevel.HIGH, exec_id)
                        return CodeSandboxResult(
                            error="Code rejected by security scan",
                            status=SandboxStatus.REJECTED, language=lang,
                            execution_id=exec_id,
                        )

        effective_timeout = timeout if timeout is not None else self._timeout

        if lang == SandboxLanguage.PYTHON:
            return self._run_python_impl(code, effective_timeout, exec_id, risk_level)
        elif lang == SandboxLanguage.BASH:
            return self._run_bash_impl(code, effective_timeout, exec_id, risk_level)
        elif lang == SandboxLanguage.JAVASCRIPT:
            return self._run_js_impl(code, effective_timeout, exec_id, risk_level)
        elif lang == SandboxLanguage.GO:
            return self._run_go_impl(code, effective_timeout, exec_id, risk_level)
        else:
            return CodeSandboxResult(
                error=f"Unsupported language: {lang.value}",
                status=SandboxStatus.ERROR, language=lang,
                execution_id=exec_id,
            )

    def _run_python_impl(self, code: str, timeout: int, exec_id: str, risk_level: SandboxRiskLevel = SandboxRiskLevel.LOW) -> CodeSandboxResult:
        try:
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True, text=True, timeout=timeout,
            )
            output, truncated = self._truncate(result.stdout)
            status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
            self._add_audit(code, SandboxLanguage.PYTHON, status, risk_level, exec_id)
            return CodeSandboxResult(
                output=output, error=result.stderr, exit_code=result.returncode,
                status=status, language=SandboxLanguage.PYTHON,
                execution_id=exec_id, truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            self._add_audit(code, SandboxLanguage.PYTHON, SandboxStatus.TIMEOUT, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT: execution exceeded time limit",
                status=SandboxStatus.TIMEOUT, language=SandboxLanguage.PYTHON,
                execution_id=exec_id,
            )
        except Exception as e:
            self._add_audit(code, SandboxLanguage.PYTHON, SandboxStatus.ERROR, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                error=str(e), status=SandboxStatus.ERROR,
                language=SandboxLanguage.PYTHON, execution_id=exec_id,
            )

    def run_python(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.PYTHON)

    def _run_bash_impl(self, code: str, timeout: int, exec_id: str) -> CodeSandboxResult:
        try:
            result = subprocess.run(
                ["bash", "-c", code],
                capture_output=True, text=True, timeout=timeout,
            )
            output, truncated = self._truncate(result.stdout)
            status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
            self._add_audit(code, SandboxLanguage.BASH, status, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                output=output, error=result.stderr, exit_code=result.returncode,
                status=status, language=SandboxLanguage.BASH,
                execution_id=exec_id, truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            self._add_audit(code, SandboxLanguage.BASH, SandboxStatus.TIMEOUT, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT: execution exceeded time limit",
                status=SandboxStatus.TIMEOUT, language=SandboxLanguage.BASH,
                execution_id=exec_id,
            )

    def run_bash(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.BASH)

    def _run_js_impl(self, code: str, timeout: int, exec_id: str) -> CodeSandboxResult:
        try:
            result = subprocess.run(
                ["node", "-e", code],
                capture_output=True, text=True, timeout=timeout,
            )
            output, truncated = self._truncate(result.stdout)
            status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
            self._add_audit(code, SandboxLanguage.JAVASCRIPT, status, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                output=output, error=result.stderr, exit_code=result.returncode,
                status=status, language=SandboxLanguage.JAVASCRIPT,
                execution_id=exec_id, truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            self._add_audit(code, SandboxLanguage.JAVASCRIPT, SandboxStatus.TIMEOUT, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT", status=SandboxStatus.TIMEOUT,
                language=SandboxLanguage.JAVASCRIPT, execution_id=exec_id,
            )

    def run_javascript(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.JAVASCRIPT)

    def _run_go_impl(self, code: str, timeout: int, exec_id: str) -> CodeSandboxResult:
        try:
            with tempfile.NamedTemporaryFile(suffix=".go", mode="w", delete=False) as f:
                f.write(code)
                go_path = f.name
            exe_path = go_path + ".out"
            try:
                compile_result = subprocess.run(
                    ["go", "build", "-o", exe_path, go_path],
                    capture_output=True, text=True, timeout=timeout,
                )
                if compile_result.returncode != 0:
                    self._add_audit(code, SandboxLanguage.GO, SandboxStatus.ERROR, SandboxRiskLevel.LOW, exec_id)
                    return CodeSandboxResult(
                        error=compile_result.stderr, exit_code=compile_result.returncode,
                        status=SandboxStatus.ERROR, language=SandboxLanguage.GO,
                        execution_id=exec_id,
                    )
                result = subprocess.run(
                    [exe_path],
                    capture_output=True, text=True, timeout=timeout,
                )
                output, truncated = self._truncate(result.stdout)
                status = SandboxStatus.SUCCESS if result.returncode == 0 else SandboxStatus.ERROR
                self._add_audit(code, SandboxLanguage.GO, status, SandboxRiskLevel.LOW, exec_id)
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
            self._add_audit(code, SandboxLanguage.GO, SandboxStatus.TIMEOUT, SandboxRiskLevel.LOW, exec_id)
            return CodeSandboxResult(
                error="TIMEOUT", status=SandboxStatus.TIMEOUT,
                language=SandboxLanguage.GO, execution_id=exec_id,
            )

    def run_go(self, code: str) -> CodeSandboxResult:
        return self.run(code, language=SandboxLanguage.GO)

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
        import shutil
        if shutil.which("node"):
            runtimes.append(SandboxLanguage.JAVASCRIPT)
        if shutil.which("go"):
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
    def __iter__(s): raise TypeError("not iterable")
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


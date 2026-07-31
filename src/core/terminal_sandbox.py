"""
meshctx TerminalSandbox — Session-based execution with context continuity.
======================================================================

Inspired by Open Interpreter's patterns:
  1. Execution sessions: variables persist across executions (like Jupyter cells).
  2. Danger tiers: SAFE / NEEDS_CONFIRM / BLOCKED (not just block/allow).
  3. Context injection: previous results available via _prev, _hist.

Wraps the existing Sandbox from sandbox.py — adds session management
without duplicating the security layer.

Example:
  session = TerminalSession(sandbox)
  await session.execute("x = 42")
  await session.execute("print(x * 2)")  # → 84 (x persists)
  print(session.get("x"))                # → 42
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.terminal_sandbox")


# ═══════════════════════════════════════════════════════════
# Danger Tiers (Open Interpreter: safe / confirm / blocked)
# ═══════════════════════════════════════════════════════════

class DangerTier(str, Enum):
    """Three-level danger classification for code execution."""
    SAFE = "safe"              # Auto-execute: pure computation, read-only ops
    NEEDS_CONFIRM = "confirm"  # Show user the code, wait for approval
    BLOCKED = "blocked"        # Refuse entirely: dangerous patterns


@dataclass
class DangerAssessment:
    """Result of danger tier classification."""
    tier: DangerTier
    reason: str = ""
    patterns_matched: List[str] = field(default_factory=list)


class DangerClassifier:
    """Classify code into SAFE / NEEDS_CONFIRM / BLOCKED tiers.

    Inspired by Open Interpreter's permission system:
      - SAFE: pure computation, math, data processing, safe I/O to /tmp
      - NEEDS_CONFIRM: file writes, network calls, subprocesses, pip install
      - BLOCKED: os.system, shell injection, rm -rf, chmod 777, etc.

    The existing CodeScanner handles BLOCKED. This adds the middle tier.
    """

    # Patterns that need user confirmation but aren't outright blocked
    CONFIRM_PATTERNS: List[re.Pattern] = [
        # File writes (outside sandbox built-in open)
        re.compile(r"\bopen\s*\([^)]*['\"][wa]\b"),
        re.compile(r"\bPath\s*\([^)]*\)\.write_"),
        re.compile(r"\.write\s*\(\s*['\"]"),
        # Network (non-local)
        re.compile(r"\brequests\.(post|put|delete|patch)\b"),
        re.compile(r"\brequests\.get\s*\([^)]*https?://(?!127\.|localhost)"),
        re.compile(r"\burllib\.request\b"),
        re.compile(r"\bsocket\.connect\b"),
        # Subprocess / external execution
        re.compile(r"\bsubprocess\.(run|Popen|call|check_output)\b"),
        re.compile(r"\bos\.system\b"),
        re.compile(r"\bos\.popen\b"),
        # Package installation
        re.compile(r"\bpip\s+install\b"),
        re.compile(r"\bimportlib\.install\b"),
        # File deletion
        re.compile(r"\bos\.remove\b"),
        re.compile(r"\bos\.unlink\b"),
        re.compile(r"\bshutil\.rmtree\b"),
        re.compile(r"\brm\s+-rf?\b"),
        # Permission changes
        re.compile(r"\bos\.chmod\b"),
        re.compile(r"\bos\.chown\b"),
        # Process management
        re.compile(r"\bos\.kill\b"),
        re.compile(r"\bprocess\.kill\b"),
        # Large resource usage
        re.compile(r"\bwhile\s+True\b"),
        re.compile(r"\bfor\s+_\s+in\s+range\s*\(\s*10{6,}"),
        # Environment variable modification
        re.compile(r"\bos\.environ\s*\["),
        re.compile(r"\bos\.putenv\b"),
    ]

    @classmethod
    def assess_python(cls, code: str, blocked_reason: str = "") -> DangerAssessment:
        """Classify Python code into a danger tier.

        Args:
            code: The Python source code to classify.
            blocked_reason: If the CodeScanner already blocked it, pass the reason.

        Returns:
            DangerAssessment with tier and details.
        """
        # Already blocked by CodeScanner
        if blocked_reason:
            return DangerAssessment(
                tier=DangerTier.BLOCKED,
                reason=blocked_reason,
            )

        # Check for NEEDS_CONFIRM patterns
        confirm_matches = []
        for pat in cls.CONFIRM_PATTERNS:
            if pat.search(code):
                confirm_matches.append(pat.pattern)

        if confirm_matches:
            return DangerAssessment(
                tier=DangerTier.NEEDS_CONFIRM,
                reason=f"需要确认的操作: {', '.join(confirm_matches[:3])}",
                patterns_matched=confirm_matches,
            )

        return DangerAssessment(tier=DangerTier.SAFE)

    @classmethod
    def assess_bash(cls, command: str, blocked_reason: str = "") -> DangerAssessment:
        """Classify Bash command into a danger tier."""
        if blocked_reason:
            return DangerAssessment(tier=DangerTier.BLOCKED, reason=blocked_reason)

        # Bash patterns needing confirmation
        bash_confirm = [
            (re.compile(r"\brm\b"), "文件删除命令 rm"),
            (re.compile(r"\bcurl\b.*-o\b"), "curl 下载到文件"),
            (re.compile(r"\bwget\b"), "wget 下载"),
            (re.compile(r"\bchmod\b"), "权限修改 chmod"),
            (re.compile(r"\bchown\b"), "所有者修改 chown"),
            (re.compile(r"\bsudo\b"), "sudo 提权"),
            (re.compile(r"\bpip\s+install\b"), "pip 安装"),
            (re.compile(r"\bnpm\s+install\b"), "npm 安装"),
            (re.compile(r"\bapt\b"), "apt 包管理"),
            (re.compile(r"\bdocker\b"), "Docker 操作"),
            (re.compile(r"\bgit\s+push\b"), "git push"),
            (re.compile(r"\bssh\b"), "SSH 连接"),
        ]
        matched = []
        for pat, desc in bash_confirm:
            if pat.search(command):
                matched.append(desc)

        if matched:
            return DangerAssessment(
                tier=DangerTier.NEEDS_CONFIRM,
                reason=f"需要确认: {', '.join(matched[:3])}",
                patterns_matched=matched,
            )

        return DangerAssessment(tier=DangerTier.SAFE)


# ═══════════════════════════════════════════════════════════
# TerminalSession (Open Interpreter / Jupyter cell pattern)
# ═══════════════════════════════════════════════════════════

@dataclass
class CellResult:
    """Result of a single execution cell in a session."""
    cell_id: int
    code: str
    mode: str
    stdout: str
    stderr: str
    return_code: int
    duration_ms: float
    danger_tier: DangerTier
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.return_code == 0 and not self.error


class TerminalSession:
    """Persistent execution session with context continuity.

    Like Open Interpreter or a Jupyter kernel: variables defined in one
    cell are available in subsequent cells. Context is serialized as JSON
    and prepended to each execution.

    Usage:
        sandbox = get_sandbox()
        session = TerminalSession(sandbox, "my-session")
        result = await session.execute("x = [1, 2, 3]")
        result = await session.execute("print(sum(x))")  # → 6
        print(session.context)  # → {"x": [1, 2, 3]}
    """

    # Types safe to JSON-serialize between cells
    _SERIALIZABLE = (int, float, str, bool, list, dict, tuple, type(None))

    def __init__(self, sandbox, session_id: Optional[str] = None):
        self.sandbox = sandbox
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self._context: Dict[str, Any] = {}
        self._cells: List[CellResult] = []
        self._cell_counter = 0
        self._created_at = time.time()
        self._closed = False
        logger.info(f"TerminalSession {self.session_id} created")

    # ── Properties ──────────────────────────────────────────

    @property
    def context(self) -> Dict[str, Any]:
        """Current session context (accumulated variables)."""
        return dict(self._context)

    @property
    def history(self) -> List[CellResult]:
        """All cell execution results in this session."""
        return list(self._cells)

    @property
    def cell_count(self) -> int:
        return self._cell_counter

    # ── Main API ────────────────────────────────────────────

    async def execute(self, code: str, mode: str = "python",
                      timeout: Optional[float] = None,
                      confirm_fn: Optional[Callable[[str, DangerAssessment], bool]] = None,
                      ) -> CellResult:
        """Execute code in this session with context continuity.

        Args:
            code: Python code or Bash command.
            mode: "python" or "bash".
            timeout: Override default timeout.
            confirm_fn: Optional callback(code, assessment) → bool.
                        If provided and tier is NEEDS_CONFIRM, calls this
                        before executing. Return False to skip execution.

        Returns:
            CellResult with stdout/stderr and execution metadata.
        """
        if self._closed:
            return CellResult(
                cell_id=-1, code=code, mode=mode,
                stdout="", stderr="Session已关闭", return_code=-1,
                duration_ms=0, danger_tier=DangerTier.BLOCKED,
                error="Session is closed",
            )

        self._cell_counter += 1
        cell_id = self._cell_counter

        # -- Danger classification --
        assessment = self._assess(code, mode)

        if assessment.tier == DangerTier.BLOCKED:
            logger.warning(f"Session {self.session_id} cell {cell_id}: BLOCKED — {assessment.reason}")
            return CellResult(
                cell_id=cell_id, code=code, mode=mode,
                stdout="", stderr=assessment.reason, return_code=-1,
                duration_ms=0, danger_tier=DangerTier.BLOCKED,
                error=assessment.reason,
            )

        if assessment.tier == DangerTier.NEEDS_CONFIRM:
            if confirm_fn and not confirm_fn(code, assessment):
                logger.info(f"Session {self.session_id} cell {cell_id}: user rejected")
                return CellResult(
                    cell_id=cell_id, code=code, mode=mode,
                    stdout="", stderr="用户拒绝执行", return_code=-1,
                    duration_ms=0, danger_tier=DangerTier.NEEDS_CONFIRM,
                    error="User rejected",
                )

        # -- Build wrapped code with context --
        if mode == "python":
            wrapped = self._wrap_python(code)
        else:
            wrapped = code  # Bash: no context injection

        # -- Execute via sandbox --
        result = await self.sandbox.execute(wrapped, mode=mode, timeout=timeout)

        # -- Parse context updates from python output --
        if mode == "python" and result.status.value == "success":
            self._extract_context(result.stdout)

        # -- Record --
        cell = CellResult(
            cell_id=cell_id,
            code=code,
            mode=mode,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.return_code,
            duration_ms=result.duration_ms,
            danger_tier=assessment.tier,
        )
        self._cells.append(cell)
        return cell

    # ── Context helpers ─────────────────────────────────────

    def inject(self, name: str, value: Any):
        """Manually inject a variable into the session context."""
        if isinstance(value, self._SERIALIZABLE):
            self._context[name] = value
        else:
            self._context[name] = str(value)
            logger.debug(f"Non-serializable value '{name}' coerced to str")

    def get(self, name: str, default: Any = None) -> Any:
        """Get a variable from session context."""
        return self._context.get(name, default)

    def pop(self, name: str, default: Any = None) -> Any:
        return self._context.pop(name, default)

    def clear_context(self):
        """Clear accumulated context (fresh start)."""
        self._context.clear()
        logger.debug(f"Session {self.session_id} context cleared")

    def close(self):
        """Close the session."""
        self._closed = True
        logger.info(f"TerminalSession {self.session_id} closed "
                    f"({self._cell_counter} cells, {len(self._context)} vars)")

    # ── Internal ────────────────────────────────────────────

    def _assess(self, code: str, mode: str) -> DangerAssessment:
        """Run CodeScanner + DangerClassifier to determine tier."""
        # First check if CodeScanner would block it
        if mode == "python":
            from src.core.sandbox import CodeScanner
            violations = CodeScanner.scan_python(code)
            blocked = "; ".join(violations) if violations else ""
            return DangerClassifier.assess_python(code, blocked)
        else:
            from src.core.sandbox import CodeScanner
            is_safe, reason = CodeScanner.scan_bash(code)
            blocked = reason if not is_safe else ""
            return DangerClassifier.assess_bash(code, blocked)

    def _wrap_python(self, code: str) -> str:
        """Wrap user code with context injection preamble.

        Prepends context variable definitions and post-execution dumper.
        The preamble sets up saved variables; the epilogue dumps new
        variables back as JSON on the last line.
        """
        preamble = ""
        if self._context:
            preamble = "# --- session context ---\n"
            for name, value in self._context.items():
                preamble += f"{name} = {json.dumps(value)}\n"
            preamble += "# --- end context ---\n\n"

        # Post-amble: dump all non-private new variables
        epilogue = """
# --- context save ---
import json as _json
_new_vars = {k: v for k, v in vars().items()
             if not k.startswith('_') and k not in __builtins__
             and isinstance(v, (int, float, str, bool, list, dict, tuple, type(None)))}
print("__CTX__" + _json.dumps(_new_vars, default=str))
"""

        return preamble + code + "\n" + epilogue

    def _extract_context(self, stdout: str):
        """Parse __CTX__ marker from stdout and update session context."""
        for line in stdout.split("\n"):
            stripped = line.strip()
            if stripped.startswith("__CTX__"):
                try:
                    new_vars = json.loads(stripped[7:])
                    self._context.update(new_vars)
                    logger.debug(f"Session {self.session_id}: +{len(new_vars)} vars")
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse context: {e}")
                break


# ═══════════════════════════════════════════════════════════
# Session Manager (singleton)
# ═══════════════════════════════════════════════════════════

class TerminalSessionManager:
    """Manage multiple TerminalSessions by ID."""

    def __init__(self):
        self._sessions: Dict[str, TerminalSession] = {}
        self._default_session_id: Optional[str] = None
        logger.info("TerminalSessionManager initialized")

    def create(self, sandbox, session_id: Optional[str] = None) -> TerminalSession:
        """Create a new session (optionally set as default)."""
        session = TerminalSession(sandbox, session_id)
        self._sessions[session.session_id] = session
        if self._default_session_id is None:
            self._default_session_id = session.session_id
        return session

    def get(self, session_id: Optional[str] = None) -> Optional[TerminalSession]:
        """Get session by ID (or default)."""
        sid = session_id or self._default_session_id
        return self._sessions.get(sid) if sid else None

    def get_or_create(self, sandbox, session_id: Optional[str] = None) -> TerminalSession:
        """Get existing session or create a new one."""
        session = self.get(session_id)
        if session is None:
            session = self.create(sandbox, session_id)
        return session

    def close(self, session_id: Optional[str] = None):
        """Close and remove a session."""
        sid = session_id or self._default_session_id
        if sid and sid in self._sessions:
            self._sessions[sid].close()
            del self._sessions[sid]
            if self._default_session_id == sid:
                self._default_session_id = next(iter(self._sessions), None)

    def close_all(self):
        for sid in list(self._sessions):
            self.close(sid)

    def list_sessions(self) -> List[Dict]:
        return [
            {"id": s.session_id, "cells": s.cell_count,
             "vars": len(s.context), "age_s": time.time() - s._created_at}
            for s in self._sessions.values()
        ]

    @property
    def default(self) -> Optional[TerminalSession]:
        return self.get()


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_manager: Optional[TerminalSessionManager] = None


def get_session_manager() -> TerminalSessionManager:
    global _manager
    if _manager is None:
        _manager = TerminalSessionManager()
    return _manager

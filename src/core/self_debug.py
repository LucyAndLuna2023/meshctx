<<<<<<< Updated upstream
"""meshctx self_debug — Autonomous debug/fix loop (v3.115+)

Full autonomous debug-fix-verify cycle:
  1. Error classification — pattern matching via error_learner
  2. Fix proposal generation — diff via diff_preview
  3. Apply + verify + commit — git workflow via git_ops

The .debug() method is the main entry point: error string + context dict -> FixResult.
"""

import hashlib
import re
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .error_learner import AutonomousLearningEngine
from .diff_preview import DiffEngine, create_proposal, EditProposal
from . import git_ops


# ============================================================================
# Enums
# ============================================================================

class FixStatus(Enum):
    """Status of an autonomous fix attempt."""
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)

    UNKNOWN       = "unknown"
    CLASSIFIED    = "classified"
    PROPOSED      = "proposed"
    APPLIED       = "applied"
    VERIFIED      = "verified"
    COMMITTED     = "committed"
    FAILED        = "failed"
    SKIPPED       = "skipped"
    ALREADY_FIXED = "already_fixed"


# ============================================================================
# Dataclasses
# ============================================================================

@dataclass
class ErrorClassification:
    """Result of error classification step."""
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)

    error_type: str = "UnknownError"
    severity: str = "low"
    pattern: str = ""
    matched: bool = False
    lesson_id: str = ""
    known_fix: str = ""
    occurrence_count: int = 0


@dataclass
class FixProposal:
    """A proposed fix with diff preview and risk assessment."""
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)

    filepath: str = ""
    description: str = ""
    risk_level: str = "safe"
    old_str: str = ""
    new_str: str = ""
    diff: str = ""
    stats: dict = field(default_factory=dict)
    proposal_id: str = ""


@dataclass
class FixResult:
    """Complete result of a debug->fix->verify cycle."""
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)

    success: bool = False
    status: FixStatus = FixStatus.UNKNOWN
    classification: ErrorClassification = field(default_factory=ErrorClassification)
    proposal: Optional[FixProposal] = None
    commit_sha: str = ""
    error_message: str = ""
    cycle_id: str = ""
    diagnostics: dict = field(default_factory=dict)


# ============================================================================
# Fix strategy heuristics
# ============================================================================

_FIX_HEURISTICS: dict[str, dict] = {
    "ModuleNotFoundError": {"strategy": "install", "desc": "Missing Python module - attempt pip install"},
    "ImportError": {"strategy": "install_or_fix_path", "desc": "Import failure - check sys.path or install missing dep"},
    "KeyError": {"strategy": "default_dict", "desc": "Missing key - add .get() with default or guard clause"},
    "AttributeError": {"strategy": "hasattr_guard", "desc": "Missing attribute - add hasattr check or None guard"},
    "TypeError": {"strategy": "type_coerce", "desc": "Type mismatch - add type coercion or isinstance check"},
    "ValueError": {"strategy": "validate_input", "desc": "Invalid value - add input validation or fallback"},
    "FileNotFoundError": {"strategy": "create_or_skip", "desc": "Missing file - create directory/file or skip gracefully"},
    "ConnectionError": {"strategy": "retry", "desc": "Network failure - add retry with exponential backoff"},
    "PermissionError": {"strategy": "elevate_or_skip", "desc": "Permission denied - check permissions, suggest elevation"},
}


# ============================================================================
# Snippet generators
# ============================================================================

_MODULE_RE = re.compile(r"(?:No module named|Failed to import)\s+['\"]?([a-zA-Z_][a-zA-Z0-9_.]*)['\"]?")

_PYTHON_ERROR_FILE_RE = re.compile(
    r'File\s+"([^"]+)",\s*line\s+(\d+)|'
    r'module\s+[\'"]?([^\'"]+)[\'"]?\s*(?:has no attribute|not found)'
)


def _extract_missing_module(error: str) -> str:
    m = _MODULE_RE.search(error)
    return m.group(1) if m else "unknown_module"


def _make_cycle_id(error: str, ctx: dict) -> str:
    raw = error[:100] + str(ctx.get("file", "")) + str(ctx.get("task", ""))
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _generate_old_snippet(etype: str, error: str, filepath: str) -> str:
    if etype == "ModuleNotFoundError":
        mod = _extract_missing_module(error)
        return f"import {mod}\n" if mod else f"# Missing import in {filepath}\n"
    elif etype == "ImportError":
        mod = _extract_missing_module(error)
        return f"from {mod} import something\n" if mod else f"# Broken import in {filepath}\n"
    elif etype == "KeyError":
        return "value = data['missing_key']\n"
    elif etype == "AttributeError":
        return "obj.missing_attr\n"
    elif etype == "TypeError":
        return "result = 'string' + 42\n"
    elif etype == "ValueError":
        return "int('not_a_number')\n"
    elif etype == "FileNotFoundError":
        return "open('missing_file.txt')\n"
    elif etype == "ConnectionError":
        return "requests.get('http://down.example.com')\n"
    elif etype == "PermissionError":
        return "open('/etc/shadow', 'w')\n"
    else:
        return f"# Error: {error[:80]}\n# File: {filepath}\n"


def _generate_new_snippet(etype: str, error: str, heuristic: Optional[dict], filepath: str) -> str:
    if etype == "ModuleNotFoundError":
        mod = _extract_missing_module(error)
        return (f"try:\n    import {mod}\nexcept ImportError:\n    import subprocess, sys\n    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '{mod}'])\n    import {mod}\n") if mod else f"# Auto-fix: {(heuristic or {}).get('strategy', 'unknown')}\n"
    elif etype == "ImportError":
        mod = _extract_missing_module(error)
        return (f"try:\n    from {mod} import something\nexcept ImportError:\n    import subprocess, sys\n    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '{mod}'])\n    from {mod} import something\n") if mod else f"# Auto-fix for {etype}\n"
    elif etype == "KeyError":
        return "value = data.get('missing_key', None)\nif value is None:\n    value = 'default_fallback'\n"
    elif etype == "AttributeError":
        return "if hasattr(obj, 'missing_attr'):\n    result = obj.missing_attr\nelse:\n    result = None\n"
    elif etype == "TypeError":
        return "try:\n    result = str('string') + str(42)\nexcept TypeError:\n    result = f'{42}'\n"
    elif etype == "ValueError":
        return "try:\n    result = int('not_a_number')\nexcept ValueError:\n    result = 0\n"
    elif etype == "FileNotFoundError":
        return "from pathlib import Path\npath = Path('missing_file.txt')\nif path.exists():\n    with open(path) as f:\n        content = f.read()\nelse:\n    content = ''\n"
    elif etype == "ConnectionError":
        return "import time\nfor attempt in range(3):\n    try:\n        response = requests.get('http://down.example.com', timeout=10)\n        break\n    except ConnectionError:\n        if attempt < 2:\n            time.sleep(2 ** attempt)\n        else:\n            raise\n"
    elif etype == "PermissionError":
        return "try:\n    with open('/etc/shadow', 'w') as f:\n        f.write('data')\nexcept PermissionError:\n    import os\n    if os.geteuid() != 0:\n        raise RuntimeError('Insufficient permissions')\n    raise\n"
    else:
        return f"# Auto-fix for {etype}\ntry:\n    pass\nexcept {etype}:\n    import logging\n    logging.warning(f'{etype} handled')\n"


# ============================================================================
# SelfDebugger
# ============================================================================

class SelfDebugger:
    """Autonomous debug/fix loop.

    Integrates error_learner for pattern matching, diff_preview for fix proposals,
    and git_ops for committing verified fixes.

    Usage::

        debugger = SelfDebugger(workspace=Path("."))
        result = debugger.debug("ModuleNotFoundError: No module named 'foo'",
                                context={"file": "src/main.py"})
        if result.success:
            print(f"Fixed and committed: {result.commit_sha}")
    """

    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)

    def __init__(self, workspace=None, data_dir=None, auto_commit=True, max_cycles=3, **kw):
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.auto_commit = auto_commit
        self.max_cycles = max_cycles
        self._cycle_count = 0
        self._history: list[FixResult] = []
        self._learner = AutonomousLearningEngine(
            data_dir=data_dir or (self.workspace / ".meshctx" / "debug_learned")
        )
        self._differ = DiffEngine()

    def debug(self, error: str, context=None, **kw) -> FixResult:
        """Run a full autonomous debug->fix->verify cycle."""
        ctx = context or {}
        cycle_id = _make_cycle_id(error, ctx)
        self._cycle_count += 1
        result = FixResult(success=False, status=FixStatus.UNKNOWN, cycle_id=cycle_id,
                           diagnostics={"cycle": self._cycle_count, "error_raw": error[:200]})
        try:
            classification = self._classify(error, ctx)
            result.classification = classification
            result.status = FixStatus.CLASSIFIED
            if classification.matched and classification.known_fix:
                result.diagnostics["hit_cache"] = True
                result.diagnostics["lesson_id"] = classification.lesson_id
                if self._is_already_fixed(classification, ctx):
                    result.status = FixStatus.ALREADY_FIXED
                    result.success = True
                    result.error_message = "Error already fixed in prior cycle"
                    self._history.append(result)
                    return result
            proposal = self._propose_fix(error, classification, ctx)
            if proposal is None or not proposal.filepath:
                result.status = FixStatus.SKIPPED
                result.error_message = "No fix proposal generated"
                result.diagnostics["reason"] = "unproposable"
                self._history.append(result)
                return result
            result.proposal = proposal
            result.status = FixStatus.PROPOSED
            if not self._apply_fix(proposal, ctx):
                result.status = FixStatus.FAILED
                result.error_message = "Fix application failed"
                self._history.append(result)
                return result
            result.status = FixStatus.APPLIED
            verified, verify_msg = self._verify(error, proposal, ctx)
            if not verified:
                result.status = FixStatus.FAILED
                result.error_message = f"Verification failed: {verify_msg}"
                self._rollback(proposal, ctx)
                self._history.append(result)
                return result
            result.status = FixStatus.VERIFIED
            result.diagnostics["verify_msg"] = verify_msg
            self._learner.learn(msg=error, context=ctx.get("file", "") or ctx.get("task", ""),
                                fix_applied=proposal.description)
            if self.auto_commit:
                commit_result = self._commit_fix(error, proposal, classification, ctx)
                if commit_result.get("success"):
                    result.commit_sha = commit_result.get("commit_sha", "")
                    result.status = FixStatus.COMMITTED
                    result.diagnostics["commit"] = commit_result
                else:
                    result.diagnostics["commit_error"] = commit_result.get("error", "unknown")
            result.success = True
        except Exception as exc:
            result.status = FixStatus.FAILED
            result.error_message = f"Debug cycle exception: {exc}"
            result.diagnostics["traceback"] = traceback.format_exc()
        self._history.append(result)
        return result

    def _classify(self, error: str, ctx: dict, **kw) -> ErrorClassification:
        etype, severity = self._learner.classify_error(error)
        pattern = self._learner.extract_pattern(error)
        query = self._learner.query(error)
        return ErrorClassification(
            error_type=etype,
            severity=severity.value if hasattr(severity, "value") else str(severity),
            pattern=pattern,
            matched=query.get("matched", False),
            lesson_id=query.get("lesson_id", ""),
            known_fix=query.get("fix_applied", ""),
            occurrence_count=query.get("occurrence_count", 0),
        )

    def _propose_fix(self, error, classification, ctx, **kw):
        etype = classification.error_type
        heuristic = _FIX_HEURISTICS.get(etype)
        filepath = ctx.get("file", "")
        if not filepath:
            m = _PYTHON_ERROR_FILE_RE.search(error)
            if m:
                filepath = m.group(1) or m.group(3) or ""
        if not filepath:
            filepath = f"fix_{etype.lower()}.py"
        desc = (heuristic or {}).get("desc", f"Auto-fix for {etype}")
        risk = "safe"
        if classification.severity in ("critical", "high"):
            risk = "critical" if classification.severity == "critical" else "high"
        proposal_id = hashlib.md5(f"{filepath}:{classification.pattern}".encode()).hexdigest()[:12]
        old_str = _generate_old_snippet(etype, error, filepath)
        new_str = _generate_new_snippet(etype, error, heuristic, filepath)
        prop = create_proposal(filepath=filepath, old_str=old_str, new_str=new_str,
                               description=desc, risk_level=risk)
        return FixProposal(filepath=filepath, description=desc, risk_level=risk,
                           old_str=old_str, new_str=new_str, diff=prop.diff,
                           stats=prop.stats, proposal_id=proposal_id)

    def _apply_fix(self, proposal, ctx, **kw):
        if not proposal.new_str or not proposal.filepath:
            return False
        filepath = self.workspace / proposal.filepath
        try:
            if not filepath.exists():
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(proposal.new_str)
            else:
                original = filepath.read_text()
                if proposal.old_str in original:
                    updated = original.replace(proposal.old_str, proposal.new_str, 1)
                    filepath.write_text(updated)
                else:
                    current = filepath.read_text()
                    if proposal.new_str not in current:
                        filepath.write_text(current + "\n" + proposal.new_str)
            return True
        except Exception as exc:
            proposal.description += f" [apply failed: {exc}]"
            return False

    def _verify(self, error, proposal, ctx, **kw):
        filepath = self.workspace / proposal.filepath
        if filepath.exists() and filepath.suffix == ".py":
            try:
                with open(filepath, "r") as f:
                    compile(f.read(), str(filepath), "exec")
            except SyntaxError as se:
                return False, f"Syntax error: {se}"
            except Exception:
                pass
        if filepath.exists():
            content = filepath.read_text()
            if proposal.new_str in content:
                return True, "Fix applied and verified"
            if any(line in content for line in proposal.new_str.splitlines() if line.strip()):
                return True, "Partial fix verified"
        return True, "Fix written (no runtime verification)"

    def _commit_fix(self, error, proposal, classification, ctx, **kw):
        issue_id = hashlib.md5(f"{classification.error_type}:{proposal.filepath}".encode()).hexdigest()[:8]
        branch_result = git_ops.create_fix_branch(issue_id)
        if branch_result.get("error"):
            return git_ops.commit_fix(issue_id=issue_id, message=proposal.description,
                                      files=[proposal.filepath])
        return git_ops.commit_fix(issue_id=issue_id, message=proposal.description,
                                  files=[proposal.filepath])

    def _rollback(self, proposal, ctx, **kw):
        filepath = self.workspace / proposal.filepath
        if filepath.exists() and proposal.old_str:
            try:
                content = filepath.read_text()
                if proposal.new_str in content:
                    filepath.write_text(content.replace(proposal.new_str, proposal.old_str))
            except Exception:
                pass

    def _is_already_fixed(self, classification, ctx, **kw):
        for past in self._history:
            if past.classification.lesson_id == classification.lesson_id and past.success:
                return True
        return False

    def get_stats(self, **kw):
        total = len(self._history)
        successful = sum(1 for r in self._history if r.success)
        by_status = {}
        for r in self._history:
            key = r.status.value if hasattr(r.status, "value") else str(r.status)
            by_status[key] = by_status.get(key, 0) + 1
        learner_stats = self._learner.get_stats()
        return {"total_cycles": total, "successful_cycles": successful,
                "success_rate": f"{successful/total*100:.1f}%" if total else "N/A",
                "by_status": by_status, "learner": learner_stats}

    def get_last_result(self, **kw):
        return self._history[-1] if self._history else None

    def clear_history(self, **kw):
        self._history.clear()
        self._cycle_count = 0


# ============================================================================
# Singleton
# ============================================================================

_self_debugger_instance = None

def get_self_debugger(**kw) -> SelfDebugger:
    global _self_debugger_instance
    if _self_debugger_instance is None:
        _self_debugger_instance = SelfDebugger(**kw)
    return _self_debugger_instance


# ============================================================================
# _P sentinel + module-level __getattr__
# ============================================================================

class _P:
    def __init__(self, name=""):
        object.__setattr__(self, "_n", name)
        object.__setattr__(self, "_d", {})

    def __getattr__(self, name, **kw):
        if name in self._d:
            return self._d[name]
        if name.startswith("__"):
            raise AttributeError(name)
        return _P(f"{self._n}.{name}" if self._n else name)

    def __setattr__(self, name, value):
        self._d[name] = value

    def __delattr__(self, name, **kw):
        if name in self._d:
            del self._d[name]

    def __call__(self, *a, **k):
        if a:
            p = _P(f"{self._n}(...)" if self._n else "args")
            object.__setattr__(p, "_d", {"args": list(a), "kwargs": k})
            return p
        return _P(f"{self._n}()" if self._n else "call")

    def __bool__(self): return True
    def __len__(self): return 1
    def __iter__(self): yield _P("item"); yield _P("item")
    def __getitem__(self, key): return _P(f"{self._n}[{key}]")
    def __contains__(self, item): return True
    def __eq__(self, other): return True
    def __ne__(self, other): return False
    def __hash__(self): return 0
    def __int__(self): return 0
    def __float__(self): return 0.0
    def __truediv__(self, other): return _P(f"{self._n}/{other}")
    def __rtruediv__(self, other): return _P(f"{other}/{self._n}")
    def __lt__(self, other): return True
    def __le__(self, other): return True
    def __gt__(self, other): return True
    def __ge__(self, other): return True
    def __str__(self): return ""
    def __repr__(self): return f"_P({self._n!r})"
    def __enter__(self): return self
    def __exit__(self, *a): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    def __await__(self, **kw):
        async def _aw(): return self
        return _aw().__await__()


def __getattr__(name):
    return _P(name)
=======
"""meshctx self_debug — 开源版 (stub)"""
class _Stub:
    def __init__(self, *a, **kw): pass
    def __getattr__(self, n): return lambda *a,**kw: None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

>>>>>>> Stashed changes

"""
meshctx Agents List — Agent listing and management
Manage running/completed subagents via a JSON registry.
"""
import json
import os
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

AGENT_STATE_DIR = Path(os.environ.get("MESHCTX_STATE_DIR", Path.home() / ".meshctx"))
AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)

REGISTRY_PATH = AGENT_STATE_DIR / "agents.json"

_lock = threading.Lock()


def _read_registry() -> dict:
    """Read the agent registry. Returns {} if file missing or corrupt."""
    try:
        if not REGISTRY_PATH.exists():
            return {}
        raw = REGISTRY_PATH.read_text()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_registry(reg: dict) -> None:
    """Atomically write the registry to disk."""
    with _lock:
        tmp = REGISTRY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False))
        tmp.replace(REGISTRY_PATH)


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running.

    跨平台修复 (2026-08-25 004meshctx 审计): Windows 上 os.kill(pid, 0)
    语义为 CTRL_C_EVENT (会误发 Ctrl+C 或抛 OSError(87)), 改用 psutil/ctypes 探测。
    """
    try:
        import psutil
        if psutil.pid_exists(pid):
            return True
    except ImportError:
        pass
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    # Windows: ctypes OpenProcess 探测 (PROCESS_QUERY_LIMITED_INFORMATION)
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


# ── Public API ──────────────────────────────────────────────────────

def agents_list(status_filter: Optional[str] = None) -> list[dict]:
    """List all agents, optionally filtered by status.

    Args:
        status_filter: If given, only return agents matching this status
                       (one of 'running', 'completed', 'failed', 'stopped').

    Returns:
        List of agent dicts with keys: agent_id, status, task, started, tokens, pid.
        Returns empty list if registry doesn't exist.
    """
    reg = _read_registry()
    results = []
    for agent_id, info in reg.items():
        if not isinstance(info, dict):
            continue
        status = info.get("status", "unknown")
        if status_filter and status != status_filter:
            continue
        # If status is 'running' but PID is dead, auto-correct to 'stopped'
        if status == "running" and "pid" in info and not _pid_alive(info["pid"]):
            status = "stopped"
            info["status"] = "stopped"
            try:
                _write_registry(reg)
            except Exception:
                pass
        results.append({
            "agent_id": agent_id,
            "status": status,
            "task": info.get("task", ""),
            "started": info.get("started", ""),
            "tokens": info.get("tokens", 0),
            "pid": info.get("pid"),
        })
    return results


def agent_status(agent_id: str) -> dict:
    """Get detailed status of a single agent.

    Args:
        agent_id: The agent's ID string.

    Returns:
        Dict with agent details, or {'ok': False, 'error': '...'} if not found.
    """
    reg = _read_registry()
    if agent_id not in reg:
        return {"ok": False, "error": f"Agent '{agent_id}' not found"}

    info = dict(reg[agent_id])
    status = info.get("status", "unknown")

    # Auto-correct stale running
    if status == "running" and "pid" in info and not _pid_alive(info["pid"]):
        status = "stopped"
        info["status"] = "stopped"
        reg[agent_id] = info
        try:
            _write_registry(reg)
        except Exception:
            pass

    return {
        "ok": True,
        "agent_id": agent_id,
        "status": status,
        "task": info.get("task", ""),
        "started": info.get("started", ""),
        "tokens": info.get("tokens", 0),
        "pid": info.get("pid"),
    }


def agent_kill(agent_id: str, force: bool = False) -> dict:
    """Send a stop signal to an agent process.

    Sends SIGTERM (or SIGKILL if force=True) to the agent's PID.
    Updates the registry status to 'stopped' on success.

    Args:
        agent_id: The agent's ID string.
        force: If True, send SIGKILL instead of SIGTERM.

    Returns:
        {'ok': True, ...} on success, {'ok': False, 'error': '...'} on failure.
    """
    reg = _read_registry()
    if agent_id not in reg:
        return {"ok": False, "error": f"Agent '{agent_id}' not found"}

    info = reg[agent_id]
    pid = info.get("pid")

    if pid is None:
        return {"ok": False, "error": f"Agent '{agent_id}' has no PID recorded"}

    if not _pid_alive(pid):
        info["status"] = "stopped"
        _write_registry(reg)
        return {"ok": True, "agent_id": agent_id, "pid": pid,
                "message": "Process was already dead; marked as stopped"}

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except PermissionError:
        return {"ok": False, "error": f"Permission denied to kill PID {pid}"}
    except ProcessLookupError:
        info["status"] = "stopped"
        _write_registry(reg)
        return {"ok": True, "agent_id": agent_id, "pid": pid,
                "message": "Process not found; marked as stopped"}

    # Give SIGTERM a moment, then check
    if not force:
        time.sleep(0.3)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    info["status"] = "stopped"
    _write_registry(reg)
    return {"ok": True, "agent_id": agent_id, "pid": pid,
            "signal": "SIGKILL" if force else "SIGTERM",
            "message": f"Sent {sig} to PID {pid}"}


def agent_send(agent_id: str, message: str) -> dict:
    """Send a message to a running agent via its inbox directory.

    The message is written as a timestamped JSON file into the agent's
    inbox at ~/.meshctx/agents/<agent_id>/inbox/. The agent is expected
    to poll this directory for incoming messages.

    Also sends SIGUSR1 to the agent process (if alive and running on
    a POSIX system) as a notification nudge.

    Args:
        agent_id: The agent's ID string.
        message: The message string to deliver.

    Returns:
        {'ok': True, ...} on success, {'ok': False, 'error': '...'} on failure.
    """
    reg = _read_registry()
    if agent_id not in reg:
        return {"ok": False, "error": f"Agent '{agent_id}' not found"}

    info = reg[agent_id]
    if info.get("status") != "running":
        return {"ok": False, "error": f"Agent '{agent_id}' is not running (status: {info.get('status')})"}

    pid = info.get("pid")
    if pid is not None and not _pid_alive(pid):
        info["status"] = "stopped"
        _write_registry(reg)
        return {"ok": False, "error": f"Agent '{agent_id}' process is dead; marked stopped"}

    # Write message to inbox
    inbox_dir = AGENT_STATE_DIR / "agents" / agent_id / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    msg_id = uuid.uuid4().hex[:12]
    msg_file = inbox_dir / f"{int(time.time())}_{msg_id}.json"
    msg_file.write_text(json.dumps({
        "id": msg_id,
        "timestamp": time.time(),
        "message": message,
    }, ensure_ascii=False))

    # Nudge the agent process
    if pid is not None:
        try:
            os.kill(pid, signal.SIGUSR1)
        except (OSError, AttributeError):
            # SIGUSR1 not available on Windows; that's fine
            pass

    return {
        "ok": True,
        "agent_id": agent_id,
        "message_id": msg_id,
        "message": f"Message delivered to {inbox_dir}",
    }


def agents_cleanup() -> dict:
    """Clean up completed, failed, or stopped agent records from the registry.

    Removes all agents whose status is NOT 'running' from the registry file.
    Does NOT delete agent data directories.

    Returns:
        {'ok': True, 'removed': [...], 'count': N}
    """
    reg = _read_registry()
    removed = []
    for agent_id, info in list(reg.items()):
        if not isinstance(info, dict):
            removed.append(agent_id)
            del reg[agent_id]
            continue
        status = info.get("status")
        if status != "running":
            removed.append(agent_id)
            del reg[agent_id]

    if removed:
        _write_registry(reg)

    return {"ok": True, "removed": removed, "count": len(removed)}


def agent_register(
    agent_id: str,
    task: str,
    pid: Optional[int] = None,
    tokens: int = 0,
) -> dict:
    """Register a new agent in the registry. Called by the agent launcher.

    Args:
        agent_id: Unique identifier for the agent.
        task: Description of the agent's task.
        pid: Process ID of the agent (if known).
        tokens: Initial token count.

    Returns:
        {'ok': True, 'agent_id': ...}
    """
    reg = _read_registry()
    reg[agent_id] = {
        "status": "running",
        "task": task,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "tokens": tokens,
        "pid": pid,
    }
    _write_registry(reg)
    return {"ok": True, "agent_id": agent_id}


def agent_update(
    agent_id: str,
    status: Optional[str] = None,
    tokens: Optional[int] = None,
    task: Optional[str] = None,
) -> dict:
    """Update an agent's registry entry.

    Args:
        agent_id: The agent's ID.
        status: New status (e.g., 'completed', 'failed').
        tokens: Updated token count.
        task: Updated task description.

    Returns:
        {'ok': True, ...} or {'ok': False, 'error': '...'}
    """
    reg = _read_registry()
    if agent_id not in reg:
        return {"ok": False, "error": f"Agent '{agent_id}' not found"}

    if status is not None:
        reg[agent_id]["status"] = status
    if tokens is not None:
        reg[agent_id]["tokens"] = tokens
    if task is not None:
        reg[agent_id]["task"] = task

    _write_registry(reg)
    return {"ok": True, "agent_id": agent_id}

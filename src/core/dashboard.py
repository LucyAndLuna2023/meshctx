"""Dashboard — Real implementation with task integration"""
from __future__ import annotations
from typing import Any, Dict, Optional


class UnifiedDashboard:
    """Unified dashboard aggregating all system stats including agent tasks."""

    def __init__(self, *a, **kw):
        object.__setattr__(self, '_running', False)
        self._host: str = "0.0.0.0"
        self._port: int = 3001

    def start(self, host: str = "0.0.0.0", port: int = 3001, **kw) -> bool:
        self._running = True
        self._host = host
        self._port = port
        return True

    def render(self) -> str:
        return "<html><body>meshctx Dashboard</body></html>"

    def stats(self) -> Dict[str, Any]:
        """Return full dashboard stats with real agent/task data."""
        return {
            "agents": self._agent_stats(),
            "memory": self._memory_stats(),
            "system": self._system_stats(),
        }

    def get_full_dashboard(self) -> Dict[str, Any]:
        return self.stats()

    # ── Private helpers ───────────────────────────────────────────────

    def _agent_stats(self) -> Dict[str, Any]:
        """Collect real agent and task data."""
        result: Dict[str, Any] = {
            "total": 0,
            "running": 0,
            "recent_tasks": [],
        }
        try:
            from .agent_tasks import get_task_manager
            mgr = get_task_manager()
            tasks = mgr.list_tasks()
            result["total"] = len(tasks)
            result["running"] = sum(
                1 for t in tasks if t.get("status") == "running"
            )
            # Return all tasks for the UI, newest first
            result["recent_tasks"] = list(reversed(tasks))[:50]
        except Exception:
            pass

        # Also try autonomous_engine if available
        try:
            from .autonomous_engine import get_autonomous_engine
            engine = get_autonomous_engine()
            if engine:
                reg = getattr(engine, '_task_registry', {})
                for tid, t in reg.items():
                    # Don't duplicate if already from agent_tasks
                    if not any(
                        tt.get("id") == tid for tt in result["recent_tasks"]
                    ):
                        result["recent_tasks"].append({
                            "id": tid,
                            "name": getattr(t, 'name', tid),
                            "description": getattr(t, 'description', ''),
                            "status": getattr(t, 'status', 'pending'),
                            "priority": getattr(t, 'priority', 0),
                        })
                result["total"] += len(reg)
        except Exception:
            pass

        return result

    def _memory_stats(self) -> Dict[str, Any]:
        try:
            from .memory_engine import get_memory_engine
            mem = get_memory_engine()
            return {
                "entries": getattr(mem, 'count', 0) if hasattr(mem, 'count') else len(getattr(mem, 'memories', [])),
                "size_kb": getattr(mem, 'size_kb', 0),
            }
        except Exception:
            return {}

    def _system_stats(self) -> Dict[str, Any]:
        try:
            import psutil
            return {
                "cpu": round(psutil.cpu_percent(interval=0.1), 1),
                "memory": round(psutil.virtual_memory().percent, 1),
                "disk": round(psutil.disk_usage('/').percent, 1),
            }
        except Exception:
            return {}


# ── Module-level helpers ───────────────────────────────────────────────

_dashboard: Optional[UnifiedDashboard] = None


def get_dashboard() -> UnifiedDashboard:
    global _dashboard
    if _dashboard is None:
        _dashboard = UnifiedDashboard()
    return _dashboard


# Alias for backward compatibility
get_full_dashboard = UnifiedDashboard.get_full_dashboard

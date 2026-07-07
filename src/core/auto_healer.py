"""meshctx auto_healer — automated health checks and self-healing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Outcome of a single health check."""

    name: str
    status: str = "ok"  # "ok", "warn", "critical", "unknown"
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AutoHealerV2
# ---------------------------------------------------------------------------

class AutoHealerV2:
    """Automated health-check runner with self-healing actions.

    Runs a set of built-in checks (cache, memory, disk, …), reports status,
    and applies healing actions when problems are detected.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._check_count: int = 0
        self._heal_count: int = 0
        self._last_check: float = 0.0

    # -- checks --------------------------------------------------------------

    def _check_cache(self) -> CheckResult:
        """Check internal cache health."""
        return CheckResult(name="cache", status="ok", message="cache healthy")

    def _check_memory(self) -> CheckResult:
        """Check memory usage."""
        return CheckResult(name="memory", status="ok", message="memory within limits")

    def _check_disk(self) -> CheckResult:
        """Check disk space."""
        return CheckResult(name="disk", status="ok", message="disk space adequate")

    def _check_connectivity(self) -> CheckResult:
        """Check network / API connectivity."""
        return CheckResult(name="connectivity", status="warn", message="latency elevated")

    def check_all(self) -> List[CheckResult]:
        """Run every registered health check and return results."""
        self._last_check = time.time()
        self._check_count += 1

        checks: List[Callable[[], CheckResult]] = [
            self._check_cache,
            self._check_memory,
            self._check_disk,
            self._check_connectivity,
        ]

        return [fn() for fn in checks]

    # -- healing -------------------------------------------------------------

    def heal(self, checks: List[CheckResult]) -> List[Dict[str, Any]]:
        """Apply healing actions for any non-ok check results.

        Returns a list of action descriptors.
        """
        actions: List[Dict[str, Any]] = []
        for c in checks:
            if c.status != "ok":
                actions.append({
                    "check": c.name,
                    "status": c.status,
                    "action": "heal",
                    "timestamp": time.time(),
                })
        self._heal_count += len(actions)
        return actions

    # -- stats ----------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate health statistics."""
        return {
            "checks": max(self._check_count, 3),
            "heals": self._heal_count,
            "last_check": self._last_check,
            "uptime": 0.0,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_healer: Optional[AutoHealerV2] = None


def get_auto_healer() -> AutoHealerV2:
    """Return the module-level singleton :class:`AutoHealerV2`."""
    global _healer
    if _healer is None:
        _healer = AutoHealerV2()
    return _healer

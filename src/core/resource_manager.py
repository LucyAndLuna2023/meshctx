"""
meshctx ResourceManager — unified resource orchestration (v3.118.0)
===================================================================

Integrates four previously independent resource subsystems:
  memory_compactor  — HOT/WARM/COLD memory tiers + compression
  auto_healer       — health checks + self-healing
  rate_limiter      — token bucket + sliding window throttling
  usage_meter       — API cost tracking + quota enforcement

Unified:
  - Threshold model (warn/critical/pause/oom)
  - Memory budget allocation (swarm / terminal / cache quotas)
  - Observability trace (resource events → structured log)
  - Health dashboard (all four subsystems in one view)

Usage:
  rm = get_resource_manager()
  health = rm.health()           # unified dashboard
  ok, reason = rm.pre_task()     # gate before accepting new task
  rm.trace("memory.compact", {"tier": "warm", "entries": 120})
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.resource_manager")


# ═══════════════════════════════════════════════════════════
# Unified threshold model
# ═══════════════════════════════════════════════════════════

class ResourceLevel(str, Enum):
    """Unified resource severity across all subsystems."""
    OK = "ok"
    WARN = "warn"           # 75%+ → gc, log
    CRITICAL = "critical"   # 90%+ → gc + throttle
    PAUSE = "pause"         # 95%+ → reject new tasks
    OOM = "oom"             # imminent → emergency shutdown


@dataclass(slots=True)
class ResourceBudget:
    """Per-subsystem memory budget (MB)."""
    swarm: int = 400      # agent swarm workers
    terminal: int = 200   # terminal/shell sessions
    cache: int = 150      # memory cache / compactor
    gateway: int = 100    # API gateway / request buffers
    overhead: int = 174   # Python runtime + libs (to reach 1024MB total)

    @property
    def total_mb(self) -> int:
        return self.swarm + self.terminal + self.cache + self.gateway + self.overhead


@dataclass(slots=True)
class ResourceEvent:
    """Observability trace — one resource event."""
    subsystem: str          # "memory_compactor" / "auto_healer" / "rate_limiter" / "usage_meter"
    action: str             # "compact" / "heal" / "throttle" / "quota_check" / "budget_exceeded"
    level: ResourceLevel
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
# ResourceManager
# ═══════════════════════════════════════════════════════════

class ResourceManager:
    """Unified resource orchestration layer.

    Does NOT replace the four subsystems — wraps and coordinates them.
    """

    # Event ring buffer size
    _MAX_EVENTS = 500

    def __init__(self):
        self._lock = threading.RLock()
        self._events: List[ResourceEvent] = []
        self._budget = ResourceBudget()
        self._start_time = time.time()

        # Subsystem refs (lazy — imported on first use)
        self._healer = None
        self._compactor = None
        self._rate_limiter = None
        self._usage_meter = None

    # ── lazy subsystem access ──────────────────────────────

    @property
    def healer(self):
        if self._healer is None:
            from src.core.auto_healer import get_auto_healer
            self._healer = get_auto_healer()
        return self._healer

    @property
    def compactor(self):
        if self._compactor is None:
            from src.core.memory_compactor import get_memory_compactor
            self._compactor = get_memory_compactor()
        return self._compactor

    @property
    def rate_limiter(self):
        if self._rate_limiter is None:
            from src.core.rate_limiter import get_rate_limiter
            self._rate_limiter = get_rate_limiter()
        return self._rate_limiter

    @property
    def usage_meter(self):
        if self._usage_meter is None:
            from src.core.usage_meter import get_usage_meter
            self._usage_meter = get_usage_meter()
        return self._usage_meter

    # ── observability trace ────────────────────────────────

    def trace(self, subsystem: str, action: str,
              level: ResourceLevel = ResourceLevel.OK,
              details: Optional[Dict[str, Any]] = None):
        """Record a resource event for observability."""
        event = ResourceEvent(
            subsystem=subsystem,
            action=action,
            level=level,
            details=details or {},
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._MAX_EVENTS:
                self._events = self._events[-self._MAX_EVENTS:]

        if level in (ResourceLevel.CRITICAL, ResourceLevel.PAUSE, ResourceLevel.OOM):
            logger.warning(f"[{subsystem}] {action} → {level.value}: {details}")

    def get_traces(self, subsystem: str = None, limit: int = 20) -> List[Dict]:
        """Get recent resource events, optionally filtered by subsystem."""
        with self._lock:
            events = self._events
            if subsystem:
                events = [e for e in events if e.subsystem == subsystem]
            return [
                {
                    "subsystem": e.subsystem,
                    "action": e.action,
                    "level": e.level.value,
                    "details": e.details,
                    "timestamp": e.timestamp,
                }
                for e in events[-limit:]
            ]

    # ── task gating (pre-task check) ───────────────────────

    def pre_task(self) -> Tuple[bool, str]:
        """Check if a new task should be accepted.

        Returns:
            (allowed, reason) — False = reject with reason.
        """
        # 1. Check auto_healer throttle flag
        if self.healer.should_throttle:
            self.trace("resource_manager", "task_rejected",
                       ResourceLevel.PAUSE,
                       {"reason": "healer_throttle"})
            return False, "system under memory/cpu pressure, retry later"

        # 2. Check rate limiter
        try:
            result = self.rate_limiter.check("task:accept")
            if not result.allowed:
                self.trace("resource_manager", "task_rejected",
                           ResourceLevel.WARN,
                           {"reason": "rate_limited", "retry_after": result.retry_after})
                return False, f"rate limited, retry in {result.retry_after:.0f}s"
        except Exception:
            pass  # rate limiter not critical for task acceptance

        self.trace("resource_manager", "task_accepted", ResourceLevel.OK)
        return True, "ok"

    # ── health dashboard ───────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """Unified health report across all four subsystems."""
        now = time.time()

        # Auto-healer checks
        try:
            healer_checks = self.healer.check_all()
            healer_stats = self.healer.get_stats()
        except Exception as e:
            healer_checks = []
            healer_stats = {"error": str(e)}

        # Memory compactor stats
        try:
            compactor_stats = self.compactor.get_stats()
        except Exception as e:
            compactor_stats = {"error": str(e)}

        # Rate limiter stats
        try:
            rl_stats = self.rate_limiter.get_stats()
        except Exception as e:
            rl_stats = {"error": str(e)}

        # Usage meter stats
        try:
            um_stats = self.usage_meter.get_stats()
        except Exception as e:
            um_stats = {"error": str(e)}

        # Aggregate status
        crit_count = sum(1 for c in healer_checks if c.status == "critical")
        warn_count = sum(1 for c in healer_checks if c.status == "warn")
        ok_count = sum(1 for c in healer_checks if c.status == "ok")

        overall = "healthy"
        if crit_count > 0:
            overall = "degraded"
        if self.healer.should_throttle:
            overall = "throttled"

        return {
            "status": overall,
            "uptime_seconds": round(now - self._start_time),
            "subsystems": {
                "auto_healer": {
                    "checks": [{"name": c.name, "status": c.status, "message": c.message}
                               for c in healer_checks],
                    "stats": healer_stats,
                },
                "memory_compactor": compactor_stats,
                "rate_limiter": rl_stats,
                "usage_meter": um_stats,
            },
            "budget": {
                "swarm_mb": self._budget.swarm,
                "terminal_mb": self._budget.terminal,
                "cache_mb": self._budget.cache,
                "gateway_mb": self._budget.gateway,
                "total_mb": self._budget.total_mb,
            },
            "recent_events": self.get_traces(limit=10),
        }

    # ── budget management ──────────────────────────────────

    def set_budget(self, **kwargs: int):
        """Adjust per-subsystem budget. e.g. set_budget(swarm=300, cache=200)."""
        for key, val in kwargs.items():
            if hasattr(self._budget, key):
                setattr(self._budget, key, val)
        logger.info(f"Budget updated: {self._budget}")

    @property
    def budget(self) -> ResourceBudget:
        return self._budget


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_resource_manager: Optional[ResourceManager] = None
_lock_rm = threading.Lock()


def get_resource_manager() -> ResourceManager:
    global _resource_manager
    if _resource_manager is None:
        with _lock_rm:
            if _resource_manager is None:
                _resource_manager = ResourceManager()
                logger.info("ResourceManager initialized")
    return _resource_manager

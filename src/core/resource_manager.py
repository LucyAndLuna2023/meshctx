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


class _StubSubsystem:
    """核心闭源子系统 (auto_healer/memory_compactor/rate_limiter/usage_meter)
    未安装时的优雅降级 — 所有查询返回"健康/无限制"默认值, 不抛错."""
    level = "healthy"
    status = "ok"
    _active = True

    # 2026-08-25 002meshctx 复审 P1 修复: 原为属性 `should_throttle = False`,
    # 但调用点已方法化 `self.healer.should_throttle()` → 降级路径 TypeError。
    # 改为方法, 兼容真实 AutoHealerV2 的方法契约。
    def should_throttle(self) -> bool:
        return False

    def __getattr__(self, name):
        # 未定义属性 → 返回 bound stub (可调用, 返回空 dict — 与 get_stats/check 语义兼容)
        return _StubMethod(name)

    def __bool__(self):
        return False


class _StubMethod:
    """Stub 子系统的任意方法 — 调用返回空 dict (与 check_all/get_stats/check 兼容)"""
    def __init__(self, name):
        self._name = name

    def __call__(self, *a, **kw):
        if self._name in ("check", "pre_task", "can_accept"):
            return True, ""
        if self._name.startswith("is_"):
            return False
        return {}

    def __getattr__(self, name):
        return _StubMethod(f"{self._name}.{name}")

    def __bool__(self):
        return False


# ═══════════════════════════════════════════════════════════


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
            try:
                from src.core.auto_healer import get_auto_healer
                self._healer = get_auto_healer()
            except Exception:
                self._healer = _StubSubsystem()  # 核心闭源未装: 优雅降级
        return self._healer

    @property
    def compactor(self):
        if self._compactor is None:
            try:
                from src.core.memory_compactor import get_memory_compactor
                self._compactor = get_memory_compactor()
            except Exception:
                self._compactor = _StubSubsystem()
        return self._compactor

    @property
    def rate_limiter(self):
        if self._rate_limiter is None:
            try:
                from src.core.rate_limiter import get_rate_limiter
                self._rate_limiter = get_rate_limiter()
            except Exception:
                self._rate_limiter = _StubSubsystem()
        return self._rate_limiter

    @property
    def usage_meter(self):
        if self._usage_meter is None:
            try:
                from src.core.usage_meter import get_usage_meter
                self._usage_meter = get_usage_meter()
            except Exception:
                self._usage_meter = _StubSubsystem()
        return self._usage_meter

    # ── lifecycle ──────────────────────────────────────────

    def start(self):
        """Start background health loop (no-op, tick is on-demand)."""
        logger.info("ResourceManager started")

    def stop(self):
        """Stop background health loop."""
        logger.info("ResourceManager stopped")

    # ── task gating ───────────────────────────────────────

    def can_accept(self, component: str = "swarm") -> bool:
        """Gate: accept new task for component?"""
        ok, _ = self.pre_task()
        return ok

    # ── budget management ──────────────────────────────────

    def allocate(self, component: str, amount_mb: float) -> bool:
        """Try to allocate `amount_mb` from component's budget."""
        try:
            limit = getattr(self._budget, component, 100)
            return amount_mb <= limit
        except Exception:
            return True  # permissive fallback

    def free(self, component: str, amount_mb: float):
        """Release budget allocation (no-op for now)."""
        pass

    # ── dashboard / events ─────────────────────────────────

    def dashboard(self) -> Dict[str, Any]:
        """Unified resource dashboard (alias for health)."""
        return self.health()

    def summary(self) -> str:
        """One-line status summary."""
        d = self.health()
        return f"[{d['status'].upper()}] budget={d['budget']['total_mb']}MB uptime={d['uptime_seconds']}s"

    def get_events(self, component: str = "", event_type: str = "",
                   limit: int = 50) -> List[Dict]:
        """Retrieve recent resource events (filterable)."""
        result = []
        for e in reversed(self._events):
            if component and e.subsystem != component:
                continue
            if event_type and e.action != event_type:
                continue
            result.append({
                "component": e.subsystem,
                "type": e.action,
                "level": e.level.value,
                "detail": str(e.details),
                "timestamp": e.timestamp,
            })
            if len(result) >= limit:
                break
        return result

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
        # 2026-08-25 004meshctx 审计修复: 原 `if self.healer.should_throttle:` 漏括号,
        # 绑定方法对象恒 truthy → 所有任务被永久拒绝 (真 bug)。
        # 2026-08-25 002meshctx 复审加固: getattr 双形态兼容 (属性/方法), 防降级路径 TypeError。
        _throttle_flag = getattr(self.healer, "should_throttle", False)
        if callable(_throttle_flag):
            _throttle_flag = _throttle_flag()
        if _throttle_flag:
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
        # 2026-08-25 004meshctx 审计修复: 同 pre_task — 漏括号导致恒 throttled
        # 2026-08-25 002meshctx 复审加固: getattr 双形态兼容 (属性/方法)
        _throttle_flag = getattr(self.healer, "should_throttle", False)
        if callable(_throttle_flag):
            _throttle_flag = _throttle_flag()
        if _throttle_flag:
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

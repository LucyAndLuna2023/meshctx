"""
meshctx alert_engine — alert management with deduplication, routing, and escalation.
Generates, routes, deduplicates, and manages alert lifecycle.

Key capabilities:
  - AlertLevel / Alert / AlertEngine: extended from existing stub
  - AlertRouting: route alerts to channels (email, Slack, webhook, log)
  - AlertDedupe: suppress duplicate alerts within a window
  - AlertEscalation: escalate unacknowledged alerts after timeout
  - AlertEngine: main orchestrator with full lifecycle management
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ── Enums ──────────────────────────────────────────────────────────────────

class AlertLevel(Enum):
    INFO = 0
    LOW = 1
    WARNING = 2
    MEDIUM = 3
    ERROR = 4
    HIGH = 5
    CRITICAL = 6

    def __ge__(self, other):
        if isinstance(other, AlertLevel):
            return self.value >= other.value
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, AlertLevel):
            return self.value <= other.value
        return NotImplemented


class AlertStatus(Enum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    SUPPRESSED = "suppressed"


class AlertChannel(Enum):
    LOG = "log"
    CONSOLE = "console"
    WEBHOOK = "webhook"
    EMAIL = "email"
    SLACK = "slack"
    CUSTOM = "custom"


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class Alert:
    """An alert with full lifecycle tracking."""
    id: str = ""
    level: AlertLevel = AlertLevel.INFO
    message: str = ""
    source: str = ""                  # Component/module that raised the alert
    status: AlertStatus = AlertStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    acknowledged_at: float = 0.0
    acknowledged_by: str = ""
    resolved_at: float = 0.0
    escalated_at: float = 0.0
    escalation_level: int = 0
    dedupe_key: str = ""
    retry_count: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.md5(
                f"{self.source}:{self.message}:{time.time()}".encode()
            ).hexdigest()[:12]
        if not self.dedupe_key:
            self.dedupe_key = hashlib.md5(
                f"{self.level.value}:{self.message}".encode()
            ).hexdigest()[:16]

    def ack(self, by: str = "system") -> None:
        """Acknowledge the alert."""
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = time.time()
        self.acknowledged_by = by

    def resolve(self) -> None:
        """Mark the alert as resolved."""
        self.status = AlertStatus.RESOLVED
        self.resolved_at = time.time()

    def escalate(self) -> None:
        """Escalate the alert to the next level."""
        self.status = AlertStatus.ESCALATED
        self.escalated_at = time.time()
        self.escalation_level += 1

    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def acknowledged(self) -> bool:
        return self.status == AlertStatus.ACKNOWLEDGED and self.acknowledged_at > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level.name,
            "message": self.message,
            "source": self.source,
            "status": self.status.value,
            "tags": self.tags,
            "age_seconds": round(self.age_seconds(), 1),
            "escalation_level": self.escalation_level,
        }


# ── Alert Deduplication ───────────────────────────────────────────────────

class AlertDeduplicator:
    """Suppresses duplicate alerts within a configurable time window."""

    def __init__(self, window_seconds: float = 300.0, max_cache: int = 1000):
        self.window = window_seconds
        self._cache: Dict[str, float] = {}        # dedupe_key -> last_seen
        self._lock = threading.Lock()
        self.max_cache = max_cache

    def is_duplicate(self, alert: Alert) -> bool:
        """Check if this alert is a duplicate of a recent one."""
        with self._lock:
            last = self._cache.get(alert.dedupe_key, 0)
            if time.time() - last < self.window:
                return True
            return False

    def record(self, alert: Alert) -> None:
        """Record an alert for future deduplication."""
        with self._lock:
            self._cache[alert.dedupe_key] = time.time()
            # Prune old entries
            if len(self._cache) > self.max_cache:
                cutoff = time.time() - self.window
                stale = [k for k, v in self._cache.items() if v < cutoff]
                for k in stale:
                    del self._cache[k]

    def flush(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"cache_size": len(self._cache), "window_seconds": self.window}


# ── Alert Routing ─────────────────────────────────────────────────────────

class AlertRouter:
    """Routes alerts to configured channels."""

    def __init__(self):
        self._routes: Dict[AlertLevel, List[AlertChannel]] = {
            AlertLevel.INFO: [AlertChannel.LOG],
            AlertLevel.WARNING: [AlertChannel.LOG, AlertChannel.CONSOLE],
            AlertLevel.ERROR: [AlertChannel.LOG, AlertChannel.CONSOLE],
            AlertLevel.CRITICAL: [AlertChannel.LOG, AlertChannel.CONSOLE],
        }
        self._handlers: Dict[AlertChannel, Callable] = {}
        self._lock = threading.Lock()

    def set_route(self, level: AlertLevel, channels: List[AlertChannel]) -> None:
        """Set routing channels for a given alert level."""
        with self._lock:
            self._routes[level] = channels

    def register_handler(self, channel: AlertChannel, handler: Callable) -> None:
        """Register a custom handler for a channel.
        
        Handler signature: handler(alert: Alert) -> None
        """
        self._handlers[channel] = handler

    def route(self, alert: Alert) -> List[AlertChannel]:
        """Route an alert to the appropriate channels."""
        channels = self._routes.get(alert.level, [AlertChannel.LOG])
        for channel in channels:
            handler = self._handlers.get(channel)
            if handler:
                try:
                    handler(alert)
                except Exception:
                    pass
        return channels

    def stats(self) -> Dict[str, Any]:
        return {
            "routes": {lvl.name: [ch.value for ch in chs] for lvl, chs in self._routes.items()},
            "registered_handlers": [ch.value for ch in self._handlers],
        }


# ── Alert Escalation ──────────────────────────────────────────────────────

class AlertEscalator:
    """Escalates unacknowledged alerts after timeouts."""

    def __init__(self):
        # level -> (timeout_seconds, escalate_to_level)
        self._policies: Dict[AlertLevel, tuple] = {
            AlertLevel.WARNING: (3600.0, AlertLevel.ERROR),      # 1 hour
            AlertLevel.ERROR: (900.0, AlertLevel.CRITICAL),      # 15 min
            AlertLevel.CRITICAL: (300.0, AlertLevel.CRITICAL),   # 5 min (re-escalate)
        }
        self._lock = threading.Lock()

    def set_policy(
        self, level: AlertLevel, timeout: float, escalate_to: AlertLevel,
    ) -> None:
        """Set escalation policy for a level."""
        with self._lock:
            self._policies[level] = (timeout, escalate_to)

    def check(self, alert: Alert) -> Optional[Alert]:
        """Check if an alert needs escalation. Returns escalated alert or None."""
        if alert.status != AlertStatus.ACTIVE:
            return None

        policy = self._policies.get(alert.level)
        if not policy:
            return None

        timeout, new_level = policy
        if alert.age_seconds() < timeout:
            return None

        # Escalate
        new_alert = Alert(
            level=new_level,
            message=f"[ESCALATED from {alert.level.name}] {alert.message}",
            source=alert.source,
            status=AlertStatus.ACTIVE,
            tags=alert.tags + ["escalated"],
            escalation_level=alert.escalation_level + 1,
        )
        alert.escalate()
        return new_alert

    def stats(self) -> Dict[str, Any]:
        return {
            "policies": {
                lvl.name: {"timeout": tout, "escalate_to": to_lvl.name}
                for lvl, (tout, to_lvl) in self._policies.items()
            }
        }


# ── Alert History ─────────────────────────────────────────────────────────

class AlertHistory:
    """Stores alert history with query capabilities."""

    def __init__(self, max_size: int = 10000):
        self.alerts: deque = deque(maxlen=max_size)
        self._by_id: Dict[str, Alert] = {}
        self._lock = threading.Lock()

    def add(self, alert: Alert) -> None:
        with self._lock:
            self.alerts.append(alert)
            self._by_id[alert.id] = alert

    def get(self, alert_id: str) -> Optional[Alert]:
        with self._lock:
            return self._by_id.get(alert_id)

    def query(
        self, level: AlertLevel = None, status: AlertStatus = None,
        source: str = "", tag: str = "", limit: int = 50,
    ) -> List[Alert]:
        """Query alerts with filters."""
        with self._lock:
            results: List[Alert] = []
            for alert in reversed(self.alerts):
                if level and alert.level != level:
                    continue
                if status and alert.status != status:
                    continue
                if source and alert.source != source:
                    continue
                if tag and tag not in alert.tags:
                    continue
                results.append(alert)
                if len(results) >= limit:
                    break
            return results

    def count_by_level(self) -> Dict[str, int]:
        with self._lock:
            counts = defaultdict(int)
            for alert in self.alerts:
                counts[alert.level.name] += 1
            return dict(counts)

    def count_by_status(self) -> Dict[str, int]:
        with self._lock:
            counts = defaultdict(int)
            for alert in self.alerts:
                counts[alert.status.value] += 1
            return dict(counts)

    def flush(self) -> None:
        with self._lock:
            self.alerts.clear()
            self._by_id.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total": len(self.alerts),
                "by_level": self.count_by_level(),
                "by_status": self.count_by_status(),
            }


# ── Main Alert Engine ─────────────────────────────────────────────────────

class AlertEngine:
    """Main alert lifecycle manager.

    Combines deduplication, routing, escalation, and history into a unified alert system.
    """

    def __init__(
        self,
        dedupe_window: float = 300.0,
        max_history: int = 10000,
    ):
        self.deduplicator = AlertDeduplicator(window_seconds=dedupe_window)
        self.router = AlertRouter()
        self.escalator = AlertEscalator()
        self.history = AlertHistory(max_size=max_history)
        self._active_alerts: Dict[str, Alert] = {}
        self._lock = threading.Lock()

    # ── Alerting ──────────────────────────────────────────────────────

    def alert(
        self,
        level: AlertLevel,
        message: str,
        source: str = "system",
        tags: List[str] = None,
        metadata: Dict[str, Any] = None,
    ) -> Optional[Alert]:
        """Create and process an alert. Returns None if suppressed as duplicate."""
        alert = Alert(
            level=level,
            message=message,
            source=source,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Deduplication
        if self.deduplicator.is_duplicate(alert):
            alert.status = AlertStatus.SUPPRESSED
            self.history.add(alert)
            return None

        self.deduplicator.record(alert)

        # Route to channels
        self.router.route(alert)

        # Track and store
        with self._lock:
            self._active_alerts[alert.id] = alert

        self.history.add(alert)
        return alert

    # ── Lifecycle ─────────────────────────────────────────────────────

    def acknowledge(self, alert_id: str, by: str = "system") -> bool:
        """Acknowledge an alert."""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if not alert:
                alert = self.history.get(alert_id)
            if not alert:
                return False
            alert.ack(by)
            return True

    def resolve(self, alert_id: str) -> bool:
        """Resolve an alert."""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if not alert:
                return False
            alert.resolve()
            del self._active_alerts[alert_id]
            return True

    def resolve_all(self, source: str = "") -> int:
        """Resolve all active alerts, optionally filtered by source."""
        count = 0
        with self._lock:
            to_resolve = [
                aid for aid, alert in self._active_alerts.items()
                if not source or alert.source == source
            ]
            for aid in to_resolve:
                self._active_alerts[aid].resolve()
                del self._active_alerts[aid]
                count += 1
        return count

    def escalate(self, alert_id: str) -> bool:
        """Manually escalate an alert to the next severity level."""
        with self._lock:
            alert = self._active_alerts.get(alert_id)
            if not alert:
                alert = self.history.get(alert_id)
            if not alert:
                return False
        escalation_map = {
            AlertLevel.INFO: AlertLevel.LOW,
            AlertLevel.LOW: AlertLevel.WARNING,
            AlertLevel.WARNING: AlertLevel.MEDIUM,
            AlertLevel.MEDIUM: AlertLevel.HIGH,
            AlertLevel.ERROR: AlertLevel.HIGH,
            AlertLevel.HIGH: AlertLevel.CRITICAL,
            AlertLevel.CRITICAL: AlertLevel.CRITICAL,
        }
        new_level = escalation_map.get(alert.level, alert.level)
        alert.level = new_level
        alert.escalate()
        return True

    def get_stats(self) -> dict:
        """Return stats with 'total' key for backwards compat."""
        with self._lock:
            return {"total": len(self.history.alerts)}

    def check_escalations(self) -> List[Alert]:
        """Check all active alerts for escalation. Returns newly escalated alerts."""
        escalated: List[Alert] = []
        with self._lock:
            for alert in list(self._active_alerts.values()):
                new_alert = self.escalator.check(alert)
                if new_alert:
                    self.deduplicator.record(new_alert)
                    self.router.route(new_alert)
                    self._active_alerts[new_alert.id] = new_alert
                    self.history.add(new_alert)
                    escalated.append(new_alert)
        return escalated

    def start_escalation_monitor(self, interval: float = 30.0) -> None:
        """Start a background thread that periodically checks for escalations."""
        def _monitor():
            while not self._shutdown.is_set():
                self.check_escalations()
                self._shutdown.wait(interval)

        self._shutdown = threading.Event()
        t = threading.Thread(target=_monitor, daemon=True)
        t.start()

    def stop_escalation_monitor(self) -> None:
        if hasattr(self, '_shutdown'):
            self._shutdown.set()

    # ── Query ─────────────────────────────────────────────────────────

    def get_active(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in self._active_alerts.values()]

    def get_by_level(self, level: AlertLevel) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.history.query(level=level)]

    def get_by_source(self, source: str) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.history.query(source=source)]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.history.query(limit=limit)]

    # ── Management ────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active_alerts": len(self._active_alerts),
                "by_level": {
                    lvl.name: sum(1 for a in self._active_alerts.values() if a.level == lvl)
                    for lvl in AlertLevel
                },
                "history": self.history.stats(),
                "deduplicator": self.deduplicator.stats(),
                "escalator": self.escalator.stats(),
                "router": self.router.stats(),
            }

    def flush(self) -> None:
        self.deduplicator.flush()
        self.history.flush()
        with self._lock:
            self._active_alerts.clear()


# ── Global instance ───────────────────────────────────────────────────────

_engine: Optional[AlertEngine] = None


def get_alert_engine() -> AlertEngine:
    global _engine
    if _engine is None:
        _engine = AlertEngine()
    return _engine

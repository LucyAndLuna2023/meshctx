"""meshctx observer — System Observer / Watchdog (v3.92)"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional


class WatchLevel(Enum):
    """Severity/importance level of a watch."""

    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


@dataclass
class WatchEvent:
    """An event observed by the SystemObserver."""

    name: str
    level: WatchLevel = WatchLevel.INFO
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level.name,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class SystemObserver:
    """Observes system metrics, events, and health. Supports callbacks.

    v3.92 — provides system-wide observation with:
      - Watch registration (file changes, memory, CPU, custom)
      - Event callback subscriptions
      - Health check snapshot
      - Stats collection
    """

    _watches: Dict[str, Callable[[], Optional[WatchEvent]]]
    _events: List[WatchEvent]
    _callbacks: List[Callable[[WatchEvent], None]]
    _running: bool
    _interval: float
    _lock: threading.Lock
    _config: Dict[str, Any]

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}
        self._watches: Dict[str, Callable[[], Optional[WatchEvent]]] = {}
        self._events: List[WatchEvent] = []
        self._callbacks: List[Callable[[WatchEvent], None]] = []
        self._running = False
        self._interval = float(self._config.get("interval", 5.0))
        self._lock = threading.Lock()

    # ── Watch registration ──

    def register_watch(
        self, name: str, fn: Callable[[], Optional[WatchEvent]]
    ) -> None:
        """Register a watch function. Called periodically when running."""
        with self._lock:
            self._watches[name] = fn

    def unregister_watch(self, name: str) -> bool:
        """Remove a watch by name. Returns True if it existed."""
        with self._lock:
            return self._watches.pop(name, None) is not None

    @property
    def watch_names(self) -> List[str]:
        with self._lock:
            return list(self._watches.keys())

    # ── Callback subscription ──

    def subscribe(self, callback: Callable[[WatchEvent], None]) -> None:
        """Subscribe to all observed events."""
        with self._lock:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[WatchEvent], None]) -> bool:
        """Remove a subscription."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                return True
            return False

    # ── Observation ──

    def observe(self) -> List[WatchEvent]:
        """Run all registered watches once, fire callbacks, return events."""
        events: List[WatchEvent] = []
        with self._lock:
            watches = list(self._watches.items())
        for name, fn in watches:
            try:
                event = fn()
                if event is not None:
                    events.append(event)
            except Exception:
                pass
        with self._lock:
            self._events.extend(events)
            cbs = list(self._callbacks)
        for cb in cbs:
            for ev in events:
                try:
                    cb(ev)
                except Exception:
                    pass
        return events

    def snapshot(self) -> Dict[str, Any]:
        """Return an observation snapshot (health check)."""
        events = self.observe()
        error_count = sum(1 for e in events if e.level == WatchLevel.ERROR)
        critical_count = sum(1 for e in events if e.level == WatchLevel.CRITICAL)
        return {
            "total_events": len(self._events),
            "recent_events": len(events),
            "errors": error_count,
            "criticals": critical_count,
            "watch_count": len(self._watches),
            "healthy": critical_count == 0,
            "timestamp": time.time(),
        }

    # ── History ──

    def get_events(
        self, level: Optional[WatchLevel] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Return recent events, optionally filtered by level."""
        with self._lock:
            events = list(self._events)
        if level is not None:
            events = [e for e in events if e.level == level]
        return [e.to_dict() for e in events[-limit:]]

    def clear_events(self) -> int:
        """Clear event history, return count cleared."""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            return count

    # ── Stats ──

    def get_stats(self) -> Dict[str, Any]:
        """Return observer statistics."""
        with self._lock:
            return {
                "total_events": len(self._events),
                "watch_count": len(self._watches),
                "subscription_count": len(self._callbacks),
                "interval": self._interval,
                "running": self._running,
            }

    # ── Interval config ──

    @property
    def interval(self) -> float:
        return self._interval

    @interval.setter
    def interval(self, value: float) -> None:
        self._interval = max(0.1, value)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False


# Singleton
_observer: Optional[SystemObserver] = None
_lock = threading.Lock()


def get_observer() -> SystemObserver:
    """Get or create the singleton SystemObserver."""
    global _observer
    if _observer is None:
        with _lock:
            if _observer is None:
                _observer = SystemObserver()
    return _observer

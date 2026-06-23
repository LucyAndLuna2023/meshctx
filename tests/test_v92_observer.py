"""v3.92 System Observer — 测试"""
import time
import pytest
from src.core.observer import (
    SystemObserver,
    WatchEvent,
    WatchLevel,
    get_observer,
)


class TestWatchEvent:
    def test_event_creation(self):
        e = WatchEvent(name="test_event", level=WatchLevel.WARNING, message="disk full")
        assert e.name == "test_event"
        assert e.level == WatchLevel.WARNING
        assert e.message == "disk full"
        assert e.data == {}
        assert e.timestamp > 0

    def test_event_to_dict(self):
        e = WatchEvent(
            name="cpu_spike",
            level=WatchLevel.ERROR,
            message="CPU > 90%",
            data={"cpu": 95.5},
        )
        d = e.to_dict()
        assert d["name"] == "cpu_spike"
        assert d["level"] == "ERROR"
        assert d["message"] == "CPU > 90%"
        assert d["data"] == {"cpu": 95.5}


class TestSystemObserver:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.obs = SystemObserver()

    # ── Registration ──

    def test_register_watch(self):
        self.obs.register_watch("disk", lambda: None)
        assert "disk" in self.obs.watch_names

    def test_unregister_watch(self):
        self.obs.register_watch("disk", lambda: None)
        assert self.obs.unregister_watch("disk")
        assert "disk" not in self.obs.watch_names

    def test_unregister_watch_missing(self):
        assert not self.obs.unregister_watch("nonexistent")

    # ── Observation ──

    def test_observe_calls_watches(self):
        called = []

        def watch_fn():
            called.append(1)
            return WatchEvent(name="test")

        self.obs.register_watch("test", watch_fn)
        events = self.obs.observe()
        assert len(called) == 1
        assert len(events) == 1
        assert events[0].name == "test"

    def test_observe_skips_none(self):
        self.obs.register_watch("returns_none", lambda: None)
        events = self.obs.observe()
        assert len(events) == 0

    def test_observe_handles_exceptions(self):
        def bad_watch():
            raise RuntimeError("boom")

        self.obs.register_watch("bad", bad_watch)
        events = self.obs.observe()  # should not raise
        assert events == []

    # ── Callbacks ──

    def test_subscribe_callback(self):
        received = []

        def cb(event: WatchEvent):
            received.append(event.name)

        self.obs.subscribe(cb)
        self.obs.register_watch("alert", lambda: WatchEvent(name="alert"))
        self.obs.observe()
        assert received == ["alert"]

    def test_unsubscribe_callback(self):
        received = []

        def cb(event: WatchEvent):
            received.append(event.name)

        self.obs.subscribe(cb)
        assert self.obs.unsubscribe(cb)
        self.obs.register_watch("alert", lambda: WatchEvent(name="alert"))
        self.obs.observe()
        assert received == []  # unsubscribed, not called

    def test_unsubscribe_missing(self):
        def cb(_): pass
        assert not self.obs.unsubscribe(cb)

    # ── Snapshot ──

    def test_snapshot(self):
        self.obs.register_watch(
            "error_watch", lambda: WatchEvent(name="err", level=WatchLevel.ERROR)
        )
        snap = self.obs.snapshot()
        assert "total_events" in snap
        assert "recent_events" in snap
        assert "errors" in snap
        assert "healthy" in snap
        assert snap["errors"] == 1
        assert snap["healthy"] is True  # errors != critical

    def test_snapshot_unhealthy(self):
        self.obs.register_watch(
            "crit", lambda: WatchEvent(name="crit", level=WatchLevel.CRITICAL)
        )
        snap = self.obs.snapshot()
        assert snap["criticals"] == 1
        assert snap["healthy"] is False

    # ── History ──

    def test_get_events_all(self):
        self.obs.register_watch("a", lambda: WatchEvent(name="a"))
        self.obs.register_watch("b", lambda: WatchEvent(name="b"))
        self.obs.observe()
        events = self.obs.get_events()
        assert len(events) == 2

    def test_get_events_filtered(self):
        self.obs.register_watch(
            "err", lambda: WatchEvent(name="err", level=WatchLevel.ERROR)
        )
        self.obs.register_watch(
            "info", lambda: WatchEvent(name="info", level=WatchLevel.INFO)
        )
        self.obs.observe()
        errors = self.obs.get_events(level=WatchLevel.ERROR)
        assert len(errors) == 1
        assert errors[0]["name"] == "err"

    def test_clear_events(self):
        self.obs.register_watch("a", lambda: WatchEvent(name="a"))
        self.obs.observe()
        count = self.obs.clear_events()
        assert count == 1
        assert self.obs.get_events() == []

    # ── Stats ──

    def test_get_stats(self):
        self.obs.register_watch("a", lambda: None)
        self.obs.register_watch("b", lambda: None)
        stats = self.obs.get_stats()
        assert stats["watch_count"] == 2
        assert stats["subscription_count"] == 0
        assert "interval" in stats
        assert "running" in stats

    # ── Config ──

    def test_init_with_config(self):
        obs = SystemObserver({"interval": 10.0})
        assert obs.interval == 10.0

    def test_interval_setter(self):
        self.obs.interval = 3.0
        assert self.obs.interval == 3.0

    def test_interval_minimum(self):
        self.obs.interval = 0.01
        assert self.obs.interval == 0.1  # clamped to min

    # ── Run state ──

    def test_start_stop(self):
        assert not self.obs.is_running
        self.obs.start()
        assert self.obs.is_running
        self.obs.stop()
        assert not self.obs.is_running

    # ── Watch names property ──

    def test_watch_names(self):
        self.obs.register_watch("cpu", lambda: None)
        self.obs.register_watch("mem", lambda: None)
        assert set(self.obs.watch_names) == {"cpu", "mem"}


class TestSingleton:
    def test_get_observer_singleton(self):
        o1 = get_observer()
        o2 = get_observer()
        assert o1 is o2

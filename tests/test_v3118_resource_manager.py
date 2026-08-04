"""Tests for ResourceManager (v3.118.0)."""
import pytest
from src.core.resource_manager import (
    ResourceLevel, ResourceBudget, ResourceEvent, ResourceManager,
    get_resource_manager,
)


class TestResourceManager:
    def test_init(self):
        rm = ResourceManager()
        assert rm._budget.total_mb == 1024
        assert rm._budget.swarm == 400
        assert rm._budget.terminal == 200
        assert rm._budget.cache == 150
        assert rm._budget.gateway == 100

    def test_pre_task(self):
        rm = ResourceManager()
        ok, reason = rm.pre_task()
        assert ok is True
        assert reason == "ok"

    def test_health(self):
        rm = ResourceManager()
        h = rm.health()
        assert h["status"] == "healthy"
        assert "subsystems" in h
        assert "budget" in h
        assert h["budget"]["total_mb"] == 1024

    def test_trace_and_events(self):
        rm = ResourceManager()
        rm._events.clear()
        rm.trace("test", "smoke", ResourceLevel.OK, {"x": 1})
        rm.trace("test", "error", ResourceLevel.CRITICAL, {"msg": "bad"})
        events = rm.get_traces()  # default limit=20, oldest-first
        assert len(events) == 2
        assert events[0]["level"] == "ok"
        assert events[1]["level"] == "critical"

    def test_get_events_filtered(self):
        rm = ResourceManager()
        rm._events.clear()
        rm.trace("A", "run", ResourceLevel.OK, {})
        rm.trace("B", "fail", ResourceLevel.WARN, {})
        rm.trace("A", "run", ResourceLevel.OK, {})
        filtered = rm.get_events(component="A")
        assert len(filtered) == 2
        assert all(e["component"] == "A" for e in filtered)
        filtered = rm.get_events(event_type="fail")
        assert len(filtered) == 1
        assert filtered[0]["component"] == "B"

    def test_event_ring_buffer(self):
        rm = ResourceManager()
        rm._events.clear()
        for i in range(600):
            rm.trace("fill", "test", ResourceLevel.OK, {"i": i})
        events = rm.get_traces(limit=500)
        assert len(events) == 500

    def test_set_budget(self):
        rm = ResourceManager()
        rm.set_budget(swarm=800)
        assert rm._budget.swarm == 800
        assert rm._budget.total_mb == 1424

    def test_can_accept(self):
        rm = ResourceManager()
        assert rm.can_accept() is True

    def test_dashboard(self):
        rm = ResourceManager()
        d = rm.dashboard()
        assert d["status"] == "healthy"

    def test_summary(self):
        rm = ResourceManager()
        s = rm.summary()
        assert "[HEALTHY]" in s
        assert "1024MB" in s

    def test_resource_level_order(self):
        levels = list(ResourceLevel)
        assert levels[0] == ResourceLevel.OK
        assert levels[-1] == ResourceLevel.OOM


class TestSingleton:
    def test_singleton(self):
        import src.core.resource_manager as rm_mod
        rm_mod._resource_manager = None
        rm1 = get_resource_manager()
        rm2 = get_resource_manager()
        assert rm1 is rm2

    def test_budget_default(self):
        import src.core.resource_manager as rm_mod
        rm_mod._resource_manager = None
        rm = get_resource_manager()
        b = rm._budget
        assert b.swarm + b.terminal + b.cache + b.gateway == 850
        assert b.total_mb == 1024


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

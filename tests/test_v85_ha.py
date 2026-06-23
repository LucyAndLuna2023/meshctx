"""v3.85 Home Assistant Bridge — 测试"""
import pytest
from src.core.ha_bridge import (
    HAEntity,
    HAService,
    HABridge,
    get_ha_bridge,
)


class TestHAEntity:
    def test_entity_creation(self):
        e = HAEntity("light.living_room", "on", {"brightness": 128})
        assert e.entity_id == "light.living_room"
        assert e.state == "on"
        assert e.attributes == {"brightness": 128}
        assert e.domain == "light"

    def test_entity_to_dict(self):
        e = HAEntity("sensor.temp", "22.5", {"unit": "°C"})
        d = e.to_dict()
        assert d["entity_id"] == "sensor.temp"
        assert d["state"] == "22.5"
        assert d["domain"] == "sensor"

    def test_entity_defaults(self):
        e = HAEntity("switch.garage")
        assert e.state == "unknown"
        assert e.attributes == {}
        assert e.domain == "switch"


class TestHAService:
    def test_service_creation(self):
        s = HAService("light", "turn_on", "Turn on", {"entity_id": "str"})
        assert s.domain == "light"
        assert s.service == "turn_on"
        assert s.full_name == "light.turn_on"

    def test_service_to_dict(self):
        s = HAService("notify", "send", "Send message")
        d = s.to_dict()
        assert d["domain"] == "notify"
        assert d["full_name"] == "notify.send"
        assert "description" in d


class TestHABridge:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.bridge = HABridge()

    # ── Connection ──

    def test_connect(self):
        assert not self.bridge.is_connected
        self.bridge.connect()
        assert self.bridge.is_connected

    def test_disconnect(self):
        self.bridge.connect()
        self.bridge.disconnect()
        assert not self.bridge.is_connected

    # ── Entities ──

    def test_list_entities_all(self):
        entities = self.bridge.list_entities()
        assert isinstance(entities, list)
        assert len(entities) >= 4

    def test_list_entities_by_domain(self):
        lights = self.bridge.list_entities(domain="light")
        assert all(e["domain"] == "light" for e in lights)

    def test_get_state_exists(self):
        state = self.bridge.get_state("light.living_room")
        assert state is not None
        assert state["entity_id"] == "light.living_room"
        assert "state" in state

    def test_get_state_missing(self):
        state = self.bridge.get_state("nonexistent.thing")
        assert state is None

    def test_set_state(self):
        assert self.bridge.set_state("light.living_room", "off")
        state = self.bridge.get_state("light.living_room")
        assert state["state"] == "off"

    def test_set_state_missing(self):
        assert not self.bridge.set_state("nonexistent.thing", "on")

    # ── Services ──

    def test_list_services_all(self):
        services = self.bridge.list_services()
        assert isinstance(services, list)
        assert len(services) >= 2

    def test_list_services_by_domain(self):
        svcs = self.bridge.list_services(domain="light")
        names = [s["full_name"] for s in svcs]
        assert "light.turn_on" in names

    def test_call_service_light_on(self):
        ok, msg = self.bridge.call_service(
            "light", "turn_on", {"entity_id": "light.kitchen"}
        )
        assert ok
        assert self.bridge.get_state("light.kitchen")["state"] == "on"

    def test_call_service_light_off(self):
        ok, msg = self.bridge.call_service(
            "light", "turn_off", {"entity_id": "light.living_room"}
        )
        assert ok
        assert self.bridge.get_state("light.living_room")["state"] == "off"

    def test_call_service_not_found(self):
        ok, msg = self.bridge.call_service("nonexistent", "do_thing")
        assert not ok

    def test_call_service_switch_toggle(self):
        ok, msg = self.bridge.call_service(
            "switch", "toggle", {"entity_id": "switch.garage_door"}
        )
        assert ok

    # ── Stats ──

    def test_get_stats(self):
        stats = self.bridge.get_stats()
        assert "total_entities" in stats
        assert "total_services" in stats
        assert "connected" in stats
        assert "domains" in stats
        assert stats["total_entities"] >= 4


class TestSingleton:
    def test_get_ha_bridge_singleton(self):
        b1 = get_ha_bridge()
        b2 = get_ha_bridge()
        assert b1 is b2

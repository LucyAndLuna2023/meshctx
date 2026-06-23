"""meshctx ha_bridge — Home Assistant integration bridge"""

import threading
from typing import Any, Dict, List, Optional, Tuple


class HAEntity:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Represents a Home Assistant entity."""

    entity_id: str
    state: str
    attributes: Dict[str, Any]
    domain: str

    def __init__(
        self,
        entity_id: str,
        state: str = "unknown",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        self.domain = entity_id.split(".")[0] if "." in entity_id else ""

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": self.attributes,
            "domain": self.domain,
        }


class HAService:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Represents a Home Assistant service."""

    domain: str
    service: str
    description: str
    fields: Dict[str, Any]

    def __init__(
        self,
        domain: str,
        service: str,
        description: str = "",
        fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.domain = domain
        self.service = service
        self.description = description
        self.fields = fields or {}

    @property
    def full_name(self, **kw) -> str:
        return f"{self.domain}.{self.service}"

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "service": self.service,
            "full_name": self.full_name,
            "description": self.description,
            "fields": self.fields,
        }


class HABridge:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Bridge to Home Assistant — manages entities, states, and services.

    This is a local mock bridge for testing. In production it would connect
    to a real Home Assistant instance via WebSocket / REST API.
    """

    _entities: Dict[str, HAEntity]
    _services: Dict[str, HAService]
    _connected: bool
    _config: Dict[str, Any]

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kw) -> None:
        self._config = config or {}
        self._entities: Dict[str, HAEntity] = {}
        self._services: Dict[str, HAService] = {}
        self._connected = False
        self._seed_defaults()

    def _seed_defaults(self, **kw) -> None:
        """Seed with default entities and services for testing."""
        defaults = [
            HAEntity("light.living_room", "on", {"brightness": 128}),
            HAEntity("light.kitchen", "off", {"brightness": 0}),
            HAEntity("switch.garage_door", "closed", {}),
            HAEntity("sensor.temperature", "22.5", {"unit": "°C"}),
            HAEntity("sensor.humidity", "55", {"unit": "%"}),
            HAEntity("binary_sensor.motion_hall", "off", {}),
        ]
        for e in defaults:
            self._entities[e.entity_id] = e

        svc_defaults = [
            HAService("light", "turn_on", "Turn a light on", {"entity_id": "str"}),
            HAService("light", "turn_off", "Turn a light off", {"entity_id": "str"}),
            HAService("switch", "toggle", "Toggle a switch", {"entity_id": "str"}),
            HAService("notify", "send", "Send a notification", {"message": "str"}),
        ]
        for s in svc_defaults:
            self._services[s.full_name] = s

    # ── Connection ──

    def connect(self, url: str = "", token: str = "", **kw) -> bool:
        """Connect to Home Assistant (mock)."""
        self._connected = True
        return True

    def disconnect(self, **kw) -> None:
        self._connected = False

    @property
    def is_connected(self, **kw) -> bool:
        return self._connected

    # ── Entity methods ──

    def list_entities(self, domain: Optional[str] = None, **kw) -> List[Dict[str, Any]]:
        """List all entities, optionally filtered by domain.

        (This maps to the ha_list_entities tool in AGENTS.md)
        """
        result = []
        for e in self._entities.values():
            if domain is None or e.domain == domain:
                result.append(e.to_dict())
        return result

    def get_state(self, entity_id: str, **kw) -> Optional[Dict[str, Any]]:
        """Get the current state of an entity.

        (This maps to the ha_get_state tool in AGENTS.md)
        """
        e = self._entities.get(entity_id)
        if e is None:
            return None
        return {"entity_id": e.entity_id, "state": e.state, "attributes": e.attributes}

    def set_state(self, entity_id: str, state: str, **kw) -> bool:
        """Set the state of an entity (for testing)."""
        e = self._entities.get(entity_id)
        if e is None:
            return False
        e.state = state
        return True

    # ── Service methods ──

    def list_services(self, domain: Optional[str] = None, **kw) -> List[Dict[str, Any]]:
        """List all services, optionally filtered by domain.

        (This maps to the ha_list_services tool in AGENTS.md)
        """
        result = []
        for s in self._services.values():
            if domain is None or s.domain == domain:
                result.append(s.to_dict())
        return result

    def call_service(
        self, domain: str, service: str, data: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """Call a Home Assistant service.

        (This maps to the ha_call_service tool in AGENTS.md)
        Returns (success: bool, message: str).
        """
        full = f"{domain}.{service}"
        if full not in self._services:
            return False, f"Service not found: {full}"

        # Mock service execution: light.turn_on / light.turn_off
        if domain == "light" and service in ("turn_on", "turn_off"):
            entity_id = (data or {}).get("entity_id", "")
            if entity_id and entity_id in self._entities:
                self._entities[entity_id].state = "on" if service == "turn_on" else "off"
                return True, f"{entity_id} → {self._entities[entity_id].state}"
            return True, "ok"

        if domain == "switch" and service == "toggle":
            entity_id = (data or {}).get("entity_id", "")
            if entity_id and entity_id in self._entities:
                cur = self._entities[entity_id].state
                self._entities[entity_id].state = "closed" if cur == "open" else "open"
                return True, f"{entity_id} toggled to {self._entities[entity_id].state}"
            return True, "ok"

        return True, f"Service {full} called"

    # ── Stats ──

    def get_stats(self, **kw) -> Dict[str, Any]:
        """Return bridge statistics."""
        return {
            "total_entities": len(self._entities),
            "total_services": len(self._services),
            "connected": self._connected,
            "domains": list({e.domain for e in self._entities.values()}),
        }


# Singleton
_bridge: Optional[HABridge] = None
_lock = threading.Lock()


def get_ha_bridge() -> HABridge:
    """Get or create the singleton HABridge."""
    global _bridge
    if _bridge is None:
        with _lock:
            if _bridge is None:
                _bridge = HABridge()
    return _bridge

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


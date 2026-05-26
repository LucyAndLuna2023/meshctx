"""Event Bus — v3.19"""
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional
logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self): self._handlers: Dict[str, List[Callable]] = defaultdict(list)
    def on(self, event: str, handler: Callable): self._handlers[event].append(handler)
    def emit(self, event: str, **data): 
        results = []
        for h in self._handlers.get(event, []):
            try: results.append(h(data))
            except Exception as e: results.append({"error": str(e)})
        return results
    def off(self, event: str, handler: Callable):
        if event in self._handlers and handler in self._handlers[event]:
            self._handlers[event].remove(handler)
    def listener_count(self, event: str) -> int: return len(self._handlers.get(event, []))
    def get_stats(self) -> Dict:
        return {"events": len(self._handlers), "total_listeners": sum(len(v) for v in self._handlers.values()),
                "events_list": list(self._handlers.keys())[:20]}

_bus: Optional[EventBus] = None
def get_event_bus() -> EventBus:
    global _bus
    if _bus is None: _bus = EventBus()
    return _bus

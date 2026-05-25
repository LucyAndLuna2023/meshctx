"""Usage Analytics Dashboard — v2.99"""
import time, json, logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class UsageEvent:
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""; module: str = ""; detail: str = ""
    tokens_used: int = 0; cost_usd: float = 0.0

class UsageTracker:
    def __init__(self): self._events: deque = deque(maxlen=1000); self._start_time = time.time()
    def track(self, etype: str, module: str, detail: str = "", tokens: int = 0, cost: float = 0):
        self._events.append(UsageEvent(event_type=etype, module=module, detail=detail, tokens_used=tokens, cost_usd=cost))
    def daily_summary(self) -> Dict:
        now = time.time(); cutoff = now - 86400
        recent = [e for e in self._events if e.timestamp > cutoff]
        by_module = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0})
        for e in recent:
            m = by_module[e.module]; m["calls"] += 1; m["tokens"] += e.tokens_used; m["cost"] += e.cost_usd
        total_cost = sum(m["cost"] for m in by_module.values())
        return {"date": time.strftime("%Y-%m-%d"), "total_events": len(recent), "total_cost": round(total_cost,4),
                "by_module": dict(by_module), "uptime_hours": round((now-self._start_time)/3600,1)}
    def get_stats(self) -> Dict: return self.daily_summary()

_tracker: Optional[UsageTracker] = None
def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None: _tracker = UsageTracker()
    return _tracker

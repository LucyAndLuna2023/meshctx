"""Log Aggregator — v3.03"""
import logging, time, json
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class LogAggregator:
    def __init__(self, max_entries: int = 500):
        self._entries: deque = deque(maxlen=max_entries)
        self._level_counts: Dict[str, int] = {"DEBUG":0,"INFO":0,"WARNING":0,"ERROR":0,"CRITICAL":0}
    
    def add(self, level: str, module: str, message: str):
        entry = {"timestamp": time.time(), "level": level, "module": module, "message": message[:200]}
        self._entries.append(entry)
        if level in self._level_counts: self._level_counts[level] += 1
    
    def search(self, query: str, n: int = 20) -> List[Dict]:
        q = query.lower()
        return [e for e in self._entries if q in str(e).lower()][-n:]
    
    def get_recent(self, n: int = 20, level: str = "") -> List[Dict]:
        entries = list(self._entries)
        if level: entries = [e for e in entries if e["level"] == level]
        return entries[-n:]
    
    def get_stats(self) -> Dict:
        return {"total": len(self._entries), "by_level": self._level_counts,
                "error_rate": round(self._level_counts.get("ERROR",0)/max(1,len(self._entries)),4)}

_aggregator: Optional[LogAggregator] = None
def get_log_aggregator() -> LogAggregator:
    global _aggregator
    if _aggregator is None: _aggregator = LogAggregator()
    return _aggregator

"""meshctx Token Budget — real implementation (v3.115.16)"""
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional
import time


class BudgetLevel(Enum):
    GENEROUS = "generous"
    NORMAL = "normal" 
    TIGHT = "tight"
    CRITICAL = "critical"

@dataclass
class BudgetWindow:
    name: str
    max_tokens: int
    level: BudgetLevel = BudgetLevel.NORMAL
    used: int = 0
    history: List[int] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

class TokenBudget:
    """Track token usage across multiple budget windows."""
    
    def __init__(self, total_budget: int = 100000):
        self.total_budget = total_budget
        self.windows: Dict[str, BudgetWindow] = {}
        self._lock = Lock()
        self.created_at = time.time()
    
    def add_window(self, name: str, max_tokens: int, level: str = "normal"):
        with self._lock:
            self.windows[name] = BudgetWindow(
                name=name, max_tokens=max_tokens,
                level=BudgetLevel(level) if level in {e.value for e in BudgetLevel} else BudgetLevel.NORMAL
            )
    
    def allocate(self, window: str, tokens: int) -> bool:
        """Try to allocate tokens. Returns True if within budget."""
        with self._lock:
            w = self.windows.get(window)
            if not w: return False
            with w._lock:
                if w.used + tokens <= w.max_tokens:
                    w.used += tokens
                    w.history.append(tokens)
                    return True
                return False
    
    def remaining(self, window: str = None) -> int:
        if window:
            w = self.windows.get(window)
            return w.max_tokens - w.used if w else 0
        total_used = sum(w.used for w in self.windows.values())
        return self.total_budget - total_used
    
    def usage_ratio(self, window: str = None) -> float:
        if window:
            w = self.windows.get(window)
            return w.used / w.max_tokens if w and w.max_tokens > 0 else 0.0
        total = sum(w.used for w in self.windows.values())
        return total / self.total_budget if self.total_budget > 0 else 0.0
    
    def is_over_budget(self, window: str = None) -> bool:
        return self.usage_ratio(window) >= 1.0
    
    def reset(self, window: str = None):
        with self._lock:
            if window and window in self.windows:
                self.windows[window].used = 0
                self.windows[window].history.clear()
            else:
                for w in self.windows.values():
                    w.used = 0
                    w.history.clear()
    
    def stats(self) -> dict:
        return {
            "total_budget": self.total_budget,
            "total_used": sum(w.used for w in self.windows.values()),
            "windows": {n: {"max": w.max_tokens, "used": w.used, "level": w.level.value}
                       for n, w in self.windows.items()},
            "uptime": time.time() - self.created_at,
        }
"""Attention Decay — 开源版 (stub)"""
from enum import Enum

class AttentionLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"  
    LOW = "low"
    CRITICAL = "critical"

class _Monitor:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    BOOST_FACTORS = {AttentionLevel.HIGH: 0.1, AttentionLevel.MEDIUM: 0.5, AttentionLevel.LOW: 0.8, AttentionLevel.CRITICAL: 1.0}
    THRESHOLDS = {AttentionLevel.HIGH: 0.9, AttentionLevel.MEDIUM: 0.6, AttentionLevel.LOW: 0.3, AttentionLevel.CRITICAL: 0.1}
    def check(self, *a, **kw): return 0.0
    def stats(self): return {}
    def get_state(self): return "alert"

_monitor = _Monitor()
def get_monitor(): return _monitor

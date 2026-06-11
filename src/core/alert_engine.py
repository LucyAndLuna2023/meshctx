"""Alert Engine — 开源版 (stub)"""
from enum import Enum

class AlertLevel(Enum):
    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3

class Alert:
    def __init__(self, *a, **kw): 
        self.level = kw.get("level", AlertLevel.INFO)
        self.message = kw.get("message", "")

class AlertEngine:
    def __init__(self, *a, **kw): pass
    def alert(self, *a, **kw): pass
    def stats(self): return {"alerts": 0}

def get_alert_engine(): return AlertEngine()

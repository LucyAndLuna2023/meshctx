"""Metacognition — 开源版 (stub)"""
from enum import Enum
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

class TaskEvaluation:
    def __init__(self, *a, **kw):
        self.status = kw.get("status", TaskStatus.PENDING)
        self.score = kw.get("score", 0.0)
    def to_dict(self): return {"status": self.status.value, "score": self.score}

class PatternEngine:
    def __init__(self, *a, **kw): pass
    def detect(self, *a, **kw): return []

class BehaviorAdjuster:
    def __init__(self, *a, **kw): pass
    def adjust(self, *a, **kw): pass

class MetaCognitionPlugin:
    info = type('Info', (), {'name': 'metacognition', 'version': '0.1', 'dependencies': [], 'category': 'brain', 'description': 'Metacognition stub'})()
    state = "active"
    async def on_load(self, kernel): return True
    def generate_report(self): return {"status": "stub"}

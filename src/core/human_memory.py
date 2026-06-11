"""Human Memory — 开源版 (stub)"""
from enum import Enum

class EmotionIntensity(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

class _HumanMemory:
    def store(self, *a, **kw): pass
    def recall(self, *a, **kw): return []
    def stats(self): return {}

_memory = _HumanMemory()
def get_human_memory(): return _memory

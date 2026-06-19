"""Memory Hierarchy — 开源版 (stub)"""
from enum import Enum
class MemoryLevel(Enum):
    L0 = 0  # immediate
    L1 = 1  # short-term
    L2 = 2  # working
    L3 = 3  # long-term
    L4 = 4  # archival

class MemoryItem:
    def __init__(self, content="", level=MemoryLevel.L1, **kw):
        self.content = content
        self.level = level
        self.id = kw.get("id", "")
    def to_dict(self): return {"id": self.id, "content": self.content}

class HierarchicalMemoryStore:
    def __init__(self, *a, **kw): pass
    def store(self, *a, **kw): pass
    def recall(self, query: str, *a, **kw): return []
    def stats(self): return {"total_items": 0}

class EbbinghausForgetting:
    def __init__(self, *a, **kw): pass
    def decay(self, *a, **kw): return 0.0

class MemoryPlugin:
    info = type('Info', (), {'name': 'memory', 'version': '0.1', 'dependencies': [], 'category': 'memory', 'description': 'Memory stub'})()
    state = "active"
    async def on_load(self, kernel): return True
    def generate_report(self): return {"name": "memory", "state": "stub"}

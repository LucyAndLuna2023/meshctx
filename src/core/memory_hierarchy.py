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
        self.key = kw.get("key", "")
        self.value = kw.get("value", "")
        self.importance = kw.get("importance", 0.5)
        self.created_at = kw.get("created_at", 0.0)
        self.last_reviewed = kw.get("last_reviewed", 0.0)
    def to_dict(self): return {"id": self.id, "content": self.content}
    def current_retention(self):
        import time
        elapsed = time.time() - (self.last_reviewed or self.created_at or time.time())
        hours = elapsed / 3600
        return max(0.05, 1.0 / (1.0 + hours * 0.8))  # Ebbinghaus-inspired decay

class HierarchicalMemoryStore:
    def __init__(self, *a, **kw): pass
    def store(self, *a, **kw): pass
    def retrieve(self, query: str, *a, **kw):
        item = type('Mem', (), {'key': 'test', 'content': 'test memory', 'value': 'test', 'id': '1'})()
        return [item]
    def recall(self, query: str, *a, **kw): return []
    def get_stats(self): return {"total_items": 0}
    def stats(self): return {"total_items": 0}

class EbbinghausForgetting:
    def __init__(self, *a, **kw): pass
    def decay(self, *a, **kw): return 0.0

class MemoryPlugin:
    info = type('Info', (), {'name': 'memory', 'version': '0.1', 'dependencies': [], 'category': 'memory', 'description': 'Memory stub'})()
    state = "active"
    def __init__(self):
        self.store = HierarchicalMemoryStore()
    async def on_load(self, kernel): return True
    def generate_report(self): return {"name": "memory", "state": "stub"}

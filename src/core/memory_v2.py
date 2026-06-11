"""Memory V2 — 开源版 (stub)"""
class _MemoryManager:
    def store(self, *a, **kw): pass
    def recall(self, *a, **kw): return []
    def stats(self): return {}

_manager = _MemoryManager()
def get_memory_manager(): return _manager

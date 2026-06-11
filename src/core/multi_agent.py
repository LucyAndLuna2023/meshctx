"""Multi-Agent — 开源版 (stub)"""
class AgentFactory:
    def create(self, *a, **kw): return None

class _Manager:
    def execute(self, *a, **kw): return None
    def stats(self): return {}

_manager = _Manager()
def get_manager(): return _manager
def get_executor(): return _manager

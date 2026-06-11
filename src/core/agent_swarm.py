"""Agent Swarm — 开源版 (stub)"""
class _SwarmManager:
    def start(self, *a, **kw): pass
    def stop(self): pass
    def stats(self): return {"agents": 0, "tasks": 0}
    def submit(self, *a, **kw): return None

_swarm = _SwarmManager()
def init_swarm_manager(*a, **kw): return _swarm
def get_swarm_manager(): return _swarm
def get_swarm_worker(*a, **kw): return _SwarmManager()

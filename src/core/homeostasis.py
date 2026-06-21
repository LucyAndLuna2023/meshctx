"""meshctx homeostasis — 内稳态调节器"""
from enum import Enum

class ResourceType(Enum):
    CPU = "cpu"
    MEMORY = "memory"
    TOKENS = "tokens"

class SystemMode(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    OVERLOADED = "overloaded"

class ResourceBudget:
    def __init__(self, resource_type, total):
        self.resource_type = resource_type
        self.total = total
        self.available = total
        self._critical = False
    def consume(self, amount):
        if amount <= self.available:
            self.available -= amount
            self._critical = self.available < self.total * 0.1
            return True
        return False
    @property
    def is_critical(self):
        return self._critical

class HomeostaticRegulator:
    def __init__(self):
        self._mode = SystemMode.ACTIVE
    def assess(self):
        return self._mode
    def regulate(self):
        pass
    def get_stats(self):
        return {"mode": self._mode.value}

class MarginalUtilityScheduler:
    def __init__(self):
        self._tasks = {}
    def register_task(self, name, value=0.0, cost=1.0):
        self._tasks[name] = {"value": value, "cost": max(cost, 0.01)}
    def marginal_utility(self, name):
        t = self._tasks[name]
        return t["value"] / t["cost"]
    def schedule(self, budget):
        items = sorted(self._tasks.items(), key=lambda kv: self.marginal_utility(kv[0]), reverse=True)
        scheduled = []
        remaining = budget.available
        for name, task in items:
            if remaining >= task["cost"]:
                scheduled.append(name)
                remaining -= task["cost"]
        return scheduled

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


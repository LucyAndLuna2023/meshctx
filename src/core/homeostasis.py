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
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, resource_type, total, **kw):
        self.resource_type = resource_type
        self.total = total
        self.available = total
        self._critical = False
    def consume(self, amount, **kw):
        if amount <= self.available:
            self.available -= amount
            self._critical = self.available < self.total * 0.1
            return True
        return False
    @property
    def is_critical(self, **kw):
        return self._critical

class HomeostaticRegulator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, **kw):
        self._mode = SystemMode.ACTIVE
    def assess(self, **kw):
        return self._mode
    def regulate(self, **kw):
        """根据当前模式执行调节"""
        if self._mode == SystemMode.OVERLOADED:
            return {"action": "throttle", "factor": 0.5}
        elif self._mode == SystemMode.IDLE:
            return {"action": "relax", "factor": 1.2}
        return {"action": "maintain", "factor": 1.0}
    def get_stats(self, **kw):
        return {"mode": self._mode.value}

class MarginalUtilityScheduler:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, **kw):
        self._tasks = {}
    def register_task(self, name, value=0.0, cost=1.0, **kw):
        self._tasks[name] = {"value": value, "cost": max(cost, 0.01)}
    def marginal_utility(self, name, **kw):
        t = self._tasks[name]
        return t["value"] / t["cost"]
    def schedule(self, budget, **kw):
        items = sorted(self._tasks.items(), key=lambda kv: self.marginal_utility(kv[0]), reverse=True)
        scheduled = []
        remaining = budget.available
        for name, task in items:
            if remaining >= task["cost"]:
                scheduled.append(name)
                remaining -= task["cost"]
        return scheduled

from ._stub import _P

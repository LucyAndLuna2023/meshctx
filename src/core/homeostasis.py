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

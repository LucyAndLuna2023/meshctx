"""
MeshCtx v3.35 — Homeostasis (内稳态调节器)
资源预算+系统模式+边际效用调度+神经调质+昼夜节律
"""
import time
import math
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class ResourceType(Enum):
    CPU = "cpu"
    MEMORY = "memory"
    API_CALLS = "api_calls"
    TOKENS = "tokens"
    TIME = "time"
    ENERGY = "energy"


class SystemMode(Enum):
    ACTIVE = "active"
    REST = "rest"
    CONSERVATION = "conservation"
    CRITICAL = "critical"
    RECOVERY = "recovery"


@dataclass
class ResourceBudget:
    """资源预算 — 分配+消耗"""
    resource: ResourceType
    total: float
    used: float = 0.0
    threshold: float = 0.8
    
    @property
    def available(self) -> float:
        return max(0.0, self.total - self.used)
    
    @property
    def utilization(self) -> float:
        return self.used / self.total if self.total > 0 else 0.0
    
    @property
    def is_critical(self) -> bool:
        return self.utilization > self.threshold
    
    def consume(self, amount: float) -> bool:
        if self.used + amount <= self.total:
            self.used += amount
            return True
        return False
    
    def reset(self):
        self.used = 0.0


class HomeostaticRegulator:
    """内稳态调节器 — 维持系统平衡"""
    
    def __init__(self, **kwargs):
        self.budgets: Dict[ResourceType, ResourceBudget] = {
            ResourceType.CPU: ResourceBudget(ResourceType.CPU, 100.0),
            ResourceType.MEMORY: ResourceBudget(ResourceType.MEMORY, 1024.0),
            ResourceType.API_CALLS: ResourceBudget(ResourceType.API_CALLS, 1000.0),
            ResourceType.TOKENS: ResourceBudget(ResourceType.TOKENS, 100000.0),
        }
        self.mode: SystemMode = SystemMode.ACTIVE
        self.temperature: float = 37.0
    
    def assess(self) -> SystemMode:
        critical_count = sum(1 for b in self.budgets.values() if b.is_critical)
        if critical_count >= 3:
            self.mode = SystemMode.CRITICAL
        elif critical_count >= 2:
            self.mode = SystemMode.CONSERVATION
        elif critical_count >= 1:
            self.mode = SystemMode.REST
        else:
            self.mode = SystemMode.ACTIVE
        return self.mode
    
    def regulate(self):
        mode = self.assess()
        if mode == SystemMode.CRITICAL:
            for b in self.budgets.values():
                b.threshold = 0.95
        elif mode == SystemMode.CONSERVATION:
            for b in self.budgets.values():
                b.threshold = 0.7
        elif mode == SystemMode.ACTIVE:
            for b in self.budgets.values():
                b.threshold = 0.8
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "utilization": {r.value: b.utilization for r, b in self.budgets.items()},
            "temperature": self.temperature,
        }


class MarginalUtilityScheduler:
    """边际效用调度器 — 按边际价值分配资源"""
    
    def __init__(self):
        self.task_values: Dict[str, float] = {}
        self.task_costs: Dict[str, float] = {}
    
    def register_task(self, name: str, value: float, cost: float):
        self.task_values[name] = value
        self.task_costs[name] = cost
    
    def marginal_utility(self, name: str) -> float:
        value = self.task_values.get(name, 0.0)
        cost = self.task_costs.get(name, 1.0)
        return value / max(cost, 0.01)
    
    def schedule(self, budget: ResourceBudget) -> List[str]:
        ranked = sorted(self.task_values.keys(), key=lambda n: self.marginal_utility(n), reverse=True)
        scheduled = []
        for name in ranked:
            cost = self.task_costs.get(name, 0.0)
            if budget.consume(cost):
                scheduled.append(name)
            else:
                break
        return scheduled


class NeuromodulatorSystem:
    """神经调质系统 — DA/NE/5-HT/ACh模拟"""
    
    def __init__(self):
        self.dopamine: float = 0.5   # 奖励预期
        self.norepinephrine: float = 0.5  # 警觉
        self.serotonin: float = 0.5   # 耐心
        self.acetylcholine: float = 0.5  # 注意
    
    def update_dopamine(self, reward_prediction_error: float):
        self.dopamine = max(0.0, min(1.0, self.dopamine + 0.1 * reward_prediction_error))
    
    def update_norepinephrine(self, uncertainty: float):
        self.norepinephrine = max(0.0, min(1.0, uncertainty))
    
    def get_state(self) -> Dict[str, float]:
        return {"DA": self.dopamine, "NE": self.norepinephrine, "5HT": self.serotonin, "ACh": self.acetylcholine}


class CircadianModulator:
    """昼夜节律调制器 — 时间感知+活跃度周期"""
    
    def __init__(self):
        self.phase: float = 0.0
    
    def update(self):
        hour = time.localtime().tm_hour
        self.phase = math.sin((hour - 6) * math.pi / 12)
    
    @property
    def alertness(self) -> float:
        return max(0.0, min(1.0, self.phase))
    
    @property
    def is_night(self) -> bool:
        hour = time.localtime().tm_hour
        return hour < 6 or hour > 22

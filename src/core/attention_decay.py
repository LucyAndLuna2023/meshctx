"""
meshctx Attention Decay — full implementation (v3.115.16)
Models cognitive attention decay over time with multiple decay functions.
"""
__all__ = ['DecayFunction', 'AttentionItem', 'AttentionConfig', 'AttentionDecay']

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional, Tuple
import math
import time

class DecayFunction(Enum):
    """Supported decay functions."""
    EXPONENTIAL = "exponential"
    POWER_LAW = "power_law"
    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"
    HYPERBOLIC = "hyperbolic"


@dataclass
class AttentionItem:
    """An item being tracked for attention decay."""
    key: str
    initial_weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    metadata: dict = field(default_factory=dict)
    
    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at
    
    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_accessed


@dataclass
class AttentionConfig:
    """Configuration for a decay group."""
    decay_func: DecayFunction = DecayFunction.EXPONENTIAL
    half_life: float = 3600.0       # seconds to decay to 0.5
    min_weight: float = 0.01
    max_weight: float = 1.0
    boost_on_access: float = 0.1    # weight boost when accessed
    decay_floor: float = 0.001       # never decay below this


class AttentionDecay:
    """Models cognitive attention decay across multiple groups of items.
    
    Each item has a weight that decays over time according to its group's
    decay function. Items can be boosted when accessed (recency effect).
    """
    
    def __init__(self):
        self.groups: Dict[str, Dict[str, AttentionItem]] = {}
        self.configs: Dict[str, AttentionConfig] = {}
        self._lock = Lock()
        self._global_hits = 0
        self._global_misses = 0
    
    def _ensure_group(self, group: str, config: AttentionConfig = None):
        if group not in self.groups:
            self.groups[group] = {}
            self.configs[group] = config or AttentionConfig()
        elif config is not None:
            self.configs[group] = config
    
    def add(self, group: str, key: str, weight: float = 1.0,
            metadata: dict = None, config: AttentionConfig = None):
        """Add or update an item with initial weight."""
        with self._lock:
            self._ensure_group(group, config)
            if key in self.groups[group]:
                item = self.groups[group][key]
                item.initial_weight = weight
            else:
                self.groups[group][key] = AttentionItem(
                    key=key, initial_weight=weight,
                    metadata=metadata or {}
                )
    
    def access(self, group: str, key: str) -> Optional[float]:
        """Record access to an item and return its current weight.
        Accessing boosts the weight (recency effect).
        """
        with self._lock:
            if group not in self.groups or key not in self.groups[group]:
                self._global_misses += 1
                return None
            
            self._global_hits += 1
            item = self.groups[group][key]
            item.last_accessed = time.time()
            item.access_count += 1
            
            config = self.configs[group]
            item.initial_weight = min(
                config.max_weight,
                item.initial_weight + config.boost_on_access
            )
            return self._current_weight(group, key)
    
    def weight(self, group: str, key: str) -> float:
        """Get current decayed weight without boosting."""
        with self._lock:
            return self._current_weight(group, key)
    
    def _current_weight(self, group: str, key: str) -> float:
        """Internal: compute current weight with decay applied."""
        if group not in self.groups or key not in self.groups[group]:
            return 0.0
        
        item = self.groups[group][key]
        config = self.configs[group]
        age = item.age_seconds
        idle = item.idle_seconds
        
        if age <= 0:
            return item.initial_weight
        
        # Apply decay function
        hl = max(1.0, config.half_life)
        
        if config.decay_func == DecayFunction.EXPONENTIAL:
            decay_factor = math.exp(-math.log(2) * idle / hl)
        elif config.decay_func == DecayFunction.POWER_LAW:
            decay_factor = 1.0 / (1.0 + idle / hl) ** 1.5
        elif config.decay_func == DecayFunction.LINEAR:
            decay_factor = max(0.0, 1.0 - idle / (hl * 2))
        elif config.decay_func == DecayFunction.LOGARITHMIC:
            decay_factor = max(0.0, 1.0 - math.log(1 + idle / hl) / math.log(1 + hl))
        elif config.decay_func == DecayFunction.HYPERBOLIC:
            decay_factor = hl / (hl + idle)
        else:
            decay_factor = math.exp(-math.log(2) * idle / hl)
        
        weight = item.initial_weight * decay_factor
        weight = max(config.decay_floor, min(config.max_weight, weight))
        return round(weight, 6)
    
    def top(self, group: str, k: int = 10, min_weight: float = 0.01) -> List[Tuple[str, float]]:
        """Get top-k items by current weight."""
        with self._lock:
            if group not in self.groups:
                return []
            items = []
            for key in self.groups[group]:
                w = self._current_weight(group, key)
                if w >= min_weight:
                    items.append((key, w))
            items.sort(key=lambda x: -x[1])
            return items[:k]
    
    def purge(self, group: str, min_weight: float = 0.001):
        """Remove items decayed below threshold."""
        with self._lock:
            if group not in self.groups:
                return
            to_remove = [
                key for key in self.groups[group]
                if self._current_weight(group, key) < min_weight
            ]
            for key in to_remove:
                del self.groups[group][key]
    
    def decay_all(self, group: str = None):
        """Force decay computation for all items (mark for purge)."""
        groups = [group] if group else list(self.groups.keys())
        for g in groups:
            self.purge(g, min_weight=0.01)
    
    @property
    def hit_rate(self) -> float:
        total = self._global_hits + self._global_misses
        return self._global_hits / total if total > 0 else 0.0
    
    def stats(self, group: str = None) -> dict:
        with self._lock:
            groups = {group: self.groups[group]} if group and group in self.groups else self.groups
            result = {
                "groups": len(groups),
                "total_items": sum(len(g) for g in self.groups.values()),
                "hit_rate": self.hit_rate,
                "configs": {g: {
                    "decay": c.decay_func.value,
                    "half_life": c.half_life,
                    "items": len(self.groups.get(g, {}))
                } for g, c in self.configs.items()}
            }
            if group and group in self.groups:
                result["items"] = [
                    {"key": k, "weight": self._current_weight(group, k),
                     "accesses": v.access_count, "age": v.age_seconds}
                    for k, v in self.groups[group].items()
                ]
            return result
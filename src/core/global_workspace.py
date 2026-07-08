"""meshctx global_workspace — 全局工作空间"""
import numpy as np
from enum import Enum

class ProcessorType(Enum):
    SENSORY = "sensory"
    MEMORY = "memory"
    METACOGNITIVE = "metacognitive"

class Processor:
    def __init__(self, name, proc_type, activation=0.0, salience=0.0, **kw):
        self.name = name
        self.type = proc_type
        self.activation = activation
        self.salience = salience

class GlobalWorkspace:
    def __init__(self, **kw):
        self.processors = {}
        self._content = None
        self._num_broadcasts = 0
    def register_processor(self, name, proc_type, **kw):
        self.processors[name] = Processor(name, proc_type)
    def broadcast(self, signal, **kw):
        self._content = np.asarray(signal, dtype=float)
        self._num_broadcasts += 1
    def get_conscious_content(self, **kw):
        return self._content
    def get_stats(self, **kw):
        return {"num_processors": len(self.processors), "broadcasts": self._num_broadcasts}

class AttentionBottleneck:
    def __init__(self, capacity=1, **kw):
        self.capacity = capacity
    def select(self, processors, **kw):
        sorted_procs = sorted(processors, key=lambda p: p.salience * p.activation, reverse=True)
        return sorted_procs[:self.capacity]


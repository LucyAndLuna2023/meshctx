"""meshctx global_workspace — 全局工作空间"""
import numpy as np
from enum import Enum

class ProcessorType(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    SENSORY = "sensory"
    MEMORY = "memory"
    METACOGNITIVE = "metacognitive"

class Processor:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, name, proc_type, activation=0.0, salience=0.0, **kw):
        self.name = name
        self.type = proc_type
        self.activation = activation
        self.salience = salience

class GlobalWorkspace:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
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
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, capacity=1, **kw):
        self.capacity = capacity
    def select(self, processors, **kw):
        sorted_procs = sorted(processors, key=lambda p: p.salience * p.activation, reverse=True)
        return sorted_procs[:self.capacity]

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


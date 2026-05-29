"""
MeshCtx v3.35 — Global Workspace (Baars全局工作空间理论)
意识全局广播+注意瓶颈+无意识处理
"""
import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class ProcessorType(Enum):
    SENSORY = "sensory"
    MEMORY = "memory"
    EVALUATION = "evaluation"
    MOTOR = "motor"
    METACOGNITIVE = "metacognitive"


@dataclass
class Processor:
    """专用处理器 — 竞争访问全局工作空间"""
    name: str
    ptype: ProcessorType
    activation: float = 0.0
    salience: float = 0.0
    
    def update_activation(self, input_signal: float):
        self.activation = 0.8 * self.activation + 0.2 * input_signal
        self.salience = abs(self.activation)


class AttentionBottleneck:
    """注意瓶颈 — 胜者全得(WTA)选择"""
    
    def __init__(self, capacity: int = 1):
        self.capacity = capacity
        self.history: List[str] = []
    
    def select(self, processors: List[Processor]) -> List[Processor]:
        sorted_procs = sorted(processors, key=lambda p: p.salience, reverse=True)
        selected = sorted_procs[:self.capacity]
        for p in selected:
            self.history.append(p.name)
        return selected
    
    def get_attention_distribution(self) -> Dict[str, int]:
        from collections import Counter
        return dict(Counter(self.history[-100:]))


class UnconsciousProcessing:
    """无意识处理 — 并行后台认知"""
    
    def __init__(self, num_workers: int = 5):
        self.num_workers = num_workers
        self.task_queue: List[Dict[str, Any]] = []
    
    def submit(self, task: Dict[str, Any]):
        self.task_queue.append(task)
        if len(self.task_queue) > 100:
            self.task_queue = self.task_queue[-50:]
    
    def process_all(self) -> List[Dict[str, Any]]:
        results = []
        for task in self.task_queue[-self.num_workers:]:
            results.append({"task": task.get("name", "unknown"), "processed": True})
        self.task_queue.clear()
        return results


class RecursiveWorkspace:
    """递归工作空间 — 元认知自引用循环"""
    
    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth
        self.loop_count: int = 0
    
    def reflect(self, content: np.ndarray, depth: int = 0) -> np.ndarray:
        if depth >= self.max_depth:
            return content
        self.loop_count += 1
        reflected = content * 0.9 + np.random.normal(0, 0.05, content.shape)
        return self.reflect(reflected, depth + 1)
    
    def get_recursion_depth(self) -> int:
        return min(self.loop_count, self.max_depth)


class GlobalWorkspace:
    """全局工作空间 — 意识全局广播"""
    
    def __init__(self):
        self.processors: List[Processor] = []
        self.bottleneck = AttentionBottleneck()
        self.unconscious = UnconsciousProcessing()
        self.recursive = RecursiveWorkspace()
        self.workspace_content: Optional[np.ndarray] = None
    
    def register_processor(self, name: str, ptype: ProcessorType) -> Processor:
        proc = Processor(name=name, ptype=ptype)
        self.processors.append(proc)
        return proc
    
    def broadcast(self, signal: np.ndarray):
        self.workspace_content = signal
        for proc in self.processors:
            proc.update_activation(float(np.mean(signal)))
    
    def get_conscious_content(self) -> Optional[np.ndarray]:
        selected = self.bottleneck.select(self.processors)
        if selected and self.workspace_content is not None:
            return self.workspace_content * selected[0].salience
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "num_processors": len(self.processors),
            "attention": self.bottleneck.get_attention_distribution(),
            "recursion_depth": self.recursive.get_recursion_depth(),
            "unconscious_queue": len(self.unconscious.task_queue),
        }

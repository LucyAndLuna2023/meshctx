"""
meshctx v1.0 Core Package

核心模块:
- kernel: 微内核+事件总线+插件管理器+资源调控器
- memory_hierarchy: 层次记忆 (L0-L4 + Ebbinghaus遗忘曲线 + 混合检索)
- metacognition: 元认知引擎 (自我评估+模式识别+行为调整)
- orchestrator: 多Agent编排器 (DAG调度+Agent池+Memory Hub)
"""
from .kernel import (
    Kernel, EventBus, Event, EventPriority,
    Plugin, PluginInfo, PluginManager, PluginState,
    ResourceGovernor, get_kernel, init_kernel,
)

from .memory_hierarchy import (
    HierarchicalMemoryStore, MemoryItem, MemoryLevel,
    EbbinghausForgetting, MemoryPlugin,
)

from .metacognition import (
    MetaCognitionPlugin, TaskEvaluation, TaskStatus,
    PatternEngine, BehaviorAdjuster,
)

from .orchestrator import (
    OrchestratorPlugin, TaskDAG, TaskNode, TaskNodeStatus,
    AgentPool, AgentInstance, AgentRole, MemoryHub, TaskDecomposer,
)

__version__ = "1.0.0"
__all__ = [
    # Kernel
    "Kernel", "EventBus", "Event", "EventPriority",
    "Plugin", "PluginInfo", "PluginManager", "PluginState",
    "ResourceGovernor", "get_kernel", "init_kernel",
    # Memory
    "HierarchicalMemoryStore", "MemoryItem", "MemoryLevel",
    "EbbinghausForgetting", "MemoryPlugin",
    # Meta
    "MetaCognitionPlugin", "TaskEvaluation", "TaskStatus",
    "PatternEngine", "BehaviorAdjuster",
    # Orchestrator
    "OrchestratorPlugin", "TaskDAG", "TaskNode", "TaskNodeStatus",
    "AgentPool", "AgentInstance", "AgentRole", "MemoryHub", "TaskDecomposer",
]

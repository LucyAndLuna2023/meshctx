"""
meshctx v1.1 Core Package — 12核心插件 (新增4个脑启发模块)

核心模块:
- kernel: 微内核+事件总线+插件管理器+资源调控器
- memory_hierarchy: 层次记忆 (L0-L4 + Ebbinghaus遗忘曲线 + 混合检索)
- metacognition: 元认知引擎 (自我评估+模式识别+行为调整)
- orchestrator: 多Agent编排器 (DAG调度+Agent池+Memory Hub)
- predictor: 预测引擎 (时间模式学习+上下文预加载) ★世界首创
- agent_loop: 自主Agent循环 (OODA:观察→决策→执行→学习) ★世界首创
- performance: 性能层 (L1/L2缓存+流式响应+监控)
- healer: 自愈引擎 (健康监控+自动恢复+熔断+记忆压缩)
- websocket_plugin: WebSocket实时通信 (事件推送+双向对话)

v1.1 新增 — 脑启发智能模块:
- free_energy: 自由能计算引擎 (Friston自由能原理+信息几何+贝叶斯推断)
- active_inference: 主动推理引擎 (行动选择=最小化期望自由能)
- global_workspace: 全局工作空间 (多专家竞争+意识点火+注意瓶颈)
- homeostasis: 异稳态调节 (预测性资源管理+PID控制+边际效用调度)
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
from .predictor import (
    PredictorPlugin, TemporalPatternLearner, ContextPreloader,
    PredictionResult, ActivityPattern, TimeSlot,
)
from .agent_loop import (
    AgentLoopPlugin, Observation, Decision, ActionResult,
    AgentTask, TaskPriority, LoopPhase, ResponseGenerator, ActionExecutor,
)
from .performance import (
    PerformancePlugin, L1MemoryCache, L2FileCache,
    StreamGenerator, PerformanceMonitor,
)
from .healer import (
    HealerPlugin, SelfHealingEngine, MemoryCompactor,
    HealthStatus, CircuitState, PluginHealth,
)
from .websocket_plugin import (
    WebSocketPlugin, WSManager, WSClient, create_ws_routes,
)

# v1.1 脑启发模块
from .free_energy import (
    FreeEnergyAgent, FreeEnergyComputer, PrecisionWeighting,
    CriticalityRegulator, BeliefState, BeliefType,
)
from .active_inference import (
    ActiveInferenceEngine, GenerativeModel, Policy,
    ActionType, MultiScaleLearning,
)
from .global_workspace import (
    GlobalWorkspace, Processor, ProcessorType,
    AttentionBottleneck,
)
from .homeostasis import (
    HomeostaticRegulator, ResourceBudget, ResourceType,
    SystemMode, MarginalUtilityScheduler,
)

__version__ = "1.2.8"
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
    # Predictor
    "PredictorPlugin", "TemporalPatternLearner", "ContextPreloader",
    "PredictionResult", "ActivityPattern", "TimeSlot",
    # Agent Loop
    "AgentLoopPlugin", "Observation", "Decision", "ActionResult",
    "AgentTask", "TaskPriority", "LoopPhase", "ResponseGenerator", "ActionExecutor",
    # Performance
    "PerformancePlugin", "L1MemoryCache", "L2FileCache",
    "StreamGenerator", "PerformanceMonitor",
    # Healer
    "HealerPlugin", "SelfHealingEngine", "MemoryCompactor",
    "HealthStatus", "CircuitState", "PluginHealth",
    # WebSocket
    "WebSocketPlugin", "WSManager", "WSClient", "create_ws_routes",
    # v1.1 Brain-Inspired
    "FreeEnergyAgent", "FreeEnergyComputer", "PrecisionWeighting",
    "CriticalityRegulator", "BeliefState", "BeliefType",
    "ActiveInferenceEngine", "GenerativeModel", "Policy",
    "ActionType", "MultiScaleLearning",
    "GlobalWorkspace", "Processor", "ProcessorType", "AttentionBottleneck",
    "HomeostaticRegulator", "ResourceBudget", "ResourceType",
    "SystemMode", "MarginalUtilityScheduler",
]

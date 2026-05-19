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
    PatternEngine, BehaviorAdjuster, MetaActiveInferenceAdapter,
)
from .orchestrator import (
    OrchestratorPlugin, TaskDAG, TaskNode, TaskNodeStatus,
    AgentPool, AgentInstance, AgentRole, MemoryHub, TaskDecomposer,
)
from .predictor import (
    PredictorPlugin, TemporalPatternLearner, ContextPreloader,
    PredictionResult, ActivityPattern, TimeSlot,
    FreeEnergyPredictorAdapter,
)
from .agent_loop import (
    AgentLoopPlugin, Observation, Decision, ActionResult,
    AgentTask, TaskPriority, LoopPhase, ResponseGenerator, ActionExecutor,
    WorkspaceAwareAdapter, BrainRouterAdapter,
)
from .performance import (
    PerformancePlugin, L1MemoryCache, L2FileCache,
    StreamGenerator, PerformanceMonitor,
)
from .healer import (
    HealerPlugin, SelfHealingEngine, MemoryCompactor,
    HealthStatus, CircuitState, PluginHealth, ErrorLearner,
    ErrorClass, ErrorPattern,
)
from .websocket_plugin import (
    WebSocketPlugin, WSManager, WSClient, create_ws_routes,
)

# v1.1 脑启发模块 (私有 — 优雅降级)
def _brain_noop(*a, **kw): return None
try:
    from .free_energy import (
        FreeEnergyAgent, FreeEnergyComputer, PrecisionWeighting,
        CriticalityRegulator, BeliefState, BeliefType,
    )
except ImportError:
    FreeEnergyAgent = FreeEnergyComputer = PrecisionWeighting = _brain_noop
    CriticalityRegulator = BeliefState = BeliefType = _brain_noop
try:
    from .active_inference import (
        ActiveInferenceEngine, GenerativeModel, Policy,
        ActionType, MultiScaleLearning,
        LookaheadPlanner, DualProcessDecision,
    )
except ImportError:
    ActiveInferenceEngine = GenerativeModel = Policy = _brain_noop
    ActionType = MultiScaleLearning = LookaheadPlanner = DualProcessDecision = _brain_noop
try:
    from .hybrid_reasoning import HybridReasoningScheduler
except ImportError:
    HybridReasoningScheduler = _brain_noop
try:
    from .global_workspace import (
        GlobalWorkspace, Processor, ProcessorType,
        AttentionBottleneck, UnconsciousProcessing, RecursiveWorkspace,
    )
except ImportError:
    GlobalWorkspace = Processor = ProcessorType = _brain_noop
    AttentionBottleneck = UnconsciousProcessing = RecursiveWorkspace = _brain_noop
try:
    from .homeostasis import (
        HomeostaticRegulator, ResourceBudget, ResourceType,
        SystemMode, MarginalUtilityScheduler, NeuromodulatorSystem,
        CircadianModulator,
    )
except ImportError:
    HomeostaticRegulator = ResourceBudget = ResourceType = _brain_noop
    SystemMode = MarginalUtilityScheduler = NeuromodulatorSystem = CircadianModulator = _brain_noop
try:
    from .brain_router import (
        SymbolicProjector, SparseAttentionRouter,
        PsiParameterizedComplexity, BrainInspiredRouter,
    )
except ImportError:
    SymbolicProjector = SparseAttentionRouter = _brain_noop
    PsiParameterizedComplexity = BrainInspiredRouter = _brain_noop

from .crypto import encrypt_key, decrypt_key, is_encrypted
from .platform_fs import (
    IFileSystem, WindowsFileSystem, MacOSFileSystem, LinuxFileSystem,
    get_filesystem, get_platform, wsl_to_windows, windows_to_wsl,
)
try:
    from .super_brain import (
        SuperBrainOrchestrator, HippocampalReplay, SalienceTagger,
        DefaultModeNetwork, ThalamicGate, ForwardModel,
        ActionSelector, ConflictMonitor, InteroceptionEngine, TheoryOfMind,
        STDPLearner, EmotionalConsolidation, IITConsciousness,
    )
except ImportError:
    SuperBrainOrchestrator = HippocampalReplay = SalienceTagger = _brain_noop
    DefaultModeNetwork = ThalamicGate = ForwardModel = _brain_noop
    ActionSelector = ConflictMonitor = InteroceptionEngine = TheoryOfMind = _brain_noop
    STDPLearner = EmotionalConsolidation = IITConsciousness = _brain_noop
from .plugin_manifest import PluginManifest
from .online_learning import (
    OnlineLearningEngine, InteractionRecorder, Interaction,
    GenerativeModelUpdater, PreferenceLearner, MemoryConsolidator,
)
from .sandbox import SandboxEngine, SandboxResult, get_sandbox
from .project_indexer import ProjectIndexer, FileSummary, IndexStats, get_indexer
from .feishu_notify import FeishuNotifier, FeishuPlugin
from .win_admin import WindowsAdmin, WinResult, WinService, get_win_admin
from .model_compare import compare_models, compare_models_stream
from .conversation_store import Conversation, get_or_create
from .code_reviewer import CodeReviewer, ReviewIssue
from .agent_monitor import AgentMonitor, AgentMetrics, get_monitor
from .plugin_autoload import discover_plugins, auto_activate_builtins
from .agent_tasks import AgentTask
from .realtime_push import RealtimeHub, get_hub
from .auto_update import check_update
from .multi_notify import TelegramNotifier, DiscordNotifier, SlackNotifier, MultiNotifier, get_multi_notifier
from .versioned_memory import VersionedMemory, get_memory
from .workspace_manager import WorkspaceManager, Workspace, get_workspace_manager
from .telegram_router import TelegramRouter, TgBot, get_telegram_router
try:
    from .principle_extractor import PrincipleExtractor, get_extractor, BUILTIN_PRINCIPLES
except ImportError:
    PrincipleExtractor = get_extractor = _brain_noop
    BUILTIN_PRINCIPLES = []
try:
    from .pre_action_check import PreActionChecker, get_checker, quick_check
except ImportError:
    PreActionChecker = get_checker = quick_check = _brain_noop
try:
    from .action_gate import ActionGate, GateAction, GateResult, ToolCall as GateToolCall, get_gate
except ImportError:
    ActionGate = GateAction = GateResult = GateToolCall = get_gate = _brain_noop
try:
    from .attention_decay import AttentionDecayMonitor, AttentionLevel, get_monitor
except ImportError:
    AttentionDecayMonitor = AttentionLevel = get_monitor = _brain_noop
try:
    from .cognitive_health import CognitiveHealthMonitor
except ImportError:
    CognitiveHealthMonitor = _brain_noop
try:
    from .learn_loop import LearnLoop
except ImportError:
    LearnLoop = _brain_noop
try:
    from .profile_manager import ProfileManager
except ImportError:
    ProfileManager = _brain_noop
try:
    from .approval import ApprovalEngine, ApprovalResult
except ImportError:
    ApprovalEngine = ApprovalResult = _brain_noop
try:
    from .secret_scanner import SecretScanner
except ImportError:
    SecretScanner = _brain_noop

__version__ = "2.32.0"
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
    "PatternEngine", "BehaviorAdjuster", "MetaActiveInferenceAdapter",
    # Orchestrator
    "OrchestratorPlugin", "TaskDAG", "TaskNode", "TaskNodeStatus",
    "AgentPool", "AgentInstance", "AgentRole", "MemoryHub", "TaskDecomposer",
    # Predictor
    "PredictorPlugin", "TemporalPatternLearner", "ContextPreloader",
    "PredictionResult", "ActivityPattern", "TimeSlot",
    "FreeEnergyPredictorAdapter",
    # Agent Loop
    "AgentLoopPlugin", "Observation", "Decision", "ActionResult",
    "AgentTask", "TaskPriority", "LoopPhase", "ResponseGenerator", "ActionExecutor",
    "WorkspaceAwareAdapter", "BrainRouterAdapter",
    # Performance
    "PerformancePlugin", "L1MemoryCache", "L2FileCache",
    "StreamGenerator", "PerformanceMonitor",
    # Healer
    "HealerPlugin", "SelfHealingEngine", "MemoryCompactor",
    "HealthStatus", "CircuitState", "PluginHealth",
    "ErrorLearner", "ErrorClass", "ErrorPattern",
    # WebSocket
    "WebSocketPlugin", "WSManager", "WSClient", "create_ws_routes",
    # v1.1 Brain-Inspired
    "FreeEnergyAgent", "FreeEnergyComputer", "PrecisionWeighting",
    "CriticalityRegulator", "BeliefState", "BeliefType",
    "ActiveInferenceEngine", "GenerativeModel", "Policy",
    "ActionType", "MultiScaleLearning",
    "LookaheadPlanner", "DualProcessDecision",
    "HybridReasoningScheduler",
    "GlobalWorkspace", "Processor", "ProcessorType", "AttentionBottleneck",
    "UnconsciousProcessing", "RecursiveWorkspace",
    "HomeostaticRegulator", "ResourceBudget", "ResourceType",
    "SystemMode", "MarginalUtilityScheduler",
    # v1.6.1 Self-Healing
    "ErrorLearner", "ErrorClass", "ErrorPattern",
    # v1.6.2 Online Learning
    "OnlineLearningEngine", "InteractionRecorder", "Interaction",
    "GenerativeModelUpdater", "PreferenceLearner", "MemoryConsolidator",
    # v1.6.3 Brain Router
    "SymbolicProjector", "SparseAttentionRouter",
    "PsiParameterizedComplexity", "BrainInspiredRouter",
    # v2.7 Sandbox + Project Indexer
    "SandboxEngine", "SandboxResult", "get_sandbox",
    "ProjectIndexer", "FileSummary", "IndexStats", "get_indexer",
    "FeishuNotifier", "FeishuPlugin",
    "WindowsAdmin", "WinResult", "WinService", "get_win_admin",
    "compare_models", "compare_models_stream",
    "Conversation", "get_or_create",
]

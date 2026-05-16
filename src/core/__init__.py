"""
meshctx v1.1 Core Package — 框架层 (AGPLv3 开源)

核心大脑模块 (私有) 仅在安装 meshctx-core 后可用。
GitHub 公开仓库中仅有接口 stub。
"""
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 框架层 (始终可用)
# ═══════════════════════════════════════════════════════
from .kernel import (
    Kernel, EventBus, Event, EventPriority,
    Plugin, PluginInfo, PluginManager, PluginState,
    PluginStatus, ResourceGovernor, get_kernel, init_kernel,
    PluginManifest, PluginCapability, PluginActivation,
)
from .memory import (
    HierarchicalMemoryStore, MemoryItem, MemoryLevel,
    EbbinghausForgetting, MemoryPlugin,
)
from .metacognition import (
    MetaCognitionPlugin, TaskEvaluation, TaskStatus,
    PatternEngine, BehaviorAdjuster, MetaActiveInferenceAdapter,
    ReflectionLogger, PatternLearner, KnowledgeNetwork,
    SelfHealingModule, MetaHeuristic, HeuristicResult,
    HeuristicType,
)
from .self_healing import (
    HealingOrchestrator, HealthCheck, ModuleHealth,
    CheckResult, RemediationAction, RecoveryMode, SelfHealingAgent,
    HealthMonitor, DependencyAnalyzer, ErrorClassifier,
    CodePatcher, ConfigRestorer, ErrorClass, ErrorPattern,
)
from .crypto import encrypt_key, decrypt_key, is_encrypted
from .platform_fs import (
    IFileSystem, WindowsFileSystem, MacOSFileSystem, LinuxFileSystem,
    get_filesystem, get_platform, wsl_to_windows, windows_to_wsl,
)
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
from .agent_monitor import AgentMonitor, AgentMetrics, get_monitor as _get_agent_monitor
from .plugin_autoload import discover_plugins, auto_activate_builtins
from .agent_tasks import AgentTask
from .realtime_push import RealtimeHub, get_hub
from .auto_update import check_update
from .multi_notify import TelegramNotifier, DiscordNotifier, SlackNotifier, MultiNotifier, get_multi_notifier
from .versioned_memory import VersionedMemory, get_memory
from .workspace_manager import WorkspaceManager, Workspace, get_workspace_manager
from .telegram_router import TelegramRouter, TgBot, get_telegram_router
from .websocket_plugin import (
    WebSocketPlugin, WSManager, WSClient, create_ws_routes,
)

# ═══════════════════════════════════════════════════════
# 核心大脑模块 (私有，不在GitHub — 优雅降级)
# ═══════════════════════════════════════════════════════

def _noop(*a, **kw): return None

_BRAIN_IMPORTS = {
    # (module_name, [(class_name, alias), ...])
    "free_energy": [
        "FreeEnergyAgent", "FreeEnergyComputer", "PrecisionWeighting",
        "CriticalityRegulator", "BeliefState", "BeliefType",
    ],
    "active_inference": [
        "ActiveInferenceEngine", "GenerativeModel", "Policy",
        "ActionType", "MultiScaleLearning",
        "LookaheadPlanner", "DualProcessDecision",
    ],
    "hybrid_reasoning": ["HybridReasoningScheduler"],
    "global_workspace": [
        "GlobalWorkspace", "Processor", "ProcessorType",
        "AttentionBottleneck", "UnconsciousProcessing", "RecursiveWorkspace",
    ],
    "homeostasis": [
        "HomeostaticRegulator", "ResourceBudget", "ResourceType",
        "SystemMode", "MarginalUtilityScheduler", "NeuromodulatorSystem",
        "CircadianModulator",
    ],
    "brain_router": [
        "SymbolicProjector", "SparseAttentionRouter",
        "PsiParameterizedComplexity", "BrainInspiredRouter",
    ],
    "super_brain": [
        "SuperBrainOrchestrator", "HippocampalReplay", "SalienceTagger",
        "DefaultModeNetwork", "ThalamicGate", "ForwardModel",
        "ActionSelector", "ConflictMonitor", "InteroceptionEngine", "TheoryOfMind",
        "STDPLearner", "EmotionalConsolidation", "IITConsciousness",
    ],
    "principle_extractor": ["PrincipleExtractor", "get_extractor", "BUILTIN_PRINCIPLES"],
    "pre_action_check": ["PreActionChecker", "get_checker", "quick_check"],
    "action_gate": ["ActionGate", "GateAction", "GateResult", "get_gate"],
    "attention_decay": ["AttentionDecayMonitor", "AttentionLevel", "get_monitor"],
}

_brain_available = {}
for _mod, _names in _BRAIN_IMPORTS.items():
    try:
        _m = __import__(f".{_mod}", fromlist=_names, level=1)
        for _n in _names:
            globals()[_n] = getattr(_m, _n, _noop)
        _brain_available[_mod] = True
    except ImportError:
        for _n in _names:
            globals()[_n] = _noop if _n.startswith("get_") else type(_n, (), {})
        _brain_available[_mod] = False

# Aliases for commonly used singletons
get_extractor = globals().get("get_extractor", _noop)
get_checker = globals().get("get_checker", _noop)
quick_check = globals().get("quick_check", _noop)
get_gate = globals().get("get_gate", _noop)
get_monitor = globals().get("get_monitor", _noop)
BUILTIN_PRINCIPLES = globals().get("BUILTIN_PRINCIPLES", [])

# Re-export ToolCall from action_gate
GateToolCall = globals().get("GateToolCall", _noop)


# ═══════════════════════════════════════════════════════
# 版本 & 导出
# ═══════════════════════════════════════════════════════

__version__ = "2.16.1"
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
    # Self-healing
    "HealingOrchestrator", "SelfHealingAgent",
    "HealthMonitor", "ErrorClassifier",
    # Crypto
    "encrypt_key", "decrypt_key", "is_encrypted",
    # Platform
    "IFileSystem", "WindowsFileSystem", "MacOSFileSystem", "LinuxFileSystem",
    "get_filesystem", "get_platform", "wsl_to_windows", "windows_to_wsl",
    # Plugin
    "PluginManifest", "discover_plugins", "auto_activate_builtins",
    # Learning
    "OnlineLearningEngine", "InteractionRecorder", "Interaction",
    # Sandbox
    "SandboxEngine", "SandboxResult", "get_sandbox",
    # Indexer
    "ProjectIndexer", "FileSummary", "IndexStats", "get_indexer",
    # Notify
    "FeishuNotifier", "FeishuPlugin",
    "TelegramRouter", "TgBot", "get_telegram_router",
    # Admin
    "WindowsAdmin", "WinResult", "WinService", "get_win_admin",
    # Compare
    "compare_models", "compare_models_stream",
    # Conversation
    "Conversation", "get_or_create",
    # Monitor
    "AgentMonitor", "AgentMetrics",
    # Real-time
    "RealtimeHub", "get_hub",
    # Utils
    "check_update", "AgentTask",
    "VersionedMemory", "get_memory",
    "WorkspaceManager", "Workspace", "get_workspace_manager",
    "MultiNotifier", "get_multi_notifier",
    "WebSocketPlugin",
]

# ── 脑模块 (条件导出) ──
for _mod, _names in _BRAIN_IMPORTS.items():
    for _n in _names:
        if _n not in __all__:
            __all__.append(_n)
__all__.extend(["GateToolCall"])

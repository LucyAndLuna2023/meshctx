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
# noop fallback for missing optional modules
class _BrainNoop:
    """空插件 — 替代缺失模块，不崩溃"""
    def __init__(self, *a, **kw): 
        Info = type('Info', (), {
            'name': 'noop', 'version': '0',
            'dependencies': [], 'category': 'noop',
            'description': 'Noop placeholder for missing module',
        })
        self.info = Info()
        self.state = {}
    
    def generate_report(self, *a, **kw):
        return {"status": "noop", "message": "Module not available"}
    
    def __getattr__(self, name):
        """Catch any missing attribute access"""
        return lambda *a, **kw: None

def _brain_noop(*a, **kw): 
    return _BrainNoop()

from .knowledge_graph import (KnowledgeGraph,KGNode,KGEdge,get_knowledge_graph,)
from .knowledge_sync import (
    KnowledgeItem, KnowledgeBus, CrossAgentSyncEngine,
    KnowledgeDomain, SyncPriority, ProfileInfo,
    get_knowledge_bus, get_sync_engine,
)
from .kernel import (
    Kernel, EventBus, Event, EventPriority,
    Plugin, PluginInfo, PluginManager, PluginState,
    ResourceGovernor, get_kernel, init_kernel,
)
from .memory_hierarchy import (
    HierarchicalMemoryStore, MemoryItem, MemoryLevel,
    EbbinghausForgetting, MemoryPlugin,
)
try:
    from .metacognition import (
        MetaCognitionPlugin, TaskEvaluation, TaskStatus,
        PatternEngine, BehaviorAdjuster, MetaActiveInferenceAdapter,
    )
except ImportError:
    MetaCognitionPlugin = TaskEvaluation = TaskStatus = _brain_noop
    PatternEngine = BehaviorAdjuster = MetaActiveInferenceAdapter = _brain_noop
from .orchestrator import (
    OrchestratorPlugin, TaskDAG, TaskNode, TaskNodeStatus,
    AgentPool, AgentInstance, AgentRole, MemoryHub, TaskDecomposer,
)
from .predictor import (
    PredictorPlugin, TemporalPatternLearner, ContextPreloader,
    PredictionResult, ActivityPattern, TimeSlot,
    FreeEnergyPredictorAdapter,
)
from .alert_engine import (AlertEngine,AlertLevel,Alert,get_alert_engine,)
from .agent_governance import (AgentGovernance,AgentIdentity,Quota,AuditEntry,get_governance,)
from .agent_loop import (
    AgentLoopPlugin, Observation, Decision, ActionResult,
    AgentTask, TaskPriority, LoopPhase, ResponseGenerator, ActionExecutor,
    WorkspaceAwareAdapter, BrainRouterAdapter,
)
from .performance_optimizer import (PerformanceOptimizer,PerfProfile,get_perf_optimizer,)
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
from .model_compare import compare_models, compare_models_stream, ModelCompareEngine, ModelResponse, CompareResult, get_compare_engine
from .conversation_store import Conversation, get_or_create
from .code_reviewer import CodeReviewer, ReviewIssue, PYTHON_PATTERNS, JAVASCRIPT_PATTERNS, GENERAL_PATTERNS, SEVERITY_ORDER
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
try:
    from .progressive_context import ProgressiveContextManager
except ImportError:
    ProgressiveContextManager = _brain_noop
try:
    from .session_identity import SessionIdentity
except ImportError:
    SessionIdentity = _brain_noop
try:
    from .llm_quality import LLMQualityMonitor
except ImportError:
    LLMQualityMonitor = _brain_noop
try:
    from .acp_server import ACPServer
except ImportError:
    ACPServer = _brain_noop
try:
    from .checkpoint import CheckpointManager
except ImportError:
    CheckpointManager = _brain_noop
try:
    from .image_gen import ImageGenerator, generate_image
except ImportError:
    ImageGenerator = generate_image = _brain_noop
try:
    from .credential_pool import CredentialPoolManager, get_credential_pool, PooledKey, PoolConfig
except ImportError:
    CredentialPoolManager = get_credential_pool = PooledKey = PoolConfig = _brain_noop
try:
    from .usage_insights import UsageInsights, get_insights
except ImportError:
    UsageInsights = get_insights = _brain_noop
try:
    from .gateway_connectors import GatewayManager, get_gateway, ConnectorStatus
except ImportError:
    GatewayManager = get_gateway = ConnectorStatus = _brain_noop
try:
    from .human_memory import HumanLikeMemory, get_human_memory, EmotionIntensity
except ImportError:
    HumanLikeMemory = get_human_memory = EmotionIntensity = _brain_noop
try:
    from .autonomous_engine import AutonomousEngine, get_autonomous_engine
except ImportError:
    AutonomousEngine = get_autonomous_engine = _brain_noop
try:
    from .diff_preview import DiffPreviewEngine, get_diff_engine
except ImportError:
    DiffPreviewEngine = get_diff_engine = _brain_noop
try:
    from .task_progress import TaskProgressEngine, get_progress_engine
except ImportError:
    TaskProgressEngine = get_progress_engine = _brain_noop
try:
    from .sdb_framework import SDBEngine, get_sdb_engine
except ImportError:
    SDBEngine = get_sdb_engine = _brain_noop
try:
    from .self_modify import SelfModifyEngine, get_self_modify_engine
except ImportError:
    SelfModifyEngine = get_self_modify_engine = _brain_noop
try:
    from .brain_validator import BrainStateValidator, get_brain_validator
except ImportError:
    BrainStateValidator = get_brain_validator = _brain_noop

from .autonomous_action import (
    ActionEngine, Action, RiskLevel, ActionStatus, get_action_engine,
    subconscious_to_action_cycle,
)
# v3.35: Session Auto-Resume Engine
try:
    from .session_resume import SessionResumeEngine, get_resume_engine
except ImportError:
    SessionResumeEngine = get_resume_engine = _brain_noop

# v3.36: JEPA World Model (杨立昆世界模型)
try:
    from .jepa_router import (JEPARouter,TaskEncoding,get_jepa_router,)
    from .jepa_world_model import (
        JEPAWorldModel, NonGenerativeRouter, UnifiedScorer,
        JEPAConfig, JEPAEncoder, JEPAPredictor, WorldState,
        get_world_model, get_non_generative_router,
    )
except ImportError:
    JEPAWorldModel = NonGenerativeRouter = UnifiedScorer = _brain_noop
    JEPAConfig = JEPAEncoder = JEPAPredictor = WorldState = _brain_noop
    get_world_model = get_non_generative_router = _brain_noop
try:
    from .gateway_llm import GatewayLLMAdapter, get_gateway_llm
except ImportError:
    GatewayLLMAdapter = get_gateway_llm = _brain_noop
try:
    from .unified_loop import UnifiedLoopEngine, get_unified_loop
except ImportError:
    UnifiedLoopEngine = get_unified_loop = _brain_noop
try:
    from .attractor_reasoner import AttractorReasoner, get_attractor_reasoner
except ImportError:
    AttractorReasoner = get_attractor_reasoner = _brain_noop
from .distributed_mesh import (DistributedAgentMesh,MeshNode,MeshTask,NodeState,get_distributed_mesh,)
from .desktop_agent import (DesktopAgent,DesktopAction,WindowInfo,get_desktop_agent,)
from .deploy_engine import (DeployEngine,DeployTarget,DeployResult,get_deploy_engine,)
from .dashboard import UnifiedDashboard, get_dashboard
try:
    from .predictive_precompute import PredictivePreCompute, get_precompute_engine
except ImportError:
    PredictivePreCompute = get_precompute_engine = _brain_noop
try:
    from .breakthrough_memory import BreakthroughMemoryEngine, get_breakthrough_memory
except ImportError:
    BreakthroughMemoryEngine = get_breakthrough_memory = _brain_noop
try:
    from .knowledge_transfer import CrossAgentKnowledgeEngine, get_knowledge_engine
except ImportError:
    CrossAgentKnowledgeEngine = get_knowledge_engine = _brain_noop

try:
    from .health_monitor import RealtimeHealthMonitor, get_health_monitor
except ImportError:
    RealtimeHealthMonitor = get_health_monitor = _brain_noop

try:
    from .smart_router import SmartModelRouter, get_model_router
except ImportError:
    SmartModelRouter = get_model_router = _brain_noop

# v3.83: Thinking Depth Controller
try:
    from .thinking_depth import (
        ThinkingDepthController, ThinkParseResult, ThinkDepth,
        get_thinking_controller, quick_parse,
        DEPTH_MODEL_PARAMS, DEPTH_SYSTEM_PROMPTS, DEPTH_INSTRUCTION_SUFFIX,
    )
except ImportError:
    ThinkingDepthController = ThinkParseResult = ThinkDepth = _brain_noop
    get_thinking_controller = quick_parse = _brain_noop
    DEPTH_MODEL_PARAMS = DEPTH_SYSTEM_PROMPTS = DEPTH_INSTRUCTION_SUFFIX = _brain_noop

# v3.82: MCP Protocol Standardizer
from .mcp_standardizer import (
    MCPStandardizer, MCPToolDef, MCPToolResult,
    get_mcp_standardizer, reset_mcp_standardizer,
    generate_json_schema_from_func, generate_schema_from_dict,
    discover_functions_in_module, discover_tools_in_package,
)

# v3.90 Rate Limiter
from .rate_limiter import (
    RateLimiter, RateLimitTier, TokenBucket, RateLimitResult,
    get_rate_limiter, reset_rate_limiter,
)

from .subconscious import (
    SubconsciousObserver, Nudge, NudgePriority, NudgeSource, get_observer,
)
from .feedback_loop import (
    FeedbackLoopEngine, ExecutionRecord, ActionProfile,
    AdaptiveConfig, AutonomousPipeline, get_feedback_engine,
    FeedbackLoop, FeedbackSentiment, UserFeedback,
    FailurePattern, StrategyAdjustment, FeedbackLoopReport,
    get_feedback_loop, reset_feedback_loop,
)

# v3.81 Deep Research Engine
try:
    from .deep_research import (
        DeepResearchEngine, SearchResult, ResearchStep,
        ResearchReport, get_deep_research,
    )
except ImportError:
    DeepResearchEngine = SearchResult = ResearchStep = _brain_noop
    ResearchReport = get_deep_research = _brain_noop

# v3.88 Cookbook Hardware Recommender
try:
    from .cookbook import (
        CookbookRecommender, GPUInfo, CPUInfo, HardwareProfile,
        ModelRecommendation, CookbookResult,
        get_cookbook, reset_cookbook,
    )
except ImportError:
    CookbookRecommender = GPUInfo = CPUInfo = HardwareProfile = _brain_noop
    ModelRecommendation = CookbookResult = get_cookbook = reset_cookbook = _brain_noop

# v3.89 Deep Research v2 (增强版多步调研)
try:
    from .deep_research_v2 import (
        DeepResearchV2, SearchResultV2, ResearchStepV2,
        ResearchReportV2, SearchAggregator,
        CitationFormatter, MermaidChartGenerator, HistoryStore,
        get_deep_research_v2, reset_deep_research_v2,
    )
except ImportError:
    DeepResearchV2 = SearchResultV2 = ResearchStepV2 = _brain_noop
    ResearchReportV2 = SearchAggregator = _brain_noop
    CitationFormatter = MermaidChartGenerator = HistoryStore = _brain_noop
    get_deep_research_v2 = reset_deep_research_v2 = _brain_noop

# v3.86 Web-to-API Proxy
try:
    from .web2api import (
        Web2APIProxy, SSEParser, ProxyStats, ProviderConfig,
        PROVIDERS, get_web2api, reset_web2api,
    )
except ImportError:
    Web2APIProxy = SSEParser = ProxyStats = ProviderConfig = _brain_noop
    PROVIDERS = {}
    get_web2api = reset_web2api = _brain_noop

# v3.91 PWA Manifest Builder
from .pwa_builder import (
    PWABuilder, PWAManifestConfig, PWAIcon, PWAShortcut,
    SWCacheRule, CacheStrategy, DisplayMode, IconPurpose,
    InstallPromptManager, PushManager, PushSubscription, PushNotification,
    get_pwa_builder, reset_pwa_builder,
)

# v3.92 Email Integration Engine
from .email_engine import (
    EmailEngine, EmailMessage, EmailAttachment,
    EmailLabel, EmailLabelType, EmailSummary, DraftReply,
    SpamVerdict, SpamLevel, InboxStats,
    get_email_engine, reset_email_engine,
)

# v3.93 Calendar Engine
from .calendar_engine import (
    CalendarEngine, CalendarEvent, CalDAVProvider, SyncStatus,
    ReminderType, RecurrenceRule, ReminderTask,
    get_calendar_engine, reset_calendar_engine,
)

# v3.94 Task Queue v2 (Enhanced)
from .task_queue_v2 import (
    TaskQueueV2, TaskV2, TaskStatusV2, PriorityV2,
    DependencyGraph, ExponentialBackoff, WorkerPool,
    get_task_queue_v2, reset_task_queue_v2,
)

# v3.95 Auto-Tuning Self-Optimization Engine
from .auto_tuner import (
    AutoTuner, PIDController, PIDParams, ABTest,
    get_auto_tuner,
)

from .notification_hub import (
    NotificationHub, Notification, NotificationResult,
    NotificationChannel, NotificationPriority,
    ChannelConfig, QuietHoursConfig, NotificationStats,
    TemplateEngine, DEFAULT_TEMPLATES,
    get_notification_hub, reset_notification_hub,
)

from .code_sandbox_v3 import (
    CodeSandboxV3, CodeSandboxResult, SandboxLanguage, SandboxStatus,
    SandboxRiskLevel, AuditEntry,
    get_code_sandbox_v3, reset_code_sandbox_v3,
)

# v3.99 Knowledge Graph V2
from .knowledge_graph_v2 import (
    KnowledgeGraphV2, Entity, Relation, KGVDocument,
    get_knowledge_graph_v2, reset_knowledge_graph_v2,
)

# v3.100 Multi-Modal Engine
try:
    from .multi_modal import (
        MultiModalEngine, MultiModalResult, MultiModalInput,
        ImageAnalysisResult, TranscriptionResult, OCRResult,
        Modality, VisionProvider, TranscriptionProvider, OCRProvider,
        get_multi_modal_engine, reset_multi_modal_engine,
    )
except ImportError:
    MultiModalEngine = MultiModalResult = MultiModalInput = _brain_noop
    ImageAnalysisResult = TranscriptionResult = OCRResult = _brain_noop
    Modality = VisionProvider = TranscriptionProvider = OCRProvider = _brain_noop
    get_multi_modal_engine = reset_multi_modal_engine = _brain_noop

# v3.103 Voice Chat Engine
try:
    from .voice_chat import (
        VoiceChat, VoiceChatConfig, VoiceChatSession,
        TTSResult, STTResult, TTSProvider, STTProvider,
        VoiceLanguage, AudioFormat, VoiceGender,
        get_voice_chat, reset_voice_chat,
        create_sine_wav,
    )
except ImportError:
    VoiceChat = VoiceChatConfig = VoiceChatSession = _brain_noop
    TTSResult = STTResult = TTSProvider = STTProvider = _brain_noop
    VoiceLanguage = AudioFormat = VoiceGender = _brain_noop
    get_voice_chat = reset_voice_chat = _brain_noop
    create_sine_wav = _brain_noop

# v3.106 Backup Vault
try:
    from .backup_vault import (
        BackupVault, BackupType, BackupTarget, BackupStatus,
        BackupManifest, BackupEntry, BackupResult, RestoreResult,
        get_backup_vault, reset_backup_vault,
    )
except ImportError:
    BackupVault = BackupType = BackupTarget = BackupStatus = _brain_noop
    BackupManifest = BackupEntry = BackupResult = RestoreResult = _brain_noop
    get_backup_vault = reset_backup_vault = _brain_noop

# v3.109 Agent Swarm V2
from .agent_swarm_v2 import (
    AgentSwarmV2, SwarmAgent, AgentRole, RoleType, RoleCapability,
    DynamicRoleManager, ConsensusEngine, ConsensusStrategy, ConsensusResult,
    Vote, TaskMarket, MarketTask, MarketTaskStatus, Bid,
    SelfOrganizingTopology, TopologyType, TopologyConfig, TopologyNode,
    get_agent_swarm_v2, reset_agent_swarm_v2,
)

# v3.111 Data Pipeline (数据管道)
from .data_pipeline import (
    DataPipeline, DataRecord, DataSourceType, ProcessingMode,
    ValidationLevel, PipelineState, PipelineStats,
    DataSourceConnector, FileConnector, HttpConnector, MemoryConnector,
    DataQualityValidator, ValidationRule, ValidationResult,
    TransformFunc,
    get_data_pipeline, reset_data_pipeline,
)

__version__ = "3.114.0"

# v3.110 API Gateway
from .api_gateway import (
    APIGateway, BackendService, BackendHealth, Route,
    AuthCredential, AuthResult, AuthMethod, Role,
    CircuitBreaker, CircuitState, TokenBucket,
    RateLimitConfig, GatewayMetrics,
    get_gateway, reset_gateway,
)
from .memory_compactor import (
    MemoryCompactor as MemoryCompactorV3, MemoryEntry, MemoryTier,
    CompressionStrategy, CompactionResult, TierMigrationResult,
    RetrievalResult, CompactionStats,
    get_memory_compactor, reset_memory_compactor,
)

# v3.104 Vector DB (向量数据库)
try:
    from .workflow_engine import (
        WorkflowEngine, WorkflowNode, WorkflowEdge,
        NodeStatus, NodeType, ExecutionContext,
        get_workflow_engine, reset_workflow_engine,
    )
except ImportError:
    WorkflowEngine = WorkflowNode = WorkflowEdge = _brain_noop
    NodeStatus = NodeType = ExecutionContext = _brain_noop
    get_workflow_engine = reset_workflow_engine = _brain_noop

# v3.104 Vector DB (向量数据库) [duplicated section header — actual v3.107 above]
from .vector_db import (
    VectorDB, VectorDBConfig, VectorDocument, SearchHit, SearchResult,
    SearchType, Backend, SimpleEncoder, KeywordIndex, BuiltinBackend,
    get_vector_db, reset_vector_db,
)

# v3.105 Prompt Optimizer
from .prompt_optimizer import (
    PromptOptimizer, PromptVariant, PromptTemplate,
    ABTestResult, EffectMetrics, OptimizationRecord,
    OptimizationStrategy, ABTestStatus, TemplateCategory,
    get_prompt_optimizer, reset_prompt_optimizer,
)

from .web_crawler import (
    WebCrawler, CrawlResult, CrawlConfig, SitemapEntry, RobotsChecker,
    html_to_markdown, extract_links, extract_title,
    get_web_crawler, reset_web_crawler,
)

# v3.112 Security Scanner
from .security_scanner import (
    SecurityScanner, ScanModule, Severity, Finding, ScanResult,
    SecurityReport, get_security_scanner, reset_security_scanner,
)

# P0-5 Goal自检机制
try:
    from .goal_checker import (
        GoalChecker, GoalCheckResult,
        get_goal_checker, reset_goal_checker,
    )
except ImportError:
    GoalChecker = GoalCheckResult = _brain_noop
    get_goal_checker = reset_goal_checker = _brain_noop

# P0-6 Hooks系统 — PreToolUse/PostToolUse事件钩子
try:
    from .hooks_engine import (
        HookSystem, HookResult, HookEvent,
        get_hook_system, reset_hook_system,
    )
except ImportError:
    HookSystem = HookResult = HookEvent = _brain_noop
    get_hook_system = reset_hook_system = _brain_noop

# v3.102 Plugin Market
from .plugin_market import (
    PluginMarket, PluginEntry, PluginVersion, PluginReview,
    get_plugin_market, reset_plugin_market,
)


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
    "ModelCompareEngine", "ModelResponse", "CompareResult", "get_compare_engine",
    "Conversation", "get_or_create",
    # v2.44 Diff Preview
    "DiffPreviewEngine", "get_diff_engine",
    # v2.45 Task Progress
    "TaskProgressEngine", "get_progress_engine",
    # v2.46 SDB Framework
    "SDBEngine", "get_sdb_engine",
    # v2.47 Self-Modify
    "SelfModifyEngine", "get_self_modify_engine",
    # v2.48 Brain Validator
    "BrainStateValidator", "get_brain_validator",
    # v2.49 Gateway LLM
    "GatewayLLMAdapter", "get_gateway_llm",
    # v2.50 Unified Loop
    "UnifiedLoopEngine", "get_unified_loop",
    # v2.51 Attractor Reasoner
    "AttractorReasoner", "get_attractor_reasoner",
    # v2.52 Dashboard
    "UnifiedDashboard", "get_dashboard",
    # v2.53 Knowledge Transfer
    "CrossAgentKnowledgeEngine", "get_knowledge_engine",
    # v2.54 Breakthrough Memory
    "BreakthroughMemoryEngine", "get_breakthrough_memory",
    # v2.55 Precompute
    "PredictivePreCompute", "get_precompute_engine",
    # v2.57 Health Monitor
    "RealtimeHealthMonitor", "get_health_monitor",
    # v3.82 MCP Protocol Standardizer
    "MCPStandardizer", "MCPToolDef", "MCPToolResult",
    "get_mcp_standardizer", "reset_mcp_standardizer",
    "generate_json_schema_from_func", "generate_schema_from_dict",
    "discover_functions_in_module", "discover_tools_in_package",
    # v3.81 Deep Research Engine
    "DeepResearchEngine", "SearchResult", "ResearchStep",
    "ResearchReport", "get_deep_research",
    # v3.89 Deep Research v2
    "DeepResearchV2", "SearchResultV2", "ResearchStepV2",
    "ResearchReportV2", "SearchAggregator",
    "CitationFormatter", "MermaidChartGenerator", "HistoryStore",
    "get_deep_research_v2", "reset_deep_research_v2",
    # v3.83 Thinking Depth Controller
    "ThinkingDepthController", "ThinkParseResult", "ThinkDepth",
    "get_thinking_controller", "quick_parse",
    "DEPTH_MODEL_PARAMS", "DEPTH_SYSTEM_PROMPTS", "DEPTH_INSTRUCTION_SUFFIX",
    # v3.88 Cookbook Hardware Recommender
    "CookbookRecommender", "GPUInfo", "CPUInfo", "HardwareProfile",
    "ModelRecommendation", "CookbookResult",
    "get_cookbook", "reset_cookbook",
    # v3.90 Rate Limiter
    "RateLimiter", "RateLimitTier", "TokenBucket", "RateLimitResult",
    "get_rate_limiter", "reset_rate_limiter",
    # v3.86 Web-to-API Proxy
    "Web2APIProxy", "SSEParser", "ProxyStats", "ProviderConfig",
    "PROVIDERS", "get_web2api", "reset_web2api",
    # v3.91 PWA Manifest Builder
    "PWABuilder", "PWAManifestConfig", "PWAIcon", "PWAShortcut",
    "SWCacheRule", "CacheStrategy", "DisplayMode", "IconPurpose",
    "InstallPromptManager", "PushManager", "PushSubscription", "PushNotification",
    "get_pwa_builder", "reset_pwa_builder",
    # v3.92 Email Integration Engine
    "EmailEngine", "EmailMessage", "EmailAttachment",
    "EmailLabel", "EmailLabelType", "EmailSummary", "DraftReply",
    "SpamVerdict", "SpamLevel", "InboxStats",
    "get_email_engine", "reset_email_engine",
    # v3.93 Calendar Engine
    "CalendarEngine", "CalendarEvent", "CalDAVProvider", "SyncStatus",
    "ReminderType", "ReminderTask", "RecurrenceRule",
    "get_calendar_engine", "reset_calendar_engine",
    # v3.94 Task Queue v2
    "TaskQueueV2", "TaskV2", "TaskStatusV2", "PriorityV2",
    "DependencyGraph", "ExponentialBackoff", "WorkerPool",
    "get_task_queue_v2", "reset_task_queue_v2",
    # v3.95 Auto-Tuning Engine
    "AutoTuner", "PIDController", "PIDParams", "ABTest",
    "get_auto_tuner",
    # v3.96 Notification Hub
    "NotificationHub", "Notification", "NotificationResult",
    "NotificationChannel", "NotificationPriority",
    "ChannelConfig", "QuietHoursConfig", "NotificationStats",
    "TemplateEngine", "DEFAULT_TEMPLATES",
    "get_notification_hub", "reset_notification_hub",
    # v3.97 Code Sandbox V3
    "CodeSandboxV3", "CodeSandboxResult", "SandboxLanguage", "SandboxStatus",
    "SandboxRiskLevel", "AuditEntry",
    "get_code_sandbox_v3", "reset_code_sandbox_v3",
    # v3.98 Feedback Loop
    "FeedbackLoop", "FeedbackSentiment", "UserFeedback",
    "FailurePattern", "StrategyAdjustment", "FeedbackLoopReport",
    "get_feedback_loop", "reset_feedback_loop",
    # v3.99 Knowledge Graph V2
    "KnowledgeGraphV2", "Entity", "Relation", "KGVDocument",
    "get_knowledge_graph_v2", "reset_knowledge_graph_v2",
    # v3.100 Multi-Modal Engine
    "MultiModalEngine", "MultiModalResult", "MultiModalInput",
    "ImageAnalysisResult", "TranscriptionResult", "OCRResult",
    "Modality", "VisionProvider", "TranscriptionProvider", "OCRProvider",
    "get_multi_modal_engine", "reset_multi_modal_engine",
    # v3.101 Web Crawler
    "WebCrawler", "CrawlResult", "CrawlConfig", "SitemapEntry", "RobotsChecker",
    "html_to_markdown", "extract_links", "extract_title",
    "get_web_crawler", "reset_web_crawler",
    # v3.102 Plugin Market
    "PluginMarket", "PluginEntry", "PluginVersion", "PluginReview",
    "get_plugin_market", "reset_plugin_market",
    # v3.103 Voice Chat Engine
    "VoiceChat", "VoiceChatConfig", "VoiceChatSession",
    "TTSResult", "STTResult", "TTSProvider", "STTProvider",
    "VoiceLanguage", "AudioFormat", "VoiceGender",
    "get_voice_chat", "reset_voice_chat",
    "create_sine_wav",
    # v3.104 Vector DB
    "VectorDB", "VectorDBConfig", "VectorDocument", "SearchHit", "SearchResult",
    "SearchType", "Backend", "SimpleEncoder", "KeywordIndex", "BuiltinBackend",
    "get_vector_db", "reset_vector_db",
    # v3.105 Prompt Optimizer
    "PromptOptimizer", "PromptVariant", "PromptTemplate",
    "ABTestResult", "EffectMetrics", "OptimizationRecord",
    "OptimizationStrategy", "ABTestStatus", "TemplateCategory",
    "get_prompt_optimizer", "reset_prompt_optimizer",
    # v3.106 Backup Vault
    "BackupVault", "BackupType", "BackupTarget", "BackupStatus",
    "BackupManifest", "BackupEntry", "BackupResult", "RestoreResult",
    "get_backup_vault", "reset_backup_vault",
    # v3.107 Workflow Engine
    "WorkflowEngine", "WorkflowNode", "WorkflowEdge",
    "NodeStatus", "NodeType", "ExecutionContext",
    "get_workflow_engine", "reset_workflow_engine",
    # v3.108 Memory Compactor
    "MemoryCompactorV3", "MemoryEntry", "MemoryTier",
    "CompressionStrategy", "CompactionResult", "TierMigrationResult",
    "RetrievalResult", "CompactionStats",
    "get_memory_compactor", "reset_memory_compactor",
    # v3.109 Agent Swarm V2
    "AgentSwarmV2", "SwarmAgent", "AgentRole", "RoleType", "RoleCapability",
    "DynamicRoleManager", "ConsensusEngine", "ConsensusStrategy", "ConsensusResult",
    "Vote", "TaskMarket", "MarketTask", "MarketTaskStatus", "Bid",
    "SelfOrganizingTopology", "TopologyType", "TopologyConfig", "TopologyNode",
    "get_agent_swarm_v2", "reset_agent_swarm_v2",
    # v3.110 API Gateway
    "APIGateway", "BackendService", "BackendHealth", "Route",
    "AuthCredential", "AuthResult", "AuthMethod", "Role",
    "CircuitBreaker", "CircuitState", "TokenBucket",
    "RateLimitConfig", "GatewayMetrics",
    "get_gateway", "reset_gateway",
    # v3.111 Data Pipeline
    "DataPipeline", "DataRecord", "DataSourceType", "ProcessingMode",
    "ValidationLevel", "PipelineState", "PipelineStats",
    "DataSourceConnector", "FileConnector", "HttpConnector", "MemoryConnector",
    "DataQualityValidator", "ValidationRule", "ValidationResult",
    "TransformFunc",
    "get_data_pipeline", "reset_data_pipeline",
    # v3.112 Security Scanner
    "SecurityScanner", "ScanModule", "Severity", "Finding", "ScanResult",
    "SecurityReport", "get_security_scanner", "reset_security_scanner",
    # P0-5 Goal自检机制
    "GoalChecker", "GoalCheckResult",
    "get_goal_checker", "reset_goal_checker",
    # P0-6 Hooks系统
    "HookSystem", "HookResult", "HookEvent",
    "get_hook_system", "reset_hook_system",
]

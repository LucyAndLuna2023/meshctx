"""
meshctx Core — 开源封装层 (Stub Mode)
=======================================
meshctx 开源 wrapper 层。核心引擎在 meshctx-core (私有仓库)。

安装完整版: pip install meshctx-core (需授权)
当前为 stub 模式 — 基础功能可用，高级能力优雅降级。
"""
__version__ = "3.115.14"

import sys, logging
from types import ModuleType

# ═══════════════ 全局 Enum stub 补丁 ═══════════════
import enum
from types import SimpleNamespace

def _stub_enum_getattr(cls, name):
    if name.startswith('_'):
        raise AttributeError(name)
    val = name.lower()
    member = SimpleNamespace(value=val, name=name.upper())
    try:
        setattr(cls, name, member)
    except (TypeError, AttributeError):
        pass
    return member

type(enum.Enum).__getattr__ = _stub_enum_getattr

# ═══════════════ 通用 Stub ═══════════════
class _StubClass:
    def __init__(self, *a, **kw): pass
    def __call__(self, *a, **kw): return self
    def __getattr__(self, name): return self
    def __bool__(self): return False
    def __repr__(self): return "<meshctx-core stub>"
    def __iter__(self): return iter([])
    def __len__(self): return 0

_stub = _StubClass()

# ═══════════════ 已知stub模块映射 ═══════════════
_known = {
    'kernel': ['Kernel','EventBus','Event','EventPriority','Plugin','PluginInfo',
               'PluginManager','PluginState','ResourceGovernor','get_kernel','init_kernel'],
    'hotreload': ['ConfigWatcher','APIKeyFailover','MemoryBackup'],
    'watchdog': ['WatchdogDaemon','get_daemon','HEARTBEAT_FILE'],
    'conversation_store': ['Conversation','get_or_create','DATA_DIR'],
    'session_archiver': ['SessionArchiver','get_archiver'],
    'crypto': ['encrypt_key','decrypt_key','is_encrypted'],
    'sandbox': ['SandboxEngine','SandboxResult','CodeSandboxV2','get_sandbox'],
    'platform_fs': ['windows_to_wsl','wsl_to_windows'],
    'plugin_autoload': ['discover_plugins','auto_activate_builtins'],
    'realtime_push': ['RealtimeHub','get_hub'],
    'agent_swarm': ['get_swarm_manager','get_swarm_worker','init_swarm_manager'],
    'multi_agent': ['AgentFactory','get_manager','get_executor'],
    'summon_engine': ['get_summon_engine'],
    'agent_governance': ['AgentGovernance','AgentIdentity','Quota','AuditEntry','get_governance'],
    'auto_healer': ['healer'],
    'performance_optimizer': ['PerformanceOptimizer','PerfProfile','optimizer','get_perf_optimizer'],
    'backup_vault': ['get_backup_vault'],
    'project_indexer': ['ProjectIndexer','FileSummary','IndexStats','get_indexer'],
    'session_resume': ['get_session_resume'],
    'spreadsheet_tool': ['spreadsheet_analyze','spreadsheet_read','spreadsheet_stats','spreadsheet_chart','spreadsheet_trend'],
    'jepa_world_model': ['get_world_model','get_non_generative_router'],
    'hybrid_reasoning': ['HybridReasoningScheduler'],
    'image_gen': ['ImageGenerator'],
    'unified_loop': ['get_unified_loop'],
    'task_progress': ['get_progress_engine'],
    'sdb_framework': ['get_sdb_engine'],
    'brain_validator': ['get_brain_validator'],
    'self_modify': ['get_self_modify_engine'],
    'code_reviewer': ['CodeReviewer','ReviewIssue','PYTHON_PATTERNS','JAVASCRIPT_PATTERNS','GENERAL_PATTERNS','SEVERITY_ORDER'],
    'profile_manager': ['ProfileManager'],
    'approval': ['ApprovalEngine'],
    'credential_pool': ['CredentialPoolManager'],
    'usage_insights': ['UsageInsights','get_usage_insights'],
    'diff_preview': ['DiffEngine','DiffChunkAction','DiffFile','DiffChunk','InlineDiffViewer','DiffRenderer','DiffApplicator','BatchDiffManager','get_diff_engine','create_proposal','render_side_by_side','render_compact_summary'],
    'thinking_pad': ['ThinkingPad','ThinkingPadManager','ThoughtNode','ThoughtCategory','ThoughtStatus','ThinkingSession'],
    'gateway_connectors': ['get_gateway'],
    'feishu_notify': ['FeishuNotifier','FeishuPlugin'],
    'telegram_router': ['TelegramRouter','TgBot','get_telegram_router'],
    'health_monitor': ['get_health_monitor'],
    'human_memory': ['EmotionIntensity','get_human_memory'],
    'learn_loop': ['LearnLoop'],
    'model_compare': ['compare_models','compare_models_stream','ModelCompareEngine','ModelResponse','CompareResult','get_compare_engine'],
    'principle_extractor': ['get_extractor'],
    'action_gate': ['TOOL_PRINCIPLE_MAP','get_gate'],
    'alert_engine': ['AlertEngine','AlertLevel','Alert','get_alert_engine'],
    'agent_loop': ['AgentLoopPlugin','Observation','Decision','ActionResult','AgentTask','TaskPriority','LoopPhase','ResponseGenerator','ActionExecutor'],
    'autonomous_engine': ['Severity','get_autonomous_engine'],
    'attention_decay': ['get_monitor'],
    'cognitive_health': ['CognitiveHealthMonitor'],
    'dashboard': ['UnifiedDashboard','get_dashboard'],
    'memory_v2': ['get_memory_manager'],
    'secret_scanner': ['SecretScanner'],
    'super_brain': ['IITConsciousness'],
    'win_admin': ['WindowsAdmin','WinResult','WinService','get_win_admin'],
    'lsp_tool': ['lsp_start','lsp_stop','lsp_definition','lsp_references','lsp_hover','lsp_diagnostics','lsp_list_servers','lsp_stop_all','detect_language','supported_languages'],
    'agent_monitor': ['AgentMonitor','AgentMetrics'],
    'agent_tasks': ['AgentTask'],
    'agents_list': ['agents_list','agent_status','agent_kill','agent_send','agents_cleanup','agent_register','agent_update'],
    'workspace_manager': ['WorkspaceManager','Workspace','get_workspace_manager'],
    'auto_update': ['check_update'],
    'multi_notify': ['TelegramNotifier','DiscordNotifier','SlackNotifier','MultiNotifier','get_multi_notifier'],
    'versioned_memory': ['VersionedMemory','get_memory'],
    'autonomous_action': ['AutonomousAction','ActionPlan','get_autonomous_action'],
    'distributed_mesh': ['DistributedAgentMesh','MeshNode','MeshTask','NodeState','get_distributed_mesh'],
    'desktop_agent': ['DesktopAgent','DesktopAction','WindowInfo','get_desktop_agent'],
    'desktop_tool': ['desktop_screenshot','desktop_click','desktop_type','desktop_press','desktop_move','desktop_scroll','desktop_size'],
    'deploy_engine': ['DeployEngine','DeployTarget','DeployResult','get_deploy_engine'],
    'mcp_standardizer': ['MCPStandardizer','MCPTool','MCPServer','get_mcp_standardizer'],
    'rate_limiter': ['RateLimiter','TokenBucket','QuotaManager'],
    'subconscious': ['SubconsciousEngine','SubconsciousThought','get_subconscious'],
    'feedback_loop': ['FeedbackLoop','FeedbackEntry','get_feedback_loop'],
    'pwa_builder': ['PWABuilder','PWAManifest','get_pwa_builder'],
    'email_engine': ['EmailEngine','EmailMessage','get_email_engine'],
    'calendar_engine': ['CalendarEngine','CalendarEvent','get_calendar_engine'],
    'task_queue_v2': ['TaskQueueV2','QueuedTask','get_task_queue_v2'],
    'auto_tuner': ['AutoTuner','TuningProfile','get_auto_tuner'],
    'notification_hub': ['NotificationHub','Notification','get_notification_hub'],
    'code_sandbox_v3': ['CodeSandboxV3','SandboxSession','get_code_sandbox_v3'],
    'knowledge_graph': ['KnowledgeGraph','KGNode','KGEdge','get_knowledge_graph'],
    'knowledge_base': ['kb_add','kb_search','kb_list','kb_remove','kb_clear','kb_stats'],
    'knowledge_graph_v2': ['KnowledgeGraphV2','KGEntity','KGRelation','get_knowledge_graph_v2'],
    'knowledge_sync': ['KnowledgeItem','KnowledgeBus','CrossAgentSyncEngine','KnowledgeDomain','SyncPriority','ProfileInfo','get_knowledge_bus','get_sync_engine'],
    'agent_swarm_v2': ['AgentSwarmV2','SwarmNode','SwarmTask','get_agent_swarm_v2'],
    'data_pipeline': ['DataPipeline','PipelineStage','DataRecord','get_data_pipeline'],
    'api_gateway': ['APIGateway','APIRoute','get_api_gateway'],
    'memory_compactor': ['MemoryCompactor','CompactionResult','get_memory_compactor'],
    'vector_db': ['VectorDB','VectorRecord','get_vector_db'],
    'prompt_optimizer': ['PromptOptimizer','OptimizedPrompt','get_prompt_optimizer'],
    'web_crawler': ['WebCrawler','CrawlResult','get_web_crawler'],
    'web_scraper': ['web_scrape','web_scrape_table','web_scrape_links','web_scrape_metadata','web_scrape_paginate'],
    'security_scanner': ['SecurityScanner','ScanResult','get_security_scanner'],
    'send_file': ['send_file','send_file_to_channel'],
    'plugin_market': ['PluginMarket','MarketPlugin','get_plugin_market'],
    'plugin_manifest': ['PluginManifest'],
    'ppt_generator': ['ppt_generate'],
    'online_learning': ['OnlineLearner','LearningSample'],
    'memory_hierarchy': ['HierarchicalMemoryStore','MemoryItem','MemoryLevel','EbbinghausForgetting','MemoryPlugin'],
    'metacognition': ['MetaCognitionPlugin','TaskEvaluation','TaskStatus','PatternEngine','BehaviorAdjuster'],
    'orchestrator': ['OrchestratorPlugin','TaskDAG','TaskNode','TaskNodeStatus','AgentPool','AgentInstance','AgentRole','MemoryHub','TaskDecomposer'],
    'predictor': ['PredictorPlugin','TemporalPatternLearner','ContextPreloader','PredictionResult','ActivityPattern','TimeSlot'],
    'healer': ['HealerPlugin','HealthStatus','CircuitBreaker'],
    'performance': ['PerformancePlugin','CacheStats','StreamStats'],
    'websocket': ['WebSocketPlugin', '_P', 'create_ws_routes'],
    'realtime_push': ['RealtimePush', 'ConnectionManager', 'create_realtime_router', 'get_realtime'],
    'hermes_connector': ['HermesConnectorPlugin','HermesDiscovery','EventBridge','HermesInstance'],
    'token_saver': ['TokenSaverPlugin','TokenSaver','TokenCounter','TokenizerRegistry','CompactionResult'],
}

def __getattr__(name):
    if name.startswith('_'):
        raise AttributeError(name)
    # 如果 name 本身是已知子模块名, 直接返回模块 (而非模块内符号)
    if name in _known:
        try:
            mod = __import__(f'src.core.{name}', fromlist=['__name__'])
            globals()[name] = mod
            return mod
        except ImportError:
            pass
    for mod_name, symbols in _known.items():
        if name in symbols:
            try:
                mod = __import__(f'src.core.{mod_name}', fromlist=[name])
                attr = getattr(mod, name)
                globals()[name] = attr
                return attr
            except (ImportError, AttributeError):
                globals()[name] = _stub
                return _stub
    try:
        mod = __import__('meshctx_core.core', fromlist=[name])
        attr = getattr(mod, name, _stub)
        globals()[name] = attr
        return attr
    except ImportError:
        pass
    globals()[name] = _stub
    return _stub

def __dir__():
    result = ['__version__']
    for syms in _known.values():
        result.extend(syms)
    return sorted(set(result))

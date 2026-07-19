"""
meshctx Core — 开源封装层 (Stub Mode)
=======================================
meshctx 开源 wrapper 层。核心引擎在 meshctx-core (私有仓库)。

安装完整版: pip install meshctx-core (需授权)
当前为 stub 模式 — 基础功能可用，高级能力优雅降级。
"""
__version__ = "3.115.22"

import sys, logging, warnings, os
from functools import lru_cache
from types import ModuleType

# ═══════════════ MESHCTX_STRICT 开关 ═══════════════
# 设置环境变量 MESHCTX_STRICT=1 可启用严格模式:
#   stub 访问不再静默失败, 而是 raise ImportError
_STRICT = os.environ.get('MESHCTX_STRICT', '').strip() in ('1', 'true', 'yes')

# ═══════════════ 通用 Stub (阶段1: 添加诊断) ═══════════════
class _StubClass:
    __slots__ = ('_warned',)  # 减少内存, 单例仅一个 set

    def __init__(self, *a, **kw):
        object.__setattr__(self, '_warned', set())

    def _warn_once(self, name):
        """每个属性名仅警告一次, 避免日志洪水"""
        _w = object.__getattribute__(self, '_warned')
        if name not in _w:
            _w.add(name)
            warnings.warn(
                f"meshctx stub accessed: .{name} — meshctx-core not installed. "
                f"Set MESHCTX_STRICT=1 to raise ImportError instead.",
                RuntimeWarning, stacklevel=3)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if _STRICT:
            raise ImportError(
                f"meshctx stub '{name}' — meshctx-core not installed. "
                f"Unset MESHCTX_STRICT for graceful degradation.")
        self._warn_once(name)
        return self

    def __call__(self, *a, **kw):
        if _STRICT:
            raise ImportError(
                "meshctx stub called — meshctx-core not installed. "
                "Unset MESHCTX_STRICT for graceful degradation.")
        self._warn_once('__call__')
        return self

    def __bool__(self):
        if _STRICT:
            raise ImportError(
                "meshctx stub truthiness check — meshctx-core not installed. "
                "Use has_module() to check availability.")
        self._warn_once('__bool__')
        return False

    def __getitem__(self, key): return self
    def __await__(self):
        async def _aw(): return self
        return _aw().__await__()
    def __gt__(self, other): return False
    def __lt__(self, other): return False
    def __ge__(self, other): return False
    def __le__(self, other): return False
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
    'jepa_world_model': ['JEPAWorldModel','JEPAPredictor','JEPARouter','LatentEncoder','get_jepa_world_model'],
    'brain': ['SuperBrain','get_super_brain','HippocampalReplay','AmygdalaSalience','DefaultModeNetwork','ThalamicGate','CerebellarForwardModel','BasalGanglia','ACCConflictMonitor','Insula','MirrorNeuron','BrainEvent','BrainState','SalienceLevel'],
    'sdm_memory': ['SparseDistributedMemory','LightSDM','HardLocation','get_sdm','get_light_sdm'],
    'context_portal': ['ContextPortal','ContextItem','MemoryPrefetchTable','PatternLearner','get_context_portal'],
    'autonomous_engine': ['AutonomousEngine','EngineState','TaskQueue','HeartbeatMonitor','AutoHealer','TaskPriority','ScheduledTask','get_autonomous_engine'],
    'breakthrough_memory': ['BreakthroughMemory','AttractorReasoner','MeshCtxBreakthrough','Insight','ExperienceFragment','SolutionNode','get_breakthrough'],
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
    'super_brain': ['SuperBrain','get_super_brain'],  # legacy alias → brain
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
    'websocket': ['WebSocketPlugin', 'create_ws_routes'],
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
    result = ['__version__', 'has_module', 'available_modules']
    for syms in _known.values():
        result.extend(syms)
    return sorted(set(result))


# ═══════════════ 阶段1: 模块可用性查询 API ═══════════════
def has_module(name):
    """检查 meshctx-core 子模块是否可用 (非 stub)。

    用法:
        if meshctx.has_module('agent_swarm'):
            meshctx.agent_swarm.get_swarm_manager()
        else:
            # 优雅降级
            pass

    返回:
        True  — meshctx-core 已安装, 模块真实可用
        False — stub 模式 (meshctx-core 未安装)
    """
    if name in _known:
        try:
            __import__(f'src.core.{name}', fromlist=['__name__'])
            return True
        except ImportError:
            return False
    return False


@lru_cache(maxsize=1)
def available_modules():
    """列出当前可用的 meshctx-core 子模块。

    返回: list[str] — 已加载或可导入的模块名
    注意: 仅反映可用模块, 不包含 stub (stub 下返回空列表)
    """
    result = []
    for mod_name in _known:
        try:
            __import__(f'src.core.{mod_name}', fromlist=['__name__'])
            result.append(mod_name)
        except ImportError:
            pass
    return sorted(result)

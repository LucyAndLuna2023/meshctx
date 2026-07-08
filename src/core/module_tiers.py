"""
meshctx Module Boundary Markers (v3.115.16)
Mark each core module as REAL (full implementation), STUB (proxy), or MIXED.
"""
from enum import Enum

class ModuleTier(Enum):
    """Module implementation tier."""
    REAL = "real"       # Full implementation, no stubs
    STUB = "stub"       # Pure proxy, all functionality in meshctx-core
    MIXED = "mixed"     # Some real code + some stubs
    SHELL = "shell"     # Intentional open-source shell


# Tier classification for all core modules
MODULE_TIERS = {
    # ── REAL: full implementations ──
    "web_ui": ModuleTier.REAL,
    "main": ModuleTier.REAL,
    "i18n": ModuleTier.REAL,
    "memory_engine": ModuleTier.REAL,
    "models": ModuleTier.REAL,
    "cli": ModuleTier.REAL,
    "diff_preview": ModuleTier.REAL,
    "doc_generator": ModuleTier.REAL,
    "notification_hub": ModuleTier.REAL,
    "load_balancer": ModuleTier.REAL,
    "task_queue_v2": ModuleTier.REAL,
    "error_recovery": ModuleTier.REAL,
    "pr_agent": ModuleTier.REAL,
    "refactor_agent": ModuleTier.REAL,
    "gateway_connectors": ModuleTier.REAL,
    "plugin_manager": ModuleTier.REAL,
    "agent_loop": ModuleTier.REAL,
    "graceful_shutdown": ModuleTier.REAL,
    "retry": ModuleTier.REAL,
    "monitoring": ModuleTier.REAL,
    "scheduler": ModuleTier.REAL,
    "ws_reliable": ModuleTier.REAL,
    "browser_tool": ModuleTier.REAL,
    "web_scraper": ModuleTier.REAL,
    "crypto": ModuleTier.REAL,
    "auth_v2": ModuleTier.REAL,
    "circuit_breaker": ModuleTier.REAL,
    "config_chain": ModuleTier.REAL,
    "test_generator": ModuleTier.REAL,
    
    # ── MIXED: partial implementation ──
    "api_gateway": ModuleTier.MIXED,
    "goal_checker": ModuleTier.MIXED,
    "super_brain": ModuleTier.MIXED,
    "mcp_integrator": ModuleTier.MIXED,
    "gateway_llm": ModuleTier.MIXED,
    
    # ── SHELL: intentional open-source shell ──
    "kernel": ModuleTier.SHELL,
    "predictor": ModuleTier.SHELL,
    "healer": ModuleTier.SHELL,
    "performance_optimizer": ModuleTier.SHELL,
    "hermes_connector": ModuleTier.SHELL,
    "orchestrator": ModuleTier.SHELL,
    "metacognition": ModuleTier.SHELL,
    "plugin_adapter": ModuleTier.SHELL,
    "auto_tune": ModuleTier.SHELL,
    "autonomous_bugfix": ModuleTier.SHELL,
    "self_healing2": ModuleTier.SHELL,
    "self_updater": ModuleTier.SHELL,
    "dreaming_agent": ModuleTier.SHELL,
    "voice_chat": ModuleTier.SHELL,
    "advanced_inference": ModuleTier.SHELL,
    "active_inference": ModuleTier.SHELL,
    "wasserstein_bridge": ModuleTier.SHELL,
    "free_energy": ModuleTier.SHELL,
    "homeostasis": ModuleTier.SHELL,
    "thermo_cost": ModuleTier.SHELL,
    "global_workspace": ModuleTier.SHELL,
    "topo_memory": ModuleTier.SHELL,
    "semantic_index": ModuleTier.SHELL,
    "knowledge_synth": ModuleTier.SHELL,
    "progressive_context": ModuleTier.SHELL,
    "context_window": ModuleTier.SHELL,
    "attention_decay": ModuleTier.SHELL,
    "token_budget": ModuleTier.SHELL,
    "interactive_console": ModuleTier.SHELL,
    "cross_validator": ModuleTier.SHELL,
    "resilience_loop": ModuleTier.SHELL,
    "error_learner": ModuleTier.SHELL,
    "usage_meter": ModuleTier.SHELL,
    "quota_manager": ModuleTier.SHELL,
    "feature_flags": ModuleTier.SHELL,
    "experiment_engine": ModuleTier.SHELL,
    "model_registry": ModuleTier.SHELL,
    "chain_engine": ModuleTier.SHELL,
    "workflow": ModuleTier.SHELL,
    "prompt_engine": ModuleTier.SHELL,
    "api_versioning": ModuleTier.SHELL,
    "hybrid_search": ModuleTier.SHELL,
    "smart_router": ModuleTier.SHELL,
    "tool_curator": ModuleTier.SHELL,
    "config_hot_reload": ModuleTier.SHELL,
    "graphql_gateway": ModuleTier.SHELL,
    "event_system": ModuleTier.SHELL,
    "rag_orchestrator": ModuleTier.SHELL,
    "vector_store": ModuleTier.SHELL,
    "embeddings": ModuleTier.SHELL,
    "distributed_lock": ModuleTier.SHELL,
    "dependency_scanner": ModuleTier.SHELL,
    "regression_shield": ModuleTier.SHELL,
    "observer": ModuleTier.SHELL,
    "audit_logger": ModuleTier.SHELL,
    "pipeline_bench": ModuleTier.SHELL,
    "memory_health": ModuleTier.SHELL,
    "swarm_engine": ModuleTier.SHELL,
    "task_planner": ModuleTier.SHELL,
    "goal_decomposer": ModuleTier.SHELL,
    "lsp_tool": ModuleTier.SHELL,
    "conversation_store": ModuleTier.SHELL,
    "monitor": ModuleTier.SHELL,
    "desktop_tool": ModuleTier.SHELL,
    "info_geo_router": ModuleTier.SHELL,
    "multi_modal": ModuleTier.SHELL,
    "knowledge_base": ModuleTier.SHELL,
    "project_indexer": ModuleTier.SHELL,
    "multi_agent": ModuleTier.SHELL,
    "online_learning": ModuleTier.SHELL,
    "watchdog": ModuleTier.SHELL,
    "hotreload": ModuleTier.SHELL,
    "platform_fs": ModuleTier.SHELL,
    "realtime_push": ModuleTier.SHELL,
}


def get_tier(module_name: str) -> ModuleTier:
    """Get the implementation tier of a module."""
    base = module_name.split('.')[-1].replace('.py', '')
    return MODULE_TIERS.get(base, ModuleTier.SHELL)


def is_real(module_name: str) -> bool:
    return get_tier(module_name) == ModuleTier.REAL


# Statistics
_tier_counts = {}
for t in MODULE_TIERS.values():
    _tier_counts[t.value] = _tier_counts.get(t.value, 0) + 1

TIER_STATS = dict(_tier_counts)

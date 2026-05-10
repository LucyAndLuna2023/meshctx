"""MeshCtx — AI 连续上下文记忆平台 + Hermes 集成层"""

from .memory_engine import (
    MemoryEngine,
    CrossPlatformEngine,
    VectorStore,
    LLMExtractor,
    get_engine,
)
from .capabilities import (
    CapabilityCatalog,
    SkillEntry,
    ToolEntry,
    ProviderEntry,
    get_catalog,
)
from .orchestrator import (
    SkillOrchestrator,
    SkillMatcher,
    IntentParser,
    MatchResult,
    ExecutionPlan,
    get_orchestrator,
    SKILL_CHAINS,
)
from .adapter import (
    ContextPortal,
    SkillContextProvider,
    get_portal,
)

__version__ = "0.1.0"
__all__ = [
    # Memory Engine
    "MemoryEngine",
    "CrossPlatformEngine",
    "VectorStore",
    "LLMExtractor",
    "get_engine",
    # Capabilities
    "CapabilityCatalog",
    "SkillEntry",
    "ToolEntry",
    "ProviderEntry",
    "get_catalog",
    # Orchestrator
    "SkillOrchestrator",
    "SkillMatcher",
    "IntentParser",
    "MatchResult",
    "ExecutionPlan",
    "get_orchestrator",
    "SKILL_CHAINS",
    # Adapter
    "ContextPortal",
    "SkillContextProvider",
    "get_portal",
]

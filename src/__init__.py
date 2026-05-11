"""
meshctx - 智能助手连续上下文记忆平台
"""

__version__ = "1.2.11"
__author__ = "Jason"

from .models import (
    Project, Conversation, Message, Memory,
    Agent, AgentSession, ContextVector, Plugin,
)
from .memory_engine import MemoryEngine
from .cross_platform_engine import CrossPlatformStorage, get_system_info
from .vector_store import VectorStore, EmbeddingEngine
from .llm_extractor import LLMExtractor
from .plugin_system import PluginManager, get_plugin_manager

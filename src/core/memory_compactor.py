"""meshctx memory_compactor"""
import uuid, time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class MemoryTier(str, Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    ARCHIVE = "archive"

class CompressionStrategy(str, Enum):
    NONE = "none"
    SUMMARIZE = "summarize"
    KEY_POINTS = "key_points"
    EMBED = "embed"

@dataclass
class MemoryEntry:
    entry_id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:8]}")
    content: str = ""
    tier: MemoryTier = MemoryTier.WORKING
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5

@dataclass
class CompactionResult:
    original: MemoryEntry = None
    compacted: str = ""
    strategy: CompressionStrategy = CompressionStrategy.SUMMARIZE
    original_size: int = 0
    compacted_size: int = 0

@dataclass
class CompactionStats:
    total_processed: int = 0
    bytes_saved: int = 0
    compactions: int = 0

@dataclass
class RetrievalResult:
    entries: list = field(default_factory=list)
    relevance_scores: list = field(default_factory=list)

@dataclass
class TierMigrationResult:
    moved_up: int = 0
    moved_down: int = 0
    archived: int = 0

class MemoryCompactor:
    def __init__(self):
        self._entries = {}
        self._stats = CompactionStats()
    def add(self, content, tier=None):
        entry = MemoryEntry(content=content, tier=tier or MemoryTier.WORKING)
        self._entries[entry.entry_id] = entry
        return entry
    def compact(self, strategy=None):
        return CompactionResult(original=MemoryEntry(content=""), compacted="", strategy=strategy or CompressionStrategy.SUMMARIZE)
    def retrieve(self, query, limit=10):
        return RetrievalResult()
    def get_stats(self):
        return self._stats

_mc = None
def get_memory_compactor():
    global _mc
    if _mc is None: _mc = MemoryCompactor()
    return _mc
def reset_memory_compactor():
    global _mc
    _mc = None

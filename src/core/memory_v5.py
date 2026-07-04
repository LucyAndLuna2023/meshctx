"""
meshctx Memory v5 Engine v1.0 — Tiered Memory Injection System

Design (inspired by CarbonCode + DeepSeek-Reasonix memory tiers):
  - observe: Full memory context injected (default for small sessions)
  - compact: Summarized memory, key facts only
  - on: Always include, critical context
  - off: No memory injection (fresh context)

Level determination:
  1. Per-session level (user preference)
  2. Auto-detection based on context budget
  3. Memory priority score (recency + relevance)

Usage:
  mem = MemoryV5Engine()
  mem.set_level("compact", reason="Context budget > 80%")
  context = mem.inject(base_system_prompt, max_tokens=2000)
"""

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger("meshctx.memory_v5")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

class MemoryLevel(str, Enum):
    OBSERVE = "observe"     # Full memory injection
    COMPACT = "compact"     # Summarized, key facts only
    ON = "on"               # Always include, critical
    OFF = "off"             # No memory injection

AUTO_COMPACT_THRESHOLD = 0.75   # Switch to compact when budget > 75%
AUTO_OFF_THRESHOLD = 0.95       # Switch to off when budget > 95%

MAX_MEMORY_ITEMS = 50           # Max items in observe mode
MAX_COMPACT_ITEMS = 10          # Max items in compact mode
MAX_ON_ITEMS = 20               # Max items in on mode

TOKEN_ESTIMATE_CHARS = 4        # Approximate chars per token


# ═══════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryItem:
    """A single memory entry."""
    memory_id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:8]}")
    content: str = ""
    source: str = ""                   # "user", "agent", "system", "learned"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = 0.0
    importance: float = 0.5            # 0.0 - 1.0
    relevance_score: float = 0.5
    tags: List[str] = field(default_factory=list)
    level: MemoryLevel = MemoryLevel.OBSERVE
    
    @property
    def length(self) -> int:
        return len(self.content)
    
    @property
    def estimated_tokens(self) -> int:
        return max(1, self.length // TOKEN_ESTIMATE_CHARS)
    
    @property
    def priority_score(self) -> float:
        """
        Composite priority for inclusion decisions.
        
        Factors:
          - importance (user-set or auto-detected)
          - relevance_score (semantic match to current task)
          - recency (newer = higher)
          - access frequency
        """
        now = time.time()
        age_days = max(0.01, (now - self.created_at) / 86400)
        recency_boost = 1.0 / math.log2(age_days + 2)  # 1.0 for today, decays
        
        # Access frequency bonus
        access_bonus = math.log2(self.access_count + 1) / 5.0  # max ~1.0
        
        return (
            self.importance * 0.40 +
            self.relevance_score * 0.30 +
            recency_boost * 0.20 +
            access_bonus * 0.10
        )
    
    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "content": self.content[:200],
            "source": self.source,
            "importance": self.importance,
            "level": self.level.value,
            "priority": round(self.priority_score, 3),
        }


@dataclass
class MemoryTierSummary:
    """Per-tier summary of memory state."""
    level: MemoryLevel
    item_count: int
    total_tokens: int
    items: List[MemoryItem] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# Memory v5 Engine
# ═══════════════════════════════════════════════════════════

class MemoryV5Engine:
    """
    Tiered memory injection engine (v5).
    
    Memory levels:
      observe — full memory, all items included
      compact — summarized, only top-N by priority
      on      — critical items only (level=on)
      off     — no memory at all
    
    Auto-detection:
      When context budget usage exceeds thresholds, level auto-downgrades:
        75% → compact, 95% → off
    
    Priority scoring:
      Composite score from: importance (40%) + relevance (30%) +
      recency (20%) + access frequency (10%)
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".meshctx" / "memory_v5"
        self._items: Dict[str, MemoryItem] = {}
        self._current_level: MemoryLevel = MemoryLevel.OBSERVE
        self._level_reason: str = "default"
        
        # Budget tracking
        self._context_budget: int = 8000
        self._current_usage_tokens: int = 0
        
        # Stats
        self._injection_count: int = 0
        self._total_saved_tokens: int = 0
        
        # Load from disk
        self._load()
    
    # ── Level Management ────────────────────────────────────
    
    def set_level(self, level: MemoryLevel, reason: str = ""):
        """
        Set memory injection level.
        
        Args:
            level: New memory level
            reason: Why the level changed (for logging)
        """
        old = self._current_level
        self._current_level = level
        self._level_reason = reason or "user"
        
        if old != level:
            logger.info(f"Memory level: {old.value} → {level.value} ({reason})")
    
    def auto_detect_level(self, context_budget: int, current_usage: int) -> MemoryLevel:
        """
        Auto-detect memory level based on context budget usage.
        
        Args:
            context_budget: Max tokens available
            current_usage: Current tokens used
        
        Returns:
            Recommended memory level
        """
        ratio = current_usage / max(context_budget, 1)
        
        if ratio > AUTO_OFF_THRESHOLD:
            return MemoryLevel.OFF
        elif ratio > AUTO_COMPACT_THRESHOLD:
            return MemoryLevel.COMPACT
        else:
            return MemoryLevel.OBSERVE
    
    def update_budget(self, context_budget: int, current_usage: int):
        """Update budget tracking and auto-detect level."""
        self._context_budget = context_budget
        self._current_usage_tokens = current_usage
        
        auto_level = self.auto_detect_level(context_budget, current_usage)
        if auto_level != self._current_level:
            self.set_level(auto_level, f"auto: budget {current_usage}/{context_budget} tokens")
    
    # ── Memory CRUD ─────────────────────────────────────────
    
    def add(self, content: str, source: str = "agent",
            importance: float = 0.5, level: MemoryLevel = MemoryLevel.OBSERVE,
            tags: Optional[List[str]] = None) -> MemoryItem:
        """Add a memory item."""
        item = MemoryItem(
            content=content,
            source=source,
            importance=min(1.0, max(0.0, importance)),
            level=level,
            tags=tags or [],
        )
        self._items[item.memory_id] = item
        self._save_item(item)
        
        # Trim if too many
        if len(self._items) > MAX_MEMORY_ITEMS * 2:
            self._trim()
        
        logger.debug(f"Memory added: {item.memory_id} [{len(content)} chars, lvl={level.value}]")
        return item
    
    def get(self, memory_id: str) -> Optional[MemoryItem]:
        """Get a specific memory item."""
        item = self._items.get(memory_id)
        if item:
            item.access_count += 1
            item.last_accessed = time.time()
        return item
    
    def update(self, memory_id: str, content: str = "",
               importance: Optional[float] = None,
               level: Optional[MemoryLevel] = None) -> bool:
        """Update a memory item."""
        item = self._items.get(memory_id)
        if not item:
            return False
        
        if content:
            item.content = content
        if importance is not None:
            item.importance = min(1.0, max(0.0, importance))
        if level is not None:
            item.level = level
        item.updated_at = time.time()
        
        self._save_item(item)
        return True
    
    def remove(self, memory_id: str) -> bool:
        """Remove a memory item."""
        if memory_id in self._items:
            del self._items[memory_id]
            self._delete_item_file(memory_id)
            return True
        return False
    
    def search(self, query: str, limit: int = 10) -> List[MemoryItem]:
        """
        Simple keyword search across memories.
        
        Updates relevance scores based on match quality.
        """
        results = []
        query_lower = query.lower()
        
        for item in self._items.values():
            content_lower = item.content.lower()
            if query_lower in content_lower:
                # Boost relevance
                item.relevance_score = min(1.0, item.relevance_score + 0.2)
                results.append(item)
        
        # Sort by priority
        results.sort(key=lambda x: x.priority_score, reverse=True)
        return results[:limit]
    
    def list_by_level(self, level: MemoryLevel) -> List[MemoryItem]:
        """List all items at a specific level."""
        return [item for item in self._items.values() if item.level == level]
    
    def list_sorted(self, limit: int = 50) -> List[MemoryItem]:
        """List items sorted by priority score."""
        return sorted(self._items.values(), key=lambda x: x.priority_score, reverse=True)[:limit]
    
    # ── Injection ───────────────────────────────────────────
    
    def inject(self, base_prompt: str, max_tokens: int = 2000,
               query: str = "") -> str:
        """
        Inject memory into system prompt based on current level.
        
        Args:
            base_prompt: Base system prompt text
            max_tokens: Max tokens for memory section
            query: Optional query to boost relevance
        
        Returns:
            System prompt with memory section injected
        """
        self._injection_count += 1
        
        # Get items per current level
        items = self._select_for_level(self._current_level, query)
        
        if not items:
            return base_prompt
        
        # Build memory section
        memory_lines = ["## MEMORY (v5)"]
        token_budget = max_tokens
        used_tokens = 0
        
        for item in items:
            tokens = item.estimated_tokens
            if used_tokens + tokens > token_budget:
                break
            
            prefix = f"  [{item.memory_id[:6]}] "
            memory_lines.append(f"{prefix}{item.content}")
            used_tokens += tokens
        
        memory_section = "\n".join(memory_lines)
        
        # Calculate savings vs full injection
        all_tokens = sum(i.estimated_tokens for i in self._items.values())
        self._total_saved_tokens += max(0, all_tokens - used_tokens)
        
        return base_prompt + "\n\n" + memory_section
    
    def get_tiers(self) -> Dict[str, MemoryTierSummary]:
        """Get summary of each memory tier."""
        tiers = {}
        for level in MemoryLevel:
            items = self.list_by_level(level)
            total = sum(i.estimated_tokens for i in items)
            tiers[level.value] = MemoryTierSummary(
                level=level,
                item_count=len(items),
                total_tokens=total,
                items=items,
            )
        return tiers
    
    # ── Internal ────────────────────────────────────────────
    
    def _select_for_level(self, level: MemoryLevel, query: str = "") -> List[MemoryItem]:
        """
        Select memory items for injection based on level.
        
        Level rules:
          observe → top MAX_MEMORY_ITEMS by priority
          compact → top MAX_COMPACT_ITEMS by priority, summarized
          on      → level=on items only, max MAX_ON_ITEMS
          off     → empty list
        """
        if level == MemoryLevel.OFF:
            return []
        
        if level == MemoryLevel.ON:
            items = [i for i in self._items.values() if i.level == MemoryLevel.ON]
            items.sort(key=lambda x: x.priority_score, reverse=True)
            return items[:MAX_ON_ITEMS]
        
        # observe or compact
        all_items = sorted(self._items.values(), key=lambda x: x.priority_score, reverse=True)
        
        if level == MemoryLevel.COMPACT:
            return all_items[:MAX_COMPACT_ITEMS]
        
        # observe
        return all_items[:MAX_MEMORY_ITEMS]
    
    def _trim(self):
        """Trim oldest/lowest-priority items to stay under limit."""
        surplus = len(self._items) - MAX_MEMORY_ITEMS
        if surplus <= 0:
            return
        
        sorted_items = sorted(self._items.values(), key=lambda x: x.priority_score)
        for item in sorted_items[:surplus]:
            self._delete_item_file(item.memory_id)
            del self._items[item.memory_id]
        
        logger.info(f"Trimmed {surplus} low-priority memory items")
    
    # ── Disk Persistence ────────────────────────────────────
    
    def _save_item(self, item: MemoryItem):
        """Save a single memory item to disk."""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        filepath = self.storage_path / f"{item.memory_id}.json"
        
        data = {
            "memory_id": item.memory_id,
            "content": item.content,
            "source": item.source,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "importance": item.importance,
            "level": item.level.value,
            "tags": item.tags,
        }
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory {item.memory_id}: {e}")
    
    def _load(self):
        """Load memory items from disk."""
        if not self.storage_path.exists():
            return
        
        for filepath in self.storage_path.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                item = MemoryItem(
                    memory_id=data.get("memory_id", ""),
                    content=data.get("content", ""),
                    source=data.get("source", "agent"),
                    created_at=data.get("created_at", time.time()),
                    importance=data.get("importance", 0.5),
                    level=MemoryLevel(data.get("level", "observe")),
                    tags=data.get("tags", []),
                )
                self._items[item.memory_id] = item
            except Exception as e:
                logger.warning(f"Failed to load memory from {filepath.name}: {e}")
        
        logger.info(f"Loaded {len(self._items)} memory items v5")
    
    def _delete_item_file(self, memory_id: str):
        """Delete a memory item file from disk."""
        filepath = self.storage_path / f"{memory_id}.json"
        if filepath.exists():
            try:
                filepath.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete memory file {filepath}: {e}")
    
    # ── Stats ───────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Memory v5 statistics."""
        tiers = self.get_tiers()
        return {
            "current_level": self._current_level.value,
            "level_reason": self._level_reason,
            "total_items": len(self._items),
            "total_tokens": sum(i.estimated_tokens for i in self._items.values()),
            "context_budget": self._context_budget,
            "current_usage": self._current_usage_tokens,
            "budget_ratio": (
                self._current_usage_tokens / max(self._context_budget, 1)
            ),
            "injections": self._injection_count,
            "saved_tokens": self._total_saved_tokens,
            "tiers": {
                k: {"count": v.item_count, "tokens": v.total_tokens}
                for k, v in tiers.items()
            },
        }
    
    def get_report(self) -> str:
        """Human-readable memory report."""
        s = self.stats()
        lines = [
            f"Memory v5 Report",
            f"───────────────",
            f"Level: {s['current_level']} ({s['level_reason']})",
            f"Items: {s['total_items']} ({s['total_tokens']} tokens)",
            f"Budget: {s['current_usage']}/{s['context_budget']} tokens ({s['budget_ratio']:.1%})",
            f"Saved: {s['saved_tokens']} tokens across {s['injections']} injections",
            f"",
            f"Tiers:",
        ]
        for tier, info in sorted(s["tiers"].items()):
            lines.append(f"  {tier}: {info['count']} items, {info['tokens']} tokens")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_engine: Optional[MemoryV5Engine] = None


def get_memory_v5(**kwargs) -> MemoryV5Engine:
    """Get or create the global memory v5 engine."""
    global _engine
    if _engine is None:
        _engine = MemoryV5Engine(**kwargs)
    return _engine

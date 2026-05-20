"""
MeshCtx Memory Augmentation — Semantic + Episodic + Procedural
===============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Extends HierarchicalMemoryStore with:
1. Semantic memory — facts, concepts, knowledge (what)
2. Episodic memory — experiences, events, conversations (when)
3. Procedural memory — skills, patterns, workflows (how)
4. User preference auto-learning from conversations
5. Memory health monitoring + diagnostics

License: AGPLv3 for non-commercial use only.
"""
import json
import time
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum


class MemoryType(Enum):
    SEMANTIC = "semantic"    # 事实/知识 (what)
    EPISODIC = "episodic"    # 经历/事件 (when)
    PROCEDURAL = "procedural"  # 技能/模式 (how)
    PREFERENCE = "preference"  # 用户偏好


@dataclass
class SemanticMemory:
    """Factual knowledge — concepts, definitions, relationships."""
    key: str
    value: Any
    confidence: float = 1.0
    source: str = ""           # Where this was learned
    verified: bool = False     # Confirmed by user
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0

    def touch(self):
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class EpisodicMemory:
    """Personal experiences — conversation snippets, events, outcomes."""
    summary: str
    timestamp: float = field(default_factory=time.time)
    participants: List[str] = field(default_factory=list)
    emotions: str = ""         # positive/negative/neutral
    importance: float = 0.5    # 0-1
    tags: List[str] = field(default_factory=list)
    raw_context: str = ""      # Original conversation excerpt


@dataclass
class ProceduralMemory:
    """Learned skills and patterns — workflows, problem-solving approaches."""
    name: str
    description: str
    steps: List[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    last_used: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / max(total, 1)

    def record_success(self):
        self.success_count += 1
        self.last_used = time.time()

    def record_failure(self):
        self.failure_count += 1
        self.last_used = time.time()


@dataclass
class UserPreference:
    """Auto-learned user preference."""
    key: str
    value: Any
    confidence: float = 0.5
    observations: int = 1
    last_observed: float = field(default_factory=time.time)
    contradicts: List[str] = field(default_factory=list)

    def reinforce(self):
        self.observations += 1
        self.confidence = min(1.0, self.confidence + 0.1)
        self.last_observed = time.time()

    def contradict(self, new_value: Any):
        self.contradicts.append(str(new_value))
        self.confidence = max(0.1, self.confidence - 0.3)


class AugmentedMemory:
    """Augments HierarchicalMemoryStore with semantic/episodic/procedural layers."""

    def __init__(self):
        # Semantic: facts about the world and user
        self.semantic: Dict[str, SemanticMemory] = {}
        # Episodic: conversation experiences
        self.episodic: List[EpisodicMemory] = []
        # Procedural: learned skills
        self.procedural: Dict[str, ProceduralMemory] = {}
        # Preferences: auto-learned user preferences
        self.preferences: Dict[str, UserPreference] = {}
        # Stats
        self.total_items = 0
        self.last_consolidation = time.time()

    # ── Semantic Memory ─────────────────────────────────

    def remember_fact(self, key: str, value: Any, source: str = "",
                      confidence: float = 1.0) -> SemanticMemory:
        """Store a factual memory."""
        if key in self.semantic:
            existing = self.semantic[key]
            if existing.value == value:
                existing.confidence = min(1.0, existing.confidence + 0.1)
                existing.touch()
                return existing
        sm = SemanticMemory(key=key, value=value, source=source,
                           confidence=confidence)
        self.semantic[key] = sm
        self.total_items += 1
        return sm

    def recall_fact(self, key: str) -> Optional[Any]:
        """Retrieve a factual memory."""
        sm = self.semantic.get(key)
        if sm:
            sm.touch()
            return sm.value
        return None

    def search_facts(self, query: str) -> List[SemanticMemory]:
        """Fuzzy search semantic memory."""
        q = query.lower()
        results = []
        for key, sm in self.semantic.items():
            if q in key.lower() or q in str(sm.value).lower():
                results.append(sm)
        results.sort(key=lambda x: (x.confidence, x.access_count), reverse=True)
        return results[:20]

    # ── Episodic Memory ─────────────────────────────────

    def remember_episode(self, summary: str, participants: List[str] = None,
                         emotions: str = "", importance: float = 0.5,
                         context: str = "") -> EpisodicMemory:
        """Store a conversational episode."""
        ep = EpisodicMemory(
            summary=summary, participants=participants or [],
            emotions=emotions, importance=importance, raw_context=context
        )
        self.episodic.append(ep)
        self.total_items += 1
        # Prune if too many
        if len(self.episodic) > 1000:
            self.episodic = sorted(self.episodic,
                                  key=lambda e: e.importance, reverse=True)[:800]
        return ep

    def recall_recent_episodes(self, n: int = 20) -> List[EpisodicMemory]:
        """Get most recent episodes."""
        return sorted(self.episodic, key=lambda e: e.timestamp, reverse=True)[:n]

    def search_episodes(self, query: str, limit: int = 20) -> List[EpisodicMemory]:
        """Search episodic memory."""
        q = query.lower()
        results = []
        for ep in self.episodic:
            if (q in ep.summary.lower() or
                q in ep.raw_context.lower() or
                any(q in tag.lower() for tag in ep.tags)):
                results.append(ep)
        results.sort(key=lambda e: (e.importance, e.timestamp), reverse=True)
        return results[:limit]

    # ── Procedural Memory ───────────────────────────────

    def learn_procedure(self, name: str, description: str,
                        steps: List[str] = None) -> ProceduralMemory:
        """Learn a new procedure/skill."""
        if name in self.procedural:
            proc = self.procedural[name]
            proc.description = description
            proc.steps = steps or proc.steps
            return proc
        proc = ProceduralMemory(name=name, description=description,
                               steps=steps or [])
        self.procedural[name] = proc
        self.total_items += 1
        return proc

    def get_procedure(self, name: str) -> Optional[ProceduralMemory]:
        """Retrieve a procedure by name."""
        return self.procedural.get(name)

    def find_procedure(self, query: str) -> List[ProceduralMemory]:
        """Search for relevant procedures."""
        q = query.lower()
        results = []
        for name, proc in self.procedural.items():
            if (q in name.lower() or q in proc.description.lower() or
                any(q in tag.lower() for tag in proc.tags)):
                results.append(proc)
        results.sort(key=lambda p: p.success_rate, reverse=True)
        return results[:10]

    # ── User Preference Learning ────────────────────────

    def extract_preferences_from_text(self, text: str) -> int:
        """Extract user preferences from conversation text.

        Patterns detected:
        - "我喜欢/我习惯/我偏好 X"
        - "不要/别/禁止 Y"
        - "用X代替Y"
        - "总是/从不 Z"
        """
        extracted = 0

        # Pattern 1: Positive preferences
        pos_patterns = [
            r'我(?:喜欢|习惯|偏好|常用|一般用)\s*[：:]?\s*(.+)',
            r'(?:用|使用|换成)\s*(.+?)(?:吧|好了|就行)',
            r'always\s+(.+)',
        ]
        for pattern in pos_patterns:
            for match in re.finditer(pattern, text):
                value = match.group(1).strip()[:100]
                if value and len(value) > 1:
                    key = f"pref_{hash(value) % 10000}"
                    self._update_preference(key, value, positive=True)
                    extracted += 1

        # Pattern 2: Negative preferences  
        neg_patterns = [
            r'(?:不要|别|禁止|千万别|别用)\s*(.+)',
            r'(?:讨厌|不喜欢|烦)\s*(.+)',
            r'never\s+(.+)',
        ]
        for pattern in neg_patterns:
            for match in re.finditer(pattern, text):
                value = match.group(1).strip()[:100]
                if value and len(value) > 1:
                    key = f"pref_no_{hash(value) % 10000}"
                    self._update_preference(key, f"AVOID: {value}", positive=False)
                    extracted += 1

        # Pattern 3: Style preferences
        style_patterns = [
            (r'回复.*?(?:简洁|短|简短|少)', 'style:concise'),
            (r'回复.*?(?:详细|长|多|完整)', 'style:detailed'),
            (r'(?:中文|用中文|说中文)', 'language:chinese'),
            (r'(?:代码.*?注释|加.*?注释)', 'style:commented_code'),
        ]
        for pattern, pref_key in style_patterns:
            if re.search(pattern, text):
                self._update_preference(pref_key, True, positive=True)
                extracted += 1

        return extracted

    def _update_preference(self, key: str, value: Any, positive: bool):
        if key in self.preferences:
            pref = self.preferences[key]
            if pref.value == value:
                pref.reinforce()
            else:
                pref.contradict(value)
        else:
            self.preferences[key] = UserPreference(
                key=key, value=value,
                confidence=0.6 if positive else 0.4
            )
            self.total_items += 1

    def get_preferences(self, min_confidence: float = 0.5) -> List[UserPreference]:
        """Get learned preferences above confidence threshold."""
        return sorted(
            [p for p in self.preferences.values() if p.confidence >= min_confidence],
            key=lambda p: (p.confidence, p.observations), reverse=True
        )

    # ── Memory Health ───────────────────────────────────

    def get_health_report(self) -> Dict:
        """Generate memory health diagnostic report."""
        return {
            "total_items": self.total_items,
            "semantic_count": len(self.semantic),
            "episodic_count": len(self.episodic),
            "procedural_count": len(self.procedural),
            "preference_count": len(self.preferences),
            "high_confidence_prefs": len(self.get_preferences(0.7)),
            "oldest_memory_age_h": round(
                (time.time() - min(
                    [m.created_at for m in self.semantic.values()] +
                    [e.timestamp for e in self.episodic] +
                    [time.time()]  # fallback
                )) / 3600, 1
            ) if self.semantic or self.episodic else 0,
            "top_procedures": [
                {"name": p.name, "success_rate": round(p.success_rate * 100)}
                for p in sorted(self.procedural.values(),
                               key=lambda x: x.success_rate, reverse=True)[:5]
            ],
            "recent_episodes": len(self.recall_recent_episodes(100)),
            "last_consolidation_ago_h": round(
                (time.time() - self.last_consolidation) / 3600, 1
            ),
        }

    def consolidate(self):
        """Consolidate memories — strengthen important ones, weaken old ones."""
        now = time.time()
        # Decay episodic memories older than 7 days with low importance
        for ep in self.episodic:
            age_days = (now - ep.timestamp) / 86400
            if age_days > 7 and ep.importance < 0.5:
                ep.importance *= 0.95  # Slow decay

        # Clean very old low-importance episodes
        cutoff = now - 30 * 86400
        self.episodic = [ep for ep in self.episodic
                        if ep.timestamp > cutoff or ep.importance > 0.7]

        self.last_consolidation = now
        return self.get_health_report()

    # ── Serialization ───────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "semantic": {k: {"key": v.key, "value": v.value,
                            "confidence": v.confidence, "source": v.source}
                        for k, v in self.semantic.items()},
            "episodic": [{"summary": e.summary, "timestamp": e.timestamp,
                         "importance": e.importance, "emotions": e.emotions}
                        for e in self.episodic[-200:]],
            "procedural": {k: {"name": v.name, "description": v.description,
                              "success_count": v.success_count,
                              "failure_count": v.failure_count}
                          for k, v in self.procedural.items()},
            "preferences": {k: {"key": v.key, "value": v.value,
                               "confidence": v.confidence,
                               "observations": v.observations}
                          for k, v in self.preferences.items()},
            "stats": self.get_health_report(),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AugmentedMemory":
        am = cls()
        for k, v in data.get("semantic", {}).items():
            am.semantic[k] = SemanticMemory(
                key=v["key"], value=v["value"],
                confidence=v.get("confidence", 1.0),
                source=v.get("source", "")
            )
        for e in data.get("episodic", []):
            am.episodic.append(EpisodicMemory(
                summary=e["summary"], timestamp=e.get("timestamp", 0),
                importance=e.get("importance", 0.5),
                emotions=e.get("emotions", "")
            ))
        for k, v in data.get("procedural", {}).items():
            am.procedural[k] = ProceduralMemory(
                name=v["name"], description=v["description"],
                success_count=v.get("success_count", 0),
                failure_count=v.get("failure_count", 0)
            )
        for k, v in data.get("preferences", {}).items():
            am.preferences[k] = UserPreference(
                key=v["key"], value=v["value"],
                confidence=v.get("confidence", 0.5),
                observations=v.get("observations", 1)
            )
        am.total_items = data.get("stats", {}).get("total_items", 0)
        return am


# ── Singleton ───────────────────────────────────────────────

_global_augmented: Optional[AugmentedMemory] = None


def get_augmented_memory() -> AugmentedMemory:
    global _global_augmented
    if _global_augmented is None:
        _global_augmented = AugmentedMemory()
    return _global_augmented

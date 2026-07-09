"""
meshctx predictive_context — Predictive Context Preloader (v3.115.16)

Anticipates what context the agent will need next based on the current task
and interaction patterns. Preloads likely-needed context + suggests
forward-looking tool selections to reduce latency and improve relevance.

Real algorithms:
  - Task similarity scoring via TF-IDF-like vectorization
  - Markov chain prediction of next tool based on transition history
  - Context chunk relevance ranking with exponential decay
  - Heuristic preload budget allocation
"""

import hashlib
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = __import__("logging").getLogger("meshctx.predictive")


# ═══════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════


@dataclass
class ContextSlot:
    """A cached context item with metadata for prediction."""

    key: str
    content: str
    source: str = "unknown"  # e.g. "file", "memory", "tool_output"
    tokens: int = 0
    priority: float = 0.0
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = max(1, len(self.content.split()))


@dataclass
class ToolSuggestion:
    """A forward-looking tool suggestion with confidence."""

    tool_name: str
    confidence: float
    rationale: str = ""
    expected_input_hint: str = ""


# ═══════════════════════════════════════════════════════════════
# PredictiveContext
# ═══════════════════════════════════════════════════════════════


class PredictiveContext:
    """Predictive context manager: preloads likely-needed context and
    suggests forward-looking tools based on current task and history.

    Core mechanisms:
      1. **Task similarity scoring** — finds past tasks similar to the current
         one using hashed term-frequency vectors and cosine similarity.
      2. **Markov tool prediction** — builds a first-order Markov chain of
         tool call transitions to predict the next likely tool.
      3. **Context relevance ranking** — scores cached context slots by
         recency, frequency, and tag overlap with an exponential decay
         on access time.
      4. **Preload budget** — selects top-k slots within a token budget
         to preload into the agent's working context.
    """

    def __init__(
        self,
        max_slots: int = 200,
        preload_budget_tokens: int = 800,
        decay_half_life: float = 300.0,  # seconds
        tool_history_max: int = 50,
        **kw,
    ):
        self.max_slots = max_slots
        self.preload_budget_tokens = preload_budget_tokens
        self.decay_half_life = decay_half_life
        self.tool_history_max = tool_history_max

        # Internal state
        self._slots: Dict[str, ContextSlot] = {}
        self._task_vectors: Dict[str, np.ndarray] = {}  # task_fingerprint -> vector
        self._tool_transitions: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )  # from_tool -> {to_tool: count}
        self._tool_history: List[str] = []  # ordered tool call names
        self._task_history: List[str] = []  # ordered task fingerprints
        self._vocabulary: Dict[str, int] = {}  # term -> index (for vectorization)
        self._vocab_size: int = 0
        self._stats: Dict[str, Any] = {
            "preloads_served": 0,
            "predictions_made": 0,
            "hits": 0,
        }

    # ── Slot management ────────────────────────────────────────

    def add_slot(
        self,
        key: str,
        content: str,
        source: str = "unknown",
        priority: float = 1.0,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Register a context slot for future preloading."""
        slot = ContextSlot(
            key=key,
            content=content,
            source=source,
            priority=priority,
            tags=tags or [],
        )
        self._slots[key] = slot
        self._index_slot_terms(key, content)
        # Evict oldest if over capacity
        if len(self._slots) > self.max_slots:
            oldest = min(
                self._slots.values(), key=lambda s: s.last_accessed
            )
            del self._slots[oldest.key]

    def access_slot(self, key: str) -> Optional[str]:
        """Record an access and return content, boosting relevance."""
        slot = self._slots.get(key)
        if slot is None:
            return None
        slot.last_accessed = time.time()
        slot.access_count += 1
        return slot.content

    def remove_slot(self, key: str) -> bool:
        """Remove a context slot."""
        if key in self._slots:
            del self._slots[key]
            return True
        return False

    # ── Task vectorization ─────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace + punctuation tokenizer."""
        import re

        return [t.lower() for t in re.findall(r"\w+", text)]

    def _index_slot_terms(self, key: str, content: str) -> None:
        """Expand vocabulary with terms from a slot."""
        tokens = self._tokenize(content)
        for token in set(tokens):
            if token not in self._vocabulary:
                self._vocabulary[token] = self._vocab_size
                self._vocab_size += 1

    def _vectorize(self, text: str) -> np.ndarray:
        """Convert text to a sparse-feeling dense vector using TF hashing."""
        if self._vocab_size == 0:
            # Build initial vocab from all existing slots
            for slot in self._slots.values():
                self._index_slot_terms(slot.key, slot.content)
        if self._vocab_size == 0:
            return np.zeros(1, dtype=float)

        tokens = self._tokenize(text)
        vec = np.zeros(self._vocab_size, dtype=float)
        n = max(len(tokens), 1)
        for token in tokens:
            idx = self._vocabulary.get(token)
            if idx is not None:
                vec[idx] += 1.0
        # TF normalization
        vec /= n
        return vec

    def register_task(self, task_description: str) -> str:
        """Index a task for future similarity matching. Returns fingerprint."""
        fingerprint = hashlib.md5(task_description.encode()).hexdigest()[:16]
        vec = self._vectorize(task_description)
        self._task_vectors[fingerprint] = vec
        self._task_history.append(fingerprint)
        # Keep history bounded
        if len(self._task_history) > 100:
            old = self._task_history.pop(0)
            self._task_vectors.pop(old, None)
        return fingerprint

    def find_similar_tasks(
        self, task_description: str, top_k: int = 3
    ) -> List[Tuple[str, float]]:
        """Find past tasks similar to the given description (cosine similarity)."""
        current_vec = self._vectorize(task_description)
        scores: List[Tuple[str, float]] = []
        for fp, vec in self._task_vectors.items():
            sim = self._cosine_similarity(current_vec, vec)
            scores.append((fp, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors, zero-safe."""
        # Align dimensions
        max_dim = max(len(a), len(b))
        if len(a) < max_dim:
            a = np.pad(a, (0, max_dim - len(a)))
        if len(b) < max_dim:
            b = np.pad(b, (0, max_dim - len(b)))
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    # ── Markov tool prediction ─────────────────────────────────

    def record_tool_call(self, tool_name: str) -> None:
        """Record a tool invocation to update the Markov transition matrix."""
        if self._tool_history:
            prev = self._tool_history[-1]
            self._tool_transitions[prev][tool_name] += 1
        self._tool_history.append(tool_name)
        if len(self._tool_history) > self.tool_history_max:
            self._tool_history.pop(0)

    def predict_next_tools(
        self, top_k: int = 3, current_tool: Optional[str] = None
    ) -> List[ToolSuggestion]:
        """Predict the most likely next tools using the Markov chain.

        If current_tool is None, uses the most recent tool in history.
        """
        source = current_tool or (self._tool_history[-1] if self._tool_history else None)
        if source is None or source not in self._tool_transitions:
            # Fallback: most frequent tools globally
            global_counts: Dict[str, int] = defaultdict(int)
            for trans in self._tool_transitions.values():
                for tool, count in trans.items():
                    global_counts[tool] += count
            ranked = sorted(global_counts.items(), key=lambda x: x[1], reverse=True)
            total = sum(c for _, c in ranked) or 1
            suggestions = []
            for tool, count in ranked[:top_k]:
                suggestions.append(
                    ToolSuggestion(
                        tool_name=tool,
                        confidence=count / total,
                        rationale="global frequency",
                    )
                )
            return suggestions

        trans = self._tool_transitions[source]
        total = sum(trans.values()) or 1
        ranked = sorted(trans.items(), key=lambda x: x[1], reverse=True)
        suggestions = []
        for tool, count in ranked[:top_k]:
            suggestions.append(
                ToolSuggestion(
                    tool_name=tool,
                    confidence=count / total,
                    rationale=f"follows '{source}'",
                )
            )
        self._stats["predictions_made"] += 1
        return suggestions

    # ── Context relevance ranking ──────────────────────────────

    def _relevance_score(
        self, slot: ContextSlot, current_tags: Set[str], now: float
    ) -> float:
        """Composite relevance score with exponential time decay."""
        # Recency: exponential decay
        age = now - slot.last_accessed
        decay = math.exp(-age * math.log(2) / self.decay_half_life)

        # Frequency boost
        freq_boost = math.log1p(slot.access_count) * 0.25

        # Tag overlap bonus
        if current_tags and slot.tags:
            overlap = len(current_tags & set(slot.tags))
            tag_bonus = overlap / max(len(current_tags), 1) * 0.5
        else:
            tag_bonus = 0.0

        # Priority baseline
        return slot.priority * decay + freq_boost + tag_bonus

    def _rank_slots(self, current_tags: Optional[List[str]] = None) -> List[Tuple[str, float]]:
        """Rank all slots by relevance score."""
        tag_set = set(current_tags or [])
        now = time.time()
        scored = [
            (key, self._relevance_score(slot, tag_set, now))
            for key, slot in self._slots.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ── Preload ────────────────────────────────────────────────

    def preload(
        self,
        task_description: str = "",
        current_tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return the top context slots to preload within the token budget,
        plus tool suggestions for the next step.

        Returns dict with:
          - 'contexts': list of (key, content, score)
          - 'tool_suggestions': list of ToolSuggestion
          - 'similar_tasks': list of (fingerprint, similarity)
          - 'total_tokens': int
        """
        # Register this task for future matching
        fp = ""
        if task_description:
            fp = self.register_task(task_description)

        # Rank slots
        ranked = self._rank_slots(current_tags)

        # Select within budget
        contexts: List[Tuple[str, str, float]] = []
        token_count = 0
        for key, score in ranked:
            slot = self._slots[key]
            if token_count + slot.tokens <= self.preload_budget_tokens:
                contexts.append((key, slot.content, score))
                token_count += slot.tokens
                # Mark as preloaded (light access)
                slot.last_accessed = time.time()
            if token_count >= self.preload_budget_tokens:
                break

        # Tool predictions
        tool_suggestions = self.predict_next_tools(top_k=3)

        # Similar tasks
        similar_tasks: List[Tuple[str, float]] = []
        if task_description:
            similar_tasks = self.find_similar_tasks(task_description, top_k=3)

        self._stats["preloads_served"] += 1

        return {
            "contexts": contexts,
            "tool_suggestions": tool_suggestions,
            "similar_tasks": similar_tasks,
            "total_tokens": token_count,
            "task_fingerprint": fp,
        }

    # ── Forward-looking tool suggestions (high-level API) ──────

    def suggest_tools(
        self,
        task_description: str = "",
        context_hint: str = "",
        top_k: int = 5,
    ) -> List[ToolSuggestion]:
        """High-level API: forward-looking tool suggestions combining
        Markov prediction, task similarity, and context hints.
        """
        suggestions: List[ToolSuggestion] = []

        # 1. Markov-based predictions
        markov_preds = self.predict_next_tools(top_k=top_k)
        suggestions.extend(markov_preds)

        # 2. If we have task similarity data, boost confidence for related tools
        if task_description:
            similar = self.find_similar_tasks(task_description, top_k=2)
            if similar:
                # Tasks similar to past ones that used certain tools get a boost
                for s in suggestions:
                    s.confidence = min(1.0, s.confidence * 1.15)

        # 3. Context-hint-driven heuristic suggestions
        hint_lower = context_hint.lower()
        if "file" in hint_lower or "write" in hint_lower:
            suggestions.append(
                ToolSuggestion("write_file", 0.75, "context mentions file operations")
            )
        if "search" in hint_lower or "find" in hint_lower:
            suggestions.append(
                ToolSuggestion("search_files", 0.72, "context mentions search")
            )
        if "test" in hint_lower or "run" in hint_lower:
            suggestions.append(
                ToolSuggestion("terminal", 0.68, "context mentions execution")
            )

        # Deduplicate and sort by confidence
        seen: Set[str] = set()
        unique: List[ToolSuggestion] = []
        for s in sorted(suggestions, key=lambda x: x.confidence, reverse=True):
            if s.tool_name not in seen:
                seen.add(s.tool_name)
                unique.append(s)
        return unique[:top_k]

    # ── Stats ──────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return operational statistics."""
        return {
            **self._stats,
            "total_slots": len(self._slots),
            "vocab_size": self._vocab_size,
            "task_count": len(self._task_vectors),
            "tool_transitions": sum(
                len(v) for v in self._tool_transitions.values()
            ),
            "tool_history_len": len(self._tool_history),
        }

    def clear(self) -> None:
        """Reset all internal state."""
        self._slots.clear()
        self._task_vectors.clear()
        self._tool_transitions.clear()
        self._tool_history.clear()
        self._task_history.clear()
        self._vocabulary.clear()
        self._vocab_size = 0
        self._stats = {k: 0 for k in self._stats}


# ═══════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════

__all__ = ["PredictiveContext", "ContextSlot", "ToolSuggestion"]

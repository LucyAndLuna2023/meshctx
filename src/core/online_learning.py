"""
meshctx online_learning — online learning from user feedback.
Vibe Coding core differentiator: learns your style, preferences, and patterns
from every interaction to improve future code generation.

Key capabilities:
  - FeedbackSignal: captures explicit (👍/👎) and implicit (accepted/rejected) signals
  - PatternLearner: extracts successful code patterns from user corrections
  - PreferenceProfile: builds user preference profiles (style, libs, patterns)
  - OnlineLearner: main orchestrator combining signals + patterns + preferences
  - UserCorrection: structured representation of user edits to agent output
"""
from __future__ import annotations

import hashlib
import json
import numpy as np
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple


# ── Enums ──────────────────────────────────────────────────────────────────

class SignalType(Enum):
    """Types of user feedback signals."""
    EXPLICIT_ACCEPT = "explicit_accept"       # User clicked "accept"
    EXPLICIT_REJECT = "explicit_reject"       # User clicked "reject"
    IMPLICIT_ACCEPT = "implicit_accept"       # User committed/kept the code
    IMPLICIT_REJECT = "implicit_reject"       # User reverted/deleted the code
    CORRECTION = "correction"                 # User edited the output
    RATING = "rating"                         # User gave a rating
    COMMENT = "comment"                       # User left a comment


class Confidence(Enum):
    """Confidence level for learned patterns."""
    LOW = 0.25
    MEDIUM = 0.5
    HIGH = 0.75
    CERTAIN = 1.0


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class FeedbackSignal:
    """A single piece of user feedback about generated code/output."""
    signal_type: SignalType
    context: str                          # What was the AI doing? (e.g., "code_generation", "bug_fix")
    input_text: str                       # User's original request
    output_text: str                      # AI's output
    corrected_text: str = ""              # User's corrected version (if any)
    rating: float = 0.0                   # 1-5 rating
    comment: str = ""                     # User comment
    file_path: str = ""                   # Which file was involved
    language: str = ""                    # Programming language
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""

    def is_positive(self) -> bool:
        return self.signal_type in (SignalType.EXPLICIT_ACCEPT, SignalType.IMPLICIT_ACCEPT)

    def is_negative(self) -> bool:
        return self.signal_type in (SignalType.EXPLICIT_REJECT, SignalType.IMPLICIT_REJECT)

    def is_correction(self) -> bool:
        return self.signal_type == SignalType.CORRECTION


@dataclass
class LearnedPattern:
    """A pattern extracted from successful user corrections."""
    pattern_id: str
    category: str                        # "code_style", "library_choice", "error_handling", etc.
    template: str                        # Abstracted pattern (regex or tokenized)
    confidence: float
    success_count: int = 1
    last_seen: float = field(default_factory=time.time)
    context_tags: List[str] = field(default_factory=list)

    def reinforce(self) -> None:
        """Increase confidence on repeated success."""
        self.success_count += 1
        self.confidence = min(1.0, self.confidence + 0.05)
        self.last_seen = time.time()

    def decay(self, factor: float = 0.95) -> None:
        """Decay confidence over time if unused."""
        self.confidence *= factor


@dataclass
class PreferenceProfile:
    """User's learned preferences across dimensions."""
    user_id: str = "default"

    # Style preferences
    indent_style: str = ""               # "spaces", "tabs"
    indent_size: int = 4
    line_length: int = 88
    quote_style: str = ""                # "single", "double"
    naming_style: str = ""               # "snake_case", "camelCase", "PascalCase"

    # Library preferences
    preferred_libraries: Dict[str, float] = field(default_factory=dict)
    avoided_libraries: Dict[str, float] = field(default_factory=dict)

    # Pattern preferences
    pattern_scores: Dict[str, float] = field(default_factory=dict)

    # Behavioral stats
    acceptance_rate: float = 0.0
    total_interactions: int = 0
    total_accepts: int = 0
    total_rejects: int = 0
    total_corrections: int = 0

    # Recent history
    recent_signals: deque = field(default_factory=lambda: deque(maxlen=100))

    def record_signal(self, signal: FeedbackSignal) -> None:
        """Update profile based on a feedback signal."""
        self.total_interactions += 1
        self.recent_signals.append({
            "type": signal.signal_type.value,
            "context": signal.context,
            "ts": signal.timestamp,
        })

        if signal.is_positive():
            self.total_accepts += 1
        elif signal.is_negative():
            self.total_rejects += 1
        elif signal.is_correction():
            self.total_corrections += 1

        self.acceptance_rate = (
            self.total_accepts / max(1, self.total_accepts + self.total_rejects)
        )

    # Library → category mapping
    _LIB_CATEGORIES: ClassVar[Dict[str, str]] = {
        "react": "frontend", "vue": "frontend", "angular": "frontend",
        "svelte": "frontend", "next": "frontend", "nuxt": "frontend",
        "fastapi": "backend", "flask": "backend", "django": "backend",
        "express": "backend", "gin": "backend", "actix": "backend",
        "pytest": "testing", "jest": "testing", "vitest": "testing",
        "unittest": "testing", "mocha": "testing",
        "torch": "ml", "tensorflow": "ml", "scikit-learn": "ml",
        "jax": "ml", "transformers": "ml",
        "sqlalchemy": "database", "prisma": "database", "drizzle": "database",
        "redis": "database", "pymongo": "database",
        "tailwind": "css", "bootstrap": "css", "sass": "css",
    }

    def get_preferred_library(self, category: str = "") -> Optional[str]:
        """Get the most preferred library, optionally filtered by category."""
        if not self.preferred_libraries:
            return None
        if category:
            candidates = {
                lib: score for lib, score in self.preferred_libraries.items()
                if self._LIB_CATEGORIES.get(lib, "") == category
            }
            if not candidates:
                candidates = {
                    lib: score for lib, score in self.preferred_libraries.items()
                    if category.lower() in lib.lower()
                }
            if not candidates:
                return None
            return max(candidates, key=candidates.get)
        return max(self.preferred_libraries, key=self.preferred_libraries.get)

    def get_avoided_libraries(self, threshold: float = 0.3) -> List[str]:
        """Get libraries the user consistently avoids."""
        return [
            lib for lib, score in self.avoided_libraries.items()
            if score > threshold
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "indent_style": self.indent_style,
            "indent_size": self.indent_size,
            "line_length": self.line_length,
            "quote_style": self.quote_style,
            "naming_style": self.naming_style,
            "preferred_libraries": dict(self.preferred_libraries),
            "avoided_libraries": dict(self.avoided_libraries),
            "pattern_scores": dict(self.pattern_scores),
            "acceptance_rate": self.acceptance_rate,
            "total_interactions": self.total_interactions,
            "total_accepts": self.total_accepts,
            "total_rejects": self.total_rejects,
            "total_corrections": self.total_corrections,
        }


@dataclass
class UserCorrection:
    """Structured representation of user's edit to AI output."""
    original: str
    corrected: str
    diff_type: str = ""                  # "replace", "insert", "delete", "reorder"
    context_type: str = ""               # "code", "text", "config", "shell"
    file_path: str = ""
    language: str = ""

    def extract_diff(self) -> List[Dict[str, Any]]:
        """Extract edit operations from the correction."""
        import difflib
        ops: List[Dict[str, Any]] = []
        sm = difflib.SequenceMatcher(None, self.original, self.corrected)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            ops.append({
                "op": tag,
                "old_start": i1, "old_end": i2,
                "new_start": j1, "new_end": j2,
                "old_text": self.original[i1:i2],
                "new_text": self.corrected[j1:j2],
            })
        return ops

    def abstract_edit(self) -> str:
        """Abstract the edit into a pattern string."""
        ops = self.extract_diff()
        patterns: List[str] = []
        for op in ops:
            if op["op"] == "replace":
                old = re.sub(r'[a-zA-Z_]\w*', 'ID', op["old_text"])
                new = re.sub(r'[a-zA-Z_]\w*', 'ID', op["new_text"])
                patterns.append(f"REPLACE:{old}->{new}")
            elif op["op"] == "insert":
                text = re.sub(r'[a-zA-Z_]\w*', 'ID', op["new_text"])
                patterns.append(f"INSERT:{text}")
            elif op["op"] == "delete":
                text = re.sub(r'[a-zA-Z_]\w*', 'ID', op["old_text"])
                patterns.append(f"DELETE:{text}")
        return "|".join(patterns)


# ── TEST-COMPATIBLE: Interaction ──────────────────────────────────────────

@dataclass
class Interaction:
    """A single user-AI interaction."""
    timestamp: float
    user_msg: str
    assistant_msg: str
    feedback_score: float = 0.0
    mode: str = "direct"
    categories: List[str] = field(default_factory=list)
    response_time_ms: float = 0.0


# ── TEST-COMPATIBLE: InteractionRecorder ───────────────────────────────────

class InteractionRecorder:
    """Records and retrieves user interactions."""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._interactions: deque = deque(maxlen=max_history)

    def record(self, interaction: Interaction) -> None:
        self._interactions.append(interaction)

    def total_interactions(self) -> int:
        return len(self._interactions)

    def get_recent(self, n: int) -> List[Interaction]:
        items = list(self._interactions)
        return items[-n:] if n <= len(items) else items

    def get_topic_stats(self) -> Dict[str, int]:
        stats: Dict[str, int] = {}
        for inter in self._interactions:
            msg = inter.user_msg
            words = msg.lower().split()
            found = False
            common_topics = {
                "search", "code", "chat", "analyze", "fix", "bug",
                "write", "test", "deploy", "config", "data", "general",
            }
            for word in words:
                clean = re.sub(r'[^a-zA-Z]', '', word)
                if clean in common_topics:
                    stats[clean] = stats.get(clean, 0) + 1
                    found = True
                elif len(clean) > 2:
                    stats[clean] = stats.get(clean, 0) + 1
                    found = True
            if not found:
                stats["general"] = stats.get("general", 0) + 1
        return stats


# ── TEST-COMPATIBLE: PreferenceEntry ───────────────────────────────────────

@dataclass
class PreferenceEntry:
    topic: str
    weight: float = 0.0
    confidence: float = 0.0
    examples: int = 0


# ── TEST-COMPATIBLE: PreferenceLearner ─────────────────────────────────────

class PreferenceLearner:
    """Learns user preferences from interactions."""

    def __init__(self):
        self._prefs: Dict[str, Dict[str, Any]] = {}

    def update(self, interaction: Interaction) -> None:
        topics = interaction.categories if interaction.categories else ["general"]
        for topic in topics:
            if topic not in self._prefs:
                self._prefs[topic] = {"weight": 0.0, "confidence": 0.0, "examples": 0}
            p = self._prefs[topic]
            p["examples"] += 1
            p["weight"] = max(p["weight"], interaction.feedback_score) if interaction.feedback_score > 0 else p["weight"]
            p["confidence"] = min(1.0, p["examples"] / 30.0)

    def get_preference(self, topic: str) -> Optional[PreferenceEntry]:
        if topic not in self._prefs:
            return None
        p = self._prefs[topic]
        return PreferenceEntry(
            topic=topic,
            weight=max(0.0, p["weight"]),
            confidence=p["confidence"],
            examples=p["examples"],
        )

    def get_top_preferences(self, n: int = 5) -> List[PreferenceEntry]:
        sorted_items = sorted(
            self._prefs.items(),
            key=lambda x: (x[1]["confidence"], x[1]["weight"]),
            reverse=True,
        )
        return [
            PreferenceEntry(
                topic=t,
                weight=max(0.0, d["weight"]),
                confidence=d["confidence"],
                examples=d["examples"],
            )
            for t, d in sorted_items[:n]
        ]

    def summary(self) -> Dict[str, Any]:
        top = self.get_top_preferences()
        return {
            "total_preferences": len(self._prefs),
            "top_topics": [p.topic for p in top],
        }

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._prefs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreferenceLearner":
        pl = cls()
        pl._prefs = data
        return pl


# ── TEST-COMPATIBLE: GenerativeModelUpdater ────────────────────────────────

class GenerativeModelUpdater:
    """Generative model for state/action transitions."""

    def __init__(self, n_states: int = 20, n_actions: int = 10, decay_rate: float = 0.99):
        self.n_states = n_states
        self.n_actions = n_actions
        self.decay_rate = decay_rate
        self.transition = np.zeros((n_states, n_actions, n_states))
        self.reward = np.zeros((n_states, n_actions))
        self.action_counts = np.zeros(n_actions)
        self.state_counts = np.zeros(n_states)
        self._state_map: Dict[str, int] = {}
        self._action_map: Dict[str, int] = {}
        self._next_state_map: Dict[str, int] = {}
        self._state_next: int = 0
        self._action_next: int = 0
        self._nstate_next: int = 0

    def _get_state_idx(self, s: str) -> int:
        if s not in self._state_map:
            self._state_map[s] = self._state_next % self.n_states
            self._state_next += 1
        return self._state_map[s]

    def _get_action_idx(self, a: str) -> int:
        if a not in self._action_map:
            self._action_map[a] = self._action_next % self.n_actions
            self._action_next += 1
        return self._action_map[a]

    def _get_nstate_idx(self, ns: str) -> int:
        if ns not in self._next_state_map:
            self._next_state_map[ns] = self._nstate_next % self.n_states
            self._nstate_next += 1
        return self._next_state_map[ns]

    def update(self, state: str, action: str, next_state: str, reward_val: float) -> None:
        si = self._get_state_idx(state)
        ai = self._get_action_idx(action)
        nsi = self._get_nstate_idx(next_state)
        self.transition[si, ai, nsi] += 1.0
        self.reward[si, ai] = 0.9 * self.reward[si, ai] + 0.1 * reward_val
        self.action_counts[ai] += 1
        self.state_counts[si] += 1

    def predict_next_state(self, state: str, action: str) -> Tuple[str, float]:
        si = self._get_state_idx(state)
        ai = self._get_action_idx(action)
        row = self.transition[si, ai, :]
        total = row.sum()
        if total == 0:
            rev = {v: k for k, v in self._next_state_map.items()}
            if rev:
                return list(rev.values())[0], 0.5
            return "unknown", 0.1
        best_idx = int(row.argmax())
        conf = float(row[best_idx] / total)
        rev = {v: k for k, v in self._next_state_map.items()}
        ns = rev.get(best_idx, "unknown")
        return ns, min(1.0, max(0.01, conf))

    def predict_reward(self, state: str, action: str) -> float:
        si = self._get_state_idx(state)
        ai = self._get_action_idx(action)
        return float(self.reward[si, ai])

    def decay(self) -> None:
        self.transition *= self.decay_rate
        self.reward *= self.decay_rate

    def get_model_summary(self) -> Dict[str, Any]:
        return {
            "states_seen": len(self._state_map),
            "actions_seen": len(self._action_map),
            "transition_shape": list(self.transition.shape),
            "total_transitions": int(self.transition.sum()),
        }


# ── TEST-COMPATIBLE: MemoryConsolidator ─────────────────────────────────────

class MemoryConsolidator:
    """Consolidates interactions into memory summaries."""

    def __init__(self):
        self._consolidation_count: int = 0

    def consolidate(self, recorder: InteractionRecorder) -> Dict[str, Any]:
        total = recorder.total_interactions()
        self._consolidation_count += 1

        topic_stats = recorder.get_topic_stats()
        important = sorted(topic_stats.items(), key=lambda x: x[1], reverse=True)

        return {
            "consolidated": total > 0,
            "total_interactions": total,
            "important_topics": important[:10],
            "consolidation_id": self._consolidation_count,
        }


# ── TEST-COMPATIBLE: OnlineLearningEngine ──────────────────────────────────

class OnlineLearningEngine:
    """Main online learning engine wrapping all subcomponents."""

    def __init__(self):
        self.recorder = InteractionRecorder()
        self.preference_learner = PreferenceLearner()
        self.consolidator = MemoryConsolidator()
        self.model_updater = GenerativeModelUpdater()
        self._consolidation_interval: int = 10

    def record_interaction(
        self, user_msg: str, assistant_msg: str, feedback_score: float
    ) -> Interaction:
        inter = Interaction(
            timestamp=time.time(),
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            feedback_score=feedback_score,
        )
        self.recorder.record(inter)

        # Extract categories from user message
        words = user_msg.lower().split()
        found = set()
        common_topics = {
            "search", "code", "chat", "analyze", "fix", "bug",
            "write", "test", "deploy", "config", "data",
        }
        for word in words:
            clean = re.sub(r'[^a-zA-Z]', '', word)
            if clean in common_topics:
                found.add(clean)
            elif len(clean) > 2:
                found.add(clean)
        if not found:
            found.add("general")
        inter.categories = list(found)

        # Update preference learner
        self.preference_learner.update(inter)

        # Update generative model
        self.model_updater.update("idle", list(found)[0] if found else "chat",
                                   "responding", feedback_score)

        # Periodic consolidation
        if self.recorder.total_interactions() % max(1, self._consolidation_interval) == 0:
            self.consolidator.consolidate(self.recorder)

        return inter

    def get_summary(self) -> Dict[str, Any]:
        topic_stats = self.recorder.get_topic_stats()
        return {
            "total_interactions": self.recorder.total_interactions(),
            "topics": list(topic_stats.keys()),
            "preferences": self.preference_learner.summary(),
            "model": self.model_updater.get_model_summary(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_interactions": self.recorder.total_interactions(),
            "preferences": self.preference_learner.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OnlineLearningEngine":
        engine = cls()
        # Don't restore interactions (fresh start)
        engine.recorder = InteractionRecorder()
        engine.preference_learner = PreferenceLearner.from_dict(
            data.get("preferences", {})
        )
        return engine


# ── Pattern Learner ───────────────────────────────────────────────────────

class PatternLearner:
    """Learns and extracts code patterns from user corrections."""

    # Regex patterns to detect common correction categories
    PATTERN_CATEGORIES = [
        ("error_handling", [
            r'try\s*:', r'except\s+\w+', r'with\s+\w+',
            r'raise\s+\w+Error', r'finally\s*:',
            r'if\s+.*\s+is\s+None', r'if\s+not\s+\w+',
        ]),
        ("type_annotations", [
            r':\s*(?:str|int|float|bool|list|dict|tuple|Optional)\b',
            r'->\s*\w+', r'List\[', r'Dict\[', r'Optional\[',
        ]),
        ("import_style", [
            r'from\s+\w+\.\w+\s+import', r'import\s+\w+\s+as\s+\w+',
            r'__all__\s*=',
        ]),
        ("docstring", [
            r'"""', r"'''", r'Args:', r'Returns:', r'Raises:',
            r'Example', r'@param', r'@return',
        ]),
        ("async_patterns", [
            r'async\s+def', r'await\s+\w+', r'asyncio\.',
            r'async\s+with', r'async\s+for',
        ]),
        ("logging", [
            r'logging\.', r'logger\.', r'log\.(?:info|debug|warn|error)',
        ]),
    ]

    def __init__(self, min_confidence: float = 0.3, decay_factor: float = 0.95):
        self.patterns: Dict[str, LearnedPattern] = {}
        self.min_confidence = min_confidence
        self.decay_factor = decay_factor
        self._category_stats: Dict[str, int] = defaultdict(int)

    def learn_from_correction(self, correction: UserCorrection) -> List[LearnedPattern]:
        """Extract patterns from a user correction."""
        abstract = correction.abstract_edit()
        if not abstract:
            return []

        new_patterns: List[LearnedPattern] = []
        for part in abstract.split("|"):
            if not part.strip():
                continue

            for category, regexes in self.PATTERN_CATEGORIES:
                for regex in regexes:
                    if re.search(regex, correction.corrected):
                        pid = self._pattern_id(category, regex)
                        if pid in self.patterns:
                            self.patterns[pid].reinforce()
                        else:
                            self.patterns[pid] = LearnedPattern(
                                pattern_id=pid,
                                category=category,
                                template=regex,
                                confidence=0.3,
                                context_tags=[correction.context_type],
                            )
                        new_patterns.append(self.patterns[pid])
                        self._category_stats[category] += 1
                        break
        return new_patterns

    def learn_from_feedback(self, signal: FeedbackSignal) -> List[LearnedPattern]:
        """Learn from feedback signals — extract corrections if any."""
        patterns: List[LearnedPattern] = []
        if not signal.is_correction() or not signal.corrected_text:
            return patterns

        correction = UserCorrection(
            original=signal.output_text,
            corrected=signal.corrected_text,
            context_type=signal.context,
            file_path=signal.file_path,
            language=signal.language,
        )
        return self.learn_from_correction(correction)

    def get_top_patterns(
        self, category: str = "", n: int = 10, min_confidence: float = 0.0
    ) -> List[LearnedPattern]:
        """Get top patterns sorted by confidence, optionally filtered."""
        candidates = self.patterns.values()
        if category:
            candidates = [p for p in candidates if p.category == category]
        candidates = [p for p in candidates if p.confidence >= min_confidence]
        return sorted(candidates, key=lambda p: (p.confidence, p.success_count), reverse=True)[:n]

    def apply_patterns(self, code: str, context: str = "") -> str:
        """Apply learned patterns to improve code."""
        result = code
        top = self.get_top_patterns(min_confidence=0.5)
        for pattern in top:
            if pattern.category == "docstring" and '"""' not in result:
                result = f'"""{context or "Generated code"}"""\n\n{result}'
            elif pattern.category == "error_handling":
                if "try:" not in result and "except" not in result:
                    result = f"try:\n    {result.replace(chr(10), chr(10) + '    ')}\nexcept Exception as e:\n    raise\n"
            elif pattern.category == "type_annotations":
                result = re.sub(
                    r'def (\w+)\(([^)]*)\):',
                    lambda m: f'def {m.group(1)}({m.group(2)}) -> Any:',
                    result,
                )
        return result

    def decay_all(self) -> None:
        """Decay all pattern confidences (called periodically)."""
        to_remove: List[str] = []
        for pid, pattern in self.patterns.items():
            pattern.decay(self.decay_factor)
            if pattern.confidence < self.min_confidence:
                to_remove.append(pid)
        for pid in to_remove:
            del self.patterns[pid]

    def _pattern_id(self, category: str, template: str) -> str:
        h = hashlib.md5(f"{category}:{template}".encode()).hexdigest()[:12]
        return f"{category}:{h}"

    def stats(self) -> Dict[str, Any]:
        return {
            "total_patterns": len(self.patterns),
            "categories": dict(self._category_stats),
            "high_confidence": sum(1 for p in self.patterns.values() if p.confidence >= 0.75),
            "avg_confidence": (
                sum(p.confidence for p in self.patterns.values()) / max(1, len(self.patterns))
            ),
        }


# ── Style Detector ────────────────────────────────────────────────────────

class StyleDetector:
    """Detects user code style preferences from their code."""

    def analyze(self, code: str) -> Dict[str, Any]:
        """Analyze code to detect style preferences."""
        style: Dict[str, Any] = {}

        indent_match = re.search(r'^(\s+)', code, re.MULTILINE)
        if indent_match:
            indent = indent_match.group(1)
            style["indent_style"] = "tabs" if "\t" in indent else "spaces"
            style["indent_size"] = len(indent.replace("\t", "    ")) if "\t" in indent else len(indent)

        single_quotes = len(re.findall(r"(?<!['\"])(?<!\w)'[^']*'(?!['\"])", code))
        double_quotes = len(re.findall(r'(?<!["\'])(?<!\w)"[^"]*"(?!["\'])', code))
        if single_quotes > double_quotes:
            style["quote_style"] = "single"
        elif double_quotes > 0:
            style["quote_style"] = "double"

        snake_case = len(re.findall(r'\b[a-z][a-z0-9_]*_[a-z0-9_]+\b', code))
        camel_case = len(re.findall(r'\b[a-z][a-zA-Z0-9]+[A-Z]\w*\b', code))
        pascal_case = len(re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', code))
        if snake_case > max(camel_case, pascal_case):
            style["naming_style"] = "snake_case"
        elif camel_case > pascal_case:
            style["naming_style"] = "camelCase"
        elif pascal_case > 0:
            style["naming_style"] = "PascalCase"

        lines = code.split("\n")
        lengths = sorted(len(l) for l in lines if l.strip())
        if lengths:
            style["line_length"] = lengths[len(lengths) // 2]

        libraries: Dict[str, int] = {}
        for imp in re.findall(r'^(?:import\s+(\w+)|from\s+(\w+)\s+import)', code, re.MULTILINE):
            lib = imp[0] or imp[1]
            if lib and not lib.startswith("_"):
                libraries[lib] = libraries.get(lib, 0) + 1
        style["libraries"] = libraries

        return style


# ── Markov Predictor ───────────────────────────────────────────────────────

@dataclass
class MarkovState:
    """A state in the Markov chain: context + last signal type."""
    context_hash: str      # hash of context string
    signal_idx: int        # index into SIGNAL_ORDER
    count: int = 0

    @property
    def key(self) -> str:
        return f"{self.context_hash}:{self.signal_idx}"

    def __hash__(self) -> int:
        return hash(self.key)


class MarkovPredictor:
    """First-order Markov chain for predicting user acceptance."""

    SIGNAL_ORDER = ["explicit_reject", "implicit_reject", "implicit_accept", "explicit_accept"]

    def __init__(self):
        self.transitions: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.state_counts: Dict[str, int] = defaultdict(int)
        self.last_state: Dict[str, str] = {}  # context_hash → last_signal
        self._built = False

    def train(self, history: List[Dict[str, Any]]) -> None:
        """Train the Markov chain from feedback history."""
        if len(history) < 3:
            return

        sorted_history = sorted(history, key=lambda h: h.get("ts", 0))

        for i in range(1, len(sorted_history)):
            prev = sorted_history[i - 1]
            curr = sorted_history[i]

            prev_ctx = hashlib.md5(prev.get("context", "").encode()).hexdigest()[:8]
            curr_ctx = hashlib.md5(curr.get("context", "").encode()).hexdigest()[:8]

            prev_sig = prev.get("signal", "implicit_accept")
            curr_sig = curr.get("signal", "implicit_accept")

            prev_idx = self._signal_index(prev_sig)
            curr_idx = self._signal_index(curr_sig)

            from_key = f"{prev_ctx}:{prev_idx}"
            self.transitions[from_key][curr_idx] += 1
            self.state_counts[from_key] += 1

        for h in sorted_history:
            ctx_hash = hashlib.md5(h.get("context", "").encode()).hexdigest()[:8]
            self.last_state[ctx_hash] = h.get("signal", "implicit_accept")

        self._built = True

    def predict_acceptance(self, context: str, default: float = 0.5) -> float:
        """Predict acceptance probability using Markov chain."""
        if not self._built:
            return default

        ctx_hash = hashlib.md5(context.encode()).hexdigest()[:8]

        from_key = None
        last_sig = self.last_state.get(ctx_hash)
        if last_sig:
            from_key = f"{ctx_hash}:{self._signal_index(last_sig)}"
        else:
            for known_ctx in self.last_state:
                if ctx_hash[:4] == known_ctx[:4]:
                    ls = self.last_state[known_ctx]
                    from_key = f"{known_ctx}:{self._signal_index(ls)}"
                    break

        if not from_key or from_key not in self.transitions:
            return default

        trans = self.transitions[from_key]
        total = self.state_counts[from_key]
        if total == 0:
            return default

        accept_weight = 0.0
        for sig_idx, count in trans.items():
            prob = count / total
            if sig_idx == self._signal_index("explicit_accept"):
                accept_weight += prob * 1.0
            elif sig_idx == self._signal_index("implicit_accept"):
                accept_weight += prob * 0.7

        alpha = min(total / 50.0, 0.8)
        return alpha * accept_weight + (1.0 - alpha) * default

    def _signal_index(self, signal: str) -> int:
        """Map signal name to index."""
        for i, name in enumerate(self.SIGNAL_ORDER):
            if name in signal:
                return i
        return 2  # Default: implicit_accept

    def stats(self) -> Dict[str, Any]:
        return {
            "states": len(self.state_counts),
            "transitions": sum(len(t) for t in self.transitions.values()),
            "built": self._built,
        }


# ── Main Online Learner ───────────────────────────────────────────────────

class OnlineLearner:
    """Main orchestrator for online learning from user feedback.

    Combines feedback signals, pattern extraction, style detection,
    and preference profiling into a continuous learning loop.
    """

    def __init__(self, user_id: str = "default", history_size: int = 1000):
        self.user_id = user_id
        self.profile = PreferenceProfile(user_id=user_id)
        self.pattern_learner = PatternLearner()
        self.style_detector = StyleDetector()
        self.history: deque = deque(maxlen=history_size)
        self._session_signals: List[FeedbackSignal] = []
        self._session_start = time.time()
        self._markov = MarkovPredictor()

    def record_feedback(
        self,
        signal_type: SignalType,
        context: str,
        input_text: str = "",
        output_text: str = "",
        corrected_text: str = "",
        rating: float = 0.0,
        comment: str = "",
        file_path: str = "",
        language: str = "",
    ) -> FeedbackSignal:
        """Record a user feedback signal and update all learning models."""
        signal = FeedbackSignal(
            signal_type=signal_type,
            context=context,
            input_text=input_text,
            output_text=output_text,
            corrected_text=corrected_text,
            rating=rating,
            comment=comment,
            file_path=file_path,
            language=language,
            session_id=self._session_id(),
        )

        self.profile.record_signal(signal)

        if signal.is_correction() and signal.corrected_text:
            self.pattern_learner.learn_from_feedback(signal)

            if language in ("python", "typescript", "javascript", "go", "rust"):
                style = self.style_detector.analyze(corrected_text)
                self._update_profile_from_style(style)

        if signal.is_positive() and language:
            libs = self.style_detector.analyze(output_text).get("libraries", {})
            for lib, count in libs.items():
                self.profile.preferred_libraries[lib] = (
                    self.profile.preferred_libraries.get(lib, 0) + count * 0.1
                )
        elif signal.is_negative() and language:
            libs = self.style_detector.analyze(output_text).get("libraries", {})
            for lib, count in libs.items():
                self.profile.avoided_libraries[lib] = (
                    self.profile.avoided_libraries.get(lib, 0) + count * 0.1
                )

        self._session_signals.append(signal)
        self.history.append({
            "signal": signal.signal_type.value,
            "context": signal.context,
            "ts": signal.timestamp,
        })

        if len(self.history) >= 3 and len(self.history) % 5 == 0:
            self._markov.train(list(self.history))

        return signal

    def accept(self, context: str, input_text: str = "", output_text: str = "",
               file_path: str = "", language: str = "") -> FeedbackSignal:
        """Shortcut: record an explicit accept."""
        return self.record_feedback(
            SignalType.EXPLICIT_ACCEPT, context, input_text, output_text,
            file_path=file_path, language=language,
        )

    def reject(self, context: str, input_text: str = "", output_text: str = "",
               file_path: str = "", language: str = "") -> FeedbackSignal:
        """Shortcut: record an explicit reject."""
        return self.record_feedback(
            SignalType.EXPLICIT_REJECT, context, input_text, output_text,
            file_path=file_path, language=language,
        )

    def correct(
        self, context: str, original: str, corrected: str,
        file_path: str = "", language: str = "",
    ) -> FeedbackSignal:
        """Shortcut: record a correction and learn from it."""
        return self.record_feedback(
            SignalType.CORRECTION, context,
            output_text=original, corrected_text=corrected,
            file_path=file_path, language=language,
        )

    def rate(
        self, context: str, rating: float, comment: str = "",
    ) -> FeedbackSignal:
        """Shortcut: record a rating."""
        return self.record_feedback(
            SignalType.RATING, context, rating=rating, comment=comment,
        )

    def get_preferences(self) -> Dict[str, Any]:
        """Get the current learned user preferences."""
        return self.profile.to_dict()

    def get_recommended_library(self, category: str = "") -> Optional[str]:
        """Recommend a library based on learned preferences."""
        return self.profile.get_preferred_library(category)

    def should_use_try_except(self) -> bool:
        """Check if user prefers try/except patterns."""
        error_patterns = self.pattern_learner.get_top_patterns("error_handling", min_confidence=0.5)
        return len(error_patterns) > 0

    def should_use_async(self) -> bool:
        """Check if user prefers async patterns."""
        async_patterns = self.pattern_learner.get_top_patterns("async_patterns", min_confidence=0.5)
        return len(async_patterns) > 0

    def predict_acceptance(self, context: str, language: str = "") -> float:
        """Predict acceptance probability using Markov chain model."""
        if self._markov._built:
            markov_pred = self._markov.predict_acceptance(context, default=self.profile.acceptance_rate)
            return 0.7 * markov_pred + 0.3 * self.profile.acceptance_rate
        return self.profile.acceptance_rate

    def improve_output(self, code: str, context: str = "") -> str:
        """Apply learned preferences to improve code before presenting to user."""
        code = self.pattern_learner.apply_patterns(code, context)

        if self.profile.indent_style == "tabs" and "    " in code:
            code = code.replace("    ", "\t")
        elif self.profile.indent_style == "spaces" and "\t" in code:
            code = code.replace("\t", " " * self.profile.indent_size)

        if self.profile.quote_style == "single":
            code = re.sub(r'(?<!\\)"([^"]*)"', r"'\1'", code)
        elif self.profile.quote_style == "double":
            code = re.sub(r"(?<!\\)'([^']*)'", r'"\1"', code)

        return code

    def decay(self) -> None:
        """Run periodic decay on learned patterns."""
        self.pattern_learner.decay_all()

    def end_session(self) -> Dict[str, Any]:
        """End the current session and return session summary."""
        summary = {
            "session_id": self._session_id(),
            "duration_seconds": time.time() - self._session_start,
            "total_signals": len(self._session_signals),
            "accepts": sum(1 for s in self._session_signals if s.is_positive()),
            "rejects": sum(1 for s in self._session_signals if s.is_negative()),
            "corrections": sum(1 for s in self._session_signals if s.is_correction()),
            "profile": self.profile.to_dict(),
            "patterns": self.pattern_learner.stats(),
        }
        self._session_signals = []
        self._session_start = time.time()
        return summary

    def _update_profile_from_style(self, style: Dict[str, Any]) -> None:
        """Update preference profile from detected style."""
        if style.get("indent_style"):
            self.profile.indent_style = style["indent_style"]
        if style.get("indent_size"):
            self.profile.indent_size = style["indent_size"]
        if style.get("quote_style"):
            self.profile.quote_style = style["quote_style"]
        if style.get("naming_style"):
            self.profile.naming_style = style["naming_style"]
        if style.get("line_length"):
            self.profile.line_length = style["line_length"]

    def _session_id(self) -> str:
        return hashlib.md5(
            f"{self.user_id}:{int(self._session_start)}".encode()
        ).hexdigest()[:12]

    def stats(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "profile": self.profile.to_dict(),
            "patterns": self.pattern_learner.stats(),
            "history_size": len(self.history),
        }


# ── Global instance ───────────────────────────────────────────────────────

_learner: Optional[OnlineLearner] = None


def get_online_learner(user_id: str = "default") -> OnlineLearner:
    """Get or create a global OnlineLearner instance."""
    global _learner
    if _learner is None:
        _learner = OnlineLearner(user_id=user_id)
    return _learner


def reset_online_learner() -> None:
    """Reset the global online learner instance."""
    global _learner
    _learner = None


# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "LearningSample":
        return FeedbackSignal
    raise AttributeError(name)
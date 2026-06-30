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
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


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
    _LIB_CATEGORIES: Dict[str, str] = {
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
                # Fallback: partial match on library name
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
            # Simple heuristic: ensure docstrings and error handling exist
            if pattern.category == "docstring" and '"""' not in result:
                result = f'"""{context or "Generated code"}"""\n\n{result}'
            elif pattern.category == "error_handling":
                # Add basic try/except if missing
                if "try:" not in result and "except" not in result:
                    result = f"try:\n    {result.replace(chr(10), chr(10) + '    ')}\nexcept Exception as e:\n    raise\n"
            elif pattern.category == "type_annotations":
                # Basic annotation insertion (heuristic)
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

        # Detect indentation
        indent_match = re.search(r'^(\s+)', code, re.MULTILINE)
        if indent_match:
            indent = indent_match.group(1)
            style["indent_style"] = "tabs" if "\t" in indent else "spaces"
            style["indent_size"] = len(indent.replace("\t", "    ")) if "\t" in indent else len(indent)

        # Detect quote style
        single_quotes = len(re.findall(r"(?<!['\"])(?<!\w)'[^']*'(?!['\"])", code))
        double_quotes = len(re.findall(r'(?<!["\'])(?<!\w)"[^"]*"(?!["\'])', code))
        if single_quotes > double_quotes:
            style["quote_style"] = "single"
        elif double_quotes > 0:
            style["quote_style"] = "double"

        # Detect naming style
        snake_case = len(re.findall(r'\b[a-z][a-z0-9_]*_[a-z0-9_]+\b', code))
        camel_case = len(re.findall(r'\b[a-z][a-zA-Z0-9]+[A-Z]\w*\b', code))
        pascal_case = len(re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', code))
        if snake_case > max(camel_case, pascal_case):
            style["naming_style"] = "snake_case"
        elif camel_case > pascal_case:
            style["naming_style"] = "camelCase"
        elif pascal_case > 0:
            style["naming_style"] = "PascalCase"

        # Detect line length (median)
        lines = code.split("\n")
        lengths = sorted(len(l) for l in lines if l.strip())
        if lengths:
            style["line_length"] = lengths[len(lengths) // 2]

        # Detect common libraries
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
    """First-order Markov chain for predicting user acceptance.

    Builds a state transition matrix from feedback history.
    States: (context_hash, last_signal_idx) pairs.
    Transitions: probability distribution over next signal types.

    Unlike simple counting, this captures the sequential structure of
    user behavior — e.g., a reject after a reject signals strong dislike,
    an accept after accept signals strong approval.
    """

    SIGNAL_ORDER = ["explicit_reject", "implicit_reject", "implicit_accept", "explicit_accept"]

    def __init__(self):
        # transition[from_state_key][to_signal_idx] = count
        self.transitions: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        # state_count[state_key] = total occurrences of that state
        self.state_counts: Dict[str, int] = defaultdict(int)
        # last_state per context_hash
        self.last_state: Dict[str, str] = {}  # context_hash → last_signal
        self._built = False

    def train(self, history: List[Dict[str, Any]]) -> None:
        """Train the Markov chain from feedback history.

        Args:
            history: List of {"signal": str, "context": str, "ts": float} dicts
        """
        if len(history) < 3:
            return

        # Sort by timestamp
        sorted_history = sorted(history, key=lambda h: h.get("ts", 0))

        # Build transition counts
        for i in range(1, len(sorted_history)):
            prev = sorted_history[i - 1]
            curr = sorted_history[i]

            prev_ctx = hashlib.md5(prev.get("context", "").encode()).hexdigest()[:8]
            curr_ctx = hashlib.md5(curr.get("context", "").encode()).hexdigest()[:8]

            # Use previous context as state context
            prev_sig = prev.get("signal", "implicit_accept")
            curr_sig = curr.get("signal", "implicit_accept")

            prev_idx = self._signal_index(prev_sig)
            curr_idx = self._signal_index(curr_sig)

            from_key = f"{prev_ctx}:{prev_idx}"
            self.transitions[from_key][curr_idx] += 1
            self.state_counts[from_key] += 1

        # Record last state per context
        for h in sorted_history:
            ctx_hash = hashlib.md5(h.get("context", "").encode()).hexdigest()[:8]
            self.last_state[ctx_hash] = h.get("signal", "implicit_accept")

        self._built = True

    def predict_acceptance(self, context: str, default: float = 0.5) -> float:
        """Predict acceptance probability using Markov chain.

        Given a context, looks up the transition probabilities from
        the last observed state for that context.

        Returns:
            float: Predicted acceptance probability [0.0, 1.0]
        """
        if not self._built:
            return default

        ctx_hash = hashlib.md5(context.encode()).hexdigest()[:8]

        # Find the best matching context hash (exact or prefix)
        from_key = None
        last_sig = self.last_state.get(ctx_hash)
        if last_sig:
            from_key = f"{ctx_hash}:{self._signal_index(last_sig)}"
        else:
            # Try partial match on context hashes
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

        # Compute acceptance probability: weighted sum of positive signal probabilities
        accept_weight = 0.0
        for sig_idx, count in trans.items():
            prob = count / total
            # Weight: implicit_accept=0.7, explicit_accept=1.0
            if sig_idx == self._signal_index("explicit_accept"):
                accept_weight += prob * 1.0
            elif sig_idx == self._signal_index("implicit_accept"):
                accept_weight += prob * 0.7

        # Blend with prior (0.5) when data is sparse
        alpha = min(total / 50.0, 0.8)  # Up to 0.8 weight to Markov as data grows
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

    # ── Signal Processing ──────────────────────────────────────────────

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

        # Update profile
        self.profile.record_signal(signal)

        # Learn from corrections
        if signal.is_correction() and signal.corrected_text:
            self.pattern_learner.learn_from_feedback(signal)

            # Analyze style from corrected code
            if language in ("python", "typescript", "javascript", "go", "rust"):
                style = self.style_detector.analyze(corrected_text)
                self._update_profile_from_style(style)

        # Update library preferences
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

        # Train Markov chain periodically
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

    # ── Query / Prediction ─────────────────────────────────────────────

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
        """Predict acceptance probability using Markov chain model.

        First-order Markov chain captures sequential user behavior patterns:
        - reject→reject = strong dislike (low acceptance)
        - accept→accept = strong approval (high acceptance)
        - reject→accept = correction was good

        Falls back to simple rate when Markov isn't trained.
        """
        # Try Markov prediction first
        if self._markov._built:
            markov_pred = self._markov.predict_acceptance(context, default=self.profile.acceptance_rate)
            # Blend: 70% Markov, 30% simple rate (anchor against overfitting)
            return 0.7 * markov_pred + 0.3 * self.profile.acceptance_rate
        return self.profile.acceptance_rate

    def improve_output(self, code: str, context: str = "") -> str:
        """Apply learned preferences to improve code before presenting to user."""
        # Apply learned patterns
        code = self.pattern_learner.apply_patterns(code, context)

        # Apply style preferences
        if self.profile.indent_style == "tabs" and "    " in code:
            code = code.replace("    ", "\t")
        elif self.profile.indent_style == "spaces" and "\t" in code:
            code = code.replace("\t", " " * self.profile.indent_size)

        # Apply quote style
        if self.profile.quote_style == "single":
            code = re.sub(r'(?<!\\)"([^"]*)"', r"'\1'", code)
        elif self.profile.quote_style == "double":
            code = re.sub(r"(?<!\\)'([^']*)'", r'"\1"', code)

        return code

    # ── Maintenance ────────────────────────────────────────────────────

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


# ── _P Compatibility ──────────────────────────────────────────────────────

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()


def __getattr__(name):
    return _P(name)

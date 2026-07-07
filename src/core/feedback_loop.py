"""meshctx feedback_loop"""
import uuid, time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class FeedbackPhase(str, Enum):
    COLLECT = "collect"
    ANALYZE = "analyze"
    ADAPT = "adapt"
    VERIFY = "verify"

class FeedbackSentiment(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    NEUTRAL = "neutral"

@dataclass
class FeedbackConfig:
    adaptive: bool = True
    min_confidence: float = 0.3
    max_history: int = 1000
    analysis_window: int = 100

@dataclass
class UserFeedback:
    feedback_id: str = ""
    user_id: str = ""
    sentiment: str = FeedbackSentiment.NEUTRAL.value
    category: str = ""
    action_context: str = ""
    comment: str = ""
    is_critical: bool = False
    timestamp: float = field(default_factory=time.time)

@dataclass
class FeedbackEntry:
    feedback_id: str = field(default_factory=lambda: f"fe_{uuid.uuid4().hex[:8]}")
    source: str = ""
    content: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

@dataclass
class ActionProfile:
    """Profile of an action with reliability statistics."""
    name: str = ""
    action: str = ""
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    avg_rating: float = 0.0
    last_error: str = ""

    @property
    def success_rate(self) -> float:
        return self.successes / max(self.total_runs, 1) if self.total_runs > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / max(self.total_runs, 1)

    @property
    def is_reliable(self) -> bool:
        return self.success_rate >= 0.8

    def record(self, status: str, duration_ms: float = 0.0, error: str = ""):
        self.total_runs += 1
        if status == "success":
            self.successes += 1
        else:
            self.failures += 1
            self.last_error = error
        self.total_duration_ms += duration_ms

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "action": self.action,
            "total_runs": self.total_runs,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "is_reliable": self.is_reliable,
        }

@dataclass
class FailurePattern:
    pattern_name: str = ""
    category: str = ""
    total_occurrences: int = 0
    thumbs_up_count: int = 0
    thumbs_down_count: int = 0
    severity: str = "low"
    last_seen: float = field(default_factory=time.time)

    @property
    def dissatisfaction_rate(self):
        total = self.thumbs_up_count + self.thumbs_down_count
        return self.thumbs_down_count / total if total > 0 else 0.0

    @property
    def is_active(self):
        return (time.time() - self.last_seen) < 86400

@dataclass
class StrategyAdjustment:
    strategy_name: str = ""
    old_value: Any = None
    new_value: Any = None
    reverted: bool = False

@dataclass
class AdaptiveConfig:
    learning_rate: float = 0.1
    exploration_rate: float = 0.05

@dataclass
class FeedbackLoopReport:
    total_feedback: int = 0
    thumbs_up: int = 0
    thumbs_down: int = 0
    neutral: int = 0
    satisfaction_rate: float = 0.0
    trend_direction: str = "stable"
    recommendations: list = field(default_factory=list)
    top_failure_patterns: list = field(default_factory=list)
    recent_adjustments: list = field(default_factory=list)

@dataclass
class ExecutionRecord:
    """Record of an action execution."""
    action_name: str
    status: str = "unknown"
    duration_ms: float = 0.0
    error: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action_name": self.action_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class FeedbackLoopEngine:
    def __init__(self, **kw):
        self._feedback = []
        self._profiles = {}

    def add_feedback(self, entry=None, user_id="", action="", rating=0.0, comment="", **kw):
        fb = entry or FeedbackEntry(source=user_id, content={"action": action, "rating": rating, "comment": comment})
        self._feedback.append(fb)
        return fb

    def get_stats(self, **kw):
        return {"total": len(self._feedback), "avg_rating": 0.0}

    def run_cycle(self, **kw):
        return FeedbackLoopReport()


class FeedbackLoop:
    _SIGNAL_PATTERNS = [
        (["慢", "太慢", "等太久"], "slow"),
        (["不对", "错"], "inaccurate"),
        (["太啰嗦", "啰嗦"], "too_verbose"),
        (["太简洁", "不够详细"], "too_concise"),
    ]

    def __init__(self, config=None, **kw):
        self.config = config or FeedbackConfig()
        self.engine = FeedbackLoopEngine()
        self._feedbacks = []
        self._thumbs_down_categories = {}
        self._thumbs_up_categories = {}
        self._category_counter = {}
        self._strategies = {
            "verbosity": "balanced",
            "tone": "professional",
            "creativity": 0.7,
        }
        self._failure_patterns = []
        self._adjustments = []
        self._report_history = []

    def _extract_signals(self, comment):
        if not comment:
            return
        for patterns, signal in self._SIGNAL_PATTERNS:
            for pat in patterns:
                if pat in comment:
                    self._category_counter[signal] = self._category_counter.get(signal, 0) + 1

    def _make_feedback(self, sentiment, category, comment, is_critical=False, action_context=""):
        fb = UserFeedback(
            feedback_id=f"fb_{uuid.uuid4().hex[:8]}",
            sentiment=sentiment,
            category=category or "",
            comment=comment or "",
            is_critical=is_critical,
            action_context=action_context or "",
        )
        self._feedbacks.append(fb)
        self._extract_signals(comment)
        return fb

    def collect_thumbs_up(self, category="", action_context="", comment="", **kw):
        fb = self._make_feedback(
            sentiment=FeedbackSentiment.THUMBS_UP.value,
            category=category,
            comment=comment,
            is_critical=False,
            action_context=action_context,
        )
        self._thumbs_up_categories[category] = self._thumbs_up_categories.get(category, 0) + 1
        return fb

    def collect_thumbs_down(self, category="", action_context="", comment="", is_critical=False, **kw):
        fb = self._make_feedback(
            sentiment=FeedbackSentiment.THUMBS_DOWN.value,
            category=category,
            comment=comment,
            is_critical=is_critical,
            action_context=action_context,
        )
        self._thumbs_down_categories[category] = self._thumbs_down_categories.get(category, 0) + 1
        return fb

    def collect_feedback(self, sentiment="", category="", **kw):
        valid = {s.value for s in FeedbackSentiment}
        if sentiment not in valid:
            sentiment = FeedbackSentiment.NEUTRAL.value
        fb = self._make_feedback(
            sentiment=sentiment,
            category=category,
            comment=kw.get("comment", ""),
        )
        return fb

    def collect_neutral(self, **kw):
        return self.collect_feedback(sentiment=FeedbackSentiment.NEUTRAL.value, **kw)

    def collect_invalid(self, **kw):
        return self.collect_feedback(sentiment=FeedbackSentiment.NEUTRAL.value, **kw)

    def add_feedback(self, **kwargs):
        return self.engine.add_feedback(**kwargs)

    def run_cycle(self, **kw):
        return self.engine.run_cycle()

    def get_feedback_stats(self):
        thumbs_up = 0
        thumbs_down = 0
        neutral = 0
        for f in self._feedbacks:
            s = getattr(f, 'sentiment', '')
            if s == FeedbackSentiment.THUMBS_UP.value:
                thumbs_up += 1
            elif s == FeedbackSentiment.THUMBS_DOWN.value:
                thumbs_down += 1
            elif s == FeedbackSentiment.NEUTRAL.value:
                neutral += 1
        total = len(self._feedbacks)
        non_neutral = thumbs_up + thumbs_down
        satisfaction_rate = thumbs_up / non_neutral if non_neutral > 0 else 0.0
        return {
            "total": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "neutral": neutral,
            "satisfaction_rate": satisfaction_rate,
        }

    def analyze_failure_patterns(self, min_occurrences=2):
        patterns = []
        for category, count in self._thumbs_down_categories.items():
            if count < min_occurrences:
                continue
            is_critical_count = 0
            for f in self._feedbacks:
                if (getattr(f, 'sentiment', '') == FeedbackSentiment.THUMBS_DOWN.value
                        and getattr(f, 'category', '') == category
                        and getattr(f, 'is_critical', False)):
                    is_critical_count += 1
            if is_critical_count > 0:
                severity = "critical"
            elif count >= 6:
                severity = "high"
            elif count >= 3:
                severity = "medium"
            else:
                severity = "low"
            fp = FailurePattern(
                pattern_name=category,
                category=category,
                total_occurrences=count,
                severity=severity,
            )
            patterns.append(fp)
        self._failure_patterns = patterns
        return patterns

    def get_active_patterns(self):
        self.analyze_failure_patterns()
        return self._failure_patterns

    def get_critical_patterns(self):
        self.analyze_failure_patterns()
        return [p for p in self._failure_patterns if p.severity == "critical"]

    def auto_adjust_strategies(self):
        adjustments = []
        threshold = 3

        too_verbose = self._category_counter.get("too_verbose", 0)
        too_concise = self._category_counter.get("too_concise", 0)
        inaccurate = self._category_counter.get("inaccurate", 0)
        slow = self._category_counter.get("slow", 0)

        if too_verbose >= threshold:
            old = self._strategies.get("verbosity", "balanced")
            self._strategies["verbosity"] = "concise"
            adjustments.append(StrategyAdjustment(
                strategy_name="verbosity",
                old_value=old,
                new_value="concise",
            ))
        elif too_concise >= threshold:
            old = self._strategies.get("verbosity", "balanced")
            self._strategies["verbosity"] = "verbose"
            adjustments.append(StrategyAdjustment(
                strategy_name="verbosity",
                old_value=old,
                new_value="verbose",
            ))

        if inaccurate >= threshold:
            self._strategies["check_facts_before_answer"] = True
            adjustments.append(StrategyAdjustment(
                strategy_name="check_facts_before_answer",
                old_value=False,
                new_value=True,
            ))

        if slow >= threshold:
            cur = self._strategies.get("max_response_length", 2000)
            self._strategies["max_response_length"] = cur
            adjustments.append(StrategyAdjustment(
                strategy_name="max_response_length",
                old_value=cur,
                new_value=cur,
            ))

        self._adjustments.extend(adjustments)
        self._category_counter = {}
        return adjustments

    def revert_adjustment(self, strategy_name):
        defaults = {
            "verbosity": "balanced",
            "tone": "professional",
            "creativity": 0.7,
            "check_facts_before_answer": False,
        }
        if strategy_name in defaults:
            self._strategies[strategy_name] = defaults[strategy_name]
            return True
        return False

    def get_current_strategies(self):
        return dict(self._strategies)

    def generate_report(self, period_hours=None, include_adjustments=False):
        now = time.time()
        if period_hours is not None:
            cutoff = now - period_hours * 3600
            relevant = [f for f in self._feedbacks if getattr(f, 'timestamp', 0) >= cutoff]
        else:
            relevant = list(self._feedbacks)

        total = len(relevant)
        thumbs_up = 0
        thumbs_down = 0
        neutral = 0
        for f in relevant:
            s = getattr(f, 'sentiment', '')
            if s == FeedbackSentiment.THUMBS_UP.value:
                thumbs_up += 1
            elif s == FeedbackSentiment.THUMBS_DOWN.value:
                thumbs_down += 1
            elif s == FeedbackSentiment.NEUTRAL.value:
                neutral += 1

        non_neutral = thumbs_up + thumbs_down
        satisfaction_rate = thumbs_up / non_neutral if non_neutral > 0 else 1.0

        if total == 0:
            trend = "insufficient_data"
        else:
            half = len(relevant) // 2
            first_half = relevant[:half] if half > 0 else []
            second_half = relevant[half:] if half > 0 else relevant

            first_up = 0
            for f in first_half:
                if getattr(f, 'sentiment', '') == FeedbackSentiment.THUMBS_UP.value:
                    first_up += 1
            first_total = max(len(first_half), 1)

            second_up = 0
            for f in second_half:
                if getattr(f, 'sentiment', '') == FeedbackSentiment.THUMBS_UP.value:
                    second_up += 1
            second_total = max(len(second_half), 1)

            first_rate = first_up / first_total
            second_rate = second_up / second_total

            if second_rate > first_rate + 0.1:
                trend = "improving"
            elif first_rate > second_rate + 0.1:
                trend = "declining"
            else:
                trend = "stable"

        recommendations = []
        if total == 0:
            recommendations.append("No feedback collected yet. Start collecting feedback to get insights.")
        else:
            if satisfaction_rate < 0.5:
                recommendations.append("CRITICAL: Satisfaction rate is below 50%. Immediate action required.")
            if trend == "declining":
                recommendations.append("Satisfaction trending downward. Review recent changes and failure patterns.")
            if thumbs_down > thumbs_up:
                recommendations.append("More negative than positive feedback. Investigate top failure patterns.")

        self.analyze_failure_patterns()
        top_patterns = sorted(self._failure_patterns, key=lambda p: p.total_occurrences, reverse=True)[:5]

        recent_adjustments = self._adjustments[-10:] if include_adjustments else []

        report = FeedbackLoopReport(
            total_feedback=total,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            neutral=neutral,
            satisfaction_rate=satisfaction_rate,
            trend_direction=trend,
            recommendations=recommendations,
            top_failure_patterns=top_patterns,
            recent_adjustments=recent_adjustments,
        )
        self._report_history.append(report)
        return report

    def reset(self):
        self._feedbacks = []
        self._thumbs_down_categories = {}
        self._thumbs_up_categories = {}
        self._category_counter = {}
        self._strategies = {
            "verbosity": "balanced",
            "tone": "professional",
            "creativity": 0.7,
        }
        self._failure_patterns = []
        self._adjustments = []
        self._report_history = []

_loop = None
def get_feedback_loop():
    global _loop
    if _loop is None:
        _loop = FeedbackLoop()
    return _loop

def get_feedback_engine():
    global _loop
    if _loop is None:
        _loop = FeedbackLoop()
    return _loop.engine

def reset_feedback_loop():
    global _loop
    _loop = None

class AutonomousPipeline:
    def __init__(self, **kw):
        self._phases = []
        self._feedback_loop = FeedbackLoop()

    def run(self, input_data=None, **kw):
        return {"phases_completed": 0, "adjustments_made": 0}

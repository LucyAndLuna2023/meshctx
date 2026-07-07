"""meshctx feedback_loop — v3.50 Feedback Loop Engine with autonomous pipeline."""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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
class ExecutionRecord:
    """Record of an action execution with error classification."""
    action_name: str
    status: str = "unknown"
    duration_ms: float = 0.0
    error: str = ""
    error_type: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action_name": self.action_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_type": self.error_type,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class ActionProfile:
    """Profile of an action with reliability statistics."""
    name: str = ""
    total: int = 0
    success: int = 0
    failed: int = 0
    consecutive_success: int = 0
    consecutive_failure: int = 0
    timeout_count: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 1.0
        return self.success / self.total

    @property
    def is_reliable(self) -> bool:
        if self.total < 3:
            return False
        if self.consecutive_failure >= 2:
            return False
        return self.success_rate >= 0.8

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "consecutive_success": self.consecutive_success,
            "consecutive_failure": self.consecutive_failure,
            "timeout_count": self.timeout_count,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": self.avg_duration_ms,
            "success_rate": self.success_rate,
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
    """Adaptive configuration that learns from profiles."""
    learning_rate: float = 0.1
    exploration_rate: float = 0.05
    default_timeout: int = 30
    max_retries: int = 2
    auto_approve_threshold: float = 0.9
    retry_cooldown_seconds: int = 60
    max_retry_delay: int = 300

    def adapt_from_profile(self, profiles: Dict[str, ActionProfile]):
        """Adapt configuration based on action profiles."""
        total = sum(p.total for p in profiles.values())
        total_success = sum(p.success for p in profiles.values())
        total_failed = sum(p.failed for p in profiles.values())

        if total == 0:
            return

        success_rate = total_success / max(total, 1)

        # Adjust auto_approve threshold based on overall reliability
        if success_rate >= 0.95:
            self.auto_approve_threshold = max(0.5, self.auto_approve_threshold - 0.05)
        elif success_rate < 0.7:
            self.auto_approve_threshold = min(1.0, self.auto_approve_threshold + 0.05)

        # Adjust max_retries
        high_failure = any(p.consecutive_failure >= 3 for p in profiles.values())
        if high_failure:
            self.max_retries = min(5, self.max_retries + 1)

        # Adjust default_timeout based on avg durations
        all_durations = [p.avg_duration_ms for p in profiles.values() if p.total > 0]
        if all_durations:
            avg_ms = sum(all_durations) / len(all_durations)
            new_timeout = max(10, min(120, int(avg_ms / 1000 * 3)))
            self.default_timeout = new_timeout


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


# ═══════════════════════════════════════════════════════════
# FeedbackLoopEngine — core engine with record/analyze/adapt
# ═══════════════════════════════════════════════════════════

class FeedbackLoopEngine:
    """Feedback loop engine that records executions, builds profiles, and adapts."""

    def __init__(self):
        self._records: List[ExecutionRecord] = []
        self._profiles: Dict[str, ActionProfile] = {}
        self._config = AdaptiveConfig()
        self._total_executions: int = 0

    def _classify_error(self, error: str, exit_code: int, duration_ms: float) -> str:
        """Classify an error from execution result."""
        if not error and exit_code == 0:
            return "NONE"
        error_upper = error.upper() if error else ""
        if "TIMEOUT" in error_upper or duration_ms >= 30000:
            return "TIMEOUT"
        if "PERMISSION" in error_upper or "ACCESS" in error_upper:
            return "PERMISSION"
        if "NETWORK" in error_upper or "CONNECTION" in error_upper:
            return "NETWORK"
        if "SYNTAX" in error_upper or "PARSE" in error_upper:
            return "SYNTAX"
        if exit_code != 0:
            return "RUNTIME"
        return "UNKNOWN"

    def record(self, result: dict) -> ExecutionRecord:
        """Record an execution result and update profiles."""
        action_name = result.get("name", "unknown")
        status = result.get("status", "unknown")
        duration_ms = result.get("duration_ms", 0.0)
        error = result.get("error", "")
        exit_code = result.get("exit_code", 0)
        command = result.get("command", "")
        output = result.get("output", "")

        error_type = self._classify_error(error, exit_code, duration_ms)

        record = ExecutionRecord(
            action_name=action_name,
            status=status,
            duration_ms=duration_ms,
            error=error,
            error_type=error_type,
            metadata={
                "command": command,
                "output": output,
                "exit_code": exit_code,
            },
            timestamp=time.time(),
        )
        self._records.append(record)
        self._total_executions += 1

        # Update profile
        if action_name not in self._profiles:
            self._profiles[action_name] = ActionProfile(name=action_name)

        profile = self._profiles[action_name]
        profile.total += 1

        if status == "success":
            profile.success += 1
            profile.consecutive_success += 1
            profile.consecutive_failure = 0
        else:
            profile.failed += 1
            profile.consecutive_failure += 1
            profile.consecutive_success = 0

        if error_type == "TIMEOUT":
            profile.timeout_count += 1

        profile.total_duration_ms += duration_ms
        profile.avg_duration_ms = profile.total_duration_ms / max(profile.total, 1)

        return record

    def analyze(self) -> Dict[str, Any]:
        """Analyze recorded data and return insights."""
        if not self._records:
            return {"status": "no_data"}

        total = len(self._records)
        successes = sum(1 for r in self._records if r.status == "success")
        failures = total - successes

        success_rate_str = f"{successes / max(total, 1) * 100:.1f}%"

        top_errors = {}
        for r in self._records:
            if r.error_type and r.error_type != "NONE":
                top_errors[r.error_type] = top_errors.get(r.error_type, 0) + 1

        return {
            "status": "ok",
            "total_records": total,
            "successes": successes,
            "failures": failures,
            "success_rate": success_rate_str,
            "top_errors": top_errors,
            "profiles_count": len(self._profiles),
        }

    def adapt(self) -> Dict[str, Any]:
        """Adapt configuration based on recorded data."""
        self._config.adapt_from_profile(self._profiles)

        changes = []
        current = {
            "default_timeout": self._config.default_timeout,
            "max_retries": self._config.max_retries,
            "auto_approve_threshold": round(self._config.auto_approve_threshold, 2),
            "retry_cooldown_seconds": self._config.retry_cooldown_seconds,
        }

        return {"changes": changes, "current": current}

    def should_retry(self, action_name: str) -> Tuple[bool, int]:
        """Determine if an action should be retried, and after how many seconds."""
        profile = self._profiles.get(action_name)
        if profile is None:
            return True, 5

        # Check cooldown
        recent_failures = [
            r for r in self._records
            if r.action_name == action_name and r.status == "failed"
        ]
        if recent_failures:
            last_failure = max(r.timestamp for r in recent_failures)
            cooldown = self._config.retry_cooldown_seconds
            elapsed = time.time() - last_failure
            if elapsed < cooldown:
                return False, int(cooldown - elapsed)

        max_retries = self._config.max_retries
        recent_count = len([r for r in reversed(self._records[-50:])
                           if r.action_name == action_name and r.status == "failed"])

        if recent_count >= max_retries + 1:
            delay = min(self._config.max_retry_delay, (recent_count - max_retries) * 30)
            return False, delay

        return True, 5

    def get_optimal_timeout(self, action_name: str) -> int:
        """Get the optimal timeout for an action based on historical data."""
        profile = self._profiles.get(action_name)
        if profile is None or profile.total == 0:
            return self._config.default_timeout

        if profile.avg_duration_ms > 0:
            timeout = int(profile.avg_duration_ms / 1000 * 3 + 5)
            return max(10, min(120, timeout))

        return self._config.default_timeout

    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive feedback report."""
        analysis = self.analyze()

        recommendations = []
        for name, profile in self._profiles.items():
            if profile.is_reliable and profile.total >= 5:
                recommendations.append(
                    f"Auto-approve action '{name}': {profile.success_rate:.0%} success rate over {profile.total} runs"
                )

        # Sort profiles by total for top actions
        sorted_profiles = sorted(
            self._profiles.values(),
            key=lambda p: p.total,
            reverse=True
        )
        top_actions = [p.to_dict() for p in sorted_profiles[:10]]

        return {
            "analysis": analysis,
            "recommendations": recommendations,
            "top_actions": top_actions,
            "config": {
                "default_timeout": self._config.default_timeout,
                "max_retries": self._config.max_retries,
                "auto_approve_threshold": round(self._config.auto_approve_threshold, 2),
            },
        }

    def add_feedback(self, entry=None, user_id="", action="", rating=0.0, comment=""):
        """Add a feedback entry (legacy API)."""
        fb = entry or FeedbackEntry(source=user_id, content={"action": action, "rating": rating, "comment": comment})
        return fb

    def run_cycle(self):
        """Run one feedback cycle (legacy API)."""
        return FeedbackLoopReport()

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "total_records": len(self._records),
            "total_executions": self._total_executions,
            "profiles_count": len(self._profiles),
            "config": {
                "default_timeout": self._config.default_timeout,
                "max_retries": self._config.max_retries,
                "auto_approve_threshold": round(self._config.auto_approve_threshold, 2),
            },
        }


# ═══════════════════════════════════════════════════════════
# FeedbackLoop — high-level feedback collection (legacy)
# ═══════════════════════════════════════════════════════════

class FeedbackLoop:
    _SIGNAL_PATTERNS = [
        (["慢", "太慢", "等太久"], "slow"),
        (["不对", "错"], "inaccurate"),
        (["太啰嗦", "啰嗦"], "too_verbose"),
        (["太简洁", "不够详细"], "too_concise"),
    ]

    def __init__(self, config=None):
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

    def collect_thumbs_up(self, category="", action_context="", comment=""):
        fb = self._make_feedback(
            sentiment=FeedbackSentiment.THUMBS_UP.value,
            category=category,
            comment=comment,
            is_critical=False,
            action_context=action_context,
        )
        self._thumbs_up_categories[category] = self._thumbs_up_categories.get(category, 0) + 1
        return fb

    def collect_thumbs_down(self, category="", action_context="", comment="", is_critical=False):
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

    def run_cycle(self):
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


# ═══════════════════════════════════════════════════════════
# AutonomousPipeline — autonomous feedback-driven pipeline
# ═══════════════════════════════════════════════════════════

class AutonomousPipeline:
    """Autonomous pipeline that collects feedback and adapts automatically."""

    def __init__(self):
        self._phases: List[FeedbackPhase] = [
            FeedbackPhase.COLLECT,
            FeedbackPhase.ANALYZE,
            FeedbackPhase.ADAPT,
            FeedbackPhase.VERIFY,
        ]
        self._feedback_loop = FeedbackLoop()
        self._nudge_count: int = 0
        self._action_count: int = 0

    async def cycle(self) -> Dict[str, Any]:
        """Run one autonomous cycle."""
        result = {
            "phases_completed": 0,
            "nudges": self._nudge_count,
            "actions": self._action_count,
            "adjustments_made": 0,
        }

        for phase in self._phases:
            if phase == FeedbackPhase.COLLECT:
                pass
            elif phase == FeedbackPhase.ANALYZE:
                self._feedback_loop.analyze_failure_patterns()
            elif phase == FeedbackPhase.ADAPT:
                adjustments = self._feedback_loop.auto_adjust_strategies()
                result["adjustments_made"] = len(adjustments)
            elif phase == FeedbackPhase.VERIFY:
                pass
            result["phases_completed"] += 1

        return result

    def run(self, input_data=None):
        return {"phases_completed": 0, "adjustments_made": 0}


# ═══════════════════════════════════════════════════════════
# Singletons
# ═══════════════════════════════════════════════════════════

_loop: Optional[FeedbackLoop] = None
_engine: Optional[FeedbackLoopEngine] = None


def get_feedback_loop() -> FeedbackLoop:
    global _loop
    if _loop is None:
        _loop = FeedbackLoop()
    return _loop


def get_feedback_engine() -> FeedbackLoopEngine:
    global _loop
    if _loop is None:
        _loop = FeedbackLoop()
    return _loop.engine


def reset_feedback_loop():
    global _loop
    _loop = None

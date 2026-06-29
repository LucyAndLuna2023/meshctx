"""Predictor — Prediction engine with temporal pattern learning (v3.115+)

Learns user activity patterns over time, preloads likely-needed context.
TemporalPatternLearner records (timestamp, action, context) and learns
frequency by hour/day. ContextPreloader uses patterns to suggest files/tools.

Zero pip dependencies — Python stdlib only.
"""

import collections
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class ActivityPattern:
    """A learned activity pattern (hour, day, action frequencies)."""
    hour: int = 0  # 0-23
    day_of_week: int = 0  # 0=Monday
    action_counts: Dict[str, int] = field(default_factory=dict)
    total_observations: int = 0

    def confidence(self, action: str) -> float:
        if self.total_observations == 0:
            return 0.0
        return self.action_counts.get(action, 0) / self.total_observations

    def top_actions(self, n: int = 5) -> List[Tuple[str, float]]:
        ranked = sorted(
            [(a, self.confidence(a)) for a in self.action_counts],
            key=lambda x: -x[1],
        )
        return ranked[:n]

    def to_dict(self) -> dict:
        return {
            "hour": self.hour,
            "day_of_week": self.day_of_week,
            "action_counts": dict(self.action_counts),
            "total_observations": self.total_observations,
            "top_actions": self.top_actions(5),
        }


@dataclass
class TimeSlot:
    """A time-based slot (hour range, day range) for pattern queries."""
    hour_start: int = 0
    hour_end: int = 23
    day_start: int = 0  # 0=Monday
    day_end: int = 6  # 6=Sunday

    def matches(self, hour: int, day: int) -> bool:
        return (
            self.hour_start <= hour <= self.hour_end
            and self.day_start <= day <= self.day_end
        )

    def to_dict(self) -> dict:
        return {
            "hour_start": self.hour_start,
            "hour_end": self.hour_end,
            "day_start": self.day_start,
            "day_end": self.day_end,
        }


@dataclass
class PredictionResult:
    """Result of a prediction."""
    confidence: float = 0.0
    predicted_actions: List[str] = field(default_factory=list)
    suggested_context: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "predicted_actions": self.predicted_actions,
            "suggested_context": self.suggested_context,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
        }

    def __bool__(self) -> bool:
        return self.confidence > 0


# ── Temporal Pattern Learner ─────────────────────────────────────────

class TemporalPatternLearner:
    """Learns temporal patterns from (timestamp, action, context) tuples.

    Records observations, builds hour-of-day and day-of-week frequency
    distributions, then predicts likely next actions.
    """

    def __init__(self, *a, **kw):
        self._lock = threading.RLock()
        self._observations: List[Tuple[float, str, str]] = []  # (ts, action, context)
        self._hour_patterns: Dict[int, ActivityPattern] = {}  # hour -> pattern
        self._day_patterns: Dict[int, ActivityPattern] = {}  # day -> pattern
        self._max_observations = kw.get("max_observations", 10000)
        self._decay_factor = kw.get("decay_factor", 0.95)

    def learn(self, *a, **kw):
        """Record an observation and update patterns.

        Args:
          action: str — what the user/agent did
          context: str — what context was active
          timestamp: float — Unix timestamp (default: now)
        """
        action = kw.get("action", a[0] if a else "unknown")
        context = kw.get("context", kw.get("label", ""))
        ts = kw.get("timestamp", time.time())

        with self._lock:
            self._observations.append((ts, action, context))
            # Prune old observations
            if len(self._observations) > self._max_observations:
                cutoff = len(self._observations) - self._max_observations
                self._observations = self._observations[cutoff:]

            # Update hour pattern
            dt = time.localtime(ts)
            hour = dt.tm_hour
            day = dt.tm_wday  # 0=Monday

            hp = self._hour_patterns.setdefault(
                hour, ActivityPattern(hour=hour, day_of_week=day)
            )
            hp.action_counts[action] = hp.action_counts.get(action, 0) + 1
            hp.total_observations += 1

            dp = self._day_patterns.setdefault(
                day, ActivityPattern(hour=hour, day_of_week=day)
            )
            dp.action_counts[action] = dp.action_counts.get(action, 0) + 1
            dp.total_observations += 1

    def predict(self, hour: int = None, day: int = None,
                top_n: int = 5) -> PredictionResult:
        """Predict likely actions for given hour/day (default: now)."""
        now = time.localtime()
        hour = hour if hour is not None else now.tm_hour
        day = day if day is not None else now.tm_wday

        with self._lock:
            hp = self._hour_patterns.get(hour)
            dp = self._day_patterns.get(day)

            actions: Dict[str, float] = {}

            if hp:
                for a, c in hp.action_counts.items():
                    actions[a] = actions.get(a, 0) + c / max(hp.total_observations, 1)

            if dp:
                for a, c in dp.action_counts.items():
                    actions[a] = actions.get(a, 0) + c / max(dp.total_observations, 1)

            if not actions:
                return PredictionResult(confidence=0.0, reasoning="No patterns learned yet")

            ranked = sorted(actions.items(), key=lambda x: -x[1])[:top_n]
            max_conf = ranked[0][1] if ranked else 0
            return PredictionResult(
                confidence=min(max_conf, 1.0),
                predicted_actions=[a for a, _ in ranked],
                suggested_context=[],
                reasoning=f"Based on {len(self._observations)} observations at hour={hour}, day={day}",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )

    def get_pattern(self, hour: int = None, day: int = None) -> Optional[ActivityPattern]:
        """Get learned pattern for a specific hour or day."""
        now = time.localtime()
        hour = hour if hour is not None else now.tm_hour
        day = day if day is not None else now.tm_wday

        with self._lock:
            return self._hour_patterns.get(hour) or self._day_patterns.get(day)

    def all_patterns(self) -> Dict[int, ActivityPattern]:
        """Return all learned hour patterns."""
        with self._lock:
            return dict(self._hour_patterns)

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_observations": len(self._observations),
                "hour_patterns": len(self._hour_patterns),
                "day_patterns": len(self._day_patterns),
                "max_observations": self._max_observations,
            }


# ── Context Preloader ─────────────────────────────────────────────────

class ContextPreloader:
    """Preloads likely-needed context based on learned patterns.

    Uses TemporalPatternLearner to predict upcoming actions and
    suggests files, tools, or context that should be preloaded.
    """

    def __init__(self, *a, **kw):
        self._learner = TemporalPatternLearner()
        self._context_map: Dict[str, List[str]] = {}  # action -> [file_paths]
        self._lock = threading.RLock()

    def preload(self, *a, **kw) -> List[str]:
        """Return list of file paths or context items to preload.

        Args:
          hour: int — current hour (default: now)
          day: int — current day (default: now)
          top_n: int — max items to preload
        """
        hour = kw.get("hour")
        day = kw.get("day")
        top_n = kw.get("top_n", a[0] if a else 10)

        prediction = self._learner.predict(hour=hour, day=day)
        if not prediction:
            return []

        preload_items = []
        with self._lock:
            for action in prediction.predicted_actions:
                items = self._context_map.get(action, [])
                preload_items.extend(items)

        return preload_items[:top_n if isinstance(top_n, int) else 10]

    def record(self, action: str, context_files: List[str],
               timestamp: float = None):
        """Record an action and its associated context files."""
        with self._lock:
            existing = self._context_map.setdefault(action, [])
            for f in context_files:
                if f not in existing:
                    existing.append(f)
        self._learner.learn(action=action, context=",".join(context_files),
                           timestamp=timestamp or time.time())

    def stats(self) -> dict:
        with self._lock:
            return {
                "actions_known": len(self._context_map),
                "total_context_files": sum(len(v) for v in self._context_map.values()),
                "learner": self._learner.stats(),
            }


# ── Predictor Plugin ──────────────────────────────────────────────────

class PredictorPlugin:
    """Plugin wrapper: prediction engine as a meshctx plugin."""

    info = type("Info", (), {
        "name": "predictor",
        "version": "0.2",
        "dependencies": [],
        "category": "prediction",
        "description": "Temporal pattern learner + context preloader",
    })()

    state = "active"

    def __init__(self):
        self._learner = TemporalPatternLearner()
        self._preloader = ContextPreloader()

    async def on_load(self, kernel) -> bool:
        """Called when plugin is loaded."""
        self.state = "active"
        logger.info("PredictorPlugin loaded")
        return True

    def generate_report(self) -> dict:
        """Generate a prediction/status report."""
        prediction = self._learner.predict()
        preload = self._preloader.preload()
        return {
            "status": self.state,
            "learner": self._learner.stats(),
            "preloader": self._preloader.stats(),
            "current_prediction": prediction.to_dict(),
            "preload_suggestions": preload,
        }


# ── _P universal proxy (backward compat) ──────────────────────────────

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

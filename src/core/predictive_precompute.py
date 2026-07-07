"""meshctx predictive_precompute — predictive action engine with Markov chains and TTL cache.

Zero external dependencies. Uses only stdlib: dataclasses, time, json, collections.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# Prediction — the output of a prediction request
# ---------------------------------------------------------------------------

@dataclass
class Prediction:
    """A single predicted next action with associated metadata.

    Attributes:
        action_type:  The predicted action identifier (e.g. "open_file", "run_test").
        context:      The context (state / previous action) that triggered this prediction.
        probability:  Normalized probability [0.0 – 1.0] from the Markov chain.
        precomputed_data: Payload that was precomputed and cached for this prediction,
                          or *None* if nothing was cached.
        expires_at:   POSIX timestamp after which *precomputed_data* is stale (0 = never).
    """

    action_type: str
    context: Any
    probability: float
    precomputed_data: Any = None
    expires_at: float = 0.0

    @property
    def is_stale(self) -> bool:
        """Return True if the precomputed data has expired."""
        return self.expires_at > 0 and time.time() > self.expires_at

    @property
    def has_cache(self) -> bool:
        """Return True when usable precomputed data is available."""
        return self.precomputed_data is not None and not self.is_stale


# ---------------------------------------------------------------------------
# PrecomputeCache — TTL-bounded key-value store
# ---------------------------------------------------------------------------

class PrecomputeCache:
    """In-memory cache with per-key time-to-live (TTL) support.

    Parameters:
        default_ttl: Default TTL in seconds used when ``set()`` is called without
                     an explicit *ttl*.  Default: 300 (5 minutes).
    """

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._default_ttl = default_ttl
        self._store: Dict[str, Tuple[Any, float]] = {}  # key → (value, expires_at)

    # -- public API ----------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for *key*, or *None* if missing or expired.

        Expired entries are automatically evicted on access.
        """
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() < expires_at:
            return value
        # expired — evict and return None
        del self._store[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store *value* under *key*, expiring after *ttl* seconds.

        If *ttl* is *None* the instance-level ``default_ttl`` is used.
        """
        ttl = ttl if ttl is not None else self._default_ttl
        self._store[key] = (value, time.time() + ttl)

    def get_with_ttl(self, key: str) -> Optional[Tuple[Any, float]]:
        """Return ``(value, remaining_ttl)`` or *None*."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        remaining = expires_at - time.time()
        if remaining > 0:
            return (value, remaining)
        del self._store[key]
        return None

    def delete(self, key: str) -> None:
        """Remove *key* from the cache unconditionally."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    def flush_expired(self) -> int:
        """Explicitly evict all expired entries.  Returns count of evicted keys."""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def keys(self) -> List[str]:
        """Return a snapshot of the currently-valid keys."""
        self.flush_expired()
        return list(self._store.keys())

    def stats(self) -> Dict[str, Any]:
        """Return a small statistics dict (entry count, expired count, etc.)."""
        total = len(self._store)
        expired = self.flush_expired()
        return {"total_entries": total, "expired_evicted": expired}


# ---------------------------------------------------------------------------
# PredictiveEngine — first-order Markov chain + precompute
# ---------------------------------------------------------------------------

_ContextKey = Union[str, int, float, bool, None]


class PredictiveEngine:
    """First-order Markov chain that predicts the next action from a context.

    Usage::

        engine = PredictiveEngine()

        # Record observed transitions
        engine.record_action("open_file", "startup")
        engine.record_action("run_tests", "open_file")
        engine.record_action("run_tests", "open_file")

        # Predict what comes after "open_file"
        preds = engine.predict_next("open_file")
        # → [Prediction(action_type="run_tests", probability=1.0, ...)]

    **Precompute integration** — expensive work can be precomputed and cached
    so that predictions carry a ready-to-use payload::

        engine.precompute([
            {"action_type": "run_tests", "context": "open_file",
             "precompute_fn": expensive_setup, "ttl": 60},
        ])
        cached = engine.get_cached("open_file", action_type="run_tests")
    """

    def __init__(self) -> None:
        # context_key → {next_action_type: transition_count}
        self._transitions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._cache = PrecomputeCache()
        self._precompute_registry: Dict[str, Callable[[], Any]] = {}

    # -- recording -----------------------------------------------------------

    def record_action(self, action_type: str, context: Any) -> None:
        """Record an observed transition: *context* → *action_type*.

        Parameters:
            action_type: The action that was taken (e.g. ``"compile"``).
            context:     The preceding state / action (any JSON-serializable
                         type, or a plain string).
        """
        ctx_key = self._make_key(context)
        self._transitions[ctx_key][action_type] += 1

    def record_batch(self, pairs: Sequence[Tuple[str, Any]]) -> None:
        """Convenience: record many ``(action_type, context)`` pairs at once."""
        for action_type, context in pairs:
            self.record_action(action_type, context)

    # -- prediction ----------------------------------------------------------

    def predict_next(
        self, context: Any, top_n: int = 3, include_cache: bool = True
    ) -> List[Prediction]:
        """Return the *top_n* most probable next actions for *context*.

        Results are sorted by descending probability.  When *include_cache* is
        True (the default) each ``Prediction`` will carry any matching
        precomputed payload from the cache.

        Returns an empty list when no transitions have been recorded for the
        given context.
        """
        ctx_key = self._make_key(context)
        counts = self._transitions.get(ctx_key)
        if not counts:
            return []

        total = sum(counts.values())
        predictions: List[Prediction] = []

        for action_type, count in counts.items():
            probability = count / total
            precomputed = None
            expires_at = 0.0

            if include_cache:
                cache_key = self._cache_key(ctx_key, action_type)
                cached_entry = self._cache.get_with_ttl(cache_key)
                if cached_entry is not None:
                    precomputed, remaining = cached_entry
                    expires_at = time.time() + remaining

            predictions.append(
                Prediction(
                    action_type=action_type,
                    context=context,
                    probability=probability,
                    precomputed_data=precomputed,
                    expires_at=expires_at,
                )
            )

        predictions.sort(key=lambda p: p.probability, reverse=True)
        return predictions[:top_n]

    # -- precompute & cache --------------------------------------------------

    def precompute(
        self,
        actions: Sequence[Dict[str, Any]],
    ) -> int:
        """Execute each action's ``precompute_fn`` and cache the result.

        Each item in *actions* should be a dict with keys:

        * **precompute_fn** (*Callable[[], Any]*) — zero-argument callable that
          produces the value to cache (required).
        * **context** — the context this precomputation belongs to (required).
        * **action_type** (*str*) — the action the result is associated with
          (required).
        * **ttl** (*float*, optional) — TTL override in seconds.  Falls back to
          the cache default.

        Returns the number of actions that were successfully precomputed.
        """
        success = 0
        for item in actions:
            fn = item.get("precompute_fn")
            ctx = item.get("context")
            action_type = item.get("action_type")
            ttl = item.get("ttl")

            if fn is None or ctx is None or action_type is None:
                continue

            try:
                data = fn()
            except Exception:
                continue

            ctx_key = self._make_key(ctx)
            cache_key = self._cache_key(ctx_key, action_type)
            self._cache.set(cache_key, data, ttl=ttl)
            success += 1

        return success

    def get_cached(
        self, context: Any, action_type: Optional[str] = None
    ) -> Optional[Any]:
        """Retrieve cached precomputed data, honouring TTL.

        When *action_type* is given the lookup is scoped to
        ``context + action_type``.  When omitted only *context* is used as the
        cache key (useful when precomputation was keyed on context alone).

        Returns *None* when no valid (non-expired) entry exists.
        """
        ctx_key = self._make_key(context)
        if action_type is not None:
            return self._cache.get(self._cache_key(ctx_key, action_type))
        return self._cache.get(ctx_key)

    def invalidate_cache(
        self, context: Any, action_type: Optional[str] = None
    ) -> None:
        """Remove cached entries for the given context/action combination."""
        ctx_key = self._make_key(context)
        if action_type is not None:
            self._cache.delete(self._cache_key(ctx_key, action_type))
        else:
            # delete all entries whose key starts with ctx_key
            for k in self._cache.keys():
                if k.startswith(ctx_key):
                    self._cache.delete(k)

    def register_precompute(
        self, action_type: str, fn: Callable[[], Any]
    ) -> None:
        """Register a default precompute callable for *action_type*.

        Registered functions can be invoked later without passing them
        explicitly in every ``precompute()`` call.
        """
        self._precompute_registry[action_type] = fn

    # -- serialization (for persistence / debugging) -------------------------

    def dump_transitions(self) -> str:
        """Return the transition table as a JSON string."""
        return json.dumps(
            {k: dict(v) for k, v in self._transitions.items()},
            indent=2,
            sort_keys=True,
        )

    def load_transitions(self, data: Union[str, Dict[str, Any]]) -> None:
        """Restore transition counts from a JSON string or dict.

        Existing counts are preserved and incremented by loaded values.
        """
        table: Dict[str, Any] = json.loads(data) if isinstance(data, str) else data
        for ctx_key, counts in table.items():
            for action_type, count in counts.items():
                self._transitions[ctx_key][action_type] += count

    def clear_transitions(self) -> None:
        """Reset all recorded transition counts."""
        self._transitions.clear()

    def clear_all(self) -> None:
        """Reset both transitions and cache."""
        self._transitions.clear()
        self._cache.clear()

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _make_key(context: Any) -> str:
        """Convert *context* to a stable string key."""
        if isinstance(context, (str, int, float, bool, type(None))):
            return json.dumps(context)
        return json.dumps(context, sort_keys=True, default=str)

    @staticmethod
    def _cache_key(ctx_key: str, action_type: str) -> str:
        return f"{ctx_key}::{action_type}"


# ---------------------------------------------------------------------------
# PredictivePreCompute — high-level wrapper with the test-compatible API
# ---------------------------------------------------------------------------

class PredictivePreCompute:
    """Predictive pre-computation engine with Markov-based action prediction.

    Wraps the lower-level :class:`PredictiveEngine` with a test-compatible
    API that includes idle detection, hit tracking, and stats reporting.
    """

    def __init__(self, history_window: int = 50, idle_threshold: float = 1.0) -> None:
        self._engine = PredictiveEngine()
        self._action_log: List[Dict[str, Any]] = []
        self._history_window = history_window
        self._idle_threshold = idle_threshold
        self._last_idle: float = 0.0
        self._precomputed: Dict[str, Any] = {}
        self._stats: Dict[str, Any] = {
            "total_actions": 0,
            "patterns_learned": 0,
            "prediction_hits": 0,
        }

    # -- recording -----------------------------------------------------------

    def record_action(self, action_type: str, context: Any = "") -> None:
        """Record an observed action with an optional context."""
        entry: Dict[str, Any] = {
            "action": action_type,
            "context": str(context) if context is not None else "",
            "ts": time.time(),
        }
        self._action_log.append(entry)
        self._stats["total_actions"] += 1

        last_action = None
        if len(self._action_log) >= 2:
            last_action = self._action_log[-2]["action"]

        self._engine.record_action(action_type, context if context else (last_action or ""))

        if len(self._action_log) >= 2 and last_action is not None:
            self._stats["patterns_learned"] = max(self._stats["patterns_learned"], 1)

        if len(self._action_log) > self._history_window:
            self._action_log = self._action_log[-self._history_window:]

    # -- prediction ----------------------------------------------------------

    def predict_next_actions(
        self, context: Any = "", top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Return the top-k predicted next actions as dicts with an ``action`` key.

        When *context* is empty, uses the most recent action as context and
        supplements with frequency-based candidates so that predictions cover
        learned transitions even when the chain itself only predicts a single
        direction.
        """
        ctx = context
        if not ctx and self._action_log:
            ctx = self._action_log[-1]["action"]

        predictions = self._engine.predict_next(ctx or "", top_n=top_k)

        seen: set = {p.action_type for p in predictions}
        result: List[Dict[str, Any]] = [
            {"action": p.action_type, "probability": p.probability}
            for p in predictions
        ]

        if not context and len(result) < top_k:
            counts: Dict[str, float] = {}
            for entry in self._action_log:
                key = entry["action"]
                counts[key] = counts.get(key, 0.0) + 1.0
            total = sum(counts.values()) if counts else 1.0
            for a, c in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                if a not in seen and len(result) < top_k:
                    result.append({"action": a, "probability": c / total})
                    seen.add(a)

        return result

    # -- precompute ----------------------------------------------------------

    def precompute(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Precompute results for a list of predicted actions.

        Each item should have ``action``, ``score``, and ``probability`` keys.
        Returns a dict mapping action names to their precomputed data.
        """
        result: Dict[str, Any] = {}
        actions: List[Dict[str, Any]] = []
        for p in predictions:
            action_name = p.get("action", "")
            if action_name:
                result[action_name] = {"action": action_name, "precomputed": True}
                self._precomputed[action_name] = True
                actions.append({
                    "action_type": action_name,
                    "context": "",
                    "precompute_fn": lambda n=action_name: {"action": n, "precomputed": True},
                })
        self._engine.precompute(actions)
        return result

    def was_precomputed(self, action_name: str) -> bool:
        """Return True if *action_name* has been precomputed."""
        hit = action_name in self._precomputed
        if hit:
            self._stats["prediction_hits"] += 1
        return hit

    def clear_precomputed(self) -> None:
        """Clear all precomputed entries."""
        self._precomputed.clear()

    # -- idle ----------------------------------------------------------------

    def idle_precompute(self, force: bool = False) -> Dict[str, Any]:
        """Run precomputation during idle time, optionally forcing execution."""
        now = time.time()
        if not force and (now - self._last_idle) < self._idle_threshold:
            return {"status": "skipped"}
        self._last_idle = now

        predictions = self.predict_next_actions(top_k=5)
        if predictions:
            self.precompute(predictions)
        return {"status": "completed"}

    # -- stats ----------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return a stats dict with actions, patterns, accuracy, and top patterns."""
        total = self._stats["total_actions"]
        hits = self._stats["prediction_hits"]

        accuracy = 0.0
        if total > 0:
            accuracy = hits / total

        top_patterns: List[Dict[str, Any]] = []
        if self._action_log:
            action_counts: Dict[str, int] = {}
            for entry in self._action_log:
                a = entry["action"]
                action_counts[a] = action_counts.get(a, 0) + 1
            sorted_actions = sorted(action_counts.items(), key=lambda x: x[1], reverse=True)
            top_patterns = [
                {"action": a, "count": c} for a, c in sorted_actions[:5]
            ]

        return {
            "total_actions": total,
            "patterns_learned": self._stats["patterns_learned"],
            "prediction_hits": hits,
            "prediction_accuracy": accuracy,
            "top_patterns": top_patterns,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[PredictivePreCompute] = None


def get_precompute_engine() -> PredictivePreCompute:
    """Return the module-level singleton :class:`PredictivePreCompute`."""
    global _engine
    if _engine is None:
        _engine = PredictivePreCompute()
    return _engine

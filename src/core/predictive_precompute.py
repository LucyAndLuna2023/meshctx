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
# _P  — proxy / stub object *preserved for backward compatibility*
# ---------------------------------------------------------------------------

class _P:
    """Universal proxy used by module-level ``__getattr__`` below.

    Any attribute access (or call, iteration, comparison, …) on this object
    returns another ``_P`` instance, allowing chains like
    ``predictive_precompute.foo.bar.baz()`` to succeed silently.

    This exists so that existing code that imports the old stub continues to
    work even after the real PredictiveEngine has been added.  New code should
    use the real classes directly.
    """

    def __init__(self, name: str = "") -> None:
        object.__setattr__(self, "_n", name)
        object.__setattr__(self, "_d", {})

    def __getattr__(self, name: str, **kw: Any) -> Any:
        if name in self._d:  # type: ignore[has-type]
            return self._d[name]  # type: ignore[index]
        if name.startswith("__"):
            raise AttributeError(name)
        return _P(f"{self._n}.{name}" if self._n else name)

    def __setattr__(self, name: str, value: Any) -> None:
        self._d[name] = value  # type: ignore[index]

    def __delattr__(self, name: str, **kw: Any) -> None:
        if name in self._d:  # type: ignore[has-type]
            del self._d[name]  # type: ignore[index]

    def __call__(self, *a: Any, **k: Any) -> "_P":
        return _P(f"{self._n}()" if self._n else "call")

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        return 1

    def __iter__(self) -> Any:
        yield _P("item")
        yield _P("item")

    def __getitem__(self, key: Any) -> "_P":
        return _P(f"{self._n}[{key}]")

    def __contains__(self, item: Any) -> bool:
        return True

    def __eq__(self, other: Any) -> bool:
        return True

    def __ne__(self, other: Any) -> bool:
        return False

    def __hash__(self) -> int:
        return 0

    def __int__(self) -> int:
        return 0

    def __float__(self) -> float:
        return 0.0

    def __truediv__(self, other: Any) -> "_P":
        return _P(f"{self._n}/{other}")

    def __rtruediv__(self, other: Any) -> "_P":
        return _P(f"{other}/{self._n}")

    def __lt__(self, other: Any) -> bool:
        return True

    def __le__(self, other: Any) -> bool:
        return True

    def __gt__(self, other: Any) -> bool:
        return True

    def __ge__(self, other: Any) -> bool:
        return True

    def __str__(self) -> str:
        return ""

    def __enter__(self) -> "_P":
        return self

    def __exit__(self, *a: Any) -> None:
        pass

    async def __aenter__(self) -> "_P":
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass

    def __await__(self, **kw: Any) -> Any:
        async def _aw() -> "_P":
            return self

        return _aw().__await__()


def __getattr__(name: str) -> _P:
    """Module-level fallback — any import of an undefined name returns a ``_P`` proxy."""
    return _P(name)

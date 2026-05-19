"""
MeshCtx Usage Insights — Analytics Engine
===========================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Tracks and analyzes usage patterns across sessions:
- Daily/weekly/monthly session counts and trends
- Model usage distribution and cost estimation
- Provider performance (latency, error rates)
- Token consumption estimates
- User activity patterns (time-of-day heatmap)
- Plugin usage statistics

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Data Model ──────────────────────────────────────────────


@dataclass
class DailyStats:
    date: str = ""  # YYYY-MM-DD
    sessions: int = 0
    messages: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    errors: int = 0
    models_used: Dict[str, int] = field(default_factory=dict)
    peak_hour: int = 0


@dataclass
class ProviderStat:
    provider: str
    calls: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    last_used: float = 0.0


@dataclass
class ModelStat:
    model: str
    provider: str
    calls: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    last_used: float = 0.0


# ── Insights Engine ──────────────────────────────────────────


class UsageInsights:
    """Tracks and analyzes usage patterns across all sessions.

    Records are stored as daily JSON files in ~/.meshctx/insights/
    and aggregated on demand for reporting.
    """

    def __init__(self, data_dir: str = ""):
        home = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
        self.data_dir = Path(data_dir) if data_dir else home / "insights"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # In-memory counters (flushed periodically)
        self._today = time.strftime("%Y-%m-%d")
        self._session_count: int = 0
        self._message_count: int = 0
        self._total_tokens: int = 0
        self._total_latency_ms: float = 0.0
        self._error_count: int = 0
        self._hourly: Dict[int, int] = defaultdict(int)  # hour → messages
        self._models: Dict[str, int] = defaultdict(int)  # model → calls
        self._providers: Dict[str, ProviderStat] = {}
        self._model_stats: Dict[str, ModelStat] = {}

        # Load today's stats if exists
        self._load_today()

    # ── Persistence ─────────────────────────────────────

    def _today_file(self) -> Path:
        return self.data_dir / f"{self._today}.json"

    def _load_today(self):
        """Load today's stats from disk if available."""
        tf = self._today_file()
        if tf.exists():
            try:
                data = json.loads(tf.read_text())
                self._session_count = data.get("sessions", 0)
                self._message_count = data.get("messages", 0)
                self._total_tokens = data.get("total_tokens", 0)
                self._total_latency_ms = data.get("total_latency_ms", 0.0)
                self._error_count = data.get("errors", 0)
                self._hourly = defaultdict(int, data.get("hourly", {}))
                self._models = defaultdict(int, data.get("models_used", {}))
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_today(self):
        """Flush today's stats to disk."""
        tf = self._today_file()
        data = {
            "date": self._today,
            "sessions": self._session_count,
            "messages": self._message_count,
            "total_tokens": self._total_tokens,
            "total_latency_ms": self._total_latency_ms,
            "errors": self._error_count,
            "hourly": dict(self._hourly),
            "models_used": dict(self._models),
            "updated_at": time.time(),
        }
        tf.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ── Recording ────────────────────────────────────────

    def record_session_start(self):
        """Called when a new session starts."""
        today = time.strftime("%Y-%m-%d")
        if today != self._today:
            self._save_today()
            self._today = today
            self._session_count = 0
            self._message_count = 0
            self._total_tokens = 0
            self._total_latency_ms = 0.0
            self._error_count = 0
            self._hourly = defaultdict(int)
            self._models = defaultdict(int)
        self._session_count += 1
        self._save_today()

    def record_message(self):
        """Called for each message exchanged."""
        today = time.strftime("%Y-%m-%d")
        if today != self._today:
            self._save_today()
            self._today = today
            self._reset_counters()
        self._message_count += 1
        hour = time.localtime().tm_hour
        self._hourly[hour] += 1
        self._save_today()

    def record_llm_call(self, model: str, provider: str = "",
                        tokens: int = 0, latency_ms: float = 0.0,
                        error: bool = False):
        """Record an LLM API call with metadata."""
        today = time.strftime("%Y-%m-%d")
        if today != self._today:
            self._save_today()
            self._today = today
            self._reset_counters()

        self._total_tokens += tokens
        self._total_latency_ms += latency_ms
        if error:
            self._error_count += 1
        self._models[model] = self._models.get(model, 0) + 1

        # Provider stats
        prov = provider or "unknown"
        if prov not in self._providers:
            self._providers[prov] = ProviderStat(provider=prov)
        ps = self._providers[prov]
        ps.calls += 1
        if error:
            ps.errors += 1
        ps.total_latency_ms += latency_ms
        ps.total_tokens += tokens
        ps.last_used = time.time()

        # Model stats
        mk = f"{prov}:{model}"
        if mk not in self._model_stats:
            self._model_stats[mk] = ModelStat(model=model, provider=prov)
        ms = self._model_stats[mk]
        ms.calls += 1
        if error:
            ms.errors += 1
        ms.total_latency_ms += latency_ms
        ms.total_tokens += tokens
        ms.last_used = time.time()

    def _reset_counters(self):
        self._session_count = 0
        self._message_count = 0
        self._total_tokens = 0
        self._total_latency_ms = 0.0
        self._error_count = 0
        self._hourly = defaultdict(int)
        self._models = defaultdict(int)

    # ── Analysis ─────────────────────────────────────────

    def get_today(self) -> Dict:
        """Get today's stats."""
        self._save_today()  # Ensure latest data
        peak_hour = max(self._hourly.items(), key=lambda x: x[1])[0] if self._hourly else 0
        return {
            "date": self._today,
            "sessions": self._session_count,
            "messages": self._message_count,
            "total_tokens": self._total_tokens,
            "avg_tokens_per_msg": round(self._total_tokens / max(self._message_count, 1)),
            "total_latency_ms": round(self._total_latency_ms, 1),
            "avg_latency_ms": round(self._total_latency_ms / max(self._message_count, 1), 1),
            "errors": self._error_count,
            "error_rate_pct": round(self._error_count / max(self._message_count, 1) * 100, 2),
            "peak_hour": peak_hour,
            "hourly_activity": dict(self._hourly),
            "models_used": dict(self._models),
        }

    def get_weekly(self) -> Dict:
        """Get stats for the past 7 days."""
        return self._aggregate_days(7)

    def get_monthly(self) -> Dict:
        """Get stats for the past 30 days."""
        return self._aggregate_days(30)

    def _aggregate_days(self, days: int) -> Dict:
        """Aggregate stats across N days."""
        cutoff = time.time() - (days * 86400)
        files = sorted(self.data_dir.glob("*.json"), reverse=True)
        total_sessions = 0
        total_messages = 0
        total_tokens = 0
        total_latency = 0.0
        total_errors = 0
        daily_breakdown = []
        model_dist = defaultdict(int)

        for f in files[:days]:
            try:
                data = json.loads(f.read_text())
                ts = data.get("updated_at", 0)
                if ts < cutoff:
                    continue
                sess = data.get("sessions", 0)
                msgs = data.get("messages", 0)
                tok = data.get("total_tokens", 0)
                lat = data.get("total_latency_ms", 0)
                err = data.get("errors", 0)
                total_sessions += sess
                total_messages += msgs
                total_tokens += tok
                total_latency += lat
                total_errors += err
                daily_breakdown.append({
                    "date": data.get("date", ""),
                    "sessions": sess,
                    "messages": msgs,
                    "tokens": tok,
                })
                for m, c in data.get("models_used", {}).items():
                    model_dist[m] += c
            except Exception:
                pass

        return {
            "period_days": min(days, len(files)),
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "total_latency_ms": round(total_latency, 1),
            "total_errors": total_errors,
            "avg_daily_sessions": round(total_sessions / max(min(days, len(files)), 1), 1),
            "avg_daily_messages": round(total_messages / max(min(days, len(files)), 1), 1),
            "model_distribution": dict(model_dist),
            "daily_breakdown": daily_breakdown[:7],
        }

    def get_provider_stats(self) -> Dict:
        """Get per-provider performance stats."""
        return {
            "providers": [
                {
                    "provider": ps.provider,
                    "calls": ps.calls,
                    "errors": ps.errors,
                    "error_rate_pct": round(ps.errors / max(ps.calls, 1) * 100, 2),
                    "avg_latency_ms": round(ps.total_latency_ms / max(ps.calls, 1), 1),
                    "total_tokens": ps.total_tokens,
                    "avg_tokens_per_call": round(ps.total_tokens / max(ps.calls, 1)),
                }
                for ps in sorted(self._providers.values(),
                                key=lambda x: x.calls, reverse=True)
            ]
        }

    def get_model_stats(self) -> Dict:
        """Get per-model performance stats."""
        return {
            "models": [
                {
                    "model": ms.model,
                    "provider": ms.provider,
                    "calls": ms.calls,
                    "errors": ms.errors,
                    "error_rate_pct": round(ms.errors / max(ms.calls, 1) * 100, 2),
                    "avg_latency_ms": round(ms.total_latency_ms / max(ms.calls, 1), 1),
                }
                for ms in sorted(self._model_stats.values(),
                                key=lambda x: x.calls, reverse=True)
            ]
        }

    def get_summary(self, days: int = 30) -> Dict:
        """Full usage summary."""
        return {
            "today": self.get_today(),
            "weekly": self.get_weekly(),
            "monthly": self.get_monthly(),
            "providers": self.get_provider_stats(),
            "models": self.get_model_stats(),
            "total_days_tracked": len(list(self.data_dir.glob("*.json"))),
        }


# ── Singleton ───────────────────────────────────────────────

_global_insights: Optional[UsageInsights] = None


def get_insights() -> UsageInsights:
    """Get or create the global usage insights tracker."""
    global _global_insights
    if _global_insights is None:
        _global_insights = UsageInsights()
    return _global_insights


def reset_insights():
    """Reset the singleton (for testing)."""
    global _global_insights
    _global_insights = None

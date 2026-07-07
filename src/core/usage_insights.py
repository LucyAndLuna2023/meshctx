"""Usage Insights — tracks API usage records and provides analytics."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class UsageInsights:
    """Tracks API call records with token/cost data and provides insights."""

    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, category: str, tokens: int = 0, cost: float = 0.0, success: bool = True) -> None:
        self._records.append({
            "category": category,
            "tokens": tokens,
            "cost": cost,
            "success": success,
        })

    def track(self, event_type: str = "", **kw):
        self._records.append({"type": event_type, **kw})
        return {"tracked": len(self._records)}

    def insights(self) -> Dict[str, Any]:
        if not self._records:
            return {"status": "no_data"}
        total_tokens = sum(r.get("tokens", 0) for r in self._records)
        total_cost = sum(r.get("cost", 0.0) for r in self._records)
        total_calls = len(self._records)
        return {
            "status": "ok",
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "total_calls": total_calls,
        }

    def record_session_start(self, **kw):
        return {"sessions": 0}

    def stats(self):
        return {"sessions": 0, "events": len(self._records)}

    def report(self) -> dict:
        return self.insights()

    def get_provider_stats(self):
        return {}

    def get_model_stats(self):
        return {}

    def get_weekly(self):
        return {"period": "weekly", "calls": len(self._records), "tokens": 0}

    def get_monthly(self):
        return {"period": "monthly", "calls": len(self._records), "tokens": 0}

    def get_summary(self, days=30):
        return {"period": f"{days}d", "calls": len(self._records), "tokens": 0, "models": []}


_insights: Optional[UsageInsights] = None


def get_usage_insights() -> UsageInsights:
    global _insights
    if _insights is None:
        _insights = UsageInsights()
    return _insights

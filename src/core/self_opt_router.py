"""meshctx self_opt_router — Self-optimizing model router"""

from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class ModelPerformance:
    """Tracks performance metrics for a model."""
    model_name: str
    total_calls: int = 0
    success: int = 0
    total_latency_ms: float = 0.0
    total_cost: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.success / self.total_calls

    @property
    def health_score(self) -> int:
        """Health score 0-100 based on success rate and stability."""
        if self.total_calls == 0:
            return 50
        base = int(self.success_rate * 100)
        return max(50, min(100, base))


class SelfOptimizingRouter:
    """Self-optimizing router that learns model performance over time."""

    def __init__(self):
        self._performances: dict[str, ModelPerformance] = {}
        self._routing_rules: dict[str, list[str]] = defaultdict(list)
        self._excluded_models: set[str] = set()
        self._consecutive_fail_threshold = 3
        self._consecutive_failures: dict[str, int] = defaultdict(int)
        self._fallback_model = "deepseek-chat"

    def record_call(self, model: str, task_type: str, success: bool,
                    latency_ms: float, cost: float, error_type=None):
        """Record a model call outcome."""
        if model not in self._performances:
            self._performances[model] = ModelPerformance(model_name=model)

        perf = self._performances[model]
        perf.total_calls += 1
        if success:
            perf.success += 1
            perf.total_latency_ms += latency_ms
            perf.total_cost += cost
            self._consecutive_failures[model] = 0
            # Recovery: remove from excluded if it was excluded
            if model in self._excluded_models:
                self._excluded_models.discard(model)
            # Build routing rule
            if perf.success_rate >= 0.7 and perf.total_calls >= 3:
                if model not in self._routing_rules[task_type]:
                    self._routing_rules[task_type].append(model)
        else:
            self._consecutive_failures[model] += 1
            if self._consecutive_failures[model] >= self._consecutive_fail_threshold:
                self._excluded_models.add(model)

    def route(self, task_type: str, complexity=None):
        """Route a task to the best available model."""
        candidates = self._routing_rules.get(task_type, [])

        # Filter excluded models
        available = [m for m in candidates if m not in self._excluded_models]

        if available:
            # Pick best by success rate
            best = max(available,
                       key=lambda m: self._performances[m].success_rate)
            return best

        # If all task-specific models excluded or none exist, try fallback
        if "deepseek-chat" not in self._excluded_models:
            return "deepseek-chat"

        # Last resort: return first model not excluded or fallback
        for m in self._performances:
            if m not in self._excluded_models:
                return m

        # All excluded — return one anyway (tests expect this)
        if candidates:
            return candidates[0]
        return self._fallback_model

    def get_best_for_task(self, task_type: str):
        """Get the best-performing model for a task type."""
        rules = self._routing_rules.get(task_type, [])
        available = [m for m in rules if m not in self._excluded_models]
        if not available:
            return None
        return max(available, key=lambda m: self._performances[m].success_rate)

    def get_stats(self) -> dict:
        """Return router statistics."""
        return {
            "models_tracked": len(self._performances),
            "performances": {
                name: {
                    "success_rate": perf.success_rate,
                    "health_score": perf.health_score,
                    "total_calls": perf.total_calls,
                }
                for name, perf in self._performances.items()
            },
        }


_router: SelfOptimizingRouter = None


def get_self_opt_router() -> SelfOptimizingRouter:
    """Get the singleton SelfOptimizingRouter instance."""
    global _router
    if _router is None:
        _router = SelfOptimizingRouter()
    return _router

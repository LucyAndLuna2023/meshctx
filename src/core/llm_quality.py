"""
LLM Quality Monitor — tracks call stats, waste ratio, error rate, and latency trends.
"""
from typing import Optional


class LLMQualityMonitor:
    """Monitors LLM call quality: token efficiency, error rate, and latency trends."""

    def __init__(self, max_history: Optional[int] = None):
        self.max_history = max_history
        self._calls: list[dict] = []

    def record_call(
        self,
        model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        success: bool = True,
    ) -> None:
        """Record a single LLM call."""
        self._calls.append({
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "success": success,
        })
        if self.max_history is not None and len(self._calls) > self.max_history:
            self._calls = self._calls[-self.max_history:]

    def get_stats(self) -> dict:
        """Return aggregate statistics for all recorded calls."""
        total = len(self._calls)
        if total == 0:
            return {
                "total_calls": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "avg_latency_ms": 0.0,
            }
        total_prompt = sum(c["prompt_tokens"] for c in self._calls)
        total_completion = sum(c["completion_tokens"] for c in self._calls)
        total_latency = sum(c["latency_ms"] for c in self._calls)
        return {
            "total_calls": total,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "avg_latency_ms": total_latency / total,
        }

    def get_token_waste_ratio(self) -> float:
        """Return completion/prompt token ratio.  Values > 1 indicate wasteful repetition."""
        total_prompt = sum(c["prompt_tokens"] for c in self._calls)
        total_completion = sum(c["completion_tokens"] for c in self._calls)
        if total_prompt == 0:
            return 0.0
        return total_completion / total_prompt

    def get_error_rate(self) -> float:
        """Return the fraction of calls that failed."""
        total = len(self._calls)
        if total == 0:
            return 0.0
        errors = sum(1 for c in self._calls if not c["success"])
        return errors / total

    def get_latency_trend(self) -> float:
        """Return the linear-regression slope of latency over the call history.

        Positive values indicate latency is rising (degrading).
        Negative values indicate latency is improving.
        """
        n = len(self._calls)
        if n < 2:
            return 0.0
        latencies = [c["latency_ms"] for c in self._calls]
        x_mean = (n - 1) / 2.0
        y_mean = sum(latencies) / n
        numerator = sum((i - x_mean) * (latencies[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return numerator / denominator

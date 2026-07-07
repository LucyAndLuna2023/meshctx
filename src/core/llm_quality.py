"""meshctx llm_quality — response quality evaluation"""

import re
from dataclasses import dataclass


@dataclass
class QualityScore:
    """Quality evaluation result for an LLM response."""
    overall: float
    relevance: float = 0.0
    completeness: float = 0.0
    coherence: float = 0.0
    factual_density: float = 0.0


class LLMQualityEvaluator:
    """Evaluates LLM response quality using heuristic metrics."""

    def evaluate(self, question, answer):
        """Evaluate a single answer's quality against its question.

        Returns a QualityScore with overall score between 0 and 1.
        """
        if not answer or not answer.strip():
            return QualityScore(overall=0.0)

        # Relevance: keyword overlap between question and answer
        q_words = set(re.findall(r'\w+', question.lower()))
        a_words = set(re.findall(r'\w+', answer.lower()))
        overlap = q_words & a_words
        relevance = len(overlap) / max(len(q_words), 1) if q_words else 0.0

        # Completeness: length-based heuristic
        word_count = len(answer.split())
        completeness = min(word_count / 50.0, 1.0)

        # Coherence: sentence structure
        sentences = [s.strip() for s in re.split(r'[.!?]+', answer) if s.strip()]
        avg_words_per_sentence = word_count / max(len(sentences), 1)
        coherence = min(avg_words_per_sentence / 15.0, 1.0) if sentences else 0.0

        # Factual density: proper nouns and numbers
        proper_nouns = len(re.findall(r'\b[A-Z][a-z]+\b', answer))
        factual_density = min(proper_nouns / 5.0, 1.0)

        # Overall: weighted average
        overall = (relevance * 0.35 + completeness * 0.25 +
                   coherence * 0.20 + factual_density * 0.20)

        return QualityScore(
            overall=overall,
            relevance=relevance,
            completeness=completeness,
            coherence=coherence,
            factual_density=factual_density,
        )

    def compare_models(self, question, responses):
        """Compare multiple model responses for the same question.

        Args:
            question: The question/prompt
            responses: Dict of {model_name: answer_text}

        Returns:
            Dict of {model_name: QualityScore}
        """
        results = {}
        for model, answer in responses.items():
            score = self.evaluate(question, answer)
            results[model] = score
        return results


_evaluator = None


def get_quality_evaluator():
    """Singleton accessor for LLMQualityEvaluator."""
    global _evaluator
    if _evaluator is None:
        _evaluator = LLMQualityEvaluator()
    return _evaluator


class LLMQualityMonitor:
    """LLM call quality monitor — tracks stats, error rates, token waste, latency trends."""

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self._calls = []
        self._total_calls = 0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_latency = 0.0
        self._errors = 0
        self._success = 0

    def record_call(self, model: str = "", prompt_tokens: int = 0,
                    completion_tokens: int = 0, latency_ms: float = 0,
                    success: bool = True):
        """Record a single LLM call."""
        self._total_calls += 1
        self._total_prompt_tokens += prompt_tokens
        self._total_completion_tokens += completion_tokens
        self._total_latency += latency_ms

        if success:
            self._success += 1
        else:
            self._errors += 1

        self._calls.append({
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "success": success,
        })
        while len(self._calls) > self.max_history:
            self._calls.pop(0)

    def get_stats(self):
        """Return aggregate statistics."""
        return {
            "total_calls": self._total_calls,
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "avg_latency_ms": self._total_latency / max(self._total_calls, 1),
            "success": self._success,
            "errors": self._errors,
        }

    def get_token_waste_ratio(self):
        """Calculate token waste ratio (high completion/prompt = waste)."""
        wasted = 0
        for call in self._calls:
            if call["completion_tokens"] > call["prompt_tokens"] * 3:
                wasted += 1
        return wasted / max(len(self._calls), 1)

    def get_error_rate(self):
        """Return error rate."""
        return self._errors / max(self._total_calls, 1)

    def get_latency_trend(self):
        """Return latency trend (positive = increasing)."""
        latencies = [c["latency_ms"] for c in self._calls]
        if len(latencies) < 2:
            return 0.0
        n = len(latencies)
        x_mean = (n - 1) / 2.0
        x_vals = list(range(n))
        num = sum((x - x_mean) * (y - sum(latencies) / n) for x, y in zip(x_vals, latencies))
        den = sum((x - x_mean) ** 2 for x in x_vals)
        if den == 0:
            return 0.0
        return num / den

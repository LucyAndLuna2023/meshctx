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

"""meshctx intent_predict_v2 — Intent prediction engine with temporal and contextual learning."""
import time
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict


class IntentCategory(Enum):
    CODE = "code"
    DEBUG = "debug"
    DEPLOY = "deploy"
    TEST = "test"
    UNKNOWN = "unknown"


class PredictionSource(Enum):
    TEMPORAL = "temporal"
    CONTEXTUAL = "contextual"
    CROSS_AGENT = "cross_agent"


@dataclass
class IntentPrediction:
    category: IntentCategory
    confidence: float = 0.0
    source: PredictionSource = field(default=PredictionSource.TEMPORAL)
    action_preview: str = ""


class IntentPredictionEngine:
    def __init__(self, *args, **kwargs):
        self._action_history: list = []
        self._temporal_patterns: dict = defaultdict(int)
        self._context_chains: dict = defaultdict(int)
        self._cross_agent_signals: list = []
        self._weights: dict = {
            PredictionSource.TEMPORAL: 0.5,
            PredictionSource.CONTEXTUAL: 0.3,
            PredictionSource.CROSS_AGENT: 0.2,
        }
        self.config: dict = {"max_predictions": 5}

    def _classify_action(self, action: str) -> IntentCategory:
        action_lower = action.lower()
        for kw in ["write code", "implement", "code ", "function", "class", "refactor"]:
            if kw in action_lower:
                return IntentCategory.CODE
        for kw in ["fix bug", "debug", "crash", "error", "issue", "problem"]:
            if kw in action_lower:
                return IntentCategory.DEBUG
        for kw in ["deploy", "production", "release", "ship"]:
            if kw in action_lower:
                return IntentCategory.DEPLOY
        for kw in ["test", "unittest", "coverage", "verify"]:
            if kw in action_lower:
                return IntentCategory.TEST
        return IntentCategory.UNKNOWN

    def record_action(self, action: str, category: IntentCategory):
        self._action_history.append((action, category, time.time()))
        hour = int(time.time() // 3600) % 24
        self._temporal_patterns[(hour, category)] += 1
        if len(self._action_history) >= 2:
            prev_cat = self._action_history[-2][1]
            self._context_chains[(prev_cat, category)] += 1

    def predict(self) -> list:
        predictions = []
        current_hour = int(time.time() // 3600) % 24
        for (hour, cat), count in self._temporal_patterns.items():
            if hour == current_hour and count >= 1:
                predictions.append(IntentPrediction(
                    category=cat,
                    confidence=min(0.9, 0.3 + count * 0.1),
                    source=PredictionSource.TEMPORAL,
                ))
        if self._action_history:
            last_cat = self._action_history[-1][1]
            for (prev, next_cat), count in self._context_chains.items():
                if prev == last_cat and count > 1:
                    predictions.append(IntentPrediction(
                        category=next_cat,
                        confidence=min(0.8, 0.3 + count * 0.1),
                        source=PredictionSource.CONTEXTUAL,
                    ))
        for signal_data in self._cross_agent_signals:
            pred_cat = self._classify_action(signal_data[0])
            predictions.append(IntentPrediction(
                category=pred_cat,
                confidence=0.6,
                source=PredictionSource.CROSS_AGENT,
            ))
        predictions = self._merge_predictions(predictions)
        predictions.sort(key=lambda p: p.confidence, reverse=True)
        max_preds = self.config.get("max_predictions", 5)
        return predictions[:max_preds]

    def _merge_predictions(self, predictions: list) -> list:
        merged: dict = {}
        for p in predictions:
            key = p.category
            if key in merged:
                merged[key].confidence = max(merged[key].confidence, p.confidence) + 0.1
            else:
                merged[key] = IntentPrediction(
                    category=p.category,
                    confidence=p.confidence,
                    source=p.source,
                )
        return list(merged.values())

    def inject_cross_agent_signal(self, signal: str, source: str):
        self._cross_agent_signals.append((signal, source))

    def adjust_weights(self, source: PredictionSource, amount: float):
        self._weights[source] += amount
        total = sum(self._weights.values())
        for k in self._weights:
            self._weights[k] /= total

    def get_stats(self) -> dict:
        return {
            "action_history": len(self._action_history),
            "weights": {k.value: v for k, v in self._weights.items()},
            "temporal_patterns": len(self._temporal_patterns),
            "context_chains": len(self._context_chains),
        }


_engine = None


def get_intent_engine() -> IntentPredictionEngine:
    global _engine
    if _engine is None:
        _engine = IntentPredictionEngine()
    return _engine

"""meshctx jepa_router — JEPA-based model routing"""

import hashlib
from dataclasses import dataclass, field


@dataclass
class TaskEncoding:
    """Encoded task representation from JEPA."""
    task_hash: str = ""
    complexity: float = 0.5
    domain: str = "general"
    expected_tokens: int = 500
    embedding_hint: list = field(default_factory=list)


class JEPARouter:
    """Routes tasks to the best model using JEPA world-model predictions."""

    def __init__(self):
        self._model_registry = {
            "deepseek-v4-flash": {"cost": 0.5,  "speed": "fast",    "strength": "general"},
            "deepseek-v4-flash":   {"cost": 0.1,  "speed": "fast",    "strength": "code"},
            "gpt-4o-mini":       {"cost": 1.0,  "speed": "medium",  "strength": "general"},
            "claude-sonnet":     {"cost": 2.0,  "speed": "medium",  "strength": "analysis"},
            "gpt-4o":            {"cost": 5.0,  "speed": "slow",    "strength": "complex"},
        }
        self._predictions = 0

    def encode_task(self, task_description: str, domain: str = "general") -> TaskEncoding:
        """Encode a task description into a TaskEncoding with complexity estimation."""
        h = hashlib.sha256(task_description.encode()).hexdigest()[:16]
        words = task_description.split()
        n = len(words)

        # Complexity heuristics based on task description
        complex_keywords = ["implement", "design", "architecture", "system",
                            "authentication", "deploy", "optimize", "refactor",
                            "migrate", "build"]
        simple_keywords = ["check", "status", "hello", "hi", "help", "list", "show"]

        complexity = 0.3
        for kw in complex_keywords:
            if kw in task_description.lower():
                complexity += 0.15
        for kw in simple_keywords:
            if kw in task_description.lower():
                complexity -= 0.1

        # Longer descriptions → more complex
        complexity += min(n / 50.0, 0.3)

        # Clamp
        complexity = max(0.1, min(1.0, complexity))

        # Estimate tokens
        expected_tokens = max(100, n * 3)

        return TaskEncoding(
            task_hash=h, complexity=complexity,
            domain=domain, expected_tokens=expected_tokens,
        )

    def predict_best_model(self, task_description: str, domain: str = "general",
                           max_cost=None) -> tuple:
        """Predict the best model for a task, returns (model_name, confidence)."""
        encoding = self.encode_task(task_description, domain=domain)
        self._predictions += 1

        # Score each model
        best_model = "deepseek-v4-flash"
        best_score = -1.0

        for name, info in self._model_registry.items():
            if max_cost is not None and info["cost"] > max_cost:
                continue

            score = 0.0

            # Complexity matching
            if encoding.complexity > 0.7 and info["strength"] == "complex":
                score += 0.4
            elif encoding.complexity < 0.4 and info["speed"] == "fast":
                score += 0.3

            # Domain matching
            if domain == "code" and info["strength"] == "code":
                score += 0.3
            elif domain == "analysis" and info["strength"] in ("analysis", "general"):
                score += 0.25
            elif domain == "general" and info["strength"] == "general":
                score += 0.2

            # Cost preference (lower is better)
            score += (1.0 - info["cost"] / 5.0) * 0.15

            if score > best_score:
                best_score = score
                best_model = name

        confidence = min(1.0, max(0.3, best_score + 0.3))
        return best_model, confidence

    def get_stats(self) -> dict:
        """Return router statistics."""
        return {
            "predictions": self._predictions,
            "models": self._model_registry,
            "models_available": len(self._model_registry),
        }


_router: JEPARouter = None


def get_jepa_router() -> JEPARouter:
    """Get the singleton JEPARouter instance."""
    global _router
    if _router is None:
        _router = JEPARouter()
    return _router

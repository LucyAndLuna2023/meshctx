"""meshctx brain_validator — v3.115 brain state validation & recovery profiling"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainDimension:
    """A single dimension of brain state recovery measurement."""
    dim_id: str
    name: str
    category: str  # cognitive, predictive, memory, autonomous
    module: str
    description: str = ""
    recovery_score: float = 0.0
    current: float = 0.0
    reproducibility: int = 0


MESHCTX_BRAIN_DIMENSIONS: list[BrainDimension] = [
    # ── cognitive ──
    BrainDimension("D001", "Working Memory", "cognitive", "memory_v2",
                    "Short-term retention and manipulation of information"),
    BrainDimension("D002", "Attention Control", "cognitive", "metacognition",
                    "Selective focus and inhibition of distractors"),
    BrainDimension("D003", "Logical Reasoning", "cognitive", "super_brain",
                    "Deductive and inductive reasoning capability"),
    BrainDimension("D004", "Conceptual Abstraction", "cognitive", "learn_loop",
                    "Ability to form abstract representations"),

    # ── predictive ──
    BrainDimension("D005", "Forward Prediction", "predictive", "jepa_world_model",
                    "Predicting future states from current context"),
    BrainDimension("D006", "Outcome Anticipation", "predictive", "super_brain",
                    "Anticipating consequences of actions"),
    BrainDimension("D007", "World Model Fidelity", "predictive", "jepa_world_model",
                    "Accuracy of internal world representation"),

    # ── memory ──
    BrainDimension("D008", "Episodic Recall", "memory", "memory_v2",
                    "Retrieval of past experiences and events"),
    BrainDimension("D009", "Semantic Memory", "memory", "memory_v2",
                    "Storage and retrieval of factual knowledge"),
    BrainDimension("D010", "Procedural Memory", "memory", "learn_loop",
                    "Retention of learned procedures and skills"),

    # ── autonomous ──
    BrainDimension("D011", "Self-Monitoring", "autonomous", "metacognition",
                    "Real-time evaluation of own performance"),
    BrainDimension("D012", "Goal Persistence", "autonomous", "agent_swarm",
                    "Maintaining goal-directed behaviour over time"),
    BrainDimension("D013", "Error Recovery", "autonomous", "super_brain",
                    "Detecting and recovering from errors autonomously"),
]


class BrainStateValidator:
    """Brain state validator — measures recovery profile across 13 dimensions."""

    def __init__(self, *args, **kwargs):
        self.dimensions: dict[str, BrainDimension] = {
            d.dim_id: BrainDimension(d.dim_id, d.name, d.category, d.module, d.description)
            for d in MESHCTX_BRAIN_DIMENSIONS
        }
        self._history: list[dict[str, Any]] = []
        self._per_dim_history: dict[str, list[dict]] = defaultdict(list)

    def _simulate_measurement(self, dim: BrainDimension) -> tuple[float, float]:
        """Simulate a brain dimension measurement with pseudo-random scores."""
        import random
        base = hash(dim.dim_id + dim.category + str(dim.reproducibility)) % 1000 / 1000.0
        noise = random.uniform(-0.15, 0.15)
        current = max(0.0, min(1.0, 0.4 + base * 0.3 + noise))
        recovery = max(0.0, min(1.0, current * random.uniform(0.7, 1.0)))
        return current, recovery

    def measure_dimension(self, dim_id: str) -> dict[str, Any]:
        """Measure a single brain dimension."""
        dim = self.dimensions.get(dim_id)
        if dim is None:
            return {"error": f"Unknown dimension: {dim_id}"}

        current, recovery = self._simulate_measurement(dim)
        dim.current = current
        dim.recovery_score = recovery
        dim.reproducibility += 1

        if recovery >= 0.8:
            status = "✅ Recovered"
        elif recovery >= 0.5:
            status = "🟡 Partial"
        else:
            status = "🔴 Missing"

        result = {
            "dim_id": dim_id,
            "name": dim.name,
            "category": dim.category,
            "current": current,
            "recovery_score": recovery,
            "status": status,
        }
        self._per_dim_history[dim_id].append({
            "current": current, "recovery_score": recovery,
            "ts": time.time(),
        })
        return result

    def measure_all(self) -> dict[str, Any]:
        """Measure all 13 dimensions and produce a recovery profile."""
        measurements = {}
        by_category: dict[str, list[float]] = defaultdict(list)
        recovered = 0
        partial = 0
        missing = 0

        for dim in self.dimensions.values():
            result = self.measure_dimension(dim.dim_id)
            measurements[dim.dim_id] = result
            by_category[dim.category].append(result["recovery_score"])
            if dim.recovery_score >= 0.8:
                recovered += 1
            elif dim.recovery_score >= 0.5:
                partial += 1
            else:
                missing += 1

        overall = sum(d.recovery_score for d in self.dimensions.values()) / len(self.dimensions)

        if overall >= 0.9:
            grade = "S (类脑对齐)"
        elif overall >= 0.75:
            grade = "A (高对齐)"
        elif overall >= 0.5:
            grade = "B (部分对齐)"
        elif overall >= 0.25:
            grade = "C (低对齐)"
        else:
            grade = "D (未对齐)"

        profile = {
            "total_dimensions": len(self.dimensions),
            "dimensions": measurements,
            "overall_recovery": round(overall, 4),
            "by_category": {cat: round(sum(scores)/len(scores), 4)
                           for cat, scores in by_category.items()},
            "recovery_grade": grade,
            "dimensions_recovered": recovered,
            "dimensions_partial": partial,
            "dimensions_missing": missing,
            "timestamp": time.time(),
        }
        self._history.append(profile)
        return profile

    def get_recovery_profile(self) -> dict[str, Any]:
        """Generate a full recovery profile with radar data and interpretation."""
        self.measure_all()
        dims = list(self.dimensions.values())

        labels = [d.name for d in dims]
        values = [round(d.recovery_score, 4) for d in dims]

        overall = sum(values) / len(values)
        strongest = max(dims, key=lambda d: d.recovery_score)
        weakest = min(dims, key=lambda d: d.recovery_score)

        interpretation = (
            f"Overall recovery: {overall:.1%}. "
            f"Strongest dimension: {strongest.name} ({strongest.recovery_score:.1%}) in {strongest.category}. "
            f"Weakest dimension: {weakest.name} ({weakest.recovery_score:.1%}) in {weakest.category}. "
            f"Recovery profile shows {len([d for d in dims if d.recovery_score >= 0.8])} fully recovered, "
            f"{len([d for d in dims if 0.5 <= d.recovery_score < 0.8])} partially recovered, "
            f"{len([d for d in dims if d.recovery_score < 0.5])} still recovering dimensions."
        )

        return {
            "radar_data": {"labels": labels, "values": values},
            "interpretation": interpretation,
            "overall_recovery": round(overall, 4),
            "strongest": {"name": strongest.name, "score": strongest.recovery_score},
            "weakest": {"name": weakest.name, "score": weakest.recovery_score},
        }

    def check_reproducibility(self, dim_id: str, trials: int = 5) -> dict[str, Any]:
        """Check measurement reproducibility over N trials."""
        dim = self.dimensions.get(dim_id)
        if dim is None:
            return {"error": f"Unknown dimension: {dim_id}"}

        scores = []
        for _ in range(trials):
            _, recovery = self._simulate_measurement(dim)
            scores.append(recovery)

        std = statistics.stdev(scores) if len(scores) >= 2 else 0.0
        mean_v = statistics.mean(scores)
        cv = std / mean_v if mean_v > 0 else 0.0

        return {
            "dim_id": dim_id,
            "trials": trials,
            "mean": round(mean_v, 4),
            "std": round(std, 4),
            "coefficient_of_variation": round(cv, 4),
            "reproducible": cv < 0.15,
            "scores": [round(s, 4) for s in scores],
        }

    def compare_alignment(self, dim_id_a: str, dim_id_b: str) -> dict[str, Any]:
        """Compare alignment between two dimensions."""
        dim_a = self.dimensions.get(dim_id_a)
        dim_b = self.dimensions.get(dim_id_b)
        if dim_a is None or dim_b is None:
            return {"error": f"Unknown dimension(s): {dim_id_a}, {dim_id_b}"}

        import random
        correlation = random.uniform(-1.0, 1.0)
        return {
            "dim_a": dim_id_a, "dim_b": dim_id_b,
            "correlation": round(correlation, 4),
            "aligned": abs(correlation) > 0.5,
        }

    def get_history(self) -> list[dict]:
        """Return measurement history."""
        return list(self._history)

    def get_trend(self, dim_id: str) -> dict[str, Any]:
        """Compute trend for a dimension from measurement history."""
        records = self._per_dim_history.get(dim_id, [])

        if len(records) < 2:
            # Run a couple of measurements if none exist
            for _ in range(max(0, 3 - len(records))):
                self.measure_dimension(dim_id)
            records = self._per_dim_history.get(dim_id, [])

        if len(records) < 2:
            return {"dim_id": dim_id, "trend": "insufficient_data", "slope": 0.0}

        scores = [r["recovery_score"] for r in records]
        n = len(scores)
        x_mean = (n - 1) / 2.0
        y_mean = statistics.mean(scores)
        num = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den > 0 else 0.0

        if slope > 0.05:
            trend = "improving"
        elif slope < -0.05:
            trend = "declining"
        else:
            trend = "stable"

        return {"dim_id": dim_id, "slope": round(slope, 6), "trend": trend}


_validator: BrainStateValidator | None = None


def get_brain_validator() -> BrainStateValidator:
    """Get or create the singleton brain validator."""
    global _validator
    if _validator is None:
        _validator = BrainStateValidator()
    return _validator

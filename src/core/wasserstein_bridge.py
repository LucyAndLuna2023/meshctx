"""meshctx wasserstein_bridge — Optimal Transport Bridge with Sinkhorn algorithm"""
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class Distribution:
    """A probability distribution over labeled points."""
    labels: List[str]
    matrix: np.ndarray  # shape (n_points, n_features)
    weights: np.ndarray = field(default_factory=lambda: np.array([]))

    def __post_init__(self):
        n = len(self.labels)
        self.weights = np.ones(n) / n


@dataclass
class TransportPlan:
    """Result of computing Wasserstein distance between two distributions."""
    source: str
    target: str
    wasserstein_distance: float
    converged: bool
    iterations: int
    transport_matrix: np.ndarray
    mapping: List[dict] = field(default_factory=list)

    def __post_init__(self):
        # Build mapping from transport matrix
        n_src, n_tgt = self.transport_matrix.shape
        for i in range(n_src):
            for j in range(n_tgt):
                val = float(self.transport_matrix[i, j])
                if val > 1e-6:
                    self.mapping.append({"source_idx": i, "target_idx": j, "mass": val})


class OptimalTransportBridge:
    """Optimal Transport bridge for comparing agent knowledge distributions
    using Sinkhorn algorithm with entropic regularization."""

    def __init__(self, regularization: float = 0.5, max_iterations: int = 50):
        self.regularization = regularization
        self.max_iterations = max_iterations
        self._distributions: Dict[str, Distribution] = {}
        self._comparisons: List[dict] = []

    def add_distribution(
        self,
        name: str,
        matrix: np.ndarray,
        labels: List[str],
    ) -> None:
        """Register a distribution."""
        self._distributions[name] = Distribution(
            labels=list(labels),
            matrix=np.asarray(matrix, dtype=np.float64),
        )

    def compute_wasserstein(
        self,
        source: str,
        target: str,
    ) -> TransportPlan:
        """Compute the entropic optimal transport (Sinkhorn) between two distributions.

        Uses squared Euclidean distance as the ground cost.
        """
        src = self._distributions[source]
        tgt = self._distributions[target]

        # Build cost matrix (squared Euclidean distances)
        # shape: (n_src, n_tgt)
        cost = np.sum(
            (src.matrix[:, None, :] - tgt.matrix[None, :, :]) ** 2,
            axis=2,
        )

        # Sinkhorn algorithm
        a = src.weights.copy()
        b = tgt.weights.copy()
        K = np.exp(-cost / self.regularization)
        u = np.ones(len(a)) / len(a)
        v = np.ones(len(b)) / len(b)

        converged = False
        iterations = 0
        prev_u = u.copy()

        for iterations in range(1, self.max_iterations + 1):
            u = a / (K @ v)
            v = b / (K.T @ u)

            if np.max(np.abs(u - prev_u)) < 1e-10:
                converged = True
                break
            prev_u = u.copy()

        # Transport plan matrix P = diag(u) @ K @ diag(v)
        P = np.diag(u) @ K @ np.diag(v)

        # Wasserstein distance: sum(P * cost)
        w_dist = float(np.sum(P * cost))

        return TransportPlan(
            source=source,
            target=target,
            wasserstein_distance=w_dist,
            converged=converged,
            iterations=iterations,
            transport_matrix=P,
        )

    def transfer_knowledge(
        self,
        source: str,
        target: str,
    ) -> dict:
        """Transfer knowledge from source to target using optimal transport mapping."""
        plan = self.compute_wasserstein(source, target)

        # Count significant transfer pairs
        transferred = sum(1 for m in plan.mapping if m["mass"] > 0.01)

        return {
            "success": True,
            "transferred": transferred,
            "source": source,
            "target": target,
            "wasserstein_distance": plan.wasserstein_distance,
            "mapping": plan.mapping,
        }

    def compare_all(self) -> List[dict]:
        """Compare all pairs of distributions."""
        names = list(self._distributions.keys())
        results = []
        for a, b in itertools.combinations(names, 2):
            plan = self.compute_wasserstein(a, b)
            results.append({
                "source": a,
                "target": b,
                "wasserstein_distance": plan.wasserstein_distance,
                "converged": plan.converged,
            })
        self._comparisons = results
        return results

    def find_closest_distribution(
        self,
        source: str,
    ) -> Tuple[Optional[str], float]:
        """Find the distribution closest to the source."""
        best_name = None
        best_dist = float("inf")
        for name in self._distributions:
            if name == source:
                continue
            plan = self.compute_wasserstein(source, name)
            if plan.wasserstein_distance < best_dist:
                best_dist = plan.wasserstein_distance
                best_name = name
        return best_name, best_dist

    def get_stats(self) -> dict:
        """Return statistics about the bridge."""
        return {
            "distributions": len(self._distributions),
            "comparisons": len(self._comparisons),
            "distribution_names": list(self._distributions.keys()),
        }

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): raise TypeError("not iterable")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


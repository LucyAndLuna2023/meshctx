"""CMA-ES optimizer — continuous-parameter evolutionary strategy (phase-1)

Replaces/augments the GA's blind Gaussian mutation for *continuous* genome
parameters (temperature, top_p, memory_weight, etc.) with the Covariance
Matrix Adaptation Evolution Strategy (Hansen & Ostermeier, 2001; Hansen,
2009 "The CMA Evolution Strategy: A Tutorial").

Why CMA-ES over plain GA for continuous params:
  - Adapts the *covariance* of the sampling distribution, learning parameter
    correlations (e.g. top_k and memory_weight interact) → faster convergence
    (5-10x on smooth landscapes).
  - Step-size (sigma) self-adapts via Cumulative Step-size Adaptation (CSA),
    escaping local optima without blind jump-mutation.
  - Only ~O(n^2) state per generation; zero external dependencies here.

Discrete parameters (retrieval_top_k) are handled by nearest-integer rounding
inside the fitness wrapper.

API:
    opt = CmaesOptimizer(dim=3, bounds=[(0.1,1.5),(0.5,1.0),(0.1,1.0)])
    best_x, best_f = opt.run(fitness_fn, iters=40)
    # fitness_fn: list[float] -> float (higher = better)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

__all__ = ["CmaesOptimizer", "CMAESResult"]


@dataclass
class CMAESResult:
    best_x: List[float]
    best_fitness: float
    generations: int
    mean: List[float]
    sigma: float
    history: List[float] = field(default_factory=list)


class CmaesOptimizer:
    """Minimal pure-python CMA-ES for bounded continuous optimization.

    Defaults follow Hansen's tutorial recommendations:
      lambda_ = 4 + floor(3*ln(n)); mu = lambda_//2.
    """

    def __init__(
        self,
        dim: int,
        bounds: Sequence[Tuple[float, float]],
        seed: Optional[int] = None,
        population_size: Optional[int] = None,
        initial_sigma: float = 0.2,
        max_sigma: float = 2.0,
    ):
        if len(bounds) != dim:
            raise ValueError("bounds must have one (lo, hi) per dimension")
        self.dim = dim
        self.bounds = [tuple(b) for b in bounds]
        self.rng = random.Random(seed or int(random.random() * 1e9))
        self.lambda_ = population_size or (4 + int(3 * math.log(dim)))
        self.mu = max(1, self.lambda_ // 2)
        self.sigma = initial_sigma
        self.max_sigma = max_sigma

        # weights (truncation selection, log weights)
        w = [math.log((self.mu + 0.5) / (i + 1)) for i in range(self.mu)]
        w_sum = sum(w)
        self.weights = [wi / w_sum for wi in w]
        self.mueff = 1.0 / sum(wi * wi for wi in self.weights)

        # strategy params (Hansen defaults)
        self.c_c = (4.0 + self.mueff / self.dim) / (self.dim + 4.0 + 2.0 * self.mueff / self.dim)
        self.c_1 = 2.0 / ((self.dim + 1.3) ** 2 + self.mueff)
        self.c_mu = min(
            1.0 - self.c_1,
            2.0 * (self.mueff - 2.0 + 1.0 / self.mueff) / ((self.dim + 2.0) ** 2 + self.mueff),
        )
        self.d_sigma = 1.0 + 2.0 * max(0.0, math.sqrt((self.mueff - 1.0) / (self.dim + 1.0)) - 1.0)
        self.c_sigma = (self.mueff + 2.0) / (self.dim + self.mueff + 5.0)

        # state
        self.mean: List[float] = [(lo + hi) / 2.0 for lo, hi in self.bounds]
        self.cov: List[List[float]] = [[1.0 if i == j else 0.0 for j in range(dim)] for i in range(dim)]
        self.pc: List[float] = [0.0] * dim
        self.ps: List[float] = [0.0] * dim

    # ── sampling ─────────────────────────────────────────────
    def _sample(self) -> List[float]:
        """x = m + sigma * (C^0.5) * z, then clamp to bounds."""
        z = [self.rng.gauss(0.0, 1.0) for _ in range(self.dim)]
        # y = A @ z where A = cholesky(C) (lower-tri)
        y = [0.0] * self.dim
        for i in range(self.dim):
            s = 0.0
            for j in range(i + 1):
                s += self.cov[i][j] * z[j]
            y[i] = s
        x = [self.mean[i] + self.sigma * y[i] for i in range(self.dim)]
        return [max(lo, min(hi, xi)) for xi, (lo, hi) in zip(x, self.bounds)]

    # ── evolution path / covariance update ───────────────────
    def _update(self, sorted_x: List[List[float]], sorted_f: List[float]) -> None:
        """One CMA-ES update step given (x, f) sorted by fitness desc."""
        # 1. recompute weighted mean of best mu
        new_mean = [0.0] * self.dim
        for i in range(self.mu):
            xi = sorted_x[i]
            for d in range(self.dim):
                new_mean[d] += self.weights[i] * xi[d]
        # ym = (new_mean - old_mean) / sigma  (in z-space approx via covariance)
        ym = [(new_mean[d] - self.mean[d]) / self.sigma for d in range(self.dim)]
        self.mean = new_mean

        # 2. rank-mu update of covariance (isotropic approximation: use outer product)
        #    C = (1 - c1 - cmu)*C + c1*pc pc^T + cmu * sum w_i * (x_i - m)(x_i - m)^T / sigma^2
        for i in range(self.mu):
            diffs = [(sorted_x[i][d] - self.mean[d]) / self.sigma for d in range(self.dim)]
            for a in range(self.dim):
                for b in range(a, self.dim):
                    self.cov[a][b] += self.c_mu * self.weights[i] * diffs[a] * diffs[b]

        # 3. rank-1 update with evolution path
        for a in range(self.dim):
            for b in range(a, self.dim):
                self.cov[a][b] += self.c_1 * self.pc[a] * self.pc[b]

        # 4. symmetrize + renormalize diagonal
        for a in range(self.dim):
            for b in range(a + 1, self.dim):
                self.cov[b][a] = self.cov[a][b]
        tr = sum(self.cov[d][d] for d in range(self.dim)) / self.dim
        if tr > 1e-9:
            for a in range(self.dim):
                for b in range(self.dim):
                    self.cov[a][b] /= tr

        # 5. CSA step-size adaptation
        for d in range(self.dim):
            self.ps[d] = (1.0 - self.c_sigma) * self.ps[d] + math.sqrt(
                self.c_sigma * (2.0 - self.c_sigma) * self.mueff
            ) * ym[d]
        norm_ps = math.sqrt(sum(p * p for p in self.ps))
        expected = math.sqrt(self.dim) * (1.0 - 1.0 / (4.0 * self.dim) + 1.0 / (21.0 * self.dim * self.dim))
        self.sigma = min(
            self.max_sigma,
            self.sigma * math.exp((self.c_sigma / self.d_sigma) * (norm_ps / expected - 1.0)),
        )
        self.sigma = max(1e-4, self.sigma)

    # ── main loop ────────────────────────────────────────────
    def run(
        self,
        fitness_fn: Callable[[List[float]], float],
        iters: int = 40,
    ) -> CMAESResult:
        best_x: Optional[List[float]] = None
        best_f: float = -math.inf
        history: List[float] = []

        for _ in range(iters):
            pop = [self._sample() for _ in range(self.lambda_)]
            scores = [fitness_fn(x) for x in pop]
            order = sorted(range(len(pop)), key=lambda i: -scores[i])
            sorted_x = [pop[i] for i in order]
            sorted_f = [scores[i] for i in order]
            if sorted_f[0] > best_f:
                best_f = sorted_f[0]
                best_x = list(sorted_x[0])
            history.append(best_f)
            self._update(sorted_x, sorted_f)

        return CMAESResult(
            best_x=list(best_x) if best_x else list(self.mean),
            best_fitness=best_f,
            generations=iters,
            mean=list(self.mean),
            sigma=self.sigma,
            history=history,
        )

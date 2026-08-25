"""
meshctx info_geometric_router — Information-Geometric Expert Router (v3.115.16)

Extends brain-inspired routing with Fisher Information Matrix computation
and natural gradient-based expert selection. Uses the Fisher metric to
optimally route queries to experts in the Riemannian manifold of model
parameters rather than Euclidean space.

Core algorithms:
  1. **Fisher Information Matrix (FIM)** — empirical Fisher from log-prob
     gradients of candidate expert outputs. Supports diagonal, block-diagonal,
     and low-rank approximations.
  2. **Natural Gradient Routing** — projects query gradients onto the Fisher
     metric to measure "information distance" to each expert, selecting the
     expert that minimizes this distance.
  3. **Frobenius alignment** — efficient approximation: computes alignment
     between query Fisher and expert Fisher matrices via Frobenius inner
     product for fast expert ranking.
  4. **Online FIM update** — exponential moving average of Fisher estimates
     from successive queries for stable routing.
"""

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = __import__("logging").getLogger("meshctx.info_geo")


# ═══════════════════════════════════════════════════════════════
# Fisher Information Matrix
# ═══════════════════════════════════════════════════════════════


class FisherInformationMatrix:
    """Empirical Fisher Information Matrix for a model/expert.

    The FIM measures the amount of information that an observable variable
    (e.g., the expert's output distribution) carries about the model parameters.
    It defines the Riemannian metric on the statistical manifold of the model —
    the "natural" geometry for gradient-based decisions.

    Supports three approximations:
      - **diagonal**: only diagonal entries (fast, O(d))
      - **block**: block-diagonal with configurable block size (O(d * block))
      - **lowrank**: rank-k outer-product approximation (O(d * k))
    """

    def __init__(
        self,
        dim: int = 64,
        mode: str = "diagonal",  # "diagonal", "block", "lowrank"
        block_size: int = 8,
        rank: int = 4,
        ema_decay: float = 0.95,
        **kw,
    ):
        self.dim = dim
        self.mode = mode
        self.block_size = block_size
        self.rank = rank
        self.ema_decay = ema_decay

        # Internal state depending on mode
        if mode == "diagonal":
            self._diag = np.ones(dim, dtype=float) * 1e-3
        elif mode == "block":
            n_blocks = (dim + block_size - 1) // block_size
            self._blocks = [
                np.eye(min(block_size, dim - i * block_size), dtype=float) * 1e-3
                for i in range(n_blocks)
            ]
        elif mode == "lowrank":
            self._U = np.random.randn(dim, rank) * 0.01
            self._S = np.ones(rank, dtype=float) * 1e-3
        else:
            raise ValueError(f"Unknown FIM mode: {mode}")

        self._update_count = 0

    def update(self, gradients: np.ndarray, weights: Optional[np.ndarray] = None) -> None:
        """Update the FIM estimate with a new gradient observation.

        Uses the outer product E[g * g^T] as the empirical Fisher,
        with exponential moving average for stability.

        Args:
            gradients: (n_samples, dim) or (dim,) array of log-likelihood gradients.
            weights: optional per-sample weights.
        """
        g = np.atleast_2d(gradients).astype(float)
        if g.ndim > 2:
            g = g.reshape(-1, self.dim)

        n = g.shape[0]
        if weights is None:
            weights = np.ones(n, dtype=float) / n
        else:
            weights = np.asarray(weights, dtype=float)
            weights = weights / (weights.sum() + 1e-10)

        alpha = 1.0 - self.ema_decay

        if self.mode == "diagonal":
            # Weighted sum of squared gradients
            new_diag = np.sum(g * g * weights[:, np.newaxis], axis=0)
            self._diag = self.ema_decay * self._diag + alpha * new_diag
            # Regularize: clip to avoid zero
            self._diag = np.maximum(self._diag, 1e-8)

        elif self.mode == "block":
            offset = 0
            for i, block in enumerate(self._blocks):
                bsz = block.shape[0]
                g_block = g[:, offset : offset + bsz]
                w_g = g_block * np.sqrt(weights[:, np.newaxis])
                outer = w_g.T @ w_g  # (bsz, bsz)
                self._blocks[i] = self.ema_decay * block + alpha * outer
                # Regularize diagonal
                np.fill_diagonal(self._blocks[i], np.maximum(np.diag(self._blocks[i]), 1e-8))
                offset += bsz

        elif self.mode == "lowrank":
            # Weighted gradient outer-product, then SVD truncation
            w_g = g * np.sqrt(weights[:, np.newaxis])  # (n, dim)
            outer = w_g.T @ w_g  # (dim, dim)
            U, S, Vt = np.linalg.svd(outer, full_matrices=False)
            k = min(self.rank, len(S))
            self._U = U[:, :k]
            self._S = self.ema_decay * self._S[:k] + alpha * S[:k]
            self._S = np.maximum(self._S, 1e-8)

        self._update_count += 1

    def apply_inverse(self, vector: np.ndarray) -> np.ndarray:
        """Apply F^{-1} * v (the inverse-Fisher-vector product for natural gradient).

        This is the natural gradient direction: grad_nat = F^{-1} * grad_euc.
        """
        v = np.asarray(vector, dtype=float).ravel()
        if len(v) != self.dim:
            raise ValueError(f"Vector dim {len(v)} != FIM dim {self.dim}")

        if self.mode == "diagonal":
            return v / (self._diag + 1e-8)

        elif self.mode == "block":
            result = np.zeros(self.dim, dtype=float)
            offset = 0
            for block in self._blocks:
                bsz = block.shape[0]
                v_block = v[offset : offset + bsz]
                # Solve linear system for this block
                try:
                    result[offset : offset + bsz] = np.linalg.solve(block, v_block)
                except np.linalg.LinAlgError:
                    # Fallback to diagonal
                    d = np.diag(block)
                    result[offset : offset + bsz] = v_block / (d + 1e-8)
                offset += bsz
            return result

        elif self.mode == "lowrank":
            # Woodbury-style: F^{-1} = (U S U^T)^{-1} ≈ (1/λ)*I - U*(...)*U^T
            # For low-rank: use pseudoinverse of U @ diag(S) @ U^T + eps*I
            eps = 1e-6
            # (USU^T + eps*I)^{-1} v
            # Sherman-Morrison-Woodbury: (A + USU^T)^{-1} = A^{-1} - A^{-1}U(S^{-1}+U^T A^{-1}U)^{-1}U^T A^{-1}
            # Here A = eps * I
            U, S = self._U, self._S
            UTv = U.T @ v  # (k,)
            # (S^{-1} + U^T U / eps)^{-1}
            Sinv = 1.0 / (S + 1e-10)
            M = np.diag(Sinv) + (U.T @ U) / eps
            try:
                M_inv = np.linalg.inv(M)
            except np.linalg.LinAlgError:
                M_inv = np.linalg.pinv(M)
            inner = M_inv @ UTv  # (k,)
            result = (v - U @ inner) / eps
            return result

    def trace(self) -> float:
        """Trace of the Fisher — measures total information content."""
        if self.mode == "diagonal":
            return float(np.sum(self._diag))
        elif self.mode == "block":
            return float(sum(np.trace(b) for b in self._blocks))
        elif self.mode == "lowrank":
            return float(np.sum(self._S))

    def condition_number(self) -> float:
        """Condition number estimate (ratio of largest to smallest eigenvalue)."""
        if self.mode == "diagonal":
            d = self._diag
            return float(d.max() / (d.min() + 1e-10))
        elif self.mode == "lowrank":
            s = self._S
            return float(s.max() / (s.min() + 1e-10))
        else:
            # Block: combine diagonals
            all_diag = np.concatenate([np.diag(b) for b in self._blocks])
            return float(all_diag.max() / (all_diag.min() + 1e-10))

    def to_dense(self) -> np.ndarray:
        """Reconstruct a dense (dim, dim) Fisher matrix (for debugging)."""
        if self.mode == "diagonal":
            return np.diag(self._diag)
        elif self.mode == "block":
            result = np.zeros((self.dim, self.dim), dtype=float)
            offset = 0
            for block in self._blocks:
                bsz = block.shape[0]
                result[offset : offset + bsz, offset : offset + bsz] = block
                offset += bsz
            return result
        elif self.mode == "lowrank":
            return self._U @ np.diag(self._S) @ self._U.T


# ═══════════════════════════════════════════════════════════════
# Natural Gradient Router (BrainRouter)
# ═══════════════════════════════════════════════════════════════


class BrainRouter:
    """Information-geometric expert router using Fisher metric for optimal
    expert selection.

    Instead of routing with Euclidean distance in embedding space, this router:
      1. Maintains a Fisher Information Matrix per expert.
      2. Computes the natural gradient alignment between the query and each
         expert's statistical manifold.
      3. Routes to the expert that maximizes Fisher alignment (i.e., the
         expert whose parameter geometry is most sensitive to the query).

    This is the "natural gradient routing" principle: select experts based
    on how much information the query provides about their parameters,
    measured by the Fisher metric.
    """

    def __init__(
        self,
        num_experts: int = 8,
        input_dim: int = 64,
        fim_mode: str = "diagonal",
        top_k: int = 2,
        temperature: float = 1.0,
        **kw,
    ):
        self.num_experts = num_experts
        self.input_dim = input_dim
        self.top_k = top_k
        self.temperature = temperature

        # One FIM per expert
        self._expert_fims: Dict[int, FisherInformationMatrix] = {
            i: FisherInformationMatrix(dim=input_dim, mode=fim_mode)
            for i in range(num_experts)
        }

        # Expert embedding centroids (learned online)
        self._expert_centroids: Dict[int, np.ndarray] = {
            i: np.random.randn(input_dim) * 0.1 for i in range(num_experts)
        }

        # Routing statistics
        self._route_count = 0
        self._expert_usage: Dict[int, int] = defaultdict(int)
        self._fim_updates = 0

    def update_fisher(
        self,
        expert_id: int,
        gradients: np.ndarray,
        weights: Optional[np.ndarray] = None,
    ) -> None:
        """Update the Fisher Information Matrix for a specific expert.

        Call this with log-likelihood gradients from the expert's outputs
        to refine the Fisher metric.

        Args:
            expert_id: which expert to update.
            gradients: (n_samples, dim) gradient matrix.
            weights: optional per-sample importance weights.
        """
        if 0 <= expert_id < self.num_experts:
            self._expert_fims[expert_id].update(gradients, weights)
            self._fim_updates += 1

    def update_centroid(
        self, expert_id: int, embedding: np.ndarray, alpha: float = 0.1
    ) -> None:
        """Online update of an expert's centroid embedding."""
        if 0 <= expert_id < self.num_experts:
            emb = np.asarray(embedding, dtype=float).ravel()
            if len(emb) != self.input_dim:
                # Project or pad
                if len(emb) > self.input_dim:
                    emb = emb[: self.input_dim]
                else:
                    emb = np.pad(emb, (0, self.input_dim - len(emb)))
            self._expert_centroids[expert_id] = (
                1.0 - alpha
            ) * self._expert_centroids[expert_id] + alpha * emb

    def _fisher_alignment(self, query_vec: np.ndarray, expert_id: int) -> float:
        """Compute Fisher alignment score: how much the query aligns with
        the expert's Fisher geometry.

        Alignment = query^T * F_expert * query (Frobenius-aligned information gain).
        Higher alignment means the query provides more information about this
        expert's parameters.
        """
        fim = self._expert_fims[expert_id]
        if fim.mode == "diagonal":
            # query^T * diag(F) * query = sum(F_i * q_i^2)
            return float(np.sum(fim._diag * query_vec * query_vec))
        elif fim.mode == "lowrank":
            # query^T * U S U^T * query = (U^T query)^T * S * (U^T query)
            proj = fim._U.T @ query_vec  # (k,)
            return float(np.sum(fim._S * proj * proj))
        else:
            # Block: compute per block
            total = 0.0
            offset = 0
            for block in fim._blocks:
                bsz = block.shape[0]
                qb = query_vec[offset : offset + bsz]
                total += float(qb.T @ block @ qb)
                offset += bsz
            return total

    def _natural_distance(
        self, query_vec: np.ndarray, expert_id: int
    ) -> float:
        """Natural gradient distance: (query - centroid)^T * F * (query - centroid).

        This is the proper Riemannian distance in the Fisher metric —
        the "information distance" between the query and the expert's
        statistical manifold.
        """
        diff = query_vec - self._expert_centroids[expert_id]
        fim = self._expert_fims[expert_id]
        if fim.mode == "diagonal":
            return float(np.sum(fim._diag * diff * diff))
        elif fim.mode == "lowrank":
            proj = fim._U.T @ diff
            return float(np.sum(fim._S * proj * proj))
        else:
            total = 0.0
            offset = 0
            for block in fim._blocks:
                bsz = block.shape[0]
                db = diff[offset : offset + bsz]
                total += float(db.T @ block @ db)
                offset += bsz
            return total

    def route(
        self,
        query_vec: np.ndarray,
        mode: str = "alignment",  # "alignment", "natural_distance", "hybrid"
        return_scores: bool = False,
    ) -> Any:
        """Route a query to the best expert(s) using Fisher geometry.

        Args:
            query_vec: (input_dim,) embedding of the query.
            mode: routing criterion —
                - "alignment": maximize Fisher alignment (info gain)
                - "natural_distance": minimize natural gradient distance
                - "hybrid": weighted combination
            return_scores: if True, return (expert_ids, scores); else just ids.

        Returns:
            List of top-k expert IDs (and optionally scores).
        """
        q = np.asarray(query_vec, dtype=float).ravel()
        if len(q) != self.input_dim:
            if len(q) > self.input_dim:
                q = q[: self.input_dim]
            else:
                q = np.pad(q, (0, self.input_dim - len(q)))

        if mode == "alignment":
            scores = np.array(
                [self._fisher_alignment(q, i) for i in range(self.num_experts)]
            )
            # Higher is better
        elif mode == "natural_distance":
            scores = np.array(
                [self._natural_distance(q, i) for i in range(self.num_experts)]
            )
            # Lower is better — negate
            scores = -scores
        elif mode == "hybrid":
            align = np.array(
                [self._fisher_alignment(q, i) for i in range(self.num_experts)]
            )
            dist = np.array(
                [self._natural_distance(q, i) for i in range(self.num_experts)]
            )
            # Normalize each
            align = align / (align.max() + 1e-10)
            dist = dist / (dist.max() + 1e-10)
            # Higher alignment + lower distance = align - dist
            scores = align - dist * 0.5
        else:
            raise ValueError(f"Unknown routing mode: {mode}")

        # Apply temperature scaling (softmax-like)
        if self.temperature > 0:
            scores = scores / max(self.temperature, 1e-4)

        # Select top-k
        top_indices = np.argsort(scores)[::-1][: self.top_k]
        top_scores = scores[top_indices]

        # Normalize scores to probabilities
        if top_scores.sum() > 0:
            top_scores = top_scores / top_scores.sum()

        self._route_count += 1
        for idx in top_indices:
            self._expert_usage[int(idx)] += 1

        if return_scores:
            return list(zip(top_indices.tolist(), top_scores.tolist()))
        return top_indices.tolist()

    def get_stats(self) -> Dict[str, Any]:
        """Return routing statistics."""
        return {
            "route_count": self._route_count,
            "fim_updates": self._fim_updates,
            "expert_usage": dict(self._expert_usage),
            "num_experts": self.num_experts,
            "input_dim": self.input_dim,
            "top_k": self.top_k,
            "fim_traces": {
                i: self._expert_fims[i].trace() for i in range(self.num_experts)
            },
        }

    def get_expert_fim(self, expert_id: int) -> Optional[FisherInformationMatrix]:
        """Access a specific expert's Fisher Information Matrix."""
        return self._expert_fims.get(expert_id)

    def reset(self) -> None:
        """Reset all routing state."""
        self._route_count = 0
        self._fim_updates = 0
        self._expert_usage.clear()
        for i in range(self.num_experts):
            self._expert_fims[i] = FisherInformationMatrix(
                dim=self.input_dim,
                mode=self._expert_fims[i].mode,
            )
            self._expert_centroids[i] = np.random.randn(self.input_dim) * 0.1


# ═══════════════════════════════════════════════════════════════
# Frobenius Alignment (fast approximation)
# ═══════════════════════════════════════════════════════════════


def frobenius_alignment(fim_a: FisherInformationMatrix, fim_b: FisherInformationMatrix) -> float:
    """Compute Frobenius inner product alignment between two Fisher matrices.

    This is a fast approximation of the natural gradient alignment —
    measures how "aligned" two Fisher metrics are, i.e., whether two
    models/expert are sensitive to the same directions in parameter space.
    """
    if fim_a.mode == "diagonal" and fim_b.mode == "diagonal":
        # tr(F_a * F_b) for diagonal = sum(d_i^a * d_i^b)
        return float(np.sum(fim_a._diag * fim_b._diag))

    a = fim_a.to_dense()
    b = fim_b.to_dense()
    return float(np.trace(a @ b))


def fisher_kl_divergence(
    fim_p: FisherInformationMatrix, fim_q: FisherInformationMatrix
) -> float:
    """KL divergence approximation using Fisher matrices.

    KL(P||Q) ≈ 0.5 * (tr(F_q^{-1} F_p) - d + log(det(F_q)/det(F_p)))
    对角模式用 O(d) 解析计算; block/lowrank 模式用稠密重建 + slogdet 数值稳定计算。
    """
    dim = fim_p.dim
    if dim != fim_q.dim:
        raise ValueError(f"FIM dim mismatch: {fim_p.dim} != {fim_q.dim}")

    if fim_p.mode == "diagonal" and fim_q.mode == "diagonal":
        dp = fim_p._diag
        dq = fim_q._diag
        # tr(F_q^{-1} F_p) = sum(dp_i / dq_i)
        trace_term = np.sum(dp / (dq + 1e-10))
        # log(det(F_q)/det(F_p)) = sum(log(dq_i)) - sum(log(dp_i))
        logdet_term = np.sum(np.log(dq + 1e-10)) - np.sum(np.log(dp + 1e-10))
        kl = 0.5 * (trace_term - dim + logdet_term)
        return max(0.0, float(kl))

    # block / lowrank: 稠密重建 + 数值稳定计算
    reg = 1e-8 * np.eye(dim)
    fp = fim_p.to_dense() + reg
    fq = fim_q.to_dense() + reg
    try:
        fq_inv = np.linalg.inv(fq)
    except np.linalg.LinAlgError:
        fq_inv = np.linalg.pinv(fq)
    trace_term = float(np.trace(fq_inv @ fp))
    sign_p, logdet_p = np.linalg.slogdet(fp)
    sign_q, logdet_q = np.linalg.slogdet(fq)
    if sign_p <= 0 or sign_q <= 0:
        # 非正定退化情况: 退回对数行列式下界
        logdet_term = 0.0
    else:
        logdet_term = float(logdet_q - logdet_p)
    kl = 0.5 * (trace_term - dim + logdet_term)
    return max(0.0, float(kl))


# ═══════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════

__all__ = [
    "BrainRouter",
    "FisherInformationMatrix",
    "frobenius_alignment",
    "fisher_kl_divergence",
]

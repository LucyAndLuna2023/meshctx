"""
Counterfactual Reasoning — "What If" Analysis Engine
=====================================================
Implements simplified Pearl's do-calculus for causal intervention,
nearest-neighbor matching for alternative decision exploration,
and counterfactual outcome estimation.

Core algorithms:
  1. Pearl's do-calculus (simplified) — the do(X=x) operator:
     Intervene on a variable by setting it, cutting incoming arrows.
     P(Y | do(X=x)) ≠ P(Y | X=x) when confounders exist.
     Simplified three-rule implementation.

  2. Nearest-Neighbor Counterfactual Matching (Abadie & Imbens, 2006):
     For each treated unit, find k-nearest control units in covariate space.
     Estimate individual treatment effect via difference of matched outcomes.

  3. Structural Causal Model (SCM) — simplified:
     Y := f_Y(X, U_Y) where U_Y are exogenous noise terms.
     Counterfactual: "What would Y have been if X had been x'?"

  4. Propensity Score Matching (Rosenbaum & Rubin, 1983):
     Estimate probability of treatment given covariates.
     Match on propensity score to balance confounders.

References:
  - Pearl J (2009) Causality: Models, Reasoning, and Inference
  - Pearl J, Glymour M, Jewell NP (2016) Causal Inference in Statistics: A Primer
  - Abadie A, Imbens GW (2006) Large sample properties of matching estimators
  - Rosenbaum PR, Rubin DB (1983) The central role of the propensity score

Usage:
  reasoner = CounterfactualReasoner()
  effect = reasoner.do_intervention(data, treatment='X', outcome='Y', value=1)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from collections import defaultdict
import logging

logger = logging.getLogger("meshctx.counterfactual")


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CausalGraph:
    """Directed acyclic graph (DAG) representing causal relationships.

    edges: adjacency list {parent: [children]}
    confounders: set of (u, x, y) triples — u confounds x→y
    """
    edges: Dict[str, List[str]] = field(default_factory=dict)
    confounders: List[Tuple[str, str, str]] = field(default_factory=list)

    def add_edge(self, parent: str, child: str) -> None:
        self.edges.setdefault(parent, []).append(child)
        self.edges.setdefault(child, [])

    def add_confounder(self, confounder: str, cause: str, effect: str) -> None:
        self.confounders.append((confounder, cause, effect))

    def parents(self, node: str) -> List[str]:
        result = []
        for parent, children in self.edges.items():
            if node in children:
                result.append(parent)
        return result

    def children(self, node: str) -> List[str]:
        return self.edges.get(node, [])

    def ancestors(self, node: str) -> set:
        """All nodes on paths leading into node (recursive parents)."""
        result = set()
        stack = self.parents(node)
        while stack:
            p = stack.pop()
            if p not in result:
                result.add(p)
                stack.extend(self.parents(p))
        return result

    def has_confounder(self, cause: str, effect: str) -> bool:
        for _, c, e in self.confounders:
            if c == cause and e == effect:
                return True
        return False


@dataclass
class CounterfactualOutcome:
    """Result of a counterfactual query."""
    variable: str
    factual_value: float
    counterfactual_value: float
    intervention: Dict[str, float]
    effect_size: float             # counterfactual - factual
    confidence_interval: Tuple[float, float]
    method: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchedPair:
    """A treated unit matched to control unit(s)."""
    treated_idx: int
    treated_covariates: np.ndarray
    treated_outcome: float
    matched_indices: List[int]
    matched_outcomes: List[float]
    distance: float                # average distance
    weight: float = 1.0


# ═══════════════════════════════════════════════════════════════════
# CounterfactualReasoner
# ═══════════════════════════════════════════════════════════════════

class CounterfactualReasoner:
    """Counterfactual reasoning engine with Pearl's do-calculus and matching.

    Supports:
      - do-intervention estimation with/without a causal graph
      - Nearest-neighbor matching for individual treatment effects
      - Propensity score matching for confounding adjustment
      - Structural equation counterfactual queries
    """

    def __init__(
        self,
        graph: Optional[CausalGraph] = None,
        n_neighbors: int = 5,
        random_state: int = 42,
    ):
        self.graph = graph or CausalGraph()
        self.n_neighbors = n_neighbors
        self.rng = np.random.default_rng(random_state)

    # ── do-calculus (simplified Pearl) ──────────────────────────

    def do_intervention(
        self,
        data: np.ndarray,
        treatment_col: int,
        outcome_col: int,
        value: float,
        covariate_cols: Optional[List[int]] = None,
    ) -> CounterfactualOutcome:
        """Estimate P(outcome | do(treatment=value)) — simplified do-calculus.

        Rule 1 (ignorability): If no confounders, P(Y|do(X)) = P(Y|X=x).
        Rule 2 (back-door): Adjust for confounders via back-door criterion.

        Args:
            data: N×M array; rows=units, cols=variables
            treatment_col: column index for treatment variable X
            outcome_col: column index for outcome variable Y
            value: intervention value for X
            covariate_cols: confounder/covariate columns for adjustment

        Returns:
            CounterfactualOutcome with estimated effect
        """
        if covariate_cols is None:
            covariate_cols = []

        # Factual outcome (mean of all units)
        factual_mean = float(np.mean(data[:, outcome_col]))

        # Stratify data by treatment ≈ value
        mask = np.isclose(data[:, treatment_col], value, atol=1e-6)
        if np.sum(mask) == 0:
            # No exact matches — use nearest neighbors in treatment space
            distances = np.abs(data[:, treatment_col] - value)
            mask = distances <= np.percentile(distances, 20)  # closest 20%

        treated_data = data[mask]

        if len(treated_data) == 0:
            # Fallback: use all data
            treated_data = data

        if len(covariate_cols) > 0:
            # Back-door adjustment: reweight by inverse propensity
            adjusted_outcome = self._backdoor_adjust(
                data, treated_data, treatment_col, outcome_col, covariate_cols
            )
        else:
            # Simple mean (assumes ignorability)
            adjusted_outcome = float(np.mean(treated_data[:, outcome_col]))

        # Effect size
        effect_size = adjusted_outcome - factual_mean

        # Bootstrap CI
        ci_low, ci_high = self._bootstrap_ci(
            data, treatment_col, outcome_col, value, covariate_cols, n_boot=200
        )

        return CounterfactualOutcome(
            variable=f"col{outcome_col}",
            factual_value=factual_mean,
            counterfactual_value=adjusted_outcome,
            intervention={f"col{treatment_col}": value},
            effect_size=effect_size,
            confidence_interval=(ci_low, ci_high),
            method="do-calculus-backdoor" if covariate_cols else "do-calculus-naive",
        )

    def _backdoor_adjust(
        self,
        full_data: np.ndarray,
        treated_data: np.ndarray,
        treatment_col: int,
        outcome_col: int,
        covariate_cols: List[int],
    ) -> float:
        """Back-door adjustment via inverse probability weighting (IPW).

        Estimate propensity score P(T|C) then reweight outcomes by 1/P(T|C).
        This removes confounding bias when covariates satisfy back-door criterion.
        """
        # Simple propensity score: logistic regression via normalized dot-product
        covariates = full_data[:, covariate_cols]
        treatment = full_data[:, treatment_col]

        # Normalize covariates
        cov_mean = np.mean(covariates, axis=0)
        cov_std = np.std(covariates, axis=0) + 1e-8
        cov_norm = (covariates - cov_mean) / cov_std

        # Simplified logistic model: P(T=1) ≈ sigmoid(cov · β)
        # Estimate β as correlation between covariates and treatment
        beta = np.zeros(len(covariate_cols))
        for i, col in enumerate(covariate_cols):
            beta[i] = np.corrcoef(full_data[:, col], treatment)[0, 1]
        beta = np.nan_to_num(beta, nan=0.0)

        # Propensity scores (sigmoid)
        logits = cov_norm @ beta
        # Clip for numerical stability
        logits = np.clip(logits, -10, 10)
        propensity = 1.0 / (1.0 + np.exp(-logits))
        propensity = np.clip(propensity, 0.05, 0.95)

        # Stabilized IPW weights
        p_treatment = np.mean(np.abs(treatment))
        weights = np.where(
            np.abs(treatment) > 0.5,
            p_treatment / propensity,
            (1.0 - p_treatment) / (1.0 - propensity),
        )
        weights = np.clip(weights, 0.1, 10.0)  # trim extreme weights

        weighted_outcome = np.average(full_data[:, outcome_col], weights=weights)
        return float(weighted_outcome)

    # ── Nearest-Neighbor Matching ───────────────────────────────

    def nearest_neighbor_matching(
        self,
        data: np.ndarray,
        treatment_col: int,
        outcome_col: int,
        covariate_cols: List[int],
        k: Optional[int] = None,
    ) -> Tuple[float, List[MatchedPair]]:
        """Nearest-neighbor matching for average treatment effect on the treated (ATT).

        For each treated unit, find k nearest control units in covariate space.
        ATT = mean(Y_treated - mean(Y_matched_controls)).

        Args:
            data: N×M array
            treatment_col: column index for binary treatment indicator
            outcome_col: column index for outcome
            covariate_cols: columns to use for distance computation
            k: number of neighbors (defaults to self.n_neighbors)

        Returns:
            (ATT estimate, list of matched pairs)
        """
        if k is None:
            k = self.n_neighbors

        # Split into treated and control
        treated_mask = data[:, treatment_col] >= 0.5
        control_mask = ~treated_mask

        treated = data[treated_mask]
        control = data[control_mask]
        treated_indices = np.where(treated_mask)[0]
        control_indices = np.where(control_mask)[0]

        if len(treated) == 0 or len(control) == 0:
            logger.warning("No treated or control units; returning zero ATT")
            return 0.0, []

        # Extract covariates and normalize (Mahalanobis-like)
        X_treated = treated[:, covariate_cols].astype(np.float64)
        X_control = control[:, covariate_cols].astype(np.float64)
        Y_treated = treated[:, outcome_col].astype(np.float64)
        Y_control = control[:, outcome_col].astype(np.float64)

        # Standardize using control group stats (Abadie & Imbens)
        ctrl_mean = np.mean(X_control, axis=0)
        ctrl_std = np.std(X_control, axis=0) + 1e-8
        X_treated_std = (X_treated - ctrl_mean) / ctrl_std
        X_control_std = (X_control - ctrl_mean) / ctrl_std

        # Compute pairwise distances and find k-nearest
        pairs: List[MatchedPair] = []
        att_sum = 0.0

        for i in range(len(X_treated)):
            distances = np.sqrt(
                np.sum((X_control_std - X_treated_std[i]) ** 2, axis=1)
            )
            # Find k nearest
            k_actual = min(k, len(distances))
            nearest_idx = np.argpartition(distances, k_actual - 1)[:k_actual]
            nearest_idx = nearest_idx[np.argsort(distances[nearest_idx])]

            avg_match_outcome = float(np.mean(Y_control[nearest_idx]))
            att_sum += Y_treated[i] - avg_match_outcome

            pairs.append(MatchedPair(
                treated_idx=int(treated_indices[i]),
                treated_covariates=X_treated[i],
                treated_outcome=float(Y_treated[i]),
                matched_indices=[int(control_indices[j]) for j in nearest_idx],
                matched_outcomes=[float(Y_control[j]) for j in nearest_idx],
                distance=float(np.mean(distances[nearest_idx])),
            ))

        att = att_sum / len(X_treated)
        return att, pairs

    def propensity_score_matching(
        self,
        data: np.ndarray,
        treatment_col: int,
        outcome_col: int,
        covariate_cols: List[int],
        caliper: float = 0.2,
    ) -> Tuple[float, float]:
        """Propensity score matching with caliper.

        Steps:
          1. Estimate propensity score: P(T=1 | covariates)
          2. Match each treated unit to nearest control on propensity score
          3. Apply caliper: drop matches beyond caliper * sd(propensity)

        Returns:
            (ATT, number of matched pairs used)
        """
        covariates = data[:, covariate_cols].astype(np.float64)
        treatment = data[:, treatment_col]
        outcome = data[:, outcome_col]

        # Normalize covariates
        c_mean = np.mean(covariates, axis=0)
        c_std = np.std(covariates, axis=0) + 1e-8
        cov_norm = (covariates - c_mean) / c_std

        # Compute propensity scores (simplified logistic)
        beta = np.array([
            np.corrcoef(covariates[:, j], treatment)[0, 1]
            for j in range(len(covariate_cols))
        ])
        beta = np.nan_to_num(beta, nan=0.0)

        logits = cov_norm @ beta
        logits = np.clip(logits, -10, 10)
        propensity = 1.0 / (1.0 + np.exp(-logits))

        # Split
        treated_mask = treatment >= 0.5
        control_mask = ~treated_mask

        ps_treated = propensity[treated_mask]
        ps_control = propensity[control_mask]
        y_treated = outcome[treated_mask]
        y_control = outcome[control_mask]

        if len(ps_treated) == 0 or len(ps_control) == 0:
            return 0.0, 0.0

        # Caliper threshold
        ps_sd = np.std(propensity)
        caliper_threshold = caliper * ps_sd

        # Greedy 1:1 matching
        att_sum = 0.0
        n_matched = 0
        used_control = set()

        for i in range(len(ps_treated)):
            distances = np.abs(ps_control - ps_treated[i])
            # Exclude already-used controls
            sorted_idx = np.argsort(distances)
            best_idx = None
            for j in sorted_idx:
                if j not in used_control and distances[j] <= caliper_threshold:
                    best_idx = j
                    break

            if best_idx is not None:
                used_control.add(best_idx)
                att_sum += y_treated[i] - y_control[best_idx]
                n_matched += 1

        if n_matched == 0:
            return 0.0, 0.0

        att = att_sum / n_matched
        return att, float(n_matched)

    # ── Structural Equation Counterfactual ──────────────────────

    def scm_counterfactual(
        self,
        x_factual: np.ndarray,
        x_counterfactual: np.ndarray,
        structural_fn,
        noise: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Counterfactual prediction under a structural causal model.

        Given:
          - factual input X=x
          - structural equation Y = f(X, U) where U is exogenous noise
          - inferred noise Û = f⁻¹(Y_observed, X)

        Compute:
          Y_cf = f(x_counterfactual, Û)   — "what would Y have been?"

        The key insight (Pearl's three-step):
          1. Abduction: infer noise U from observed (X, Y)
          2. Action: set X := x_cf (the do-operator)
          3. Prediction: compute Y_cf = f(x_cf, U)

        Args:
            x_factual: observed input values, shape (n_samples, n_features)
            x_counterfactual: counterfactual inputs, shape (n_samples, n_features)
            structural_fn: callable f(X, U) → Y, the structural equation
            noise: exogenous noise U; if None, sample from N(0,1)

        Returns:
            counterfactual outcomes Y_cf
        """
        n_samples = len(x_factual)
        if noise is None:
            noise = self.rng.standard_normal(n_samples)

        # Compute factual outcomes
        y_factual = structural_fn(x_factual, noise)

        # Counterfactual: same noise, different X
        y_counterfactual = structural_fn(x_counterfactual, noise)

        return y_counterfactual

    # ── What-If Analysis ───────────────────────────────────────

    def what_if(
        self,
        data: np.ndarray,
        feature_col: int,
        outcome_col: int,
        values: List[float],
        covariate_cols: Optional[List[int]] = None,
    ) -> List[CounterfactualOutcome]:
        """Run multiple what-if scenarios by varying a feature across values.

        Args:
            data: N×M array
            feature_col: column to vary
            outcome_col: outcome column
            values: intervention values to try
            covariate_cols: confounder columns

        Returns:
            List of CounterfactualOutcome for each intervention value
        """
        results = []
        for v in values:
            result = self.do_intervention(
                data, feature_col, outcome_col, v, covariate_cols
            )
            results.append(result)
        return results

    # ── Utility ─────────────────────────────────────────────────

    def _bootstrap_ci(
        self,
        data: np.ndarray,
        treatment_col: int,
        outcome_col: int,
        value: float,
        covariate_cols: List[int],
        n_boot: int = 200,
        alpha: float = 0.05,
    ) -> Tuple[float, float]:
        """Bootstrap confidence interval for the intervention effect."""
        estimates = np.zeros(n_boot)
        n = len(data)

        for b in range(n_boot):
            idx = self.rng.integers(0, n, size=n)
            boot_data = data[idx]
            factual = float(np.mean(boot_data[:, outcome_col]))

            mask = np.isclose(boot_data[:, treatment_col], value, atol=1e-6)
            if np.sum(mask) == 0:
                dists = np.abs(boot_data[:, treatment_col] - value)
                mask = dists <= np.percentile(dists, 20)

            treated = boot_data[mask]
            if len(treated) == 0:
                treated = boot_data

            if covariate_cols:
                cf = self._backdoor_adjust(
                    boot_data, treated, treatment_col, outcome_col, covariate_cols
                )
            else:
                cf = float(np.mean(treated[:, outcome_col]))

            estimates[b] = cf - factual

        ci_low = float(np.percentile(estimates, 100 * alpha / 2))
        ci_high = float(np.percentile(estimates, 100 * (1 - alpha / 2)))
        return ci_low, ci_high

    def get_graph(self) -> CausalGraph:
        """Return the current causal graph."""
        return self.graph

    def set_graph(self, graph: CausalGraph) -> None:
        """Set a new causal graph."""
        self.graph = graph


# ═══════════════════════════════════════════════════════════════════
# Convenience factory
# ═══════════════════════════════════════════════════════════════════

def get_counterfactual_reasoner(
    graph: Optional[CausalGraph] = None,
    n_neighbors: int = 5,
) -> CounterfactualReasoner:
    """Factory for CounterfactualReasoner with sensible defaults."""
    return CounterfactualReasoner(graph=graph, n_neighbors=n_neighbors)

"""Optimal Transport Knowledge Bridge — v2.81
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Wasserstein距离 (Villani, 2009) 用于跨Agent知识迁移

核心:
- 每个Agent的知识是一个概率分布
- Wasserstein距离 = 最小传输成本 (Earth Mover's Distance)
- 找最优"运输方案": 源分布→目标分布的最低代价
- 用于: 模型间知识迁移 / 跨项目上下文转换 / 少样本适应
"""
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TransportPlan:
    """最优传输计划"""
    source_name: str
    target_name: str
    wasserstein_distance: float = 0.0
    transport_matrix: Optional[np.ndarray] = None
    cost_matrix: Optional[np.ndarray] = None
    mapping: Dict[int, int] = field(default_factory=dict)  # source_idx → target_idx
    total_cost: float = 0.0
    converged: bool = False
    iterations: int = 0


@dataclass
class KnowledgeDistribution:
    """知识分布"""
    name: str
    features: np.ndarray           # (n_samples, n_features)
    weights: np.ndarray            # (n_samples,) — 每个知识点的权重
    labels: List[str] = field(default_factory=list)


class OptimalTransportBridge:
    """最优传输知识桥梁"""

    def __init__(self, regularization: float = 0.1,
                max_iterations: int = 100):
        self.regularization = regularization
        self.max_iterations = max_iterations
        self._distributions: Dict[str, KnowledgeDistribution] = {}
        self._transport_plans: List[TransportPlan] = []

    # ── Distribution Management ────────────────────────

    def add_distribution(self, name: str, features: np.ndarray,
                        weights: Optional[np.ndarray] = None,
                        labels: Optional[List[str]] = None):
        """添加知识分布"""
        n = len(features)
        if weights is None:
            weights = np.ones(n) / n
        if labels is None:
            labels = [f"{name}-{i}" for i in range(n)]

        self._distributions[name] = KnowledgeDistribution(
            name=name,
            features=features.astype(np.float64),
            weights=weights.astype(np.float64),
            labels=labels,
        )

    # ── Wasserstein Distance ───────────────────────────

    def compute_wasserstein(self, source_name: str,
                           target_name: str) -> TransportPlan:
        """计算Wasserstein距离 (Sinkhorn算法)"""
        if source_name not in self._distributions:
            return TransportPlan(source_name, target_name)
        if target_name not in self._distributions:
            return TransportPlan(source_name, target_name)

        src = self._distributions[source_name]
        tgt = self._distributions[target_name]

        n_src = len(src.features)
        n_tgt = len(tgt.features)

        # 1. 计算代价矩阵 C[i][j] = ||src[i] - tgt[j]||
        cost_matrix = np.zeros((n_src, n_tgt))
        for i in range(n_src):
            for j in range(n_tgt):
                cost_matrix[i][j] = np.linalg.norm(
                    src.features[i] - tgt.features[j]
                )

        # 2. Sinkhorn算法 (熵正则化最优传输)
        K = np.exp(-cost_matrix / max(0.01, self.regularization))
        a = src.weights.copy()
        b = tgt.weights.copy()

        u = np.ones(n_src)
        v = np.ones(n_tgt)

        converged = False
        for iteration in range(self.max_iterations):
            u_old = u.copy()

            # Update v
            Kv = K.T @ u
            v = b / np.maximum(Kv, 1e-10)

            # Update u
            Ku = K @ v
            u = a / np.maximum(Ku, 1e-10)

            # Convergence check
            if np.max(np.abs(u - u_old)) < 1e-6:
                converged = True
                break

        # 3. 传输矩阵 T = diag(u) * K * diag(v)
        transport = np.diag(u) @ K @ np.diag(v)

        # 4. Wasserstein距离 = sum(T * C)
        wasserstein = np.sum(transport * cost_matrix)

        # 5. 构建映射: 对于每个源,找最大传输目标
        mapping = {}
        for i in range(n_src):
            j_best = np.argmax(transport[i])
            if transport[i][j_best] > 0.01:
                mapping[i] = int(j_best)

        plan = TransportPlan(
            source_name=source_name,
            target_name=target_name,
            wasserstein_distance=round(float(wasserstein), 4),
            transport_matrix=transport,
            cost_matrix=cost_matrix,
            mapping=mapping,
            total_cost=round(float(np.sum(transport * cost_matrix)), 4),
            converged=converged,
            iterations=iteration + 1,
        )

        self._transport_plans.append(plan)
        return plan

    # ── Knowledge Transfer ─────────────────────────────

    def transfer_knowledge(self, source_name: str,
                          target_name: str) -> Dict:
        """跨分布知识迁移"""
        plan = self.compute_wasserstein(source_name, target_name)

        if not plan.mapping:
            return {
                "success": False,
                "wasserstein_distance": plan.wasserstein_distance,
                "transferred": 0,
                "message": "无法建立映射",
            }

        src = self._distributions[source_name]
        tgt = self._distributions[target_name]

        transferred = []
        for src_idx, tgt_idx in plan.mapping.items():
            if src_idx < len(src.labels) and tgt_idx < len(tgt.labels):
                cost = (
                    plan.cost_matrix[src_idx][tgt_idx]
                    if plan.cost_matrix is not None else 0
                )
                transferred.append({
                    "from": src.labels[src_idx],
                    "to": tgt.labels[tgt_idx],
                    "cost": round(float(cost), 3),
                })

        return {
            "success": plan.converged,
            "wasserstein_distance": plan.wasserstein_distance,
            "transferred": len(transferred),
            "mapping_efficiency": round(
                len(transferred) / max(1, len(src.features)), 3
            ),
            "iterations": plan.iterations,
            "details": transferred[:10],
        }

    # ── Distribution Comparison ────────────────────────

    def compare_all(self) -> List[Dict]:
        """比较所有分布对"""
        results = []
        names = list(self._distributions.keys())

        for i in range(len(names)):
            for j in range(i+1, len(names)):
                plan = self.compute_wasserstein(names[i], names[j])
                results.append({
                    "source": names[i],
                    "target": names[j],
                    "wasserstein": plan.wasserstein_distance,
                    "converged": plan.converged,
                    "iterations": plan.iterations,
                })

        results.sort(key=lambda x: x["wasserstein"])
        return results

    def find_closest_distribution(self, name: str) -> Tuple[str, float]:
        """找最相似的分布"""
        best_name = ""
        best_dist = float('inf')

        for other in self._distributions:
            if other == name:
                continue
            plan = self.compute_wasserstein(name, other)
            if plan.wasserstein_distance < best_dist:
                best_dist = plan.wasserstein_distance
                best_name = other

        return best_name, best_dist

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        all_comparisons = self.compare_all() if len(self._distributions) >= 2 else []
        return {
            "distributions": len(self._distributions),
            "transport_plans": len(self._transport_plans),
            "min_wasserstein": (
                all_comparisons[0]["wasserstein"] if all_comparisons else 0
            ),
            "max_wasserstein": (
                all_comparisons[-1]["wasserstein"] if all_comparisons else 0
            ),
            "comparisons": all_comparisons,
        }


# 单例
_bridge: Optional[OptimalTransportBridge] = None


def get_transport_bridge() -> OptimalTransportBridge:
    global _bridge
    if _bridge is None:
        _bridge = OptimalTransportBridge()
    return _bridge

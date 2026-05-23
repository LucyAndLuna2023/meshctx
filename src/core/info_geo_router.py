"""Information Geometric Router — v2.76
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用信息几何(Fisher信息度量)优化模型选择

核心思想 (Amari, 2016):
- 模型空间是统计流形
- Fisher信息矩阵定义Riemannian度量
- 最优模型选择 = 流形上的geodesic路径
- 选"信息距离"最近的最便宜模型

超越v2.62: 不仅按价格选，而是按"统计相似度"选
"""
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ModelPoint:
    """模型在统计流形上的点"""
    model_id: str
    # Fisher信息矩阵的局部坐标 (简化为特征向量)
    features: np.ndarray = field(default_factory=lambda: np.zeros(8))
    cost_per_1k: float = 0.0
    capability_score: float = 0.0
    provider: str = ""


class InformationGeometricRouter:
    """信息几何路由器"""

    # 模型特征维度: [推理深度, 代码能力, 速度, 上下文窗口(log),
    #              安全性, 中文能力, 多模态, 一致性]
    _MODEL_FEATURES: Dict[str, List[float]] = {
        "deepseek-chat":     [0.3, 0.6, 0.9, 0.7, 0.4, 0.9, 0.1, 0.7],
        "deepseek-reasoner": [0.8, 0.7, 0.5, 0.7, 0.5, 0.8, 0.1, 0.8],
        "claude-haiku-4":    [0.4, 0.7, 0.9, 0.8, 0.8, 0.3, 0.3, 0.7],
        "claude-sonnet-4":   [0.8, 0.9, 0.6, 0.8, 0.9, 0.4, 0.5, 0.9],
        "claude-opus-4":     [0.95, 0.95, 0.3, 0.8, 0.95, 0.5, 0.7, 0.95],
        "gpt-4o-mini":       [0.3, 0.5, 0.9, 0.7, 0.5, 0.4, 0.5, 0.6],
        "gpt-4o":            [0.7, 0.8, 0.7, 0.7, 0.7, 0.5, 0.9, 0.8],
        "o4-mini":           [0.9, 0.8, 0.5, 0.8, 0.6, 0.4, 0.3, 0.9],
        "gemini-2.5-flash":  [0.4, 0.6, 0.9, 0.95, 0.5, 0.5, 0.8, 0.6],
        "gemini-2.5-pro":    [0.8, 0.85, 0.6, 0.95, 0.7, 0.6, 0.95, 0.85],
        "llama-4-maverick":  [0.5, 0.7, 0.7, 0.95, 0.4, 0.3, 0.4, 0.7],
        "llama-4-scout":     [0.9, 0.9, 0.5, 0.99, 0.5, 0.4, 0.6, 0.9],
    }

    _MODEL_COSTS: Dict[str, Tuple[float, float]] = {
        "deepseek-chat":     (0.14, 0.28),
        "deepseek-reasoner": (0.55, 2.19),
        "claude-haiku-4":    (1.0, 5.0),
        "claude-sonnet-4":   (3.0, 15.0),
        "claude-opus-4":     (15.0, 75.0),
        "gpt-4o-mini":       (0.15, 0.60),
        "gpt-4o":            (2.5, 10.0),
        "o4-mini":           (1.1, 4.4),
        "gemini-2.5-flash":  (0.15, 0.60),
        "gemini-2.5-pro":    (1.25, 10.0),
        "llama-4-maverick":  (0.2, 0.6),
        "llama-4-scout":     (0.4, 1.2),
    }

    def __init__(self):
        self._model_points: Dict[str, ModelPoint] = {}
        self._init_manifold()
        self._selection_history: List[Dict] = []

    def _init_manifold(self):
        """初始化统计流形"""
        for model_id, features in self._MODEL_FEATURES.items():
            costs = self._MODEL_COSTS.get(model_id, (0, 0))
            self._model_points[model_id] = ModelPoint(
                model_id=model_id,
                features=np.array(features, dtype=np.float64),
                cost_per_1k=costs[0] + costs[1],  # total per 1k
                capability_score=np.mean(features),
                provider=model_id.split("-")[0],
            )

    # ── Fisher Information Metric ──────────────────────

    def fisher_distance(self, model_a: str, model_b: str) -> float:
        """计算两个模型间的Fisher信息距离 (Riemannian metric近似)"""
        if model_a not in self._model_points or model_b not in self._model_points:
            return float('inf')

        fa = self._model_points[model_a].features
        fb = self._model_points[model_b].features

        # 1. 欧几里得距离 (平坦流形近似)
        euclidean = np.linalg.norm(fa - fb)

        # 2. Fisher信息对角近似 (每个维度的信息量)
        # 特征方差越大 → Fisher信息越大 → 该方向越"弯曲"
        fisher_diag = np.var([p.features for p in self._model_points.values()], axis=0)
        fisher_diag = np.maximum(fisher_diag, 0.01)  # 避免除零

        # 3. Mahalanobis距离 (Fisher度量的对角近似)
        delta = fa - fb
        mahalanobis = np.sqrt(np.sum((delta ** 2) / fisher_diag))

        # 4. 混合: 平坦+弯曲
        return 0.3 * euclidean + 0.7 * mahalanobis

    def capability_distance(self, required_features: np.ndarray,
                           model_id: str) -> float:
        """计算需求特征与模型能力的距离"""
        if model_id not in self._model_points:
            return float('inf')
        fm = self._model_points[model_id].features

        # 只惩罚能力不足 (不奖励超额能力)
        deficit = np.maximum(0, required_features - fm)
        return np.linalg.norm(deficit)

    # ── Optimal Model Selection ────────────────────────

    def select_optimal(self,
                      required_capabilities: Dict[str, float],
                      max_cost: Optional[float] = None,
                      preferred_provider: Optional[str] = None
                      ) -> Dict:
        """信息几何最优模型选择"""
        t0 = time.time()

        # 1. 将需求转化为特征向量
        req_features = self._requirements_to_features(required_capabilities)

        # 2. 计算每个模型的综合得分
        candidates = []
        for model_id, point in self._model_points.items():
            # a. 能力距离: 越小越好
            cap_dist = self.capability_distance(req_features, model_id)

            # b. 成本因子
            cost = point.cost_per_1k
            if max_cost and cost > max_cost:
                continue

            # c. 偏好提供者加权
            provider_bonus = 0.0
            if preferred_provider and point.provider == preferred_provider:
                provider_bonus = 0.5  # 50%距离折扣

            # d. 综合得分: 能力满足 + 成本低 → 得分高
            # 归一化成本
            max_possible_cost = max(p.cost_per_1k for p in self._model_points.values())
            cost_factor = cost / max(0.01, max_possible_cost)

            # 得分 = 能力满足度 * (1 - 成本因子) * 提供者偏好
            capability_score = 1.0 / (1.0 + cap_dist)
            cost_score = 1.0 - cost_factor
            final_score = capability_score * 0.6 + cost_score * 0.4

            if provider_bonus > 0:
                final_score *= (1.0 + provider_bonus)

            candidates.append({
                "model_id": model_id,
                "capability_distance": round(cap_dist, 3),
                "cost_per_1k": cost,
                "cost_factor": round(cost_factor, 3),
                "final_score": round(final_score, 4),
                "provider": point.provider,
            })

        # 3. 排序: 得分高 → 选择
        candidates.sort(key=lambda x: x["final_score"], reverse=True)
        best = candidates[0] if candidates else None

        # 4. 计算与最佳模型的Fisher距离 (用于降级选择)
        if best and len(candidates) > 1:
            best_id = best["model_id"]
            for c in candidates[1:]:
                c["fisher_dist_to_best"] = round(
                    self.fisher_distance(best_id, c["model_id"]), 3
                )

        result = {
            "selected": best,
            "fallback": candidates[1] if len(candidates) > 1 else None,
            "all_candidates": candidates[:5],
            "requirements": required_capabilities,
            "reasoning": (
                f"需求特征={req_features[:3]}... → "
                f"最优={best['model_id'] if best else 'none'} "
                f"(得分{best['final_score'] if best else 0}) "
                f"成本${best['cost_per_1k'] if best else 0}/1k"
            ),
            "duration_ms": (time.time() - t0) * 1000,
        }

        self._selection_history.append(result)
        if len(self._selection_history) > 100:
            self._selection_history = self._selection_history[-100:]

        return result

    def _requirements_to_features(self, caps: Dict[str, float]) -> np.ndarray:
        """将用户需求转化为特征向量"""
        features = np.zeros(8)
        mapping = {
            "reasoning": 0,    # 推理深度
            "code": 1,          # 代码能力
            "speed": 2,         # 速度
            "context": 3,       # 上下文窗口
            "safety": 4,        # 安全性
            "chinese": 5,       # 中文能力
            "multimodal": 6,    # 多模态
            "consistency": 7,   # 一致性
        }
        for cap, value in caps.items():
            idx = mapping.get(cap, -1)
            if idx >= 0:
                features[idx] = float(value)
        return features

    # ── Geodesic Path (升级路径) ────────────────────────

    def find_upgrade_path(self, from_model: str,
                         target_capabilities: Dict[str, float]) -> List[str]:
        """找从当前模型到目标能力的最短geodesic路径"""
        if from_model not in self._model_points:
            return [from_model]

        path = [from_model]
        current = from_model
        req_features = self._requirements_to_features(target_capabilities)

        for _ in range(3):  # 最多3步
            best_next = None
            best_dist = float('inf')

            for model_id, point in self._model_points.items():
                if model_id == current:
                    continue
                cap_dist = self.capability_distance(req_features, model_id)
                if cap_dist < best_dist:
                    best_dist = cap_dist
                    best_next = model_id

            if best_next and best_next not in path:
                path.append(best_next)
                current = best_next
                # 如果已经满足需求，停止
                if best_dist < 0.3:
                    break
            else:
                break

        return path

    # ── Stats ──────────────────────────────────────────

    def get_manifold_stats(self) -> Dict:
        """统计流形信息"""
        distances = []
        model_ids = list(self._model_points.keys())
        for i in range(len(model_ids)):
            for j in range(i+1, len(model_ids)):
                d = self.fisher_distance(model_ids[i], model_ids[j])
                distances.append((model_ids[i], model_ids[j], d))

        # 找最相似和最不同的模型对
        distances.sort(key=lambda x: x[2])
        closest = distances[:3]
        farthest = distances[-3:]

        return {
            "models_on_manifold": len(self._model_points),
            "manifold_diameter": round(max(d[2] for d in distances), 3),
            "closest_pairs": [
                f"{a}↔{b}: {d:.3f}" for a, b, d in closest
            ],
            "farthest_pairs": [
                f"{a}↔{b}: {d:.3f}" for a, b, d in farthest
            ],
            "total_selections": len(self._selection_history),
        }

    def get_stats(self) -> Dict:
        return self.get_manifold_stats()


# 单例
_router: Optional[InformationGeometricRouter] = None


def get_info_geo_router() -> InformationGeometricRouter:
    global _router
    if _router is None:
        _router = InformationGeometricRouter()
    return _router

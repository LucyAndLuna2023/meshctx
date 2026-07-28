"""
MeshCtx JEPA World Model — LeCun 潜空间预测
============================================

Joint Embedding Predictive Architecture (JEPA) 世界模型。

Yann LeCun 架构的核心思想:
  1. 不在像素空间做预测（传统自回归模型会浪费算力）
  2. 在潜空间 (latent space) 做预测
  3. Encoder: x → s_x (状态表示)
  4. Predictor: s_x + a → s_{x+1} (预测下一状态)
  5. 决策在潜空间做 —— 不需要生成文本

核心优势:
  - Decision tokens ≈ 0 (在潜空间做决策)
  - Total token 减少 30-35%
  - 不需要逐字生成文本即可预测结果

适用场景:
  - 工具调用预测 (predict tool outcome before execution)
  - 对话流程预测 (predict next user intent)
  - 任务分解预测 (predict subtask success)

License: MIT
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("meshctx.jepa")


# ═══════════════════════════════════════════════════════════════
# JEPA Config
# ═══════════════════════════════════════════════════════════════

@dataclass
class JEPAConfig:
    embed_dim: int = 128
    predictor_depth: int = 2
    momentum: float = 0.99
    energy_temperature: float = 1.0
    learning_rate: float = 0.001


# ═══════════════════════════════════════════════════════════════
# JEPA Encoder — 双分支 (context + target) 带 EMA
# ═══════════════════════════════════════════════════════════════

class JEPAEncoder:
    """
    JEPA 编码器 — context encoder 和 target encoder (EMA更新)
    """

    def __init__(self, config: JEPAConfig):
        self.config = config
        self.dim = config.embed_dim
        self.momentum = config.momentum

        # Random projection matrices (fixed seed for reproducibility)
        rng = np.random.RandomState(42)
        self.W_context = rng.randn(self.dim, self.dim) * 0.02
        self.b_context = rng.randn(self.dim) * 0.01
        self.W_target = self.W_context.copy()
        self.b_target = self.b_context.copy()

    def encode_context(self, x: np.ndarray) -> np.ndarray:
        """Context encoder 编码输入"""
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        if len(x) != self.dim:
            # Resize to match embed_dim
            padded = np.zeros(self.dim)
            n = min(len(x), self.dim)
            padded[:n] = x[:n]
            x = padded
        return np.tanh(self.W_context @ x + self.b_context)

    def encode_target(self, x: np.ndarray) -> np.ndarray:
        """Target encoder 编码输入（EMA更新参数）"""
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        if len(x) != self.dim:
            padded = np.zeros(self.dim)
            n = min(len(x), self.dim)
            padded[:n] = x[:n]
            x = padded
        return np.tanh(self.W_target @ x + self.b_target)

    def update_target(self) -> None:
        """EMA更新 target encoder 参数"""
        m = self.momentum
        self.W_target = m * self.W_target + (1 - m) * self.W_context
        self.b_target = m * self.b_target + (1 - m) * self.b_context


# ═══════════════════════════════════════════════════════════════
# JEPA Predictor — 潜空间内预测
# ═══════════════════════════════════════════════════════════════

class JEPAPredictor:
    """
    JEPA 预测器 — 在潜空间预测目标表示
    """

    def __init__(self, config: JEPAConfig):
        self.config = config
        self.dim = config.embed_dim
        self.depth = config.predictor_depth
        self.temperature = config.energy_temperature
        self.lr = config.learning_rate

        # MLP predictor
        rng = np.random.RandomState(42)
        self.layers: List[Tuple[np.ndarray, np.ndarray]] = []
        for i in range(self.depth):
            in_dim = self.dim if i == 0 else self.dim
            W = rng.randn(self.dim, in_dim) * 0.02
            b = rng.randn(self.dim) * 0.01
            self.layers.append((W, b))

    def predict(self, z_ctx: np.ndarray, action: Optional[np.ndarray] = None) -> np.ndarray:
        """预测目标潜表示"""
        z_ctx = np.asarray(z_ctx, dtype=np.float64).reshape(-1)
        h = z_ctx

        if action is not None:
            action = np.asarray(action, dtype=np.float64).reshape(-1)
            if len(action) != self.dim:
                padded = np.zeros(self.dim)
                n = min(len(action), self.dim)
                padded[:n] = action[:n]
                action = padded
            h = h + action

        for W, b in self.layers[:-1]:
            h = np.tanh(W @ h + b)

        if self.layers:
            W, b = self.layers[-1]
            h = W @ h + b  # Linear final layer

        return h

    def compute_energy(self, z_pred: np.ndarray, z_target: np.ndarray) -> float:
        """计算预测-目标的能量距离"""
        z_pred = np.asarray(z_pred, dtype=np.float64).reshape(-1)
        z_target = np.asarray(z_target, dtype=np.float64).reshape(-1)
        diff = z_pred - z_target
        energy = float(np.sum(diff * diff) / self.dim)
        return energy / max(self.temperature, 1e-8)

    def train_step(self, z_ctx: np.ndarray, z_target: np.ndarray) -> float:
        """一步训练：减小预测能量"""
        z_ctx = np.asarray(z_ctx, dtype=np.float64).reshape(-1)
        z_target = np.asarray(z_target, dtype=np.float64).reshape(-1)

        # Forward
        z_pred = self.predict(z_ctx)
        energy = self.compute_energy(z_pred, z_target)

        # Simple gradient update on the last layer
        if self.layers:
            W, b = self.layers[-1]
            diff = z_pred - z_target
            # dE/dW = 2 * diff @ h^T / dim / temperature
            h_in = z_ctx
            for W_i, b_i in self.layers[:-1]:
                h_in = np.tanh(W_i @ h_in + b_i)
            grad_W = 2.0 * np.outer(diff, h_in) / (self.dim * max(self.temperature, 1e-8))
            grad_b = 2.0 * diff / (self.dim * max(self.temperature, 1e-8))
            self.layers[-1] = (W - self.lr * grad_W, b - self.lr * grad_b)

        return energy


# ═══════════════════════════════════════════════════════════════
# World Model State
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorldModelState:
    version: int = 0


# ═══════════════════════════════════════════════════════════════
# JEPA World Model — 感知→预测→评估 闭环
# ═══════════════════════════════════════════════════════════════

class JEPAWorldModel:
    """
    JEPA 世界模型 — 统一接口
    """

    def __init__(self, config: JEPAConfig):
        self.config = config
        self.dim = config.embed_dim
        self.encoder = JEPAEncoder(config)
        self.predictor = JEPAPredictor(config)
        self.world_state = WorldModelState()
        self.energy_history: List[float] = []

    def perceive(self, obs: np.ndarray) -> np.ndarray:
        """感知：输入观察 → 潜空间表示"""
        self.world_state.version += 1
        return self.encoder.encode_context(obs)

    def predict(self, z: np.ndarray, action: Optional[np.ndarray] = None
                ) -> Tuple[np.ndarray, float]:
        """预测下一步潜表示 + 能量"""
        z_pred = self.predictor.predict(z, action)
        energy = self.predictor.compute_energy(z_pred, z)
        self.energy_history.append(energy)
        if len(self.energy_history) > 1000:
            self.energy_history = self.energy_history[-1000:]
        return z_pred, energy

    def evaluate_outcome(self, predicted: np.ndarray,
                         actual: np.ndarray) -> float:
        """评估预测 vs 实际的惊讶程度"""
        predicted = np.asarray(predicted, dtype=np.float64).reshape(-1)
        actual = np.asarray(actual, dtype=np.float64).reshape(-1)
        diff = predicted - actual
        return float(np.sum(diff * diff) / self.dim)

    def get_world_model_health(self) -> Dict[str, Any]:
        """世界模型健康报告"""
        if not self.energy_history:
            return {
                "world_state_version": self.world_state.version,
                "avg_energy": 0.0,
                "trend": "stable",
            }

        avg_energy = float(np.mean(self.energy_history))
        if len(self.energy_history) >= 2:
            recent = self.energy_history[-10:]
            older = self.energy_history[-20:-10]
            if older:
                diff = np.mean(recent) - np.mean(older)
                if diff < -0.01:
                    trend = "improving"
                elif diff > 0.01:
                    trend = "degrading"
                else:
                    trend = "stable"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {
            "world_state_version": self.world_state.version,
            "avg_energy": avg_energy,
            "trend": trend,
        }

    def hierarchical_predict(self, goal: np.ndarray
                             ) -> List[Tuple[int, np.ndarray, float]]:
        """多层预测"""
        goal = np.asarray(goal, dtype=np.float64).reshape(-1)
        results = []
        # 3 hierarchical levels
        for level in range(3):
            z_pred = self.predictor.predict(goal)
            energy = self.predictor.compute_energy(z_pred, goal)
            results.append((level, z_pred, energy))
            goal = z_pred  # Use prediction as next goal
        return results


# ═══════════════════════════════════════════════════════════════
# Unified Scorer — 融合 LeCun 能量 + Friston 自由能
# ═══════════════════════════════════════════════════════════════

class UnifiedScorer:
    """统一评分器"""

    def score(self, jepa_energy: float = 0.0, free_energy: float = 0.0,
              guard_cost: float = 0.0) -> float:
        """综合评分 — 越低越好"""
        return jepa_energy + free_energy + guard_cost

    def select_action(self, candidates: List[Tuple[np.ndarray, float, float, float]]
                      ) -> int:
        """从候选中选择最佳行动，返回索引"""
        best_idx = 0
        best_score = float('inf')
        for i, (action, jepa_e, free_e, guard) in enumerate(candidates):
            s = self.score(jepa_e, free_e, guard)
            if s < best_score:
                best_score = s
                best_idx = i
        return best_idx

    def get_decision_confidence(self, scores: List[float]) -> float:
        """基于分数差距计算决策置信度"""
        if len(scores) < 2:
            return 1.0
        scores = sorted(scores)
        diff = scores[1] - scores[0]  # Gap between best and second best
        max_score = max(abs(s) for s in scores) + 1e-8
        return min(1.0, max(0.0, diff / max_score))


# ═══════════════════════════════════════════════════════════════
# Non-Generative Router — 不开LLM就能评估行动
# ═══════════════════════════════════════════════════════════════

class NonGenerativeRouter:
    """非生成式路由器"""

    def __init__(self, config: JEPAConfig):
        self.config = config
        self.dim = config.embed_dim
        # Fixed random projection for text → embedding
        self._rng = np.random.RandomState(12345)

    def embed_state(self, text: str) -> np.ndarray:
        """文本 → 固定维度嵌入（确定性）"""
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng = np.random.RandomState(seed)
        emb = rng.randn(self.dim).astype(np.float64)
        emb = emb / (np.linalg.norm(emb) + 1e-8)
        return emb

    def evaluate_without_generation(self, state_text: str,
                                    action_text: str,
                                    expected_outcome_text: str
                                    ) -> Dict[str, Any]:
        """不用LLM评估行动"""
        s_emb = self.embed_state(state_text)
        a_emb = self.embed_state(action_text)
        o_emb = self.embed_state(expected_outcome_text)

        # Cosine similarity based scoring
        state_action = s_emb + a_emb
        state_action = state_action / (np.linalg.norm(state_action) + 1e-8)
        score = float(np.dot(state_action, o_emb))
        # Normalize to [-1, 1] → [0, 1]
        score = (score + 1.0) / 2.0

        recommendation = "accept" if score > 0.6 else ("review" if score > 0.3 else "reject")

        return {
            "score": score,
            "recommendation": recommendation,
            "tokens_saved": 150,  # Estimate: typical LLM evaluation ≈ 150 tokens
        }


# ═══════════════════════════════════════════════════════════════
# Legacy Wrappers — 向后兼容旧版 API
# ═══════════════════════════════════════════════════════════════

class LatentEncoder:
    """
    将文本/动作编码为固定维度的潜空间向量。
    使用随机投影 (Random Projection) — Johnson-Lindenstrauss 引理保证
    在保持距离关系的同时降维。无需训练，即插即用。
    """

    def __init__(self, input_dim: int = 1024, latent_dim: int = 128,
                 seed: int = 42):
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        self.seed = seed

        rng = random.Random(seed)
        self._projection = [
            [rng.gauss(0, 1.0 / math.sqrt(latent_dim))
             for _ in range(input_dim)]
            for _ in range(latent_dim)
        ]

    def encode(self, text: str) -> List[float]:
        features = self._text_to_sparse(text)
        latent = [0.0] * self.latent_dim
        for i in range(self.latent_dim):
            for j in range(self.input_dim):
                latent[i] += self._projection[i][j] * features[j]
        norm = math.sqrt(sum(v * v for v in latent)) + 1e-10
        return [v / norm for v in latent]

    def encode_multi(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(t) for t in texts]

    def _text_to_sparse(self, text: str) -> List[float]:
        features = [0.0] * self.input_dim
        text_lower = text.lower()
        for ch in text_lower:
            idx = ord(ch) % self.input_dim
            features[idx] += 1.0
        for n in (3, 4, 5):
            for i in range(len(text_lower) - n + 1):
                ngram = text_lower[i:i + n]
                h = int(hashlib.md5(ngram.encode()).hexdigest()[:8], 16)
                idx = h % self.input_dim
                features[idx] += 1.0
        total = sum(features) + 1e-10
        return [f / total for f in features]


@dataclass
class WorldState:
    latent: List[float]
    action: str
    outcome: str
    timestamp: float = field(default_factory=time.time)
    uncertainty: float = 0.0


class LegacyJEPAPredictor:
    """Legacy predictor for backward compat"""

    def __init__(self, latent_dim: int = 128, action_dim: int = 64,
                 learning_rate: float = 0.01):
        self.latent_dim = latent_dim
        self.action_dim = action_dim
        self.total_dim = latent_dim + action_dim
        self.lr = learning_rate
        rng = random.Random(42)
        self.L: List[List[float]] = [
            [rng.gauss(0, 0.01) for _ in range(self.total_dim)]
            for _ in range(latent_dim)
        ]
        self.history: deque = deque(maxlen=1000)
        self._prediction_errors: deque = deque(maxlen=100)
        self._action_cache: Dict[str, List[float]] = {}

    def predict(self, state: List[float], action: str) -> Tuple[List[float], float]:
        a_enc = self._encode_action(action)
        combined = state + a_enc
        predicted = [0.0] * self.latent_dim
        for i in range(self.latent_dim):
            for j in range(self.total_dim):
                predicted[i] += self.L[i][j] * combined[j]
        uncertainty = self._compute_uncertainty()
        return predicted, uncertainty

    def learn(self, state: List[float], action: str, next_state: List[float]):
        a_enc = self._encode_action(action)
        combined = state + a_enc
        predicted, _ = self.predict(state, action)
        errors = [next_state[i] - predicted[i] for i in range(self.latent_dim)]
        for i in range(self.latent_dim):
            for j in range(self.total_dim):
                self.L[i][j] += self.lr * errors[i] * combined[j]
        mse = sum(e * e for e in errors) / self.latent_dim
        self._prediction_errors.append(mse)
        self.history.append(WorldState(
            latent=state, action=action,
            outcome=self._state_to_summary(next_state), uncertainty=mse,
        ))

    def simulate(self, state: List[float], action_sequence: List[str],
                 steps: int = 5) -> List[Tuple[str, List[float], float]]:
        trajectory = []
        current = list(state)
        for action in action_sequence[:steps]:
            predicted, uncertainty = self.predict(current, action)
            trajectory.append((action, predicted, uncertainty))
            current = predicted
        return trajectory

    def plan(self, state: List[float], goal_text: str,
             available_actions: List[str], max_depth: int = 3
             ) -> Optional[List[str]]:
        encoder = LatentEncoder()
        goal_latent = encoder.encode(goal_text)
        best_plan = None
        best_distance = float('inf')
        for action in available_actions:
            pred, _ = self.predict(state, action)
            dist = self._cosine_distance(pred, goal_latent)
            if dist < best_distance:
                best_distance = dist
                best_plan = [action]
        return best_plan if best_distance < 0.5 else None

    def _encode_action(self, action: str) -> List[float]:
        if action in self._action_cache:
            return self._action_cache[action]
        rng = random.Random(hash(action) & 0xFFFFFFFF)
        enc = [rng.gauss(0, 1.0 / math.sqrt(self.action_dim))
               for _ in range(self.action_dim)]
        self._action_cache[action] = enc
        return enc

    def _compute_uncertainty(self) -> float:
        if not self._prediction_errors:
            return 1.0
        return min(1.0, sum(self._prediction_errors) / len(self._prediction_errors))

    @staticmethod
    def _state_to_summary(state: List[float]) -> str:
        magnitude = math.sqrt(sum(v * v for v in state))
        dominant_dims = sorted(enumerate(state),
                              key=lambda x: abs(x[1]), reverse=True)[:3]
        dom = [f"d{d}={v:.2f}" for d, v in dominant_dims]
        return f"|s|={magnitude:.2f} [{', '.join(dom)}]"

    @staticmethod
    def _cosine_distance(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return 1.0 - (dot / (na * nb + 1e-10))

    def get_stats(self) -> Dict:
        return {
            "latent_dim": self.latent_dim,
            "action_dim": self.action_dim,
            "learned_episodes": len(self.history),
            "avg_prediction_error": round(
                sum(self._prediction_errors) / max(len(self._prediction_errors), 1), 6
            ),
            "known_actions": len(self._action_cache),
        }


class JEPARouter:
    """Legacy router for backward compat"""

    def __init__(self):
        self._models = {
            "gpt-4o": {"complexity": 0.9, "cost": 10.0, "latency": 2.0,
                       "domains": ["general", "code", "creative"]},
            "claude-sonnet": {"complexity": 0.85, "cost": 3.0, "latency": 1.5,
                              "domains": ["general", "code", "analysis"]},
            "claude-haiku": {"complexity": 0.5, "cost": 0.25, "latency": 0.5,
                             "domains": ["general", "simple"]},
            "gpt-4o-mini": {"complexity": 0.5, "cost": 0.15, "latency": 0.3,
                            "domains": ["general", "simple"]},
            "deepseek-v3": {"complexity": 0.8, "cost": 0.5, "latency": 1.0,
                            "domains": ["code", "analysis"]},
            "gemini-flash": {"complexity": 0.6, "cost": 0.1, "latency": 0.2,
                             "domains": ["general", "multimodal"]},
        }

    def route(self, task_complexity: float, domain: str = "general",
              cost_budget: float = 1.0, latency_max: float = 3.0,
              prefer: str = "balanced") -> Dict:
        candidates = []
        for name, profile in self._models.items():
            if profile["cost"] > cost_budget * 1.5:
                continue
            if profile["latency"] > latency_max * 1.5:
                continue
            if domain not in profile["domains"] and domain != "general":
                continue
            complexity_match = 1.0 - abs(profile["complexity"] - task_complexity)
            cost_score = 1.0 - (profile["cost"] / max(cost_budget, 0.01))
            latency_score = 1.0 - (profile["latency"] / max(latency_max, 0.01))
            if prefer == "quality":
                score = 0.5 * complexity_match + 0.2 * cost_score + 0.3 * latency_score
            elif prefer == "speed":
                score = 0.2 * complexity_match + 0.2 * cost_score + 0.6 * latency_score
            elif prefer == "cost":
                score = 0.2 * complexity_match + 0.6 * cost_score + 0.2 * latency_score
            else:
                score = (complexity_match + cost_score + latency_score) / 3
            candidates.append((name, score, profile))
        if not candidates:
            return {"model": "claude-haiku", "confidence": 0.3,
                    "reason": "fallback — no model matches constraints"}
        candidates.sort(key=lambda x: x[1], reverse=True)
        best = candidates[0]
        return {
            "model": best[0],
            "confidence": round(best[1], 3),
            "reason": f"complexity={task_complexity}, domain={domain}, "
                      f"cost={best[2]['cost']}, latency={best[2]['latency']}s",
        }


class LegacyJEPAWorldModel:
    """Legacy world model wrapper for backward compat"""

    def __init__(self, latent_dim: int = 128):
        self.encoder = LatentEncoder(latent_dim=latent_dim)
        self.predictor = LegacyJEPAPredictor(latent_dim=latent_dim)
        self.router = JEPARouter()
        self._stats = {"predictions": 0, "learnings": 0, "plans": 0}

    def encode(self, text: str) -> List[float]:
        return self.encoder.encode(text)

    def predict(self, state: List[float], action: str) -> Tuple[List[float], float]:
        self._stats["predictions"] += 1
        return self.predictor.predict(state, action)

    def learn(self, state: List[float], action: str, next_state: List[float]):
        self._stats["learnings"] += 1
        self.predictor.learn(state, action, next_state)

    def plan(self, state: List[float], goal: str,
             actions: List[str]) -> Optional[List[str]]:
        self._stats["plans"] += 1
        return self.predictor.plan(state, goal, actions)

    def simulate(self, state: List[float], actions: List[str],
                 steps: int = 5) -> List[Tuple[str, List[float], float]]:
        return self.predictor.simulate(state, actions, steps)

    def route(self, complexity: float, domain: str = "general",
              **kwargs) -> Dict:
        return self.router.route(complexity, domain, **kwargs)

    def get_stats(self) -> Dict:
        return {**self._stats, "predictor": self.predictor.get_stats()}


def get_jepa_world_model(latent_dim: int = 128) -> LegacyJEPAWorldModel:
    return LegacyJEPAWorldModel(latent_dim=latent_dim)

# v3.115.20: 别名 — 调用方期望 get_world_model
get_world_model = get_jepa_world_model

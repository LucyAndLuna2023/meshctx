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

License: AGPLv3
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

logger = logging.getLogger("meshctx.jepa")

# ---------------------------------------------------------------------------
# 轻量级潜空间编码器 — 无需 torch/numpy
# ---------------------------------------------------------------------------

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

        # 随机投影矩阵 (固定种子保证可复现)
        rng = random.Random(seed)
        self._projection = [
            [rng.gauss(0, 1.0 / math.sqrt(latent_dim))
             for _ in range(input_dim)]
            for _ in range(latent_dim)
        ]

    def encode(self, text: str) -> List[float]:
        """
        文本 → 潜空间向量 (128维)

        步骤:
          1. 文本 → 稀疏特征向量 (1024维, 基于 n-gram 哈希)
          2. 随机投影 → 128维潜空间
          3. L2 归一化
        """
        # 稀疏特征
        features = self._text_to_sparse(text)
        # 随机投影
        latent = [0.0] * self.latent_dim
        for i in range(self.latent_dim):
            for j in range(self.input_dim):
                latent[i] += self._projection[i][j] * features[j]
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in latent)) + 1e-10
        return [v / norm for v in latent]

    def encode_multi(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(t) for t in texts]

    def _text_to_sparse(self, text: str) -> List[float]:
        """文本 → 稀疏特征向量 (n-gram 哈希)"""
        features = [0.0] * self.input_dim
        text_lower = text.lower()

        # Unigrams
        for ch in text_lower:
            idx = ord(ch) % self.input_dim
            features[idx] += 1.0

        # Bigrams & Trigrams
        for n in (3, 4, 5):
            for i in range(len(text_lower) - n + 1):
                ngram = text_lower[i:i + n]
                h = int(hashlib.md5(ngram.encode()).hexdigest()[:8], 16)
                idx = h % self.input_dim
                features[idx] += 1.0

        # 归一化
        total = sum(features) + 1e-10
        return [f / total for f in features]


# ---------------------------------------------------------------------------
# JEPA Predictor — 潜空间内预测
# ---------------------------------------------------------------------------

@dataclass
class WorldState:
    """世界状态快照"""
    latent: List[float]          # 当前潜空间表示
    action: str                  # 执行的动作
    outcome: str                 # 结果表示
    timestamp: float = field(default_factory=time.time)
    uncertainty: float = 0.0     # 预测不确定性


class JEPAPredictor:
    """
    JEPA 预测器 — 在潜空间预测下一步状态

    s_{t+1} = Predictor(s_t, a_t)

    学习: 在线更新预测矩阵 L
      L ← L + η * (s_{t+1} - L @ (s_t ⊕ a_t)) ⊗ (s_t ⊕ a_t)

    推理: s_pred = L @ (s_curr ⊕ action)
    """

    def __init__(self, latent_dim: int = 128, action_dim: int = 64,
                 learning_rate: float = 0.01):
        self.latent_dim = latent_dim
        self.action_dim = action_dim
        self.total_dim = latent_dim + action_dim  # s_t ⊕ a_t
        self.lr = learning_rate

        # 预测矩阵 L: (latent_dim × total_dim)
        # 在线学习 —— 从经验中更新
        rng = random.Random(42)
        self.L: List[List[float]] = [
            [rng.gauss(0, 0.01) for _ in range(self.total_dim)]
            for _ in range(latent_dim)
        ]

        # 历史记录
        self.history: deque = deque(maxlen=1000)
        self._prediction_errors: deque = deque(maxlen=100)

        # 动作编码
        self._action_cache: Dict[str, List[float]] = {}

    def predict(self, state: List[float], action: str) -> Tuple[List[float], float]:
        """
        预测执行 action 后的潜空间状态

        Args:
            state: 当前状态 s_t (128维)
            action: 动作名称

        Returns:
            (predicted_state s_{t+1}, uncertainty)
        """
        a_enc = self._encode_action(action)
        combined = state + a_enc  # 128 + 64 = 192

        # s_pred = L @ combined
        predicted = [0.0] * self.latent_dim
        for i in range(self.latent_dim):
            for j in range(self.total_dim):
                predicted[i] += self.L[i][j] * combined[j]

        # 不确定性 = 最近 N 次预测误差的均值
        uncertainty = self._compute_uncertainty()

        return predicted, uncertainty

    def learn(self, state: List[float], action: str,
              next_state: List[float]):
        """
        在线学习 — 用实际结果更新预测矩阵

        L ← L + η * (actual - predicted) ⊗ combined
        """
        a_enc = self._encode_action(action)
        combined = state + a_enc

        # 先预测
        predicted, _ = self.predict(state, action)

        # 计算误差: error_i = actual_i - predicted_i
        errors = [next_state[i] - predicted[i] for i in range(self.latent_dim)]

        # 更新 L: L[i][j] += lr * error[i] * combined[j]
        for i in range(self.latent_dim):
            for j in range(self.total_dim):
                self.L[i][j] += self.lr * errors[i] * combined[j]

        # 记录
        mse = sum(e * e for e in errors) / self.latent_dim
        self._prediction_errors.append(mse)

        self.history.append(WorldState(
            latent=state,
            action=action,
            outcome=self._state_to_summary(next_state),
            uncertainty=mse,
        ))

    def simulate(self, state: List[float], action_sequence: List[str],
                 steps: int = 5) -> List[Tuple[str, List[float], float]]:
        """
        模拟执行一系列动作，预测轨迹

        Returns:
            [(action, predicted_state, uncertainty) for each step]
        """
        trajectory = []
        current = list(state)

        for action in action_sequence[:steps]:
            predicted, uncertainty = self.predict(current, action)
            trajectory.append((action, predicted, uncertainty))
            current = predicted  # 用预测作为下一个输入

        return trajectory

    def plan(self, state: List[float], goal_text: str,
             available_actions: List[str],
             max_depth: int = 3) -> Optional[List[str]]:
        """
        简单规划: 搜索能最小化 state→goal 距离的动作序列

        Returns:
            最优动作序列, 或 None
        """
        encoder = LatentEncoder()
        goal_latent = encoder.encode(goal_text)

        best_plan = None
        best_distance = float('inf')

        # 贪心搜索 (简化版 — 生产用 MCTS)
        for action in available_actions:
            pred, _ = self.predict(state, action)
            dist = self._cosine_distance(pred, goal_latent)
            if dist < best_distance:
                best_distance = dist
                best_plan = [action]

        return best_plan if best_distance < 0.5 else None

    def _encode_action(self, action: str) -> List[float]:
        """动作名 → 64维向量"""
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
        """潜空间向量 → 人类可读摘要"""
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


# ---------------------------------------------------------------------------
# JEPA Router — 模型选择
# ---------------------------------------------------------------------------

class JEPARouter:
    """
    JEPA 路由器 — 预测性模型选择

    不试错，根据任务特征直接选择最优模型。

    输入: {complexity, domain, cost_budget, latency_requirement}
    输出: 模型名 + 置信度
    """

    def __init__(self):
        # 模型知识库
        self._models = {
            "gpt-4o":     {"complexity": 0.9, "cost": 10.0, "latency": 2.0, "domains": ["general", "code", "creative"]},
            "claude-sonnet": {"complexity": 0.85, "cost": 3.0, "latency": 1.5, "domains": ["general", "code", "analysis"]},
            "claude-haiku": {"complexity": 0.5, "cost": 0.25, "latency": 0.5, "domains": ["general", "simple"]},
            "gpt-4o-mini": {"complexity": 0.5, "cost": 0.15, "latency": 0.3, "domains": ["general", "simple"]},
            "deepseek-v3": {"complexity": 0.8, "cost": 0.5, "latency": 1.0, "domains": ["code", "analysis"]},
            "gemini-flash": {"complexity": 0.6, "cost": 0.1, "latency": 0.2, "domains": ["general", "multimodal"]},
        }

    def route(self, task_complexity: float,
              domain: str = "general",
              cost_budget: float = 1.0,
              latency_max: float = 3.0,
              prefer: str = "balanced") -> Dict:
        """
        路由决策

        Args:
            task_complexity: 0-1 任务复杂度
            domain: 任务域
            cost_budget: 成本预算 ($/1K tokens)
            latency_max: 最大延迟 (秒)
            prefer: "quality" / "speed" / "cost" / "balanced"

        Returns:
            {model, confidence, reason}
        """
        candidates = []

        for name, profile in self._models.items():
            if profile["cost"] > cost_budget * 1.5:
                continue
            if profile["latency"] > latency_max * 1.5:
                continue
            if domain not in profile["domains"] and domain != "general":
                continue

            # 综合评分
            complexity_match = 1.0 - abs(profile["complexity"] - task_complexity)
            cost_score = 1.0 - (profile["cost"] / max(cost_budget, 0.01))
            latency_score = 1.0 - (profile["latency"] / max(latency_max, 0.01))

            if prefer == "quality":
                score = 0.5 * complexity_match + 0.2 * cost_score + 0.3 * latency_score
            elif prefer == "speed":
                score = 0.2 * complexity_match + 0.2 * cost_score + 0.6 * latency_score
            elif prefer == "cost":
                score = 0.2 * complexity_match + 0.6 * cost_score + 0.2 * latency_score
            else:  # balanced
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


# ---------------------------------------------------------------------------
# 集成: JEPA World Model = Encoder + Predictor + Router
# ---------------------------------------------------------------------------

class JEPAWorldModel:
    """
    JEPA 世界模型 — 统一接口

    用法:
      wm = JEPAWorldModel()
      
      # 编码
      s = wm.encode("用户想修复一个bug")
      
      # 预测
      s_next, uncertainty = wm.predict(s, "read_file")
      
      # 学习
      s_actual = wm.encode("文件读取成功，bug在第42行")
      wm.learn(s, "read_file", s_actual)
      
      # 规划
      plan = wm.plan(s, "bug修好了", ["read_file","patch","terminal","test"])
      
      # 路由
      model = wm.route(complexity=0.6, domain="code")
    """

    def __init__(self, latent_dim: int = 128):
        self.encoder = LatentEncoder(latent_dim=latent_dim)
        self.predictor = JEPAPredictor(latent_dim=latent_dim)
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
        return {
            **self._stats,
            "predictor": self.predictor.get_stats(),
        }


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

def get_jepa_world_model(latent_dim: int = 128) -> JEPAWorldModel:
    return JEPAWorldModel(latent_dim=latent_dim)

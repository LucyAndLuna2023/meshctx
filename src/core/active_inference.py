"""
MeshCtx Active Inference Engine — Proprietary Core
====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Implements active inference with expected free energy minimization,
information gain maximization, and precision-weighted learning —
proprietary algorithms.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com

跨学科融合:
- 认知科学: 感知与行动的数学统一 → 行动服务于信念更新
- 博弈论: 与环境的动态博弈 → 策略选择对抗不确定性
- 信息论: 信息增益最大化 → 认知价值驱动探索
- 神经科学: 多巴胺编码预测误差 → 精密加权的学习信号

核心公式:
  G(π) = E_q[ln q(s|π) - ln p(s,o|π)]
       = 认知价值 + 实用价值
  
  认知价值 = 行动π期望带来多少信息增益 (好奇心驱动)
  实用价值 = 行动π期望达成偏好的程度 (目标驱动)

主动推理 vs 强化学习:
  RL:  最大化期望奖励
  AI:  最小化期望自由能 = 最小化惊讶
  两者等价当奖励函数 = -ln p(o|C)
"""

import math
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .free_energy import (
    BeliefState, BeliefType, FreeEnergyComputer,
    PrecisionWeighting, CriticalityRegulator,
)

logger = logging.getLogger("meshctx.active_inference")


# ═══════════════════════════════════════════════════════════════════════
# 策略空间
# ═══════════════════════════════════════════════════════════════════════

class ActionType(Enum):
    """行动类型"""
    EXPLORE = "explore"        # 纯探索 — 获取信息
    EXPLOIT = "exploit"        # 纯利用 — 使用已知最佳
    HYBRID = "hybrid"          # 混合 — 信息+目标
    AVOID = "avoid"            # 规避 — 减少惊讶
    OBSERVE = "observe"        # 观察 — 被动收集
    DEFER = "defer"            # 延迟 — 等更多信息
    META = "meta"              # 元行动 — 调整自身参数


@dataclass
class Policy:
    """行动策略 (π)"""
    name: str
    action_type: ActionType
    epistemic_weight: float = 0.5    # 认知权重 (0=纯利用, 1=纯探索)
    pragmatic_weight: float = 0.5    # 实用权重
    expected_duration: float = 10.0  # 预期耗时(秒)
    expected_cost: float = 0.0       # 预期资源消耗
    preconditions: List[str] = field(default_factory=list)
    
    def expected_free_energy(self, 
                              belief_state: BeliefState,
                              preferred_outcomes: np.ndarray,
                              temperature: float = 1.0) -> float:
        """
        计算策略的期望自由能 G(π)。
        
        认知价值 (Epistemic):
          策略执行后信念熵的期望减少
          = H[当前] - E[H[后验]]
          高 → 策略会带来大量信息
        
        实用价值 (Pragmatic):
          策略达成偏好结果的期望对数概率
          = -E[ln p(o|C,π)]
          高 → 策略很可能达成目标
        """
        # 认知价值: 当前不确定性越高，探索越有价值
        epistemic = self.epistemic_weight * belief_state.uncertainty
        
        # 实用价值: 期望达成偏好的程度
        if preferred_outcomes is not None and len(preferred_outcomes) > 0:
            probs = belief_state.expected_probability
            pragmatic = -self.pragmatic_weight * np.sum(probs * np.log(np.maximum(preferred_outcomes, 1e-10)))
        else:
            pragmatic = 0.0
        
        # 成本项: 资源消耗
        cost = self.expected_cost * 0.01
        
        # 温度修正
        G = cost - epistemic - pragmatic
        G += temperature * belief_state.uncertainty * 0.1  # 高温时鼓励探索
        
        return G


# ═══════════════════════════════════════════════════════════════════════
# 生成模型 — 世界内部模型
# ═══════════════════════════════════════════════════════════════════════

class GenerativeModel:
    """
    智能体的内部生成模型 p(s, o, π)。
    
    包含:
    1. 状态转移 p(s'|s, π) — 行动如何改变世界
    2. 观察似然 p(o|s) — 世界如何产生感知
    3. 先验偏好 p(o|C) — 什么是"好"的结果
    
    这个模型使智能体能够"想象"行动的结果，
    在脑中模拟而非实际执行。
    """

    def __init__(self, n_states: int = 10, n_observations: int = 10):
        self.n_states = n_states
        self.n_observations = n_observations
        
        # 状态转移矩阵 A[s, a, s'] = p(s'|s, a)
        self.transition_matrix = np.ones((n_states, 5, n_states)) / n_states
        
        # 观察矩阵 B[s, o] = p(o|s)
        self.observation_matrix = np.ones((n_states, n_observations)) / n_observations
        
        # 偏好先验 C[o] = p(o|C) — 越高的观察越被偏好
        self.preferences = np.ones(n_observations) / n_observations
        
        # 初始状态先验
        self.initial_state_prior = np.ones(n_states) / n_states

    def predict_forward(self, state_belief: np.ndarray, action: int, steps: int = 1) -> np.ndarray:
        """前向预测: 给定当前信念和行动，预测未来状态"""
        belief = state_belief.copy()
        for _ in range(steps):
            belief = belief @ self.transition_matrix[:, action, :]
        return belief

    def expected_observation(self, state_belief: np.ndarray) -> np.ndarray:
        """期望观察: 给定状态信念，期望看到什么"""
        return state_belief @ self.observation_matrix

    def update_transition(self, from_state: int, action: int, to_state: int, weight: float = 1.0):
        """更新状态转移模型 (学习)"""
        self.transition_matrix[from_state, action, to_state] += weight
        # 归一化
        row_sum = self.transition_matrix[from_state, action, :].sum()
        if row_sum > 0:
            self.transition_matrix[from_state, action, :] /= row_sum


# ═══════════════════════════════════════════════════════════════════════
# 主动推理引擎
# ═══════════════════════════════════════════════════════════════════════

class ActiveInferenceEngine:
    """
    主动推理引擎 — 统一感知-行动循环。
    
    工作流:
    1. 感知观测 o
    2. 更新信念 q(s) ← Bayes(q(s), o)
    3. 枚举策略 π ∈ Π
    4. 计算期望自由能 G(π) 对每个策略
    5. 选择 π* = argmin G(π)
    6. 执行 π*，回到步骤1
    
    这比强化学习更基础:
    RL需要外部奖励函数 → 主观且需要设计
    AI只需要最小化惊讶 → 自动从数据中学习
    """

    def __init__(self, name: str = "active_inference"):
        self.name = name
        
        # 预定义策略库
        self.policies: Dict[str, Policy] = {
            "explore_random": Policy("explore_random", ActionType.EXPLORE, 
                                      epistemic_weight=1.0, pragmatic_weight=0.0),
            "exploit_best": Policy("exploit_best", ActionType.EXPLOIT,
                                    epistemic_weight=0.0, pragmatic_weight=1.0),
            "balanced": Policy("balanced", ActionType.HYBRID,
                               epistemic_weight=0.5, pragmatic_weight=0.5),
            "observe_first": Policy("observe_first", ActionType.OBSERVE,
                                     epistemic_weight=0.8, pragmatic_weight=0.2),
            "safe_path": Policy("safe_path", ActionType.AVOID,
                                epistemic_weight=0.2, pragmatic_weight=0.3),
            "defer_decision": Policy("defer_decision", ActionType.DEFER,
                                      epistemic_weight=0.4, pragmatic_weight=0.1),
        }
        
        # 策略效果信念 (每个策略的成功率)
        self.policy_belief = BeliefState(
            name="policy_effectiveness",
            belief_type=BeliefType.DIRICHLET,
            n_categories=len(self.policies),
        )
        
        # 核心组件
        self.generative_model = GenerativeModel()
        self.precision = PrecisionWeighting()
        self.criticality = CriticalityRegulator()
        
        # 经验
        self.episode_history: List[Dict] = []

    def select_action(self,
                       belief_state: BeliefState,
                       preferred_outcomes: Optional[np.ndarray] = None,
                       forced_exploration: bool = False) -> Tuple[str, Policy, Dict[str, float]]:
        """
        主动推理的行动选择。
        
        1. 对每个策略计算期望自由能 G(π)
        2. Softmin选择 → 概率 ∝ exp(-G/T)
        3. 返回选择的策略
        
        热力学:
        T → 0: greedy (只选最优)
        T → ∞: random (完全探索)
        最佳: T ≈ 1 (平衡)
        """
        if forced_exploration:
            # 强制探索: 选择最不确定的策略
            policy_names = list(self.policies.keys())
            probs = self.policy_belief.alpha / self.policy_belief.alpha.sum()
            uncertainty = -probs * np.log(np.maximum(probs, 1e-10))
            return policy_names[np.argmax(uncertainty)], self.policies[policy_names[np.argmax(uncertainty)]], {}

        T = self.criticality.temperature
        
        # 计算每个策略的期望自由能
        G_values = {}
        for name, policy in self.policies.items():
            idx = list(self.policies.keys()).index(name)
            G = policy.expected_free_energy(
                belief_state=belief_state,
                preferred_outcomes=preferred_outcomes,
                temperature=T,
            )
            # 加入策略信念的影响
            policy_prob = self.policy_belief.expected_probability[idx]
            G -= 0.1 * math.log(max(policy_prob, 1e-10))  # 偏好已知有效的策略
            G_values[name] = G

        # Softmin选择
        G_array = np.array(list(G_values.values()))
        G_min = G_array.min()
        weights = np.exp(-(G_array - G_min) / max(T, 0.05))
        probs = weights / weights.sum()

        # 采样
        names = list(G_values.keys())
        chosen_idx = np.random.choice(len(names), p=probs)
        chosen_name = names[chosen_idx]

        return chosen_name, self.policies[chosen_name], {
            "G_values": {k: round(v, 3) for k, v in G_values.items()},
            "selection_probs": {n: round(float(p), 3) for n, p in zip(names, probs)},
            "temperature": T,
        }

    def learn_from_outcome(self, policy_name: str, success: bool, duration: float):
        """
        从行动结果学习。
        
        成功 → 强化策略信念
        失败 → 当前信念受到挑战
        
        神经科学类比:
        多巴胺信号 = 实际 - 预期 = 预测误差
        正预测误差 → 强化
        负预测误差 → 削弱
        """
        if policy_name in self.policies:
            idx = list(self.policies.keys()).index(policy_name)
            self.policy_belief.observe(idx, weight=1.0 if success else 0.1)

            # 记录经验
            self.episode_history.append({
                "policy": policy_name,
                "success": success,
                "duration": duration,
            })
            if len(self.episode_history) > 1000:
                self.episode_history = self.episode_history[-1000:]

            # 临界态调节
            expected_success = float(self.policy_belief.expected_probability[idx])
            surprise = -math.log(max(expected_success, 1e-10)) if success else -math.log(max(1-expected_success, 1e-10))
            self.criticality.adjust(surprise, 1.0)

    def get_exploration_ratio(self) -> float:
        """当前探索倾向: 0=纯利用, 1=纯探索"""
        T = self.criticality.temperature
        return min(T / 5.0, 1.0)

    def should_explore(self) -> bool:
        """是否应该探索 (高不确定性或高温度)"""
        return (self.policy_belief.uncertainty > 1.5 or 
                self.criticality.temperature > 2.0)


# ═══════════════════════════════════════════════════════════════════════
# 多时间尺度学习
# ═══════════════════════════════════════════════════════════════════════

class MultiScaleLearning:
    """
    多时间尺度的学习机制。
    
    同时维护多个时间尺度的信念:
    - 快尺度 (τ₁ ≈ 分钟): 快速适应当前会话
    - 中尺度 (τ₂ ≈ 小时): 日间模式学习  
    - 慢尺度 (τ₃ ≈ 天): 长期趋势
    
    神经科学基础:
    - 快 = AMPA受体 (快速突触可塑性)
    - 中 = NMDA受体 (中等)
    - 慢 = 基因表达 (结构性变化)
    """

    def __init__(self, n_categories: int = 5):
        self.n_categories = n_categories
        
        # 三个时间尺度的信念
        self.fast_belief = BeliefState("fast", BeliefType.DIRICHLET, n_categories=n_categories)
        self.medium_belief = BeliefState("medium", BeliefType.DIRICHLET, n_categories=n_categories)
        self.slow_belief = BeliefState("slow", BeliefType.DIRICHLET, n_categories=n_categories)
        
        self.fast_count = 0

    def observe(self, category: int, weight: float = 1.0):
        """在所有时间尺度上更新"""
        self.fast_belief.observe(category, weight * 1.0)
        self.medium_belief.observe(category, weight * 0.3)
        self.slow_belief.observe(category, weight * 0.1)
        self.fast_count += 1

    def get_consensus_belief(self) -> np.ndarray:
        """
        多个时间尺度的加权共识。
        
        近期偏好快尺度，长期信任慢尺度。
        分歧过大 → 环境可能正在变化 → 提高警觉
        """
        # 权重取决于观察量
        fast_w = min(self.fast_count / 10, 0.5)  # 逐渐增加快尺度权重
        medium_w = 0.3
        slow_w = 0.2
        
        belief = (fast_w * self.fast_belief.expected_probability +
                  medium_w * self.medium_belief.expected_probability +
                  slow_w * self.slow_belief.expected_probability)
        return belief / belief.sum()

    def detect_regime_change(self) -> bool:
        """
        检测环境突变。
        """
        if self.fast_count < 5:
            return False
        fast_prob = self.fast_belief.expected_probability
        slow_prob = self.slow_belief.expected_probability
        divergence = np.sum(np.abs(fast_prob - slow_prob))
        return bool(divergence > 0.5)  # 分歧 > 0.5 → 可能发生制度转变


# ═══════════════════════════════════════════════════════════════════════
# P1: 多步前瞻规划 (Lookahead Monte Carlo Tree Search)
# ═══════════════════════════════════════════════════════════════════════

class LookaheadPlanner:
    """
    基于 Monte Carlo Rollout 的深度时间规划。
    
    超越贪心单步决策: 模拟未来 N 步轨迹, 选择期望自由能最小的行动序列。
    
    论文: Fountas et al. (2024) "Deep Active Inference for Episodic Planning"
    """
    
    def __init__(self, model: GenerativeModel, horizon: int = 3, n_rollouts: int = 50):
        self.model = model
        self.horizon = horizon
        self.n_rollouts = n_rollouts
    
    def plan(self, belief: BeliefState, preferences: np.ndarray, 
             n_actions: int = 5, temperature: float = 1.0) -> tuple:
        """
        多步前瞻规划: 返回 (最优行动, G值).
        
        Args:
            belief: 当前信念状态
            preferences: 偏好分布 p(o) ~ exp(-G)
            n_actions: 行动空间大小
            temperature: 探索温度 (高→更随机)
        
        Returns:
            (best_action, expected_free_energy)
        """
        action_G = {}
        
        for a0 in range(n_actions):
            total_G = 0.0
            
            for _ in range(self.n_rollouts):
                G_trajectory = 0.0
                state = belief.expected_probability
                action = a0
                discount = 1.0
                
                for t in range(self.horizon):
                    # 模拟状态转移 (带噪声)
                    next_state = self.model.predict_forward(state, action)
                    noise = np.random.dirichlet(np.ones_like(next_state) * 0.1) * 0.05
                    next_state = 0.95 * next_state + noise
                    next_state /= next_state.sum()
                    
                    # 计算该步期望自由能 G_t ≈ -ln(p(o|π)·preferences) + epistemic
                    obs_probs = self.model.expected_observation_probability(next_state)
                    expected_utility = np.dot(obs_probs, preferences)
                    epistemic_value = -np.sum(next_state * np.log(next_state + 1e-10))  # entropy
                    
                    G_step = -np.log(expected_utility + 1e-10) + temperature * epistemic_value
                    G_trajectory += discount * G_step
                    
                    discount *= 0.9  # 未来衰减
                    state = next_state
                    action = np.random.choice(n_actions)  # 后续简单随机策略
                
                total_G += G_trajectory
            
            action_G[a0] = total_G / self.n_rollouts
        
        best_action = min(action_G, key=action_G.get)
        return best_action, action_G[best_action]


# ═══════════════════════════════════════════════════════════════════════
# P1: 双过程决策 (系统1习惯 + 系统2规划)
# ═══════════════════════════════════════════════════════════════════════

class DualProcessDecision:
    """
    系统1(习惯,快速) + 系统2(规划,精确)的双过程决策模型。
    
    神经科学基础:
    - 系统1 = 纹状体习惯回路 (模型自由, TD学习)
    - 系统2 = 前额叶规划回路 (模型基, 主动推理)
    - 仲裁 = 前扣带皮层 (基于不确定性/认知负荷切换)
    
    论文: Pezzulo et al. (2025) "Habit and Goal-Directed Control"
    """
    
    def __init__(self, ai_engine: ActiveInferenceEngine = None):
        self.habit_cache: Dict[int, float] = {}  # state_hash → estimated_value
        self.use_counts: Dict[int, int] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.habit_threshold = 10  # 重复N次后形成习惯
        self.ai_engine = ai_engine
    
    def _hash_state(self, belief: BeliefState) -> int:
        """对信念状态做轻量哈希"""
        prob = belief.expected_probability
        return hash(tuple(np.round(prob, 3)))
    
    def cached_value(self, state_hash: int) -> Optional[float]:
        """查询习惯缓存的动作值"""
        self.use_counts[state_hash] = self.use_counts.get(state_hash, 0) + 1
        if self.use_counts[state_hash] >= self.habit_threshold:
            self.cache_hits += 1
            return self.habit_cache.get(state_hash)
        self.cache_misses += 1
        return None
    
    def update_habit(self, state_hash: int, action_value: float, lr: float = 0.1):
        """更新习惯缓存 (模型自由 TD 学习)"""
        old = self.habit_cache.get(state_hash, 0.5)
        self.habit_cache[state_hash] = old + lr * (action_value - old)
    
    def should_use_habit(self, uncertainty: float = 0.0) -> bool:
        """
        决定使用系统1(习惯)还是系统2(规划)。
        
        - 低不确定性 + 高缓存命中率 → 习惯 (快速)
        - 高不确定性 + 新状态 → 规划 (精确)
        """
        total = max(self.cache_hits + self.cache_misses, 1)
        hit_rate = self.cache_hits / total
        
        if hit_rate < 0.6:
            return False  # 缓存还不够可靠
        if uncertainty > 0.4:
            return False  # 环境太不确定, 需要仔细推理
        
        return True
    
    def get_stats(self) -> dict:
        """返回双过程统计"""
        total = max(self.cache_hits + self.cache_misses, 1)
        return {
            "cache_size": len(self.habit_cache),
            "hit_rate": self.cache_hits / total,
            "mode": "habit" if self.should_use_habit() else "planning",
        }

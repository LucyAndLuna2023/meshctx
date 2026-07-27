"""
MeshCtx Super Brain — 11-Region Cognitive Architecture
======================================================

哺乳动物大脑11区域的工程化映射。每个区域解决一个真实问题。

架构:
  ThalamicGate ──→ Cortex (Agent Loop) ──→ BasalGanglia (Action)
       ↑                    ↓                      ↓
  Insula (内部感知)   HippocampalReplay    CerebellarForward
       ↑              (记忆+模式)           (结果预测)
  AmygdalaSalience ←── ACC (冲突) ──→ MirrorNeuron (心智)
       ↓                                  ↓
  DefaultModeNetwork (创意)          (他者建模)
       ↓
  LTP (突触增强) ←── GnosticField (直觉识别)

License: MIT
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.brain")

# ── External brain region modules ────────────────────────────────────────
from .brain_ltp import LTPEngine, LTPEnsemble
from .brain_gnostic import GnosticField, GestaltManager

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

class SalienceLevel(Enum):
    """重要性等级（杏仁核输出）"""
    CRITICAL  = 5   # 必须永久记忆
    HIGH      = 4   # 重要，长期存储
    MEDIUM    = 3   # 普通，中期存储
    LOW       = 2   # 琐碎，短期存储
    TRIVIAL   = 1   # 噪音，可丢弃

class ConflictType(Enum):
    """冲突类型（ACC 检测）"""
    GOAL_CONFLICT    = auto()  # 多目标互斥
    RESOURCE_RACE    = auto()  # 资源争抢
    TIMING_CLASH     = auto()  # 时序冲突
    VALUE_DIVERGENCE = auto()  # 价值分歧

class BrainState(Enum):
    """大脑全局状态"""
    FOCUSED   = "focused"     # 专注执行
    REFLECTIVE = "reflective" # 反思/回放
    CREATIVE  = "creative"    # 发散思维
    IDLE      = "idle"        # 待机
    ALERT     = "alert"       # 警觉
    RECOVERING = "recovering" # 恢复中

# ---------------------------------------------------------------------------
# 统一事件总线
# ---------------------------------------------------------------------------

@dataclass
class BrainEvent:
    """大脑内部事件"""
    source: str           # 来源区域名
    event_type: str       # 事件类型
    payload: Any          # 载荷
    timestamp: float = field(default_factory=time.time)
    salience: SalienceLevel = SalienceLevel.MEDIUM

# ---------------------------------------------------------------------------
# Region 1: Hippocampal Replay (海马回放)
# ---------------------------------------------------------------------------

class HippocampalReplay:
    """
    海马回放 — Sharp-Wave Ripple 记忆巩固

    空闲时以 10-20x 速度重播近期经历，发现跨记忆模式，
    生成创造性洞察并转变为技能。

    机制:
      1. 收集近期 episode（任务+结果+反思）
      2. 压缩重播 — 提取关键帧
      3. 模式发现 — 跨 episode 的共性序列
      4. 技能生成 — 模式 → 可复用技能
    """

    def __init__(self, replay_speed: int = 15, max_episodes: int = 100):
        self.replay_speed = replay_speed
        self.episodes: deque = deque(maxlen=max_episodes)
        self.discovered_patterns: List[Dict] = []
        self.generated_skills: List[Dict] = []
        self._index: Dict[str, List[int]] = {}  # 倒排索引加速模式匹配

    def record_episode(self, task: str, actions: List[str],
                       outcome: str, reflection: str,
                       salience: SalienceLevel = SalienceLevel.MEDIUM) -> Dict:
        """记录一个 episode 到海马体"""
        ep = {
            "id": len(self.episodes),
            "task": task,
            "actions": actions,
            "outcome": outcome,
            "reflection": reflection,
            "salience": salience.value,
            "timestamp": time.time(),
        }
        self.episodes.append(ep)
        # 更新倒排索引
        for token in self._tokenize(task):
            self._index.setdefault(token, []).append(ep["id"])
        return ep

    def replay(self, top_n: int = 10) -> List[Dict]:
        """
        执行一次回放 — 压缩重播最近 N 个 episode，
        返回发现的跨记忆模式
        """
        if len(self.episodes) < 3:
            return []

        recent = list(self.episodes)[-top_n:]
        if len(recent) < 3:
            return []

        patterns = []
        # 模式1: 重复出现的 action 序列
        action_sequences = [tuple(e["actions"]) for e in recent]
        for i in range(len(action_sequences)):
            for j in range(i + 1, len(action_sequences)):
                common = self._lcs(action_sequences[i], action_sequences[j])
                if len(common) >= 2:
                    patterns.append({
                        "type": "action_sequence",
                        "pattern": list(common),
                        "frequency": sum(1 for s in action_sequences
                                        if self._is_subsequence(common, s)),
                        "episodes": [recent[i]["id"], recent[j]["id"]],
                    })

        # 模式2: 成功模式的共性（outcome positives）
        successes = [e for e in recent if "成功" in e.get("outcome", "")
                     or "PASS" in e.get("outcome", "")
                     or "✅" in e.get("outcome", "")]
        if len(successes) >= 2:
            common_actions = set(successes[0]["actions"])
            for s in successes[1:]:
                common_actions &= set(s["actions"])
            if common_actions:
                patterns.append({
                    "type": "success_pattern",
                    "common_actions": list(common_actions),
                    "success_count": len(successes),
                })

        # 模式3: 失败 → 修复的因果链
        for e in recent:
            if "失败" in e.get("outcome", "") or "FAIL" in e.get("outcome", ""):
                # 找同一 session 中后续的成功
                later = [r for r in recent if r["id"] > e["id"]
                        and ("成功" in r.get("outcome", "")
                             or "PASS" in r.get("outcome", ""))]
                if later:
                    patterns.append({
                        "type": "failure_recovery",
                        "failure_id": e["id"],
                        "failure": e["task"],
                        "recovery_id": later[0]["id"],
                        "recovery_actions": later[0]["actions"],
                    })

        if patterns:
            self.discovered_patterns.extend(patterns)

        # 从模式生成技能
        self._generate_skills_from_patterns(patterns)

        return patterns

    def _generate_skills_from_patterns(self, patterns: List[Dict]):
        """从发现的模式生成可复用技能"""
        for p in patterns:
            if p["type"] == "action_sequence" and p.get("frequency", 0) >= 3:
                skill = {
                    "name": f"pattern_{len(self.generated_skills)}",
                    "trigger": "自动 — 海马回放发现",
                    "actions": p["pattern"],
                    "confidence": min(p["frequency"] / 5.0, 1.0),
                    "source_pattern": p,
                }
                self.generated_skills.append(skill)

    def get_state(self) -> Dict:
        return {
            "episodes": len(self.episodes),
            "patterns": len(self.discovered_patterns),
            "skills": len(self.generated_skills),
            "latest_skills": self.generated_skills[-3:] if self.generated_skills else [],
        }

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        import re
        return re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z_]\w*', text.lower())

    @staticmethod
    def _lcs(a: Tuple, b: Tuple) -> Tuple:
        """最长公共子序列"""
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m):
            for j in range(n):
                dp[i+1][j+1] = dp[i][j] + 1 if a[i] == b[j] else max(dp[i+1][j], dp[i][j+1])
        # backtrack
        i, j = m, n
        result = []
        while i > 0 and j > 0:
            if a[i-1] == b[j-1]:
                result.append(a[i-1])
                i -= 1; j -= 1
            elif dp[i-1][j] > dp[i][j-1]:
                i -= 1
            else:
                j -= 1
        return tuple(reversed(result))

    @staticmethod
    def _is_subsequence(sub: Tuple, full: Tuple) -> bool:
        it = iter(full)
        return all(s in it for s in sub)  # simplified


# ---------------------------------------------------------------------------
# Region 2: Amygdala Salience (杏仁核 — 情感标记)
# ---------------------------------------------------------------------------

class AmygdalaSalience:
    """
    杏仁核 — 情感标记与重要性评分

    为每个事件/记忆打分，决定：
      - 存储优先级（L0-L4 记忆层级）
      - 检索时的排名权重
      - 是否触发警觉状态

    评分维度:
      1. 新颖性 (novelty)     — 从未见过
      2. 意外性 (surprise)    — 预测偏差
      3. 奖励性 (reward)      — 任务成功
      4. 惩罚性 (punishment)  — 错误/失败
      5. 关联性 (relevance)   — 与当前目标相关度
    """

    def __init__(self, decay_rate: float = 0.05):
        self.decay_rate = decay_rate
        self._known_patterns: Set[str] = set()   # 已知模式哈希
        self._reward_history: deque = deque(maxlen=100)
        self._punishment_history: deque = deque(maxlen=100)
        self._baseline_surprise: float = 0.0

    def evaluate(self, event: BrainEvent,
                 context: Optional[Dict] = None) -> SalienceLevel:
        """
        评估事件的重要性

        Returns:
            SalienceLevel: CRITICAL / HIGH / MEDIUM / LOW / TRIVIAL
        """
        scores = {
            "novelty": self._score_novelty(event),
            "surprise": self._score_surprise(event),
            "reward": self._score_reward(event, context),
            "punishment": self._score_punishment(event),
            "relevance": self._score_relevance(event, context),
        }

        # 加权求和
        weights = {"novelty": 0.20, "surprise": 0.25, "reward": 0.20,
                   "punishment": 0.20, "relevance": 0.15}
        total = sum(scores[k] * weights[k] for k in weights)

        # 惩罚性有杠杆效应 — 失败记得更牢
        if scores["punishment"] > 0.7:
            total *= 1.5

        # 映射到等级
        if total >= 0.85:  return SalienceLevel.CRITICAL
        if total >= 0.65:  return SalienceLevel.HIGH
        if total >= 0.40:  return SalienceLevel.MEDIUM
        if total >= 0.20:  return SalienceLevel.LOW
        return SalienceLevel.TRIVIAL

    def _score_novelty(self, event: BrainEvent) -> float:
        key = f"{event.source}:{event.event_type}"
        if key in self._known_patterns:
            return 0.0
        self._known_patterns.add(key)
        # 事件类型越罕见，新颖性越高
        type_count = sum(1 for p in self._known_patterns
                        if event.event_type in p)
        return min(1.0, 2.0 / (type_count + 1))

    def _score_surprise(self, event: BrainEvent) -> float:
        # 简单版：事件严重程度与基线偏差
        payload_str = str(event.payload)[:200]
        surprise = min(1.0, len(payload_str) / 500.0)
        self._baseline_surprise = (0.9 * self._baseline_surprise
                                   + 0.1 * surprise)
        return surprise

    def _score_reward(self, event: BrainEvent,
                      context: Optional[Dict]) -> float:
        positive = ["成功", "PASS", "✅", "completed", "success",
                    "通过", "修复", "solved", "resolved"]
        payload_str = str(event.payload)
        score = sum(1 for w in positive if w in payload_str) / max(len(positive), 1)
        return min(score, 1.0)

    def _score_punishment(self, event: BrainEvent) -> float:
        negative = ["失败", "FAIL", "❌", "error", "ERROR", "crash",
                    "超时", "timeout", "blocked", "denied", "崩溃"]
        payload_str = str(event.payload)
        score = sum(1 for w in negative if w in payload_str) / max(len(negative), 1)
        if score > 0:
            self._punishment_history.append(time.time())
        return min(score, 1.0)

    def _score_relevance(self, event: BrainEvent,
                         context: Optional[Dict]) -> float:
        if not context or "active_goals" not in context:
            return 0.3
        goals = context.get("active_goals", [])
        payload_str = str(event.payload).lower()
        matches = sum(1 for g in goals if g.lower() in payload_str)
        return min(1.0, matches / max(len(goals), 1))


# ---------------------------------------------------------------------------
# Region 3: Default Mode Network (默认模式网络 — 创意发散)
# ---------------------------------------------------------------------------

class DefaultModeNetwork:
    """
    默认模式网络 — 背景创意发散

    空闲时随机连接远距离概念，生成新颖想法。
    模拟人脑的"走神"（mind-wandering）——看似不相关，
    但常产生突破性洞见。

    机制:
      1. 从记忆库随机取两个远距离概念
      2. 尝试建立隐喻连接
      3. 评估创意质量
      4. 推送高质量创意给海马体
    """

    def __init__(self, creativity: float = 0.7):
        self.creativity = creativity
        self.concept_store: Dict[str, List[str]] = {}  # domain → concepts
        self.ideas_generated: List[Dict] = []
        self._last_wander: float = 0

    def add_concept(self, domain: str, concept: str, tags: List[str] = None):
        """向概念库添加一个概念"""
        self.concept_store.setdefault(domain, []).append(concept)

    def wander(self) -> Optional[Dict]:
        """
        一次"走神" — 随机连接两个远距离概念，
        生成一个创意想法
        """
        import random

        if len(self.concept_store) < 2:
            return None

        # 选两个不同领域
        domains = list(self.concept_store.keys())
        d1, d2 = random.sample(domains, min(2, len(domains)))

        if not self.concept_store[d1] or not self.concept_store[d2]:
            return None

        c1 = random.choice(self.concept_store[d1])
        c2 = random.choice(self.concept_store[d2])

        # 生成创意连接
        bridges = [
            f"用 {d1} 的方法解决 {d2} 领域的问题: {c1} → {c2}",
            f"如果 {c1} 和 {c2} 结合，会产生什么新事物？",
            f"从 {c1} 的失败模式中，{d2} 可以学到什么？",
        ]
        idea = {
            "domain_a": d1, "concept_a": c1,
            "domain_b": d2, "concept_b": c2,
            "bridge": random.choice(bridges),
            "quality": self.creativity * random.random(),
            "timestamp": time.time(),
        }

        if idea["quality"] > 0.5:
            self.ideas_generated.append(idea)

        self._last_wander = time.time()
        return idea

    def get_best_ideas(self, n: int = 5) -> List[Dict]:
        """获取最高质量的创意"""
        return sorted(self.ideas_generated,
                     key=lambda i: i["quality"], reverse=True)[:n]

    def get_state(self) -> Dict:
        return {
            "domains": len(self.concept_store),
            "concepts": sum(len(v) for v in self.concept_store.values()),
            "ideas": len(self.ideas_generated),
        }


# ---------------------------------------------------------------------------
# Region 4: Thalamic Gate (丘脑门 — 注意力过滤)
# ---------------------------------------------------------------------------

class ThalamicGate:
    """
    丘脑门 — 感觉信息门控

    决定什么信息进入"皮层"（主 agent 循环）。
    防止上下文窗口被无关信息淹没。

    过滤层级:
      1. 基于当前目标的相关性
      2. 基于杏仁核的显著性
      3. 基于容量限制（上下文窗口上限）
    """

    def __init__(self, max_context_tokens: int = 8000,
                 max_memories: int = 20):
        self.max_context_tokens = max_context_tokens
        self.max_memories = max_memories
        self.current_focus: List[str] = []   # 当前焦点目标
        self._attention_weights: Dict[str, float] = {}

    def set_focus(self, goals: List[str]):
        """设置当前注意力焦点"""
        self.current_focus = goals

    def filter_memories(self, memories: List[Dict],
                        salience_map: Dict[int, SalienceLevel]) -> List[Dict]:
        """
        过滤记忆 — 只让高相关+高显著性的通过

        Args:
            memories: 记忆列表, 每项含 {id, content, domain, ...}
            salience_map: memory_id → SalienceLevel

        Returns:
            通过过滤的记忆列表（按优先级排序，最多 max_memories 条）
        """
        scored = []
        for mem in memories:
            score = self._compute_attention_score(mem, salience_map)
            if score > 0.1:  # 阈值过滤
                scored.append((score, mem))

        # 按分数降序，截断
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:self.max_memories]]

    def filter_context(self, items: List[Dict]) -> List[Dict]:
        """
        过滤上下文项 — 保留高相关性的

        每个 item 应有: {type, content, relevance(0-1)}
        """
        scored = [(item.get("relevance", 0.5), item) for item in items]
        scored.sort(key=lambda x: x[0], reverse=True)

        total_tokens = 0
        result = []
        for score, item in scored:
            tokens = len(str(item.get("content", ""))) // 4  # 粗略估计
            if total_tokens + tokens > self.max_context_tokens:
                break
            result.append(item)
            total_tokens += tokens
        return result

    def _compute_attention_score(self, memory: Dict,
                                 salience_map: Dict) -> float:
        """计算综合注意力得分"""
        score = 0.0

        # 与当前目标的相关性
        content = str(memory.get("content", ""))
        for goal in self.current_focus:
            if goal.lower() in content.lower():
                score += 0.3

        # 显著性贡献（杏仁核）
        mem_id = memory.get("id")
        if mem_id in salience_map:
            salience = salience_map[mem_id]
            score += {SalienceLevel.CRITICAL: 0.5, SalienceLevel.HIGH: 0.35,
                      SalienceLevel.MEDIUM: 0.2, SalienceLevel.LOW: 0.1,
                      SalienceLevel.TRIVIAL: 0.0}.get(salience, 0.1)

        # 时近性
        age = time.time() - memory.get("timestamp", time.time())
        recency = max(0, 1.0 - age / 86400)  # 24小时内新鲜
        score += 0.15 * recency

        return min(score, 1.0)

    def get_state(self) -> Dict:
        return {
            "focus": self.current_focus,
            "max_memories": self.max_memories,
            "attention_weights": dict(list(self._attention_weights.items())[:10]),
        }


# ---------------------------------------------------------------------------
# Region 5: Cerebellar Forward Model (小脑前向模型 — 结果预测)
# ---------------------------------------------------------------------------

class CerebellarForwardModel:
    """
    小脑前向模型 — 动作结果预测

    在执行动作前预测其后果。用于：
      1. 工具调用的安全预判
      2. 多步计划的模拟执行
      3. 异常检测（实际 vs 预测偏差）

    学习机制: 每次执行后比较预测 vs 实际，更新模型
    """

    def __init__(self):
        # 动作 → (平均耗时, 成功率, 典型输出模式)
        self._action_profile: Dict[str, Dict[str, Any]] = {}
        self._prediction_errors: deque = deque(maxlen=50)

    def predict(self, action: str, params: Dict = None) -> Dict:
        """
        预测一个动作的执行结果

        Returns:
            {duration_estimate, success_probability, risk_level, warnings}
        """
        profile = self._action_profile.get(action, {})
        params = params or {}

        # 默认预测
        prediction = {
            "duration_estimate": profile.get("avg_duration", 5.0),
            "success_probability": profile.get("success_rate", 0.85),
            "risk_level": self._assess_risk(action, params),
            "warnings": [],
        }

        # 高风险操作
        if action in ("write_file", "terminal", "remote_exec", "deploy"):
            prediction["risk_level"] = "HIGH"
            prediction["warnings"].append(f"⚠ {action} is destructive — verify params")

        # 已知慢操作
        if action in ("browser_navigate", "web_extract", "vision_analyze"):
            prediction["duration_estimate"] = max(prediction["duration_estimate"], 8.0)

        return prediction

    def update(self, action: str, predicted: Dict, actual: Dict):
        """
        执行后更新模型 — 比较预测 vs 实际
        """
        profile = self._action_profile.setdefault(action, {
            "avg_duration": predicted.get("duration_estimate", 5.0),
            "success_rate": predicted.get("success_probability", 0.85),
            "sample_count": 1,
        })

        n = profile["sample_count"]
        # 指数加权更新
        alpha = 0.3
        profile["avg_duration"] = ((1 - alpha) * profile["avg_duration"]
                                   + alpha * actual.get("duration", profile["avg_duration"]))
        profile["success_rate"] = ((1 - alpha) * profile["success_rate"]
                                   + alpha * (1.0 if actual.get("success") else 0.0))
        profile["sample_count"] = n + 1

        # 记录预测误差
        error = abs(predicted.get("duration_estimate", 5)
                   - actual.get("duration", 5))
        self._prediction_errors.append(error)

    def _assess_risk(self, action: str, params: Dict) -> str:
        """评估动作风险"""
        destructive = {"write_file", "terminal", "remote_exec", "deploy",
                       "patch", "browser_click"}
        if action in destructive:
            if params.get("__approved"):
                return "MEDIUM"
            return "HIGH"
        return "LOW"

    def get_state(self) -> Dict:
        recent_errors = (sum(self._prediction_errors) /
                        max(len(self._prediction_errors), 1))
        return {
            "profiled_actions": len(self._action_profile),
            "avg_prediction_error": round(recent_errors, 2),
        }


# ---------------------------------------------------------------------------
# Region 6: Basal Ganglia (基底节 — 动作选择)
# ---------------------------------------------------------------------------

class BasalGanglia:
    """
    基底节 — 动作选择与强化学习

    基于历史奖励信号选择最优动作。
    实现 softmax over Q-values + ε-greedy 探索。

    同时管理习惯形成 — 高频成功动作变为习惯（自动执行）
    """

    def __init__(self, temperature: float = 0.5,
                 epsilon: float = 0.1):
        self.temperature = temperature
        self.epsilon = epsilon
        # action → {q_value, success_count, total_count, is_habit}
        self._action_values: Dict[str, Dict] = {}
        self.habits: Set[str] = set()

    def select_action(self, available_actions: List[str],
                      context: str = "") -> Optional[str]:
        """
        从可用动作中选择一个

        Returns:
            选择的动作名，或 None
        """
        if not available_actions:
            return None

        import random

        # ε-greedy 探索
        if random.random() < self.epsilon:
            return random.choice(available_actions)

        # Softmax over Q-values
        q_values = [self._action_values.get(a, {}).get("q_value", 0.5)
                    for a in available_actions]

        # 数值稳定性
        max_q = max(q_values) if q_values else 0
        import math
        exp_values = [math.exp((q - max_q) / max(self.temperature, 0.01))
                      for q in q_values]
        total = sum(exp_values)
        probs = [e / total for e in exp_values]

        return random.choices(available_actions, weights=probs, k=1)[0]

    def reinforce(self, action: str, reward: float):
        """
        强化学习更新 — Q-learning 风格

        Args:
            action: 动作名
            reward: 奖励 (-1.0 ~ 1.0)
        """
        entry = self._action_values.setdefault(action, {
            "q_value": 0.5, "success_count": 0,
            "total_count": 0, "is_habit": False,
        })

        n = entry["total_count"] + 1
        lr = 1.0 / n  # 递减学习率
        entry["q_value"] += lr * (reward - entry["q_value"])
        entry["total_count"] = n
        if reward > 0:
            entry["success_count"] += 1

        # 习惯形成: 连续10次成功 + 成功率 > 90%
        if (entry["total_count"] >= 10
                and entry["success_count"] / entry["total_count"] > 0.9):
            entry["is_habit"] = True
            self.habits.add(action)

    def is_habit(self, action: str) -> bool:
        return action in self.habits

    def get_state(self) -> Dict:
        return {
            "known_actions": len(self._action_values),
            "habits": list(self.habits),
            "top_actions": sorted(
                self._action_values.items(),
                key=lambda x: x[1]["q_value"], reverse=True
            )[:5],
        }


# ---------------------------------------------------------------------------
# Region 7: ACC (前扣带回 — 冲突监测)
# ---------------------------------------------------------------------------

class ACCConflictMonitor:
    """
    ACC — 前扣带回冲突监测

    检测并解决:
      1. 目标冲突 — 两个目标不可同时达成
      2. 资源争抢 — 多个 agent 抢同一资源
      3. 时序冲突 — 动作顺序矛盾
      4. 价值分歧 — 安全 vs 效率的权衡
    """

    def __init__(self):
        self.active_goals: List[Dict] = []
        self.active_conflicts: List[Dict] = []
        self.resolved_conflicts: deque = deque(maxlen=200)

    def check_goal_conflict(self, goal_a: Dict, goal_b: Dict) -> Optional[Dict]:
        """
        检查两个目标是否冲突

        Returns:
            冲突描述 dict，或无冲突时返回 None
        """
        # 简单检测：目标关键词互斥
        exclusive_pairs = [
            ({"修复", "fix"}, {"部署", "deploy"}),
            ({"删除", "delete", "remove"}, {"保留", "keep", "preserve"}),
            ({"重启", "restart"}, {"运行", "run", "running"}),
            ({"禁止", "block"}, {"允许", "allow", "enable"}),
        ]

        keywords_a = set(str(goal_a.get("description", "")).lower().split())
        keywords_b = set(str(goal_b.get("description", "")).lower().split())

        for excl_a, excl_b in exclusive_pairs:
            if (keywords_a & excl_a and keywords_b & excl_b):
                return {
                    "type": ConflictType.GOAL_CONFLICT,
                    "goal_a": goal_a["id"],
                    "goal_b": goal_b["id"],
                    "reason": f"关键词冲突: {excl_a} vs {excl_b}",
                    "suggestion": "确定优先级顺序或寻找可并行的替代方案",
                }

        return None

    def add_goal(self, goal: Dict):
        """添加活动目标，检查冲突"""
        for existing in self.active_goals:
            conflict = self.check_goal_conflict(existing, goal)
            if conflict:
                self.active_conflicts.append(conflict)
                logger.warning(f"ACC: 检测到冲突 — {conflict['reason']}")
        self.active_goals.append(goal)

    def resolve_conflicts(self) -> List[Dict]:
        """
        尝试自动解决冲突

        Returns:
            解决方案列表
        """
        resolutions = []
        remaining = []

        for conflict in self.active_conflicts:
            if conflict["type"] == ConflictType.GOAL_CONFLICT:
                # 策略：按优先级排序，低优先级目标推迟
                goals = [g for g in self.active_goals
                        if g["id"] in (conflict["goal_a"], conflict["goal_b"])]
                if len(goals) == 2:
                    # 优先保留高优先级目标
                    goals.sort(key=lambda g: g.get("priority", 5), reverse=True)
                    resolutions.append({
                        "conflict": conflict,
                        "resolution": "prioritize",
                        "keep": goals[0]["id"],
                        "defer": goals[1]["id"],
                    })
                    self.active_goals.remove(goals[1])
                else:
                    remaining.append(conflict)
            else:
                remaining.append(conflict)

        self.active_conflicts = remaining
        self.resolved_conflicts.extend(resolutions)
        return resolutions

    def get_state(self) -> Dict:
        return {
            "active_goals": len(self.active_goals),
            "conflicts": len(self.active_conflicts),
            "resolved_total": len(self.resolved_conflicts),
        }


# ---------------------------------------------------------------------------
# Region 8: Insula (岛叶 — 内部感知)
# ---------------------------------------------------------------------------

class Insula:
    """
    岛叶 — 内部状态感知 (Interoception)

    持续监控 agent 内部健康:
      - CPU / 内存使用
      - 错误率趋势
      - 响应延迟
      - Token 消耗速率
      - 会话状态

    触发 BrainState.ALERT 或 BrainState.RECOVERING
    """

    def __init__(self, health_check_interval: float = 30.0):
        self.interval = health_check_interval
        self._last_check: float = 0
        self._error_counts: deque = deque(maxlen=60)     # 每分钟错误数
        self._latency_samples: deque = deque(maxlen=100)  # 响应延迟
        self._token_usage: deque = deque(maxlen=100)      # token消耗
        self.state: BrainState = BrainState.IDLE
        self.alerts: List[Dict] = []

    def check(self) -> Dict:
        """
        执行一次健康检查

        Returns:
            健康报告 dict
        """
        import os
        import psutil

        self._last_check = time.time()
        report = {
            "timestamp": self._last_check,
            "state": self.state.value,
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "error_rate": self._compute_error_rate(),
            "avg_latency": self._compute_avg_latency(),
        }

        # 状态判定
        if report["error_rate"] > 0.3 or report["memory_percent"] > 90:
            self.state = BrainState.ALERT
            self.alerts.append({
                "type": "resource_critical",
                "report": report,
                "timestamp": self._last_check,
            })
        elif report["error_rate"] > 0.1 or report["memory_percent"] > 75:
            self.state = BrainState.RECOVERING
        elif self.state in (BrainState.ALERT, BrainState.RECOVERING):
            if report["error_rate"] < 0.05 and report["memory_percent"] < 70:
                self.state = BrainState.IDLE
                self.alerts.append({
                    "type": "recovery_complete",
                    "timestamp": self._last_check,
                })

        return report

    def record_error(self, error_type: str, details: str = ""):
        """记录一个错误事件"""
        self._error_counts.append(time.time())
        logger.debug(f"Insula: 记录错误 — {error_type}: {details[:100]}")

    def record_latency(self, duration: float):
        """记录响应延迟"""
        self._latency_samples.append(duration)

    def record_tokens(self, tokens: int):
        """记录 token 消耗"""
        self._token_usage.append(tokens)

    def _compute_error_rate(self) -> float:
        """计算最近60秒错误率"""
        now = time.time()
        recent = sum(1 for t in self._error_counts if now - t < 60)
        return min(recent / 60.0, 1.0)

    def _compute_avg_latency(self) -> float:
        if not self._latency_samples:
            return 0
        return sum(self._latency_samples) / len(self._latency_samples)

    def get_state(self) -> Dict:
        return {
            "brain_state": self.state.value,
            "error_rate": self._compute_error_rate(),
            "avg_latency": self._compute_avg_latency(),
            "alert_count": len(self.alerts),
        }


def get_super_brain(enable_daemon: bool = False) -> SuperBrain:
    """工厂: 获取 SuperBrain 实例"""
    return SuperBrain(enable_daemon=enable_daemon)


# ====== end of SuperBrain ======


# ---------------------------------------------------------------------------
# Region 9: Mirror Neuron (镜像神经元 — 他者建模)
# ---------------------------------------------------------------------------

class MirrorNeuron:
    """
    镜像神经元 — 心智理论 (Theory of Mind)

    建模其他 agent / 用户的意图、期望和知识状态。

    用于:
      1. 预测用户下一步需求
      2. 多 agent 协作中的角色理解
      3. 用户偏好推断
    """

    def __init__(self, max_models: int = 10):
        self.max_models = max_models
        # entity_id → {estimated_goals, known_facts, behavior_patterns, ...}
        self._entity_models: Dict[str, Dict] = {}

    def observe(self, entity_id: str, action: str,
                context: Dict = None) -> Optional[Dict]:
        """
        观察一个实体的行为，更新心智模型

        Returns:
            推断的意图/目标
        """
        model = self._entity_models.setdefault(entity_id, {
            "estimated_goals": [],
            "observed_actions": deque(maxlen=50),
            "behavior_patterns": {},
            "knowledge_beliefs": set(),
            "last_seen": time.time(),
        })

        model["observed_actions"].append({
            "action": action,
            "context": str(context)[:200] if context else "",
            "timestamp": time.time(),
        })
        model["last_seen"] = time.time()

        # 从行为推断目标
        inferred = self._infer_goal(entity_id, model)
        if inferred:
            model["estimated_goals"].append(inferred)
            model["estimated_goals"] = model["estimated_goals"][-5:]

        return inferred

    def predict_next_action(self, entity_id: str) -> Optional[str]:
        """
        预测一个实体下一步可能做什么

        Returns:
            预测的动作描述
        """
        model = self._entity_models.get(entity_id)
        if not model or not model["observed_actions"]:
            return None

        actions = list(model["observed_actions"])
        if len(actions) < 2:
            return None

        # 找最常见的 action → next_action 转换
        transitions = {}
        for i in range(len(actions) - 1):
            key = actions[i]["action"]
            val = actions[i + 1]["action"]
            transitions.setdefault(key, []).append(val)

        last_action = actions[-1]["action"]
        candidates = transitions.get(last_action, [])
        if candidates:
            from collections import Counter
            return Counter(candidates).most_common(1)[0][0]
        return None

    def estimate_knowledge(self, entity_id: str,
                           fact: str) -> float:
        """
        估计一个实体是否知道某个事实

        Returns:
            0.0(肯定不知道) ~ 1.0(肯定知道)
        """
        model = self._entity_models.get(entity_id, {})
        if fact in model.get("knowledge_beliefs", set()):
            return 0.9

        # 从观察到的上下文推断
        for action_rec in model.get("observed_actions", []):
            if fact.lower() in action_rec.get("context", "").lower():
                return 0.7

        return 0.2  # 默认：可能不知道

    def teach(self, entity_id: str, fact: str):
        """告知：某个实体知道了某个事实"""
        model = self._entity_models.setdefault(entity_id, {})
        model.setdefault("knowledge_beliefs", set()).add(fact)

    def _infer_goal(self, entity_id: str, model: Dict) -> Optional[Dict]:
        """从行为序列推断目标"""
        actions = list(model["observed_actions"])
        if len(actions) < 3:
            return None

        # 最近3个动作的聚合
        recent = [a["action"] for a in actions[-3:]]

        goal_patterns = {
            ("read_file", "search_files", "terminal"): "代码审查/调试",
            ("web_search", "web_extract", "web_search"): "信息研究",
            ("terminal", "terminal", "terminal"): "运维操作",
            ("write_file", "patch", "terminal"): "代码开发",
            ("browser_navigate", "browser_click", "browser_snapshot"): "Web操作",
        }

        recent_tuple = tuple(recent)
        for pattern, goal in goal_patterns.items():
            if self._is_subsequence(pattern, recent_tuple):
                return {"goal": goal, "confidence": 0.8,
                        "based_on": list(recent_tuple)}

        return {"goal": "通用探索", "confidence": 0.3,
                "based_on": list(recent_tuple)}

    @staticmethod
    def _is_subsequence(sub: Tuple, full: Tuple) -> bool:
        it = iter(full)
        return all(s in it for s in sub)

    def get_state(self) -> Dict:
        return {
            "tracked_entities": len(self._entity_models),
            "entities": list(self._entity_models.keys()),
        }


# ---------------------------------------------------------------------------
# Brain Orchestrator — 统一编排
# ---------------------------------------------------------------------------

class SuperBrain:
    """
    超级大脑编排器 — 11区域协调调度

    大脑状态机:
      IDLE → FOCUSED → REFLECTIVE → CREATIVE → IDLE
        ↑         ↓           ↓           ↓
        └─── ALERT ← RECOVERING ←─────────┘
    """

    def __init__(self, enable_daemon: bool = True):
        # 11个区域
        self.hippocampus = HippocampalReplay()
        self.amygdala = AmygdalaSalience()
        self.dmn = DefaultModeNetwork()
        self.thalamus = ThalamicGate()
        self.cerebellum = CerebellarForwardModel()
        self.basal_ganglia = BasalGanglia()
        self.acc = ACCConflictMonitor()
        self.insula = Insula()
        self.mirror = MirrorNeuron()
        self.ltp = LTPEnsemble(n_synapses=128)     # Region 10: 突触可塑性
        self.gnostic = GestaltManager(dim=512)       # Region 11: 直觉识别

        self.state: BrainState = BrainState.IDLE
        self._event_queue: deque = deque(maxlen=200)
        self._daemon_thread: Optional[threading.Thread] = None
        self._running = False

        if enable_daemon:
            self._start_daemon()

    # ── 事件处理 ──

    def process_event(self, event: BrainEvent,
                      context: Dict = None) -> Dict:
        """
        处理一个大脑事件 — 流经各区域

        Returns:
            处理结果 {salience, filtered, predictions, conflicts, ...}
        """
        context = context or {}
        self._event_queue.append(event)

        # 1. 杏仁核: 评估显著性
        salience = self.amygdala.evaluate(event, context)
        event.salience = salience

        # 2. 岛叶: 记录（如是错误）
        if salience.value >= SalienceLevel.HIGH.value:
            if "error" in event.event_type.lower():
                self.insula.record_error(event.event_type,
                                         str(event.payload)[:200])

        # 3. 镜像神经元: 观察（如果是外部事件）
        if event.source not in ("insula", "amygdala", "acc"):
            self.mirror.observe(event.source, event.event_type, context)

        # 4. 小脑: 如是动作事件，记录预测vs实际
        if event.event_type == "action_result":
            self.cerebellum.update(
                event.source,
                context.get("predicted", {}),
                context.get("actual", {}),
            )

        # 5. 基底节: 强化学习更新
        if event.event_type in ("task_success", "task_failure"):
            reward = 1.0 if "success" in event.event_type else -0.5
            self.basal_ganglia.reinforce(event.source, reward)

        # 6. 海马体: 记录重要事件
        if salience.value >= SalienceLevel.MEDIUM.value:
            self.hippocampus.record_episode(
                task=event.event_type,
                actions=[event.source],
                outcome=str(event.payload)[:200],
                reflection=f"Salience: {salience.name}",
                salience=salience,
            )

        # 7. LTP: 突触增强 — 高频重要事件触发长时程增强
        if salience.value >= SalienceLevel.HIGH.value:
            self.ltp.tetanize(voltage=-60, frequency=100, duration=500, p_stimulate=0.3)
        ltp_state = self.ltp.get_ensemble_state()

        # 8. Gnostic: 直觉识别 — 对事件负载进行gestalt模式匹配
        gnostic_result = {"label": None, "system": 0, "confidence": 0.0}
        if isinstance(event.payload, str) and len(event.payload) > 10:
            try:
                import numpy as np
                embedding = np.random.randn(512) * 0.1  # placeholder: 实际应使用text embedding
                gnostic_result = self.gnostic.intuit(embedding, require_confidence=0.6)
            except Exception:
                pass

        return {
            "salience": salience.name,
            "salience_level": salience.value,
            "state": self.state.value,
            "ltp": {
                "potentiated": ltp_state["potentiated"],
                "memory_strength": ltp_state["memory_strength"],
            },
            "gnostic": {
                "label": gnostic_result.get("label"),
                "system": gnostic_result.get("system", 0),
            },
        }

    # ── 状态循环 ──

    def step(self) -> Dict:
        """
        大脑一次 tick — 状态机推进

        Returns:
            当前状态和执行的动作
        """
        action = {"state": self.state.value, "performed": []}

        if self.state == BrainState.IDLE:
            # 空闲时触发反思
            patterns = self.hippocampus.replay(top_n=10)
            if patterns:
                action["performed"].append("hippocampal_replay")
                action["patterns_found"] = len(patterns)
            # 然后进入创造性思维
            self.state = BrainState.CREATIVE

        elif self.state == BrainState.CREATIVE:
            # DMN 走神
            idea = self.dmn.wander()
            if idea and idea["quality"] > 0.6:
                action["performed"].append("creative_idea")
                action["idea"] = idea["bridge"]
            # 检查健康
            health = self.insula.check()
            if health["error_rate"] > 0.2:
                self.state = BrainState.ALERT
            else:
                self.state = BrainState.FOCUSED

        elif self.state == BrainState.FOCUSED:
            # 专注模式 — 主要工作循环入口
            # 检查是否有冲突需要处理
            resolutions = self.acc.resolve_conflicts()
            if resolutions:
                action["performed"].append("conflict_resolved")
                action["resolutions"] = len(resolutions)
            # 工作完成 → 反思
            self.state = BrainState.REFLECTIVE

        elif self.state == BrainState.REFLECTIVE:
            # 反思模式 — 回放+学习
            patterns = self.hippocampus.replay(top_n=5)
            if patterns:
                action["performed"].append("reflection_patterns")
            # 回到空闲
            self.state = BrainState.IDLE

        elif self.state == BrainState.ALERT:
            # 警觉 — 上报问题
            health = self.insula.check()
            action["alerts"] = health
            if health["error_rate"] < 0.05:
                self.state = BrainState.RECOVERING

        elif self.state == BrainState.RECOVERING:
            health = self.insula.check()
            if health["error_rate"] < 0.03:
                self.state = BrainState.IDLE
                action["performed"].append("recovery_complete")

        return action

    # ── 高层API ──

    def select_tool(self, available: List[str],
                    context: str = "") -> Optional[str]:
        """基底节: 选择最优工具"""
        return self.basal_ganglia.select_action(available, context)

    def predict_action(self, action: str, params: Dict = None) -> Dict:
        """小脑: 预测动作结果"""
        return self.cerebellum.predict(action, params)

    def filter_memories(self, memories: List[Dict]) -> List[Dict]:
        """丘脑门: 过滤记忆"""
        return self.thalamus.filter_memories(memories, {})

    def set_focus(self, goals: List[str]):
        """丘脑门: 设置焦点"""
        self.thalamus.set_focus(goals)

    def add_goal(self, goal: Dict):
        """ACC: 添加目标（自动冲突检测）"""
        self.acc.add_goal(goal)

    def estimate_user_knowledge(self, user_id: str, fact: str) -> float:
        """镜像神经元: 估计用户知识"""
        return self.mirror.estimate_knowledge(user_id, fact)

    def get_brain_report(self) -> Dict:
        """全局大脑状态报告"""
        return {
            "state": self.state.value,
            "regions": {
                "hippocampus": self.hippocampus.get_state(),
                "amygdala": {"known_patterns": len(self.amygdala._known_patterns)},
                "dmn": self.dmn.get_state(),
                "thalamus": self.thalamus.get_state(),
                "cerebellum": self.cerebellum.get_state(),
                "basal_ganglia": self.basal_ganglia.get_state(),
                "acc": self.acc.get_state(),
                "insula": self.insula.get_state(),
                "mirror_neuron": self.mirror.get_state(),
            },
            "event_queue": len(self._event_queue),
        }

    # ── 后台守护 ──

    def _start_daemon(self):
        """启动后台大脑循环线程"""
        self._running = True
        self._daemon_thread = threading.Thread(
            target=self._daemon_loop,
            daemon=True,
            name="super-brain-daemon",
        )
        self._daemon_thread.start()

    def _daemon_loop(self):
        """后台循环 — 空闲时自动反思+创意"""
        while self._running:
            try:
                if self.state in (BrainState.IDLE, BrainState.REFLECTIVE,
                                  BrainState.CREATIVE):
                    self.step()
                time.sleep(5)
            except Exception as e:
                logger.error(f"Brain daemon error: {e}")
                time.sleep(10)

    def shutdown(self):
        self._running = False

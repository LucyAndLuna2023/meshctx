"""
在线学习引擎 — Online Learning Engine
===============================

从用户交互中持续学习，更新生成模型的世界表征和用户偏好。

核心功能：
1. InteractionRecorder — 记录用户交互（消息/反馈/编辑）
2. GenerativeModelUpdater — 从交互更新过渡/观测矩阵
3. PreferenceLearner — 从隐式反馈学习用户偏好
4. MemoryConsolidator — 睡眠式记忆巩固（慢波→快速波模式）

用法：
    engine = OnlineLearningEngine()
    engine.record_interaction(user_msg, assistant_msg, feedback_score)
    engine.consolidate()  # 定期巩固
"""

import time
import json
import math
import numpy as np
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

# ── 数据类型 ──────────────────────────────────────────────

@dataclass
class Interaction:
    """单次用户交互记录"""
    timestamp: float
    user_msg: str
    assistant_msg: str
    feedback_score: float  # -1 (负面) ~ +1 (正面), 0=中性
    context: dict = field(default_factory=dict)
    mode: str = "direct"  # "explore" or "direct"
    response_time_ms: float = 0.0
    categories: List[str] = field(default_factory=list)


@dataclass
class Preference:
    """推断的用户偏好"""
    topic: str
    weight: float  # 0~1, 越高代表越偏好
    confidence: float  # 0~1, 数据充足度
    last_updated: float = 0.0
    examples: int = 0


# ── 核心引擎 ──────────────────────────────────────────────

class InteractionRecorder:
    """记录并索引用户交互"""

    def __init__(self, max_history=1000):
        self.history: deque = deque(maxlen=max_history)
        self._topic_counter: Dict[str, float] = defaultdict(float)
        self._category_index: Dict[str, List[int]] = defaultdict(list)
        self._recency_bias = 0.7  # 近期交互权重更高

    def record(self, interaction: Interaction) -> None:
        """记录一次交互"""
        idx = len(self.history)
        self.history.append(interaction)

        # 主题提取/分词
        topics = self._extract_topics(interaction.user_msg)
        for topic in topics:
            self._topic_counter[topic] += 1.0
            self._category_index[topic].append(idx)

        # 给交互附上类别
        interaction.categories = topics

    def _extract_topics(self, text: str, max_kw=5) -> List[str]:
        """简单关键字主题提取"""
        keywords = []
        for kw in ["代码", "搜索", "分析", "写作", "翻译", "数据",
                    "code", "search", "analyze", "write", "translate",
                    "debug", "build", "deploy", "fix", "test", "chat"]:
            if kw.lower() in text.lower() and len(keywords) < max_kw:
                keywords.append(kw)
        return keywords or ["general"]

    def get_recent(self, n=10) -> List[Interaction]:
        """最近n条交互"""
        return list(self.history)[-n:]

    def get_topic_stats(self) -> Dict[str, int]:
        """主题统计"""
        return dict(self._topic_counter)

    def total_interactions(self) -> int:
        return len(self.history)


class GenerativeModelUpdater:
    """
    从交互历史更新生成模型（过渡矩阵 + 观测矩阵）。

    工作原理：
    - 记录用户在每个上下文中选择的行为模式
    - 当反馈为正时强化该过渡
    - 当反馈为负时削弱该过渡
    """

    def __init__(self, n_states=20, n_actions=10, decay_rate=0.98):
        # 过渡矩阵 P(s'|s, a): 从状态s执行动作a→新的状态分布
        self.transition = np.ones((n_states, n_actions, n_states)) * 0.01
        self.transition /= self.transition.sum(axis=2, keepdims=True)  # 归一化

        # 观测矩阵 P(o|s): 在状态s下产生观测o的概率
        self.observation = np.ones((n_states, n_actions)) * 0.05

        # 动作计数器
        self.action_counts = np.zeros((n_states, n_actions))

        self.decay_rate = decay_rate
        self.n_states = n_states
        self.n_actions = n_actions

        # 在线状态编码
        self._state_encoder = {}
        self._action_encoder = {}

    def update(self, prev_state: str, action: str, next_state: str,
               reward: float) -> None:
        """从交互更新模型"""
        si = self._get_state_idx(prev_state)
        ai = self._get_action_idx(action)
        snext = self._get_state_idx(next_state)

        # 更新过渡矩阵
        lr = 0.1 * (1.0 + max(0, reward))  # 正奖励→更快学习
        self.transition[si, ai, snext] += lr
        # 重新归一化
        row_sum = self.transition[si, ai].sum()
        if row_sum > 0:
            self.transition[si, ai] /= row_sum

        # 更新观测矩阵
        self.action_counts[si, ai] += 1
        self.observation[si, ai] = (1 - lr) * self.observation[si, ai] + lr * reward

    def predict_next_state(self, state: str, action: str) -> Tuple[str, float]:
        """预测在给定状态和动作下的下一个状态"""
        si = self._get_state_idx(state)
        ai = self._get_action_idx(action)
        probs = self.transition[si, ai]
        next_si = np.argmax(probs)
        confidence = probs[next_si]
        return self._decode_state(next_si), float(confidence)

    def predict_reward(self, state: str, action: str) -> float:
        """预测动作的期望奖励"""
        si = self._get_state_idx(state)
        ai = self._get_action_idx(action)
        return float(self.observation[si, ai])

    def decay(self):
        """逐步衰减旧知识"""
        self.transition *= self.decay_rate
        self.observation *= self.decay_rate
        # 重新归一化
        for si in range(self.n_states):
            for ai in range(self.n_actions):
                row = self.transition[si, ai]
                s = row.sum()
                if s > 0:
                    row /= s

    def get_model_summary(self) -> dict:
        return {
            "states_seen": len(self._state_encoder),
            "actions_seen": len(self._action_encoder),
            "total_state_actions": int(self.action_counts.sum()),
            "decay_rate": self.decay_rate,
        }

    def _get_state_idx(self, s: str) -> int:
        if s not in self._state_encoder:
            self._state_encoder[s] = len(self._state_encoder) % self.n_states
        return self._state_encoder[s]

    def _get_action_idx(self, a: str) -> int:
        if a not in self._action_encoder:
            self._action_encoder[a] = len(self._action_encoder) % self.n_actions
        return self._action_encoder[a]

    def _decode_state(self, idx: int) -> str:
        rev = {v: k for k, v in self._state_encoder.items()}
        return rev.get(idx, f"state_{idx}")


class PreferenceLearner:
    """
    从隐式反馈学习用户偏好。

    隐式信号：
    - 消息长度：用户发送长消息→更感兴趣
    - 重复主题：多次问同类问题→偏好该主题
    - 反馈得分：直接反馈
    - 响应时间：慢响应→困惑/不感兴趣
    """

    def __init__(self, topic_decay=0.95):
        self.preferences: Dict[str, Preference] = {}
        self.topic_decay = topic_decay

    def update(self, interaction: Interaction) -> None:
        """从一次交互更新偏好"""
        topics = interaction.categories or ["general"]

        for topic in topics:
            if topic not in self.preferences:
                self.preferences[topic] = Preference(
                    topic=topic, weight=0.0, confidence=0.0
                )

            pref = self.preferences[topic]

            # 隐式信号
            msg_length_signal = min(1.0, len(interaction.user_msg) / 200.0)
            feedback_signal = (interaction.feedback_score + 1.0) / 2.0  # 映射到0~1
            repetition_bonus = 0.1 * self._get_topic_count(topic)

            # 加权更新
            new_weight = (
                0.3 * msg_length_signal +
                0.5 * feedback_signal +
                0.2 * min(1.0, repetition_bonus)
            )

            # 指数移动平均
            alpha = 0.3
            pref.weight = (1 - alpha) * pref.weight + alpha * new_weight
            pref.examples += 1
            pref.confidence = min(1.0, pref.examples / 20.0)  # 20次交互后置信
            pref.last_updated = time.time()

    def _get_topic_count(self, topic: str) -> int:
        count = 0
        for p in self.preferences.values():
            if p.topic == topic:
                count = p.examples
        return count

    def get_preference(self, topic: str) -> Optional[Preference]:
        return self.preferences.get(topic)

    def get_top_preferences(self, n=5) -> List[Preference]:
        sorted_prefs = sorted(
            self.preferences.values(),
            key=lambda p: p.weight * p.confidence,
            reverse=True
        )
        return sorted_prefs[:n]

    def summary(self) -> dict:
        return {
            "total_preferences": len(self.preferences),
            "top_topics": [(p.topic, round(p.weight, 2))
                          for p in self.get_top_preferences(5)],
        }


class MemoryConsolidator:
    """
    睡眠式记忆巩固。

    模拟慢波睡眠（SWS）→ 快速眼动（REM）模式：
    - SWS: 重复回放近期交互，强化重要记忆
    - REM: 交叉关联新旧记忆，发现模式

    consolidate() 应定期调用（非每次交互）
    """

    def __init__(self, slow_replay=3, fast_associations=5):
        self.slow_replay = slow_replay
        self.fast_associations = fast_associations
        self._consolidation_count = 0

    def consolidate(self, recorder: InteractionRecorder) -> dict:
        """执行一次记忆巩固"""
        self._consolidation_count += 1
        total = recorder.total_interactions()

        if total == 0:
            return {"consolidated": False, "reason": "no interactions"}

        stats = {
            "cycle": self._consolidation_count,
            "total_interactions": total,
            "topics": recorder.get_topic_stats(),
        }

        # 慢波回放：将高频主题标记为"重要"
        topic_counts = recorder.get_topic_stats()
        important_topics = sorted(topic_counts.items(),
                                  key=lambda x: -x[1])[:5]
        stats["important_topics"] = important_topics
        stats["consolidated"] = True

        return stats


class OnlineLearningEngine:
    """
    在线学习引擎统一入口。

    集成所有组件：
    - InteractionRecorder
    - GenerativeModelUpdater
    - PreferenceLearner
    - MemoryConsolidator
    """

    def __init__(self, max_history=1000):
        self.recorder = InteractionRecorder(max_history=max_history)
        self.model_updater = GenerativeModelUpdater()
        self.preference_learner = PreferenceLearner()
        self.consolidator = MemoryConsolidator()
        self._last_consolidation = time.time()
        self._consolidation_interval = 300  # 每5分钟巩固一次

    def record_interaction(self, user_msg: str, assistant_msg: str,
                           feedback_score: float = 0.0,
                           mode: str = "direct",
                           response_time_ms: float = 0.0,
                           context: dict = None) -> Interaction:
        """记录一次交互并触发学习"""
        interaction = Interaction(
            timestamp=time.time(),
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            feedback_score=max(-1.0, min(1.0, feedback_score)),
            mode=mode,
            response_time_ms=response_time_ms,
            context=context or {},
        )

        # 1. 记录交互
        self.recorder.record(interaction)

        # 2. 更新偏好
        self.preference_learner.update(interaction)

        # 3. 更新生成模型
        for topic in interaction.categories:
            self.model_updater.update(
                prev_state="idle",
                action=topic,
                next_state="responding" if mode == "direct" else "exploring",
                reward=feedback_score
            )

        # 4. 定期巩固
        now = time.time()
        if now - self._last_consolidation > self._consolidation_interval:
            self.consolidator.consolidate(self.recorder)
            self.model_updater.decay()
            self._last_consolidation = now

        return interaction

    def get_summary(self) -> dict:
        return {
            "total_interactions": self.recorder.total_interactions(),
            "topics": self.recorder.get_topic_stats(),
            "preferences": self.preference_learner.summary(),
            "model": self.model_updater.get_model_summary(),
            "consolidations": self.consolidator._consolidation_count,
            "last_consolidation": self._last_consolidation,
        }

    def to_dict(self) -> dict:
        """序列化为可持久化的字典"""
        return {
            "preferences": {
                k: {
                    "topic": v.topic,
                    "weight": v.weight,
                    "confidence": v.confidence,
                    "last_updated": v.last_updated,
                    "examples": v.examples,
                }
                for k, v in self.preference_learner.preferences.items()
            },
            "model_summary": self.model_updater.get_model_summary(),
            "total_interactions": self.recorder.total_interactions(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OnlineLearningEngine":
        engine = cls()
        for topic, pref_data in data.get("preferences", {}).items():
            engine.preference_learner.preferences[topic] = Preference(
                **pref_data
            )
        return engine

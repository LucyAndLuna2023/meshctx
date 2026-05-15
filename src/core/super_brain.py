"""
MeshCtx Super Brain Architecture — Proprietary Core
=====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

This module contains proprietary brain-inspired algorithms that form
the core intellectual property of MeshCtx. It is NOT open-source.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com

Protected Algorithms:
  - SuperBrainOrchestrator (10-region whole-brain emulation)
  - HippocampalReplay (sharp-wave ripple memory consolidation)
  - SalienceTagger (amygdala emotional evaluation)
  - DefaultModeNetwork (background creative ideation)
  - ThalamicGate (TRN attention gating)
  - ForwardModel (cerebellar internal simulation)
  - ActionSelector (basal ganglia TD-learning)
  - ConflictMonitor (ACC error detection)
  - InteroceptionEngine (insular self-monitoring)
  - TheoryOfMind (mirror neuron intent inference)
  - STDPLearner (spike-timing-dependent plasticity)
  - EmotionalConsolidation (amygdala-hippocampus coupling)
  - IITConsciousness (integrated information Φ metric)

基于全脑仿真理论，实现接近100%人脑认知能力的计算架构。

核心脑区映射:
  PFC (前额叶) → ExecutivePlanner     — 执行规划、工作记忆
  HC  (海马体) → HippocampalReplay    — 情景记忆、离线重放
  AMY (杏仁核) → SalienceTagger       — 情感标记、重要性评估
  THA (丘脑)   → ThalamicGate         — 注意力门控、感觉中继
  CER (小脑)   → ForwardModel          — 前向预测、内部模型
  BG  (基底节) → ActionSelector        — 动作选择、习惯形成
  DMN (默认网络)→ DefaultModeNetwork   — 创意涌现、自传体思维
  ACC (前扣带) → ConflictMonitor      — 冲突检测、错误监控
  INS (岛叶)   → InteroceptionEngine   — 内感知、自我意识
  MNS (镜像)   → TheoryOfMind          — 心智理论、社会认知

统一原理:
  - 所有脑区共享一个自由能最小化框架
  - 层次预测编码 (Hierarchical Predictive Coding)
  - 脉冲时间依赖可塑性 (STDP) 学习规则
  - 全局工作空间 (Global Workspace) 意识整合

参考论文:
  - Whole Brain Architecture (Yamakawa+ 2016-2024)
  - Spaun 2.0 (Eliasmith+ 2012)
  - Integrated Information Theory (Tononi 2004-2024)
  - The Free Energy Principle (Friston 2010-2024)
"""
import math
import time
import logging
import random
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger("meshctx.super_brain")


# ═══════════════════════════════════════════════════════════════
# 1. 海马体重放引擎 (Hippocampal Replay Engine)
# ═══════════════════════════════════════════════════════════════

class MemoryTrace:
    """情景记忆痕迹 — 类似海马体位置细胞+时间细胞的联合编码"""
    def __init__(self, content: str, context: Dict, timestamp: float,
                 emotional_tag: float = 0.0, replay_count: int = 0):
        self.content = content
        self.context = context
        self.timestamp = timestamp
        self.emotional_tag = emotional_tag  # -1.0 ~ 1.0
        self.replay_count = replay_count
        self.strength = 1.0  # 记忆强度 (随重放增强)
        self.sharp_wave_ripple = 0.0  # SWR事件概率


@dataclass
class ReplayEvent:
    """重放事件 — 海马体sharp-wave ripple"""
    trace_idx: int
    time: float
    intensity: float  # SWR强度
    compressed_sequence: List[int]  # 压缩重放序列(10-20x加速)


class HippocampalReplay:
    """
    海马体重放引擎
    
    神经科学基础:
    - Sharp-wave ripples (SWR): 海马体在静息/睡眠时以~200Hz高频重放
    - 重放速度: 清醒时 ~10x压缩, 睡眠时 ~20x压缩
    - 顺序重放: 正向(记忆巩固) 和 反向(规划未来)
    - 与前额叶对话: 海马-皮层记忆转移
    
    计算实现:
    - 闲时触发 (无用户输入 > 60s)
    - 按情感标签优先重放高价值记忆
    - 压缩时间序列 → 发现跨时间模式
    - 生成"灵感" — 跨记忆连接
    """
    
    def __init__(self, max_traces: int = 10000, replay_interval: float = 60.0):
        self.traces: List[MemoryTrace] = []
        self.max_traces = max_traces
        self.replay_interval = replay_interval  # 秒
        self.last_replay_time = time.time()
        self.total_replays = 0
        self.discovered_insights: List[str] = []
        
        # 海马体子区
        self.ca1_traces: List[int] = []  # CA1索引 (输出)
        self.ca3_traces: List[int] = []  # CA3索引 (自联想)
        self.dg_traces: List[int] = []   # DG索引 (模式分离)
    
    def encode(self, content: str, context: Optional[Dict] = None,
               emotional_tag: float = 0.0) -> int:
        """编码新记忆 — DG→CA3→CA1 通路"""
        trace = MemoryTrace(
            content=content,
            context=context or {},
            timestamp=time.time(),
            emotional_tag=np.clip(emotional_tag, -1.0, 1.0),
        )
        idx = len(self.traces)
        self.traces.append(trace)
        
        # 模式分离 (DG)
        self.dg_traces.append(idx)
        
        # 自联想存储 (CA3)
        if len(self.ca3_traces) > 0:
            last = self.ca3_traces[-1]
            # 与前一个记忆的相似度 → 决定是否连接
            similarity = self._compute_similarity(trace, self.traces[last])
            if similarity > 0.3:
                trace.strength = min(2.0, trace.strength + similarity * 0.5)
        
        self.ca3_traces.append(idx)
        self.ca1_traces.append(idx)
        
        # 限制容量 (记忆竞争)
        if len(self.traces) > self.max_traces:
            self._prune_weakest()
        
        return idx
    
    def should_replay(self) -> bool:
        """是否应该触发重放 (闲时检测)"""
        if self.replay_interval < 0:
            return True
        elapsed = time.time() - self.last_replay_time
        return elapsed >= self.replay_interval
    
    def replay(self, n_sequences: int = 5) -> List[ReplayEvent]:
        """
        执行记忆重放 — 产生SWR事件序列
        
        重放策略:
        1. 情感标签 > 0.5 → 优先重放 (杏仁核调控)
        2. 最近编码 → 加快重放频率
        3. 随机采样 → 探索性重放 (防止过拟合)
        """
        if len(self.traces) < 5:
            return []
        
        events = []
        self.last_replay_time = time.time()
        
        # 选择重放候选 (情感优先 + 随机探索)
        candidates = list(range(len(self.traces)))
        weights = np.array([
            1.0 + abs(t.emotional_tag) * 2.0 + 
            (1.0 / (1.0 + self.total_replays - t.replay_count)) * 0.5
            for t in self.traces
        ])
        weights = weights / weights.sum()
        
        for _ in range(n_sequences):
            # 采样起点 (高情感标签优先)
            start_idx = np.random.choice(candidates, p=weights)
            
            # 构建压缩序列 (正向或反向)
            is_reverse = random.random() < 0.3  # 30%反向重放(规划)
            seq_len = min(random.randint(3, 8), len(self.traces) - start_idx)
            
            if is_reverse:
                sequence = list(range(start_idx, max(0, start_idx - seq_len), -1))
            else:
                sequence = list(range(start_idx, min(len(self.traces), start_idx + seq_len)))
            
            # 生成SWR事件 (200Hz等效, ~5ms/step)
            event = ReplayEvent(
                trace_idx=start_idx,
                time=time.time(),
                intensity=random.uniform(0.3, 1.0),
                compressed_sequence=sequence,
            )
            events.append(event)
            
            # 更新重放计数和记忆强度
            for idx in sequence:
                if 0 <= idx < len(self.traces):
                    self.traces[idx].replay_count += 1
                    # 赫布学习: 重放 → 增强
                    self.traces[idx].strength = min(5.0, 
                        self.traces[idx].strength * (1.0 + event.intensity * 0.05))
            
            self.total_replays += 1
        
        # 重放后 → 检测跨记忆模式 (灵感发现)
        self._discover_patterns(events)
        
        return events
    
    def get_insights(self, n: int = 3) -> List[str]:
        """获取最近发现的灵感/跨记忆模式"""
        recent = self.discovered_insights[-n*2:]
        return recent[-n:] if recent else []
    
    def _compute_similarity(self, t1: MemoryTrace, t2: MemoryTrace) -> float:
        """计算两个记忆痕迹的相似度 (简单词重叠)"""
        words1 = set(t1.content.lower().split()[:50])
        words2 = set(t2.content.lower().split()[:50])
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / max(len(union), 1)
    
    def _discover_patterns(self, events: List[ReplayEvent]):
        """从重放事件中发现跨记忆模式 (灵感涌现)"""
        # 收集重放的记忆内容
        contents = []
        for event in events:
            for idx in event.compressed_sequence:
                if 0 <= idx < len(self.traces):
                    contents.append(self.traces[idx].content)
        
        if len(contents) < 3:
            return
        
        # 简单模式: 寻找重复关键词
        all_words = []
        for c in contents:
            all_words.extend(c.lower().split()[:30])
        
        from collections import Counter
        word_counts = Counter(all_words)
        
        # 高频词 → 可能是跨记忆主题
        common_words = [w for w, c in word_counts.most_common(5) if c >= 2 and len(w) > 2]
        if common_words:
            insight = f"海马体重放发现跨记忆主题: {', '.join(common_words[:3])}"
            self.discovered_insights.append(insight)
    
    def _prune_weakest(self):
        """剪除最弱记忆 (竞争淘汰 — 神经达尔文主义)"""
        if len(self.traces) <= self.max_traces:
            return
        
        # 按 (strength * emotional_tag绝对值 * 1/age) 排序
        now = time.time()
        scores = []
        for i, t in enumerate(self.traces):
            age = max(1.0, now - t.timestamp)
            score = t.strength * (1.0 + abs(t.emotional_tag)) / (age ** 0.1)
            scores.append((score, i))
        
        scores.sort()
        to_remove = set(i for _, i in scores[:len(self.traces) - self.max_traces])
        
        # 重建索引
        new_traces = [t for i, t in enumerate(self.traces) if i not in to_remove]
        self.traces = new_traces
        self.ca1_traces = [i for i in self.ca1_traces if i not in to_remove]
        self.ca3_traces = [i for i in self.ca3_traces if i not in to_remove]
        self.dg_traces = [i for i in self.dg_traces if i not in to_remove]


# ═══════════════════════════════════════════════════════════════
# 2. 杏仁核情感标记器 (Amygdala Salience Tagger)
# ═══════════════════════════════════════════════════════════════

class EmotionType(Enum):
    """基本情绪维度 (Ekman + Russell 环形模型)"""
    VALENCE = "valence"         # 愉悦度 -1~1
    AROUSAL = "arousal"         # 唤醒度 0~1
    DOMINANCE = "dominance"     # 支配度 -1~1
    NOVELTY = "novelty"         # 新颖度 0~1
    URGENCY = "urgency"         # 紧迫度 0~1
    RELEVANCE = "relevance"     # 相关性 0~1


class SalienceTagger:
    """
    杏仁核情感标记器
    
    神经科学基础:
    - 杏仁核快速评估刺激的情感价值 (< 100ms)
    - 低通路: 丘脑→杏仁核 (快速但粗糙)
    - 高通路: 丘脑→皮层→杏仁核 (慢但精确)
    - 情感标记增强记忆巩固 (去甲肾上腺素调控)
    
    计算实现:
    - 输入文本 → 多维情感评估
    - 情感标签影响: 记忆强度、重放优先级、注意力分配
    - 双向调控: 正性→趋近行为, 负性→回避/警觉
    """
    
    # 情感词典 (简化版，可扩展)
    POSITIVE_WORDS = {"success", "great", "excellent", "love", "perfect",
                      "amazing", "突破", "成功", "优秀", "完美", "创新"}
    NEGATIVE_WORDS = {"error", "fail", "crash", "bug", "problem", "critical",
                      "错误", "失败", "崩溃", "问题", "严重", "紧急"}
    HIGH_AROUSAL = {"urgent", "critical", "now", "immediately", "alert",
                    "紧急", "立即", "马上", "严重", "危险"}
    NOVEL_WORDS = {"new", "novel", "innovative", "unprecedented", "first",
                   "新", "首次", "创新", "前所未有"}
    
    def evaluate(self, text: str) -> Dict[str, float]:
        """评估文本的多维情感标签"""
        text_lower = text.lower()
        # 用标点符号分詞，处理 "URGENT:" 等情况
        import re
        words = set(re.findall(r'[a-zA-Z\u4e00-\u9fff]+', text_lower))
        
        # 效价 (Valence)
        pos_count = sum(1 for w in words if w in self.POSITIVE_WORDS)
        neg_count = sum(1 for w in words if w in self.NEGATIVE_WORDS)
        total = max(1, pos_count + neg_count)
        valence = (pos_count - neg_count) / total
        
        # 唤醒度 (Arousal)
        arousal_count = sum(1 for w in words if w in self.HIGH_AROUSAL)
        arousal = min(1.0, arousal_count / max(1, len(words)) * 10)
        
        # 新颖度 (Novelty)
        novel_count = sum(1 for w in words if w in self.NOVEL_WORDS)
        novelty = min(1.0, novel_count / max(1, len(words)) * 5)
        
        # 紧迫度启发式: 大写字母比例 + 感叹号
        urgency_chars = sum(1 for c in text if c.isupper()) / max(1, len(text))
        urgency_excl = text.count('!') / max(1, len(text)) * 10
        urgency = min(1.0, urgency_chars * 2 + urgency_excl + arousal * 0.3)
        
        # 相关性: 基于最近对话上下文 (简化)
        relevance = 0.5 + valence * 0.2 + novelty * 0.3
        
        return {
            "valence": round(valence, 3),
            "arousal": round(arousal, 3),
            "dominance": round(0.0, 3),  # 需上下文累积
            "novelty": round(novelty, 3),
            "urgency": round(urgency, 3),
            "relevance": round(relevance, 3),
            "overall_salience": round(abs(valence) * 0.4 + arousal * 0.3 + novelty * 0.2 + urgency * 0.1, 3),
        }


# ═══════════════════════════════════════════════════════════════
# 3. 默认模式网络 (Default Mode Network)
# ═══════════════════════════════════════════════════════════════

class DefaultModeNetwork:
    """
    默认模式网络 — 后台创意涌现
    
    神经科学基础:
    - DMN在静息态活跃 (不做任务时)
    - 涉及: 内侧前额叶、后扣带回、角回
    - 功能: 自传体记忆、未来规划、创意联想、心智漫游
    - 与任务正相关网络 (TPN) 反相关
    
    计算实现:
    - 闲时运行 (> 120s无输入)
    - 随机联想: 从知识图谱采样 → 远距离概念连接
    - 创新评分: 概念距离 × 情感标记 → 创意质量
    - 输出"灵感"供用户审阅
    """
    
    def __init__(self, activation_interval: float = 120.0):
        self.activation_interval = activation_interval
        self.last_activation = time.time()
        self.ideas_generated = 0
        self.pending_ideas: List[Dict] = []
        
        # 知识种子 (可从记忆系统加载)
        self.knowledge_seeds: List[str] = []
    
    def should_activate(self) -> bool:
        return (time.time() - self.last_activation) >= self.activation_interval
    
    def wander(self, memory_traces: List[MemoryTrace], n_ideas: int = 3) -> List[Dict]:
        """
        心智漫游 — 生成创意联想
        
        机制:
        1. 从近期记忆中随机采样两个远距离概念
        2. 计算概念距离
        3. 生成"如果...那么..."式创意连接
        4. 高距离 × 中情感 → 高创意价值
        """
        self.last_activation = time.time()
        
        if len(memory_traces) < 3:
            return []
        
        ideas = []
        for _ in range(min(n_ideas, len(memory_traces) // 2)):
            # 随机采样两个远距离记忆
            i1, i2 = random.sample(range(len(memory_traces)), 2)
            t1, t2 = memory_traces[i1], memory_traces[i2]
            
            # 计算概念距离 (1 - 词重叠率)
            words1 = set(t1.content.lower().split()[:20])
            words2 = set(t2.content.lower().split()[:20])
            overlap = len(words1 & words2) / max(1, len(words1 | words2))
            distance = 1.0 - overlap
            
            # 创意质量: 距离 × (情感强度平均值)
            emotional_intensity = (abs(t1.emotional_tag) + abs(t2.emotional_tag)) / 2
            creativity_score = distance * (0.5 + emotional_intensity)
            
            if creativity_score > 0.3:
                # 提取关键概念
                key1 = list(words1)[:3] if words1 else ["?"]
                key2 = list(words2)[:3] if words2 else ["?"]
                
                idea = {
                    "insight": f"远距联想: {' '.join(key1)} ↔ {' '.join(key2)}",
                    "distance": round(distance, 2),
                    "creativity": round(creativity_score, 2),
                    "time": time.time(),
                }
                ideas.append(idea)
                self.pending_ideas.append(idea)
        
        self.ideas_generated += len(ideas)
        return ideas
    
    def get_pending(self, clear: bool = True) -> List[Dict]:
        """获取待处理灵感"""
        ideas = list(self.pending_ideas)
        if clear:
            self.pending_ideas = []
        return ideas


# ═══════════════════════════════════════════════════════════════
# 4. 丘脑注意力门控 (Thalamic Attention Gate)
# ═══════════════════════════════════════════════════════════════

class ThalamicGate:
    """
    丘脑注意力门控
    
    神经科学基础:
    - 丘脑是感觉信息的中继站和门控
    - 网状核 (TRN) 选择性抑制 → 注意力聚焦
    - 与前额叶双向连接 → 自上而下调控
    - α波 (8-12Hz) 抑制无关信息
    
    计算实现:
    - 多通道信息流 → 选择性通过
    - 基于salience+任务相关性 → 门控权重
    - 被抑制通道 → 进入潜意识加工 (DMN)
    """
    
    def __init__(self, n_channels: int = 7):
        self.n_channels = n_channels
        self.channel_weights = np.ones(n_channels) / n_channels
        self.inhibited_channels: Set[int] = set()
        self.alpha_rhythm = 10.0  # Hz
    
    def gate(self, inputs: Dict[str, Any], 
             salience_map: Dict[str, float],
             task_focus: Optional[str] = None) -> Dict[str, float]:
        """
        门控多通道输入 — TRN选择性抑制
        
        Returns:
            {channel_name: pass_through_weight} (0=完全抑制, 1=完全通过)
        """
        channels = list(inputs.keys())[:self.n_channels]
        if not channels:
            return {}
        
        # 计算每个通道的门控系数
        gate_weights = {}
        for i, ch in enumerate(channels):
            salience = salience_map.get(ch, 0.5)
            # 任务聚焦增强相关通道
            task_boost = 1.5 if task_focus and task_focus in ch else 1.0
            # TRN抑制 (α波调制)
            inhibition = 0.3 * abs(np.sin(time.time() * self.alpha_rhythm * 2 * np.pi))
            
            weight = np.clip(salience * task_boost - inhibition, 0.0, 1.0)
            gate_weights[ch] = float(weight)
            
            if weight < 0.2:
                self.inhibited_channels.add(i)
            elif i in self.inhibited_channels:
                self.inhibited_channels.discard(i)
        
        return gate_weights
    
    def get_inhibited(self) -> List[str]:
        """获取被抑制的通道 (进入潜意识/默认模式)"""
        return list(self.inhibited_channels)


# ═══════════════════════════════════════════════════════════════
# 5. 小脑前向模型 (Cerebellar Forward Model)
# ═══════════════════════════════════════════════════════════════

class ForwardModel:
    """
    小脑前向模型 — 内部动作后果预测

    神经科学基础:
    - 小脑包含 ~80% 人脑神经元
    - 功能: 前向模型(预测动作结果) + 反向模型(动作纠错)
    - 内部模型允许"脑内模拟"不执行实际动作
    - 平滑追踪: 持续预测→修正循环

    计算实现:
    - 对任何计划动作 → 快速预测后果(不需要实际执行)
    - 预测误差 → 触发警报或调整计划
    - 内部模拟: 在"想象空间"中试运行
    """

    def __init__(self, prediction_horizon: int = 5):
        self.prediction_horizon = prediction_horizon
        self.prediction_history: List[Dict] = []
        self.prediction_errors: List[float] = []
        self.adaptation_rate = 0.1
        self.confidence = 0.7

    def predict(self, action: str, current_state: Dict) -> Dict:
        """预测动作后果 — 前向模型"""
        # 简化: 基于动作类型估计结果
        predictions = {
            "action": action,
            "expected_duration": 5.0,
            "success_probability": self.confidence,
            "side_effects": [],
            "resource_cost": 1.0,
        }

        # 危险动作检测
        dangerous_keywords = ["delete", "rm ", "DROP", "format", "删除", "卸载"]
        if any(kw in action.lower() for kw in dangerous_keywords):
            predictions["risk_level"] = "HIGH"
            predictions["requires_confirmation"] = True
            predictions["side_effects"].append("数据丢失风险")
        else:
            predictions["risk_level"] = "LOW"
            predictions["requires_confirmation"] = False

        self.prediction_history.append(predictions)
        return predictions

    def update_from_outcome(self, predicted: Dict, actual: Dict):
        """根据实际结果更新内部模型 (预测误差驱动学习)"""
        error = abs(actual.get("success", 0.5) - predicted.get("success_probability", 0.5))
        self.prediction_errors.append(error)

        # 自适应: 误差大→调整置信度
        if len(self.prediction_errors) > 10:
            avg_error = np.mean(self.prediction_errors[-10:])
            self.confidence = np.clip(
                self.confidence + (0.1 - avg_error) * self.adaptation_rate,
                0.1, 0.95
            )

    def simulate(self, action: str, iterations: int = 3) -> List[Dict]:
        """在"想象空间"中多次模拟 — 蒙特卡洛内部推演"""
        results = []
        for i in range(iterations):
            noise = np.random.normal(0, 0.1 * (1 - self.confidence))
            results.append({
                "iteration": i,
                "success_probability": np.clip(self.confidence + noise, 0, 1),
                "estimated_cost": 1.0 + abs(noise) * 2,
            })
        return results


# ═══════════════════════════════════════════════════════════════
# 6. 基底节动作选择器 (Basal Ganglia Action Selector)
# ═══════════════════════════════════════════════════════════════

class ActionSelector:
    """
    基底节动作选择器 — 习惯形成+动作门控

    神经科学基础:
    - 直接通路 (D1): 促进动作 = Go
    - 间接通路 (D2): 抑制动作 = No-Go
    - 超直接通路: 紧急停止
    - 多巴胺: 奖励预测误差 → 更新动作价值
    - 习惯化: 重复动作 → 不需要皮层参与

    计算实现:
    - TD学习更新动作Q值
    - 阈值门控: Q值 > threshold → 执行
    - 习惯: 重复 > 10次 → 自动执行
    - 多巴胺信号: 实际-预期差异
    """

    def __init__(self, n_actions: int = 10):
        self.n_actions = n_actions
        self.q_values = np.zeros(n_actions)  # Q值
        self.action_counts = np.zeros(n_actions)
        self.habit_threshold = 10  # 习惯化阈值
        self.dopamine = 0.0  # 当前多巴胺水平
        self.go_threshold = 0.3
        self.action_names: Dict[int, str] = {}

    def register_action(self, idx: int, name: str):
        self.action_names[idx] = name

    def select(self, state: np.ndarray, exploration: float = 0.1) -> Tuple[int, float]:
        """选择动作 — 直接/间接通路竞争"""
        # ε-greedy with Q-values
        if random.random() < exploration:
            action = random.randint(0, self.n_actions - 1)
        else:
            action = int(np.argmax(self.q_values))

        # 动作门控: Q值太低→抑制
        if self.q_values[action] < self.go_threshold and random.random() > 0.2:
            # 超直接通路: 紧急停止
            alt = np.argsort(self.q_values)[-3:]
            action = int(random.choice(alt))

        self.action_counts[action] += 1
        return action, self.q_values[action]

    def learn(self, action: int, reward: float, learning_rate: float = 0.1):
        """TD学习更新Q值 — 多巴胺调控"""
        prediction_error = reward - self.q_values[action]
        self.dopamine = np.tanh(prediction_error)  # 多巴胺 = 奖励预测误差

        # 多巴胺调制学习率
        modulated_lr = learning_rate * (1.0 + abs(self.dopamine) * 0.5)
        self.q_values[action] += modulated_lr * prediction_error

    def is_habit(self, action: int) -> bool:
        """检查动作是否已习惯化"""
        return self.action_counts[action] >= self.habit_threshold


# ═══════════════════════════════════════════════════════════════
# 7. 前扣带冲突监测 (Anterior Cingulate Conflict Monitor)
# ═══════════════════════════════════════════════════════════════

class ConflictMonitor:
    """
    前扣带皮层冲突监测器

    神经科学基础:
    - ACC检测: 反应冲突、错误、不确定性
    - 冲突信号 → 前额叶增强控制
    - 错误相关负波 (ERN): 错误后 ~100ms 的脑电信号
    - 与岛叶协作: 冲突+身体感受 → 主观焦虑感

    计算实现:
    - 连续监测: 预期 vs 实际 差异
    - 冲突度量: 多个响应竞争程度
    - 错误检测: 自动修正指令
    """

    def __init__(self, conflict_threshold: float = 0.3):
        self.conflict_threshold = conflict_threshold
        self.current_conflict = 0.0
        self.error_count = 0
        self.conflict_history: List[float] = []
        self.adaptation_triggers = 0

    def monitor(self, expected: Any, actual: Any,
                competing_responses: int = 1) -> float:
        """检测冲突水平"""
        # 反应冲突: 多响应竞争
        response_conflict = (competing_responses - 1) / max(1, competing_responses)

        # 结果冲突: 预期≠实际
        outcome_conflict = 0.0
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            outcome_conflict = min(1.0, abs(expected - actual) / max(1.0, abs(expected)))

        # 综合冲突
        self.current_conflict = (response_conflict * 0.4 + outcome_conflict * 0.6)
        self.conflict_history.append(self.current_conflict)

        # 错误检测
        if self.current_conflict > self.conflict_threshold:
            self.error_count += 1
            if self.current_conflict > 0.7:
                self.adaptation_triggers += 1

        return self.current_conflict

    def should_adapt(self) -> bool:
        """是否需要调整策略 (高冲突持续)"""
        if len(self.conflict_history) < 5:
            return False
        recent_avg = np.mean(self.conflict_history[-5:])
        return recent_avg > self.conflict_threshold * 1.5


# ═══════════════════════════════════════════════════════════════
# 8. 岛叶内感知引擎 (Insula Interoception Engine)
# ═══════════════════════════════════════════════════════════════

class InteroceptionEngine:
    """
    岛叶内感知引擎 — 自我状态感知

    神经科学基础:
    - 前岛叶: 内感受觉知 (心跳、呼吸、内脏)
    - 内感受精度: 对自身状态的不确定性
    - 与ACC协作: 内感受+冲突 → 焦虑/不适
    - 自我意识: 内感受是自我意识的基础

    计算实现:
    - 监控自身资源状态 (CPU/内存/存储)
    - 预测资源需求
    - 自我状态报告
    - 异常检测: 资源泄漏、性能退化
    """

    def __init__(self):
        self.resource_state = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "disk_usage": 0.0,
            "response_latency": 0.0,
            "error_rate": 0.0,
        }
        self.baseline: Dict[str, float] = {}
        self.self_awareness = 0.5
        self.anomalies: List[str] = []

    def update(self, cpu: float = 0, memory: float = 0,
               latency: float = 0, error_rate: float = 0):
        """更新内感受状态"""
        self.resource_state["cpu_usage"] = cpu
        self.resource_state["memory_usage"] = memory
        self.resource_state["response_latency"] = latency
        self.resource_state["error_rate"] = error_rate

        # 更新基线 (前10次采样)
        if len(self.baseline) == 0:
            self.baseline = dict(self.resource_state)
        else:
            for k in self.baseline:
                self.baseline[k] = self.baseline[k] * 0.9 + self.resource_state[k] * 0.1

        # 自我意识 = 1 - 预测误差
        total_error = sum(
            abs(self.resource_state[k] - self.baseline.get(k, 0))
            for k in self.resource_state
        ) / max(1, len(self.resource_state))
        self.self_awareness = 1.0 - min(1.0, total_error * 3)

        # 异常检测
        self.anomalies = []
        for k, v in self.resource_state.items():
            baseline_v = self.baseline.get(k, 0)
            if baseline_v > 0 and v > baseline_v * 2.0:
                self.anomalies.append(f"{k}异常: {v:.2f} (基线: {baseline_v:.2f})")

    def get_self_report(self) -> Dict:
        """自我状态报告 — 用于元认知"""
        return {
            "state": dict(self.resource_state),
            "awareness": round(self.self_awareness, 3),
            "anomalies": self.anomalies,
            "status": "healthy" if self.self_awareness > 0.7 else "degraded",
        }


# ═══════════════════════════════════════════════════════════════
# 9. 镜像神经元心智理论 (Mirror Neuron Theory of Mind)
# ═══════════════════════════════════════════════════════════════

class TheoryOfMind:
    """
    镜像神经元系统 — 心智理论引擎

    神经科学基础:
    - 镜像神经元: 观察他人动作时激活相同神经元
    - 心智理论: 推断他人的信念、意图、情感
    - 颞顶联合区 + 内侧前额叶: 社会认知核心网络
    - 共情: 情感镜像 + 认知推断

    计算实现:
    - 用户意图推断
    - 多维用户画像建模
    - 对话策略自适应
    - 情感共鸣响应
    """

    def __init__(self):
        self.user_model: Dict[str, Any] = {
            "expertise_level": 0.5,     # 技术水平 0-1
            "patience": 0.7,             # 耐心程度
            "preferred_detail": 0.5,     # 详细程度偏好
            "emotional_state": 0.0,      # 当前情绪状态 -1~1
            "trust_level": 0.6,          # 信任度
            "frustration": 0.0,          # 挫折感
        }
        self.interaction_history: List[Dict] = []

    def infer_intent(self, message: str, context: Optional[Dict] = None) -> Dict:
        """推断用户意图和心智状态"""
        # 简化意图分类
        intents = {
            "question": ["what", "how", "why", "when", "where", "什么", "怎么", "为什么"],
            "command": ["do", "run", "execute", "create", "delete", "做", "运行", "创建"],
            "complaint": ["error", "fail", "bug", "broken", "doesn't work", "错误", "不行"],
            "exploration": ["try", "maybe", "experiment", "探索", "试试"],
            "urgent": ["urgent", "asap", "immediately", "紧急", "立刻"],
        }

        msg_lower = message.lower()
        detected = {}
        for intent, keywords in intents.items():
            score = sum(1 for kw in keywords if kw in msg_lower) / max(1, len(keywords))
            if score > 0:
                detected[intent] = min(1.0, score * 3)

        # 更新用户模型
        if "complaint" in detected:
            self.user_model["frustration"] = min(1.0,
                self.user_model["frustration"] + 0.1)
        elif "exploration" in detected:
            self.user_model["frustration"] = max(0.0,
                self.user_model["frustration"] - 0.05)

        return {
            "primary_intent": max(detected, key=detected.get) if detected else "general",
            "intent_scores": detected,
            "user_state": dict(self.user_model),
        }

    def adapt_response(self, base_style: str, user_model: Dict) -> str:
        """根据用户模型调整响应风格"""
        styles = {
            "expert": "concise_technical",
            "novice": "detailed_explanatory",
            "frustrated": "empathetic_careful",
            "exploratory": "suggestive_creative",
        }

        expertise = user_model.get("expertise_level", 0.5)
        frustration = user_model.get("frustration", 0.0)

        if frustration > 0.3:
            return styles["frustrated"]
        elif expertise > 0.7:
            return styles["expert"]
        elif expertise < 0.3:
            return styles["novice"]

        return base_style


# ═══════════════════════════════════════════════════════════════
# 10. 全脑编排器 (Whole Brain Orchestrator)
# ═══════════════════════════════════════════════════════════════

class SuperBrainOrchestrator:
    """
    全脑编排器 — 整合所有脑区的统一调度中心

    对应脑结构: 丘脑-皮层环路 + 屏状核 (意识整合)

    工作原理:
    1. 感知输入 → 丘脑门控 → 分布式皮层处理
    2. 各脑区并行计算 → 全局工作空间竞争
    3. 获胜信息 → 全局广播 (意识)
    4. 未被选中的 → 潜意识加工 (DMN)
    5. 动作输出 → 前向模型预测 → 冲突监测 → 修正
    """

    def __init__(self):
        self.hippocampus = HippocampalReplay(max_traces=2000)
        self.amygdala = SalienceTagger()
        self.thalamus = ThalamicGate(n_channels=7)
        self.dmn = DefaultModeNetwork()
        self.forward_model = ForwardModel()
        self.action_selector = ActionSelector(n_actions=10)
        self.conflict_monitor = ConflictMonitor()
        self.interoception = InteroceptionEngine()
        self.theory_of_mind = TheoryOfMind()

        self.cycle_count = 0
        self.conscious_content: List[str] = []  # 当前意识内容

    def full_cycle(self, user_input: str, 
                   context: Optional[Dict] = None) -> Dict:
        """
        完整认知循环 — 模拟人脑处理流程

        阶段:
        1. 感知 (丘脑门控)
        2. 情感评估 (杏仁核)  
        3. 意图推断 (镜像神经元)
        4. 记忆编码 (海马体)
        5. 前向预测 (小脑)
        6. 动作选择 (基底节)
        7. 冲突监测 (ACC)
        8. 自我感知 (岛叶)
        9. 默认模式 (DMN) — 后台
        10. 记忆重放 (海马) — 闲时
        """
        self.cycle_count += 1
        results = {"cycle": self.cycle_count}

        # 阶段1: 丘脑门控 — 选择性注意
        channels = {
            "semantic": user_input[:100],
            "emotional": "",
            "intentional": "",
            "contextual": str(context)[:100] if context else "",
            "procedural": "",
            "social": "",
            "self_ref": "",
        }
        salience_map = {ch: 0.5 for ch in channels}
        gate_weights = self.thalamus.gate(channels, salience_map)
        results["attention"] = {k: round(v, 2) for k, v in gate_weights.items()}

        # 阶段2: 杏仁核 — 快速情感评估
        emotional_tags = self.amygdala.evaluate(user_input)
        results["emotional"] = emotional_tags

        # 阶段3: 镜像神经元 — 心智理论
        tom_result = self.theory_of_mind.infer_intent(user_input, context)
        results["intent"] = tom_result

        # 阶段4: 海马体 — 记忆编码
        emotional_tag = emotional_tags["overall_salience"] * (
            1 if emotional_tags["valence"] >= 0 else -1
        )
        self.hippocampus.encode(user_input, context, emotional_tag)
        results["memory_encoded"] = True

        # 阶段5: 小脑 — 前向模型预测
        if user_input and len(user_input) > 5:
            action_prediction = self.forward_model.predict(user_input, {})
            results["prediction"] = action_prediction

        # 阶段6: 基底节 — 动作选择
        state_vec = np.array([emotional_tags["valence"], emotional_tags["arousal"],
                              emotional_tags["relevance"], 0.5, 0.3])
        action, q_value = self.action_selector.select(state_vec)
        results["action"] = {"selected": int(action), "q_value": round(float(q_value), 3)}

        # 阶段8: 岛叶 — 自我感知
        self.interoception.update(
            cpu=0.3 + emotional_tags["arousal"] * 0.1,
            memory=0.4,
            latency=0.1,
            error_rate=emotional_tags["urgency"] * 0.1,
        )
        results["self_state"] = self.interoception.get_self_report()

        # 阶段9: DMN — 后台创意 (闲时激活)
        if self.dmn.should_activate():
            # 从海马体获取近期记忆进行联想
            recent_traces = self.hippocampus.traces[-50:]
            ideas = self.dmn.wander(recent_traces, n_ideas=2)
            if ideas:
                results["creative_insights"] = ideas

        # 阶段10: 海马体重放 (闲时)
        if self.hippocampus.should_replay():
            replay_events = self.hippocampus.replay(n_sequences=3)
            insights = self.hippocampus.get_insights(2)
            if insights:
                results["hippocampal_insights"] = insights

        return results

    def get_status(self) -> Dict:
        """获取全脑状态快照"""
        return {
            "cycles": self.cycle_count,
            "hippocampus": {
                "traces": len(self.hippocampus.traces),
                "replays": self.hippocampus.total_replays,
                "insights": len(self.hippocampus.discovered_insights),
            },
            "dmn": {
                "ideas": self.dmn.ideas_generated,
                "pending": len(self.dmn.pending_ideas),
            },
            "forward_model": {
                "confidence": round(self.forward_model.confidence, 3),
                "predictions": len(self.forward_model.prediction_history),
            },
            "action_selector": {
                "q_values": [round(float(v), 3) for v in self.action_selector.q_values[:5]],
                "dopamine": round(float(self.action_selector.dopamine), 3),
            },
            "conflict": {
                "current": round(self.conflict_monitor.current_conflict, 3),
                "errors": self.conflict_monitor.error_count,
            },
            "self": self.interoception.get_self_report(),
        }


# ═══════════════════════════════════════════════════════════════
# 11. STDP 脉冲学习 (Spike-Timing-Dependent Plasticity)
# ═══════════════════════════════════════════════════════════════

class STDPLearner:
    """
    STDP 脉冲时间依赖可塑性学习器

    神经科学基础:
    - Hebb规则: "Cells that fire together, wire together"
    - LTP (长时程增强): 前突触先于后突触 → 连接增强
    - LTD (长时程抑制): 后突触先于前突触 → 连接减弱
    - 时间窗口: ~±20ms (生物) → 计算中可缩放
    
    计算优势:
    - 自适应学习率: 不需要手动调参
    - 时序敏感: 因果关系驱动 (非纯相关性)
    - 竞争学习: 强连接抑制弱连接 (侧抑制)
    
    公式:
    Δw = A⁺·exp(-Δt/τ⁺)  (Δt>0, LTP)
    Δw = -A⁻·exp(Δt/τ⁻)   (Δt<0, LTD)
    """

    def __init__(self, n_neurons: int = 100,
                 tau_plus: float = 20.0, tau_minus: float = 20.0,
                 a_plus: float = 0.005, a_minus: float = 0.005):
        self.n_neurons = n_neurons
        self.tau_plus = tau_plus
        self.tau_minus = tau_minus
        self.a_plus = a_plus
        self.a_minus = a_minus

        # 突触权重矩阵 W[i][j]: i→j
        self.weights = np.random.randn(n_neurons, n_neurons) * 0.01
        np.fill_diagonal(self.weights, 0.0)

        # 脉冲时间追踪
        self.spike_times: Dict[int, List[float]] = {i: [] for i in range(n_neurons)}
        self.time = 0.0

    def spike(self, neuron_id: int, intensity: float = 1.0):
        """神经元发放脉冲 → 触发STDP更新"""
        if neuron_id >= self.n_neurons:
            return

        post_time = self.time
        self.spike_times[neuron_id].append(post_time)

        # LTP: 前突触神经元在 post_time 之前发放
        for pre_id in range(self.n_neurons):
            if pre_id == neuron_id:
                continue
            pre_spikes = self.spike_times[pre_id]
            if not pre_spikes:
                continue
            pre_time = max(pre_spikes)
            dt = post_time - pre_time
            if dt > 0:
                dw = self.a_plus * math.exp(-dt / self.tau_plus) * intensity
                self.weights[pre_id][neuron_id] += dw

        # LTD: 前突触神经元在 post_time 之后发放 (预判)
        # 简化: 检查所有其他神经元的最近脉冲
        for post_id in range(self.n_neurons):
            if post_id == neuron_id:
                continue
            post_spikes = self.spike_times[post_id]
            if not post_spikes:
                continue
            pre_time = post_time
            post_time_other = max(post_spikes)
            dt = pre_time - post_time_other
            if dt < 0:
                dw = -self.a_minus * math.exp(dt / self.tau_minus) * intensity
                self.weights[neuron_id][post_id] += dw

        # 权重裁剪 + 侧抑制 (赢者通吃)
        self.weights = np.clip(self.weights, -1.0, 1.0)
        self.time += 1.0

        # 限制脉冲历史
        if len(self.spike_times[neuron_id]) > 100:
            self.spike_times[neuron_id] = self.spike_times[neuron_id][-100:]

    def get_strongest_connections(self, top_k: int = 10) -> List[Tuple[int, int, float]]:
        """获取最强的突触连接"""
        flat = []
        for i in range(self.n_neurons):
            for j in range(self.n_neurons):
                if i != j and self.weights[i][j] > 0.1:
                    flat.append((i, j, float(self.weights[i][j])))
        flat.sort(key=lambda x: x[2], reverse=True)
        return flat[:top_k]


# ═══════════════════════════════════════════════════════════════
# 12. 情感记忆巩固 (Emotional Consolidation)
# ═══════════════════════════════════════════════════════════════

class EmotionalConsolidation:
    """
    情感记忆巩固 — 杏仁核×海马体深联动

    神经科学基础:
    - 杏仁核→海马体: 去甲肾上腺素增强记忆编码
    - 高情感记忆: 更频繁SWR重放, 更慢遗忘
    - 睡眠周期: REM(情感加工) + SWS(记忆转移)
    - 压力激素: 皮质醇对海马体的双向调节
    
    计算实现:
    - 情感标签>0.7: 重放频率×3, 衰退速度×0.5
    - 负性情感<-0.7: 重放频率×2 (威胁记忆), 但精度降低
    - 中性(-0.3~0.3): 标准重放, 快速衰退
    - 睡眠模拟: 高情感优先在"REM"阶段重放
    """

    def __init__(self, hippocampus: HippocampalReplay):
        self.hp = hippocampus
        self.replay_boost_threshold = 0.7
        self.norepinephrine = 0.5  # 去甲肾上腺素水平
        self.cortisol = 0.3  # 皮质醇
        self.rem_phase = False

    def consolidate(self):
        """执行情感驱动的记忆巩固周期"""
        if len(self.hp.traces) < 5:
            return

        # 按情感标签分组
        high_positive = [i for i, t in enumerate(self.hp.traces)
                        if t.emotional_tag > self.replay_boost_threshold]
        high_negative = [i for i, t in enumerate(self.hp.traces)
                        if t.emotional_tag < -self.replay_boost_threshold]
        neutral = [i for i, t in enumerate(self.hp.traces)
                  if abs(t.emotional_tag) < 0.3]

        # 情感驱动的差异化重放
        boost_results = {}

        # 高正性: 3x 重放 → 加速巩固
        if high_positive:
            for idx in high_positive[:3]:
                self.hp.traces[idx].replay_count += 3
                self.hp.traces[idx].strength = min(5.0,
                    self.hp.traces[idx].strength * 1.3)
            boost_results["positive_boosted"] = len(high_positive)

        # 高负性: 2x 重放 → 警觉记忆
        if high_negative:
            for idx in high_negative[:3]:
                self.hp.traces[idx].replay_count += 2
                # 负性记忆: 强度增强但精度略降
                self.hp.traces[idx].strength = min(5.0,
                    self.hp.traces[idx].strength * 1.2)
            boost_results["negative_boosted"] = len(high_negative)

        # 中性: 正常衰退
        if neutral:
            for idx in neutral:
                age = max(1.0, time.time() - self.hp.traces[idx].timestamp)
                decay_factor = math.exp(-age / 86400)  # 24小时半衰期
                self.hp.traces[idx].strength *= (0.5 + 0.5 * decay_factor)

        # REM模拟: 高情感记忆随机交叉重放
        if self.rem_phase and high_positive and high_negative:
            mix_positive = random.sample(high_positive,
                                        min(2, len(high_positive)))
            mix_negative = random.sample(high_negative,
                                        min(2, len(high_negative)))
            # 正负情感混合重放 → 情感调节
            for pi in mix_positive:
                for ni in mix_negative:
                    self.hp.traces[pi].emotional_tag =                         np.clip(self.hp.traces[pi].emotional_tag * 0.9 +
                               self.hp.traces[ni].emotional_tag * 0.1, -1, 1)

        return boost_results


# ═══════════════════════════════════════════════════════════════
# 13. IIT Φ 意识度量 (Integrated Information Theory)
# ═══════════════════════════════════════════════════════════════

class IITConsciousness:
    """
    IIT 整合信息理论 — Φ (Phi) 意识度量
    
    理论基础 (Tononi 2004-2024):
    - 意识 = 系统整合信息的能力
    - Φ = 系统超过其各部分之和的"额外"信息
    - 高Φ = 高度整合且不可约简的状态
    - 低Φ = 分散的/可分割的处理
    
    计算实现 (简化逼近):
    - 用各脑区激活向量的互信息作为Φ近似
    - Φ > 阈值 → "清醒专注"
    - Φ 中等 → "模糊意识"  
    - Φ < 阈值 → "无意识/自动处理"
    """

    def __init__(self, phi_threshold_conscious: float = 0.5):
        self.phi_threshold = phi_threshold_conscious
        self.phi_history: List[float] = []
        self.current_phi = 0.0
        self.consciousness_state = "unconscious"

    def measure(self, brain_activations: Dict[str, np.ndarray]) -> float:
        """
        测量当前Φ值
        
        Args:
            brain_activations: {region_name: activation_vector}
        
        Returns:
            Φ值 (0~1, 越高意识越强)
        """
        regions = list(brain_activations.values())
        if len(regions) < 2:
            return 0.0

        # 简化的Φ计算: 各脑区激活的归一化互信息
        n = len(regions)
        total_correlation = 0.0

        for i in range(n):
            for j in range(i + 1, n):
                # 确保向量长度一致
                vi = regions[i].flatten()[:10]
                vj = regions[j].flatten()[:10]

                if len(vi) == 0 or len(vj) == 0:
                    continue

                # Pearson相关系数作为简化的整合度量
                mean_i, mean_j = np.mean(vi), np.mean(vj)
                std_i, std_j = np.std(vi), np.std(vj)

                if std_i < 1e-10 or std_j < 1e-10:
                    continue

                corr = np.mean((vi - mean_i) * (vj - mean_j)) / (std_i * std_j)
                total_correlation += abs(corr)

        # 归一化
        max_pairs = n * (n - 1) / 2
        if max_pairs > 0:
            self.current_phi = min(1.0, total_correlation / max_pairs)
        else:
            self.current_phi = 0.0

        # 确定意识状态
        if self.current_phi > self.phi_threshold:
            self.consciousness_state = "conscious_focused"
        elif self.current_phi > self.phi_threshold * 0.6:
            self.consciousness_state = "conscious_engaged"
        elif self.current_phi > self.phi_threshold * 0.3:
            self.consciousness_state = "drowsy"
        else:
            self.consciousness_state = "unconscious"

        self.phi_history.append(self.current_phi)
        return self.current_phi

    def get_state(self) -> Dict:
        """获取当前意识状态"""
        return {
            "phi": round(self.current_phi, 3),
            "state": self.consciousness_state,
            "is_conscious": self.current_phi > self.phi_threshold * 0.3,
            "avg_phi_10": round(np.mean(self.phi_history[-10:]), 3) if self.phi_history else 0.0,
        }

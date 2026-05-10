"""
meshctx v1.1 — 全局工作空间 (Global Workspace Architecture)

跨学科融合:
- 认知科学: Baars的全局工作空间理论 → 意识作为信息广播机制
- 神经科学: Dehaene的全局神经元工作空间 → 前额叶-顶叶网络的实现
- 人工智能: 多Agent竞争 → 胜者获得"意识"访问权并全局广播
- 心理学: 注意的选择性 → 瓶颈模型 (bottleneck)
- 物理学: 相变 → 竞争激活超过阈值时发生意识"点火"

核心机制:
  多个专业化处理器 (专家) 并行运算
  → 竞争全局工作空间的有限容量 (~7 chunks)
  → 胜者的输出被全局广播给所有处理器
  → 未胜出的信息留在无意识层面影响后续竞争
  → 注意力作为精密加权决定谁进入工作空间

意识"点火" (Ignition):
  当某个处理器的激活超过阈值时，发生全脑同步
  → 表现为P3b脑电波 (~300ms潜伏期)
  → 对应算法中的激活传播和胜者选择
"""

import asyncio
import logging
import math
import time
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .free_energy import BeliefState, BeliefType, PrecisionWeighting

logger = logging.getLogger("meshctx.workspace")


# ═══════════════════════════════════════════════════════════════════════
# 专业化处理器
# ═══════════════════════════════════════════════════════════════════════

class ProcessorType(Enum):
    """处理器类型 — 模拟大脑的功能分区"""
    ANALYST = "analyst"          # 分析师: 深度推理 (前额叶)
    CREATOR = "creator"          # 创造者: 发散思维 (默认模式网络)
    CRITIC = "critic"            # 批评家: 评估质疑 (前扣带回)
    EXECUTOR = "executor"        # 执行者: 行动执行 (运动皮层)
    OBSERVER = "observer"        # 观察者: 情境感知 (感觉皮层)
    MEMORY = "memory"            # 记忆者: 检索关联 (海马体)
    EMOTION = "emotion"          # 情绪: 价值评估 (杏仁核)
    PREDICTOR = "predictor"      # 预测者: 结果预期 (小脑)


@dataclass
class Processor:
    """
    专业化处理器 — 大脑功能分区的计算模拟。
    
    每个处理器:
    1. 接收全局广播信息
    2. 在自己的专业领域处理
    3. 产生输出竞争全局工作空间
    
    神经动力学:
    - 基线激活 → 静息状态
    - 输入驱动 → 响应外部刺激
    - 水平连接 → 同区域相互兴奋
    - 侧抑制 → 不同区域相互竞争
    """
    name: str
    processor_type: ProcessorType
    activation: float = 0.0              # 当前激活水平 (0-1)
    baseline: float = 0.05               # 基线激活 (静息)
    excitability: float = 1.0            # 兴奋性 (增益)
    adaptation: float = 0.0              # 适应水平 (疲劳)
    output: Any = None                   # 处理器输出
    confidence: float = 0.5              # 输出置信度
    
    # 统计
    times_selected: int = 0
    total_activation: float = 0.0
    
    def stimulate(self, input_signal: float, relevance: float = 1.0):
        """
        输入刺激 + 内部动力学。
        
        动力学方程 (Wilson-Cowan简化):
          τ * da/dt = -a + S(w*a + I - θ)
        
        其中 S = sigmoid, w = 自兴奋权重, I = 输入, θ = 阈值
        """
        # 简化的激活更新
        self_excitation = 0.1 * self.activation  # 自兴奋
        noise = np.random.normal(0, 0.02)         # 神经噪声
        
        delta = (-self.activation 
                 + self_excitation
                 + self.excitability * input_signal * relevance
                 + noise
                 - self.adaptation)
        
        self.activation = max(0.0, min(1.0, self.activation + 0.1 * delta))
        self.total_activation += self.activation
        
        # 疲劳累积
        self.adaptation = 0.9 * self.adaptation + 0.1 * self.activation

    def inhibit(self, amount: float = 0.1):
        """侧抑制"""
        self.activation = max(0.0, self.activation - amount)

    def reset_adaptation(self):
        """选择后重置部分疲劳"""
        self.adaptation *= 0.5


# ═══════════════════════════════════════════════════════════════════════
# 全局工作空间
# ═══════════════════════════════════════════════════════════════════════

class GlobalWorkspace:
    """
    全局工作空间 — 意识的计算模型。
    
    工作空间容量: ~7 chunks (Miller's Law)
    选择机制: 竞争 + 精密加权
    
    工作流程:
    1. 接收外部输入 (任务/问题)
    2. 广播给所有处理器
    3. 处理器并行运算
    4. 竞争进入工作空间 (基于激活水平+精密权重)
    5. 胜者(1-2个)的输出被选中 → "意识到"
    6. 胜者的输出广播给所有处理器 → 下一轮
    
    意识"点火":
    当某个处理器激活超过 IGNITION_THRESHOLD → 
    发生全局同步 → 对应"aha moment"
    """

    IGNITION_THRESHOLD = 0.75      # 点火阈值
    WORKSPACE_CAPACITY = 3          # 同时可意识到的项目数
    ATTENTION_DECAY = 0.95          # 注意衰减率
    COMPETITION_STRENGTH = 0.15     # 竞争强度 (侧抑制)

    def __init__(self):
        self.processors: Dict[str, Processor] = {
            "analyst": Processor("analyst", ProcessorType.ANALYST, 
                                  baseline=0.1, excitability=1.2),
            "creator": Processor("creator", ProcessorType.CREATOR,
                                  baseline=0.08, excitability=1.0),
            "critic": Processor("critic", ProcessorType.CRITIC,
                                 baseline=0.06, excitability=0.8),
            "executor": Processor("executor", ProcessorType.EXECUTOR,
                                   baseline=0.05, excitability=1.1),
            "observer": Processor("observer", ProcessorType.OBSERVER,
                                   baseline=0.12, excitability=1.3),
            "memory": Processor("memory", ProcessorType.MEMORY,
                                 baseline=0.07, excitability=0.9),
            "predictor": Processor("predictor", ProcessorType.PREDICTOR,
                                    baseline=0.06, excitability=0.7),
        }
        
        # 精密权重 (注意力分配)
        self.precision = PrecisionWeighting()
        
        # 当前工作空间内容
        self.workspace: List[Tuple[str, Any, float]] = []  # (processor, output, confidence)
        
        # 全局广播历史
        self.broadcast_history: List[Dict] = []
        
        # 点火事件
        self.ignition_events: List[Dict] = []
        
        # 信念: 哪个处理器最可靠
        self.processor_belief = BeliefState(
            name="processor_reliability",
            belief_type=BeliefType.DIRICHLET,
            n_categories=len(self.processors),
        )

    def broadcast(self, stimulus: Dict[str, float]) -> Dict[str, Any]:
        """
        全局广播: 向所有处理器发送刺激。
        
        stimulus: {processor_name: input_signal}
        未指定的处理器获得基线输入。
        """
        # 广播给所有处理器
        for name, proc in self.processors.items():
            signal = stimulus.get(name, 0.0)
            relevance = stimulus.get(f"{name}_relevance", 0.5)
            proc.stimulate(signal, relevance)
        
        return {"broadcast_to": list(self.processors.keys())}

    def compete(self) -> List[Tuple[str, Processor, float]]:
        """
        竞争: 处理器竞争进入全局工作空间。
        
        竞争规则:
        1. 激活水平最高的进入
        2. 疲劳的处理器被抑制 (避免重复)
        3. 精密权重调整: 历史表现好的获得增益
        
        神经基础: 侧抑制网络
        活跃的神经元抑制邻近神经元
        → 形成胜者通吃 (winner-take-all)
        """
        # 计算竞争分数
        scores = {}
        for name, proc in self.processors.items():
            belief_idx = list(self.processors.keys()).index(name)
            reliability = float(self.processor_belief.expected_probability[belief_idx])
            scores[name] = proc.activation * (0.5 + 0.5 * reliability) - proc.adaptation * 0.3

        # 胜者选择 + 侧抑制
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winners = []
        
        for i, (name, score) in enumerate(ranked[:self.WORKSPACE_CAPACITY]):
            proc = self.processors[name]
            if score > 0.1:  # 最低阈值
                winners.append((name, proc, score))
                proc.times_selected += 1
                proc.reset_adaptation()
        
        # 侧抑制: 未入选的被抑制
        winner_names = {w[0] for w in winners}
        for name, proc in self.processors.items():
            if name not in winner_names:
                proc.inhibit(self.COMPETITION_STRENGTH)
        
        return winners

    def ignition_check(self, processor_name: str, activation: float) -> bool:
        """
        检查是否发生意识"点火"。
        
        点火条件: 激活 > 阈值 且 不是噪音
        点火后果: 全局广播 + 信念更新
        
        神经科学:
        点火 = P3b事件相关电位 ≈ 刺激后300ms的全局同步
        对应"意识到的瞬间"
        """
        if activation > self.IGNITION_THRESHOLD:
            self.ignition_events.append({
                "processor": processor_name,
                "activation": activation,
                "timestamp": time.time(),
            })
            if len(self.ignition_events) > 100:
                self.ignition_events = self.ignition_events[-100:]
            return True
        return False

    def cycle(self, stimulus: Dict[str, float], preferred_processor: Optional[str] = None) -> Dict[str, Any]:
        """
        一个完整的意识循环。
        
        1. 广播刺激
        2. 处理器竞争
        3. 胜者进入工作空间
        4. 点火检测
        5. 更新信念
        
        约300ms → 模拟大脑的theta-gamma耦合周期
        """
        # 1. 广播
        if preferred_processor:
            stimulus = {**stimulus, preferred_processor: stimulus.get(preferred_processor, 0.5) + 0.3}
        self.broadcast(stimulus)
        
        # 2. 竞争
        winners = self.compete()
        
        # 3. 更新工作空间
        self.workspace = [(name, proc.output, proc.confidence) for name, proc, _ in winners]
        
        # 4. 点火检测
        ignited = []
        for name, proc, score in winners:
            if self.ignition_check(name, proc.activation):
                ignited.append(name)
        
        # 5. 注意衰减
        for proc in self.processors.values():
            proc.activation *= self.ATTENTION_DECAY
        
        # 6. 记录广播
        self.broadcast_history.append({
            "winners": [w[0] for w in winners],
            "ignited": ignited,
            "timestamp": time.time(),
        })
        if len(self.broadcast_history) > 200:
            self.broadcast_history = self.broadcast_history[-200:]
        
        return {
            "workspace": [{"processor": n, "confidence": c} for n, _, c in winners],
            "ignition": ignited,
            "activation_levels": {n: round(p.activation, 3) for n, p in self.processors.items()},
        }

    def learn_from_feedback(self, processor_name: str, was_helpful: bool):
        """从反馈中学习哪个处理器值得信赖"""
        if processor_name in self.processors:
            idx = list(self.processors.keys()).index(processor_name)
            self.processor_belief.observe(idx, weight=1.0 if was_helpful else 0.3)

    def get_dominant_processor(self) -> Optional[str]:
        """当前主导的处理器 (最高激活)"""
        if not self.processors:
            return None
        return max(self.processors, key=lambda n: self.processors[n].activation)

    def get_cognitive_state(self) -> Dict[str, Any]:
        """
        获取当前认知状态快照。
        
        类似于大脑的"全局状态": 清醒/专注/分心/疲劳动
        """
        activations = {n: p.activation for n, p in self.processors.items()}
        avg_activation = np.mean(list(activations.values()))
        max_activation = max(activations.values())
        
        if max_activation > 0.8:
            mode = "focused"          # 高度专注
        elif avg_activation > 0.4:
            mode = "engaged"          # 活跃参与
        elif avg_activation > 0.15:
            mode = "default"          # 默认模式
        else:
            mode = "resting"          # 静息
        
        return {
            "mode": mode,
            "dominant": self.get_dominant_processor(),
            "avg_activation": round(float(avg_activation), 3),
            "ignition_count": len(self.ignition_events),
            "workspace_items": len(self.workspace),
        }


# ═══════════════════════════════════════════════════════════════════════
# 注意瓶颈 — Miller's Law 实现
# ═══════════════════════════════════════════════════════════════════════

class AttentionBottleneck:
    """
    注意瓶颈 — 人类工作记忆 ≈ 7±2 chunks。
    
    为什么需要瓶颈:
    1. 计算资源有限 → 需要选择性注意
    2. 并行处理 → 串行意识 (一次只能意识到少数事物)
    3. 抑制不相关信息 → 防止信息过载
    
    神经基础:
    前额叶-顶叶注意网络 → 选择性增强 + 选择性抑制
    """

    def __init__(self, capacity: int = 7):
        self.capacity = capacity  # Miller: 7±2
        self.current_chunks: List[Dict] = []
        self.salience_threshold: float = 0.3

    def filter(self, candidates: List[Tuple[str, float, Any]]) -> List[Dict]:
        """
        过滤候选进入注意焦点。
        
        只允许最高显著性的 capacity 个项目进入意识。
        """
        # 按显著性排序
        sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
        
        # 只取前 capacity 个
        self.current_chunks = [
            {"name": c[0], "salience": c[1], "content": c[2]}
            for c in sorted_candidates[:self.capacity]
            if c[1] > self.salience_threshold
        ]
        
        return self.current_chunks

    def is_overloaded(self) -> bool:
        """检查是否认知过载"""
        return len(self.current_chunks) >= self.capacity

    def drop_least_salient(self):
        """卸载最不显著的项目"""
        if self.current_chunks:
            self.current_chunks.pop()

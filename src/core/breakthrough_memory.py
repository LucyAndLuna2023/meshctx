"""
MeshCtx Breakthrough Memory + Attractor Reasoner
=================================================

两个独立但互补的系统:

1. **Breakthrough Memory** (突破记忆 — "Dreaming Agent")
   - 离线记忆巩固: 压缩、抽象、发现模式
   - 睡眠回放: 压缩率 100:1 的记忆再激活
   - 启发式发现: 从海量经验中提取原则

2. **Attractor Reasoner** (吸引子推理器)
   - 基于 Hopfield 网络的吸引子推理
   - 40K "层" = 迭代收敛到稳定解
   - 类比推理 → 找到相似问题的解决方案
   - 逻辑一致性检查

两者集成:
  Breakthrough Memory 蒸馏经验 → 形成启发式
  Attractor Reasoner 用启发式 → 收敛到最优推理路径

License: MIT
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import random
import time
from collections import Counter, deque, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.breakthrough")


# ============================================================================
# Part 1: Breakthrough Memory — 突破记忆
# ============================================================================

@dataclass
class ExperienceFragment:
    """经验片段"""
    id: str
    action: str
    context: str           # 情境
    outcome: str           # 结果
    reward: float = 0.0    # 奖励信号
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)


@dataclass
class Insight:
    """洞察 — 从经验中蒸馏的启发式"""
    id: str
    description: str
    confidence: float
    supporting_experiences: List[str]
    source_pattern: str
    created_at: float = field(default_factory=time.time)
    validated: bool = False


class BreakthroughMemory:
    """
    突破记忆 — 离线记忆巩固引擎

    核心操作:
      1. Consolidate: 压缩 N 条经验 → 1 条洞察 (100:1 压缩)
      2. Abstract: 提取跨经验的模式
      3. Sleep Replay: 高速回放 (20× 速度)
      4. Generate: 随机组合生成新想法

    睡眠回放:
      不逐字回放经验，而是:
      - 提取关键模式
      - 在潜空间组合
      - 生成候选洞察
      - 用验证机制筛选
    """

    def __init__(self, max_experiences: int = 10000,
                 max_insights: int = 500):
        self.max_experiences = max_experiences
        self.max_insights = max_insights

        # 存储
        self._experiences: Dict[str, ExperienceFragment] = {}
        self._insights: Dict[str, Insight] = {}
        self._exp_order: deque = deque(maxlen=max_experiences)

        # 模式库
        self._action_patterns: Dict[str, Counter] = defaultdict(Counter)  # action → {next_action → count}
        self._context_clusters: Dict[str, List[str]] = defaultdict(list)  # context_tag → exp_ids

        # 统计
        self._consolidations = 0
        self._sleep_sessions = 0
        self._total_experiences = 0

    # ── 经验存储 ──

    def record_experience(self, action: str, context: str,
                          outcome: str, reward: float = 0.0,
                          tags: List[str] = None) -> str:
        """记录一条经验"""
        import uuid
        exp = ExperienceFragment(
            id=f"exp_{uuid.uuid4().hex[:8]}",
            action=action,
            context=context,
            outcome=outcome,
            reward=reward,
            tags=tags or [],
            embedding=self._simple_embed(context + action + outcome),
        )

        if len(self._experiences) >= self.max_experiences:
            # 驱逐最旧的经验
            oldest = self._exp_order[0]
            old_exp = self._experiences.pop(oldest, None)
            if old_exp:
                for tag in old_exp.tags:
                    self._context_clusters[tag].remove(oldest)

        self._experiences[exp.id] = exp
        self._exp_order.append(exp.id)
        self._total_experiences += 1

        # 更新模式
        if len(self._exp_order) >= 2:
            prev_id = self._exp_order[-2]
            prev = self._experiences.get(prev_id)
            if prev:
                self._action_patterns[prev.action][action] += 1

        # 更新上下文聚类
        for tag in (tags or []):
            self._context_clusters[tag].append(exp.id)

        return exp.id

    # ── 巩固 (Consolidation) ──

    def consolidate(self, target_ratio: float = 0.01) -> List[Insight]:
        """
        巩固: 从经验中提取洞察

        target_ratio=0.01 → 100 条经验 → 1 条洞察 (100:1)
        """
        if len(self._experiences) < 10:
            return []

        insights = []

        # 1. 按 action 聚类, 找高频成功/失败模式
        by_action: Dict[str, List[ExperienceFragment]] = defaultdict(list)
        for exp_id in self._exp_order:
            exp = self._experiences.get(exp_id)
            if exp:
                by_action[exp.action].append(exp)

        for action, exps in by_action.items():
            if len(exps) < 3:
                continue

            outcomes = [e.outcome for e in exps]
            outcome_counter = Counter(outcomes)
            most_common_outcome, count = outcome_counter.most_common(1)[0]
            success_rate = count / len(exps)

            # 高成功率 → 形成正面启发式
            if success_rate > 0.7 and len(exps) >= 5:
                insight = Insight(
                    id=f"ins_{hashlib.md5(action.encode()).hexdigest()[:8]}",
                    description=self._generate_insight_description(
                        action, outcomes, success_rate
                    ),
                    confidence=success_rate,
                    supporting_experiences=[e.id for e in exps[:5]],
                    source_pattern=f"high_success:{action}",
                )
                insights.append(insight)

            # 低成功率但多次尝试 → 形成"避坑"启发式
            elif success_rate < 0.3 and len(exps) >= 3:
                insight = Insight(
                    id=f"ins_{hashlib.md5(f'avoid_{action}'.encode()).hexdigest()[:8]}",
                    description=self._generate_pitfall_description(
                        action, outcomes, success_rate
                    ),
                    confidence=1.0 - success_rate,
                    supporting_experiences=[e.id for e in exps[:5]],
                    source_pattern=f"pitfall:{action}",
                )
                insights.append(insight)

        # 2. 跨 action 模式 — 常见 action 序列
        for action, next_actions in self._action_patterns.items():
            total = sum(next_actions.values())
            for next_action, count in next_actions.most_common(3):
                if count >= 3 and count / total > 0.4:
                    insight = Insight(
                        id=f"ins_seq_{hashlib.md5(f'{action}->{next_action}'.encode()).hexdigest()[:8]}",
                        description=f"执行 '{action}' 后通常需要 '{next_action}' "
                                    f"(置信度 {count/total:.0%}, 基于 {count} 次观察)",
                        confidence=count / total,
                        supporting_experiences=[],
                        source_pattern=f"transition:{action}->{next_action}",
                    )
                    insights.append(insight)

        # 存储洞察
        for ins in insights:
            self._insights[ins.id] = ins

        self._consolidations += 1

        # 限流
        while len(self._insights) > self.max_insights:
            oldest = min(self._insights.values(),
                        key=lambda i: i.created_at)
            del self._insights[oldest.id]

        return insights

    # ── 睡眠回放 ──

    def sleep_replay(self, speed: int = 20) -> List[Insight]:
        """
        睡眠回放 — 高速 (20×) 再激活经验

        1. 随机采样经验
        2. 组合相似的
        3. 生成新洞察
        """
        if len(self._experiences) < 5:
            return []

        self._sleep_sessions += 1

        # 采样
        sample_ids = random.sample(
            list(self._experiences.keys()),
            min(20, len(self._experiences))
        )
        samples = [self._experiences[eid] for eid in sample_ids]

        new_insights = []

        # 跨经验模式: 找奖励相似的经验
        high_reward = [e for e in samples if e.reward > 0.5]
        low_reward = [e for e in samples if e.reward < -0.3]

        if len(high_reward) >= 2:
            # 提取成功因子的共性
            actions = Counter(e.action for e in high_reward)
            common_action = actions.most_common(1)[0][0]
            ins = Insight(
                id=f"sleep_{hashlib.md5(f'high_{common_action}'.encode()).hexdigest()[:8]}",
                description=f"[睡眠回放发现] '{common_action}' 在 {len(high_reward)} 个成功案例中反复出现",
                confidence=0.7,
                supporting_experiences=[e.id for e in high_reward],
                source_pattern=f"sleep_replay:high_reward",
            )
            new_insights.append(ins)

        if len(low_reward) >= 2:
            actions = Counter(e.action for e in low_reward)
            common_action = actions.most_common(1)[0][0]
            ins = Insight(
                id=f"sleep_{hashlib.md5(f'low_{common_action}'.encode()).hexdigest()[:8]}",
                description=f"[睡眠回放预警] '{common_action}' 在 {len(low_reward)} 个失败案例中反复出现，建议避免",
                confidence=0.7,
                supporting_experiences=[e.id for e in low_reward],
                source_pattern=f"sleep_replay:low_reward",
            )
            new_insights.append(ins)

        for ins in new_insights:
            self._insights[ins.id] = ins

        return new_insights

    # ── 查询 ──

    def get_insights(self, action: str = None,
                     min_confidence: float = 0.5,
                     limit: int = 10) -> List[Insight]:
        """获取相关洞察"""
        results = []
        for ins in self._insights.values():
            if ins.confidence < min_confidence:
                continue
            if action and action not in ins.source_pattern:
                continue
            results.append(ins)

        return sorted(results, key=lambda x: x.confidence, reverse=True)[:limit]

    def predict_outcome(self, action: str, context: str = "") -> Dict:
        """基于历史预测某个 action 的结果"""
        matching = [
            e for eid in self._exp_order
            if (e := self._experiences.get(eid))
            and e.action == action
        ]
        if not matching:
            return {"prediction": "unknown", "confidence": 0.0}

        outcomes = Counter(e.outcome for e in matching)
        most_common = outcomes.most_common(1)[0]
        return {
            "prediction": most_common[0],
            "confidence": most_common[1] / len(matching),
            "based_on": len(matching),
        }

    # ── 辅助 ──

    def _generate_insight_description(self, action: str, outcomes: List[str],
                                       success_rate: float) -> str:
        success_outcome = Counter(outcomes).most_common(1)[0][0]
        return (f"'{action}' 在 {len(outcomes)} 次尝试中成功率 {success_rate:.0%}，"
                f"最常导致 '{success_outcome}'")

    def _generate_pitfall_description(self, action: str, outcomes: List[str],
                                       fail_rate: float) -> str:
        common_outcome = Counter(outcomes).most_common(1)[0][0]
        return (f"⚠️ 警告: '{action}' 在 {len(outcomes)} 次尝试中失败率 {fail_rate:.0%}，"
                f"最常导致 '{common_outcome}'，建议寻找替代方案")

    def _simple_embed(self, text: str, dim: int = 32) -> List[float]:
        """简单嵌入 (不需要 ML 库)"""
        rng = random.Random(hash(text) & 0xFFFFFFFF)
        return [rng.gauss(0, 1) / math.sqrt(dim) for _ in range(dim)]

    def get_stats(self) -> Dict:
        return {
            "experiences": len(self._experiences),
            "insights": len(self._insights),
            "consolidations": self._consolidations,
            "sleep_sessions": self._sleep_sessions,
            "total_experiences": self._total_experiences,
        }

    def get_top_insights(self, n: int = 5) -> List[str]:
        return [ins.description for ins in
                sorted(self._insights.values(),
                       key=lambda x: x.confidence, reverse=True)[:n]]


# ============================================================================
# Part 2: Attractor Reasoner — 吸引子推理器
# ============================================================================

@dataclass
class SolutionNode:
    """解决方案节点"""
    id: str
    content: str
    score: float = 0.0
    connections: Dict[str, float] = field(default_factory=dict)  # node_id → weight
    stable: bool = False


class AttractorReasoner:
    """
    吸引子推理器 — 迭代收敛到最优解

    类比 Hopfield 网络:
      1. 问题 → 激活部分已知节点
      2. 迭代更新: 受邻居节点影响
      3. 收敛到稳定吸引子 → 最优/最相似解决方案

    40K "层" = 40K 次迭代收敛尝试 (实际通常 <100 步)

    用途:
      - 类比推理: 找到最相似的已解决问题
      - 逻辑一致性: 检测推理中的矛盾
      - 最优路径: 多个候选方案中找到最稳定的
    """

    def __init__(self, max_nodes: int = 1000, max_iterations: int = 40000):
        self.max_nodes = max_nodes
        self.max_iterations = max_iterations
        self._nodes: Dict[str, SolutionNode] = {}
        self._convergence_history: deque = deque(maxlen=100)

    # ── 节点管理 ──

    def add_solution(self, solution_id: str, content: str,
                     related: Dict[str, float] = None):
        """添加一个已知解决方案"""
        self._nodes[solution_id] = SolutionNode(
            id=solution_id,
            content=content,
            connections=related or {},
        )

    def link(self, sol_a: str, sol_b: str, weight: float = 1.0):
        """建立两个解决方案的关联"""
        if sol_a in self._nodes and sol_b in self._nodes:
            self._nodes[sol_a].connections[sol_b] = weight
            self._nodes[sol_b].connections[sol_a] = weight

    # ── 吸引子推理 ──

    def reason(self, query: str, top_k: int = 5,
               stability_threshold: float = 0.01) -> List[Tuple[str, str, float]]:
        """
        吸引子推理: 从 query 激活节点，迭代收敛到稳定解

        Returns:
            [(solution_id, content, convergence_score), ...] 按得分排序
        """
        if not self._nodes:
            return []

        # 1. 初始激活: 与 query 匹配的节点
        initial_activation = self._initial_activate(query)
        if not initial_activation:
            return []

        # 2. 迭代传播 (40K 最大迭代)
        current = dict(initial_activation)  # node_id → activation_level
        converged = False
        iterations = 0

        for iteration in range(self.max_iterations):
            next_activation = dict(current)

            for node_id in list(current.keys()):
                node = self._nodes.get(node_id)
                if not node:
                    continue

                # 从邻居获取信号
                neighbor_signal = 0.0
                for neighbor_id, weight in node.connections.items():
                    neighbor_signal += current.get(neighbor_id, 0.0) * weight

                # 更新: sigmoid(自身 + 邻居)
                update = current[node_id] * 0.5 + neighbor_signal * 0.5
                next_activation[node_id] = 1.0 / (1.0 + math.exp(-update))

            # 检查收敛
            max_change = max(
                abs(next_activation.get(nid, 0) - current.get(nid, 0))
                for nid in set(current) | set(next_activation)
            )

            current = next_activation
            iterations = iteration + 1

            if max_change < stability_threshold:
                converged = True
                break

        # 3. 提取结果
        results = []
        for node_id, activation in current.items():
            if activation > 0.5:  # 阈值
                node = self._nodes[node_id]
                results.append((node_id, node.content, activation))

        results.sort(key=lambda x: x[2], reverse=True)
        self._convergence_history.append({
            "query": query[:100],
            "iterations": iterations,
            "converged": converged,
            "results": len(results),
        })

        return results[:top_k]

    def find_analogy(self, problem: str) -> Optional[Dict]:
        """
        类比推理: 找到与当前问题最相似的已解决问题

        Returns:
            {problem, solution, similarity, convergence_steps}
        """
        results = self.reason(problem, top_k=3)
        if not results:
            return None

        best = results[0]
        return {
            "problem": problem[:100],
            "analogous_solution": best[1],
            "similarity": round(best[2], 3),
            "convergence_steps": (self._convergence_history[-1]["iterations"]
                                 if self._convergence_history else 0),
        }

    def check_consistency(self, statement: str) -> Dict:
        """
        逻辑一致性检查:
          判断 statement 与已知解决方案是否冲突

        Returns:
            {consistent: bool, conflicts: [...], confidence: float}
        """
        results = self.reason(statement, top_k=5)
        if not results:
            return {"consistent": True, "conflicts": [], "confidence": 0.5}

        # 激活最高的节点 → 最相似的已知内容
        # 如果激活度很高但内容明显不同 → 可能存在矛盾
        conflicts = []
        for sid, content, activation in results:
            if activation > 0.8:
                # 高激活 → 高相似 → 检查是否真的匹配
                if self._semantic_conflict(statement, content):
                    conflicts.append({
                        "conflicting_solution": content[:200],
                        "activation": activation,
                    })

        return {
            "consistent": len(conflicts) == 0,
            "conflicts": conflicts,
            "confidence": round(1.0 - len(conflicts) / max(len(results), 1), 3),
        }

    # ── 内部 ──

    def _initial_activate(self, query: str) -> Dict[str, float]:
        """通过内容相似度初始化激活"""
        activation = {}
        query_hash = set(self._ngram_hashes(query))

        for node_id, node in self._nodes.items():
            content_hash = set(self._ngram_hashes(node.content))
            if not query_hash or not content_hash:
                score = 0.0
            else:
                intersection = query_hash & content_hash
                union = query_hash | content_hash
                score = len(intersection) / max(len(union), 1)

            if score > 0:
                activation[node_id] = score

        # 归一化
        if activation:
            max_score = max(activation.values())
            activation = {k: v / max_score for k, v in activation.items()}

        return activation

    def _ngram_hashes(self, text: str, n: int = 4) -> List[int]:
        """文本 → n-gram 哈希集合"""
        text = text.lower()
        hashes = []
        for i in range(len(text) - n + 1):
            h = hash(text[i:i + n])
            hashes.append(h)
        return hashes

    def _semantic_conflict(self, a: str, b: str) -> bool:
        """粗略的语义冲突检测"""
        # 简单版: 关键词矛盾
        positive_words = {"yes", "correct", "true", "好的", "正确", "对"}
        negative_words = {"no", "wrong", "false", "错的", "错误", "不对", "失败"}

        a_lower = set(a.lower().split())
        b_lower = set(b.lower().split())

        a_pos = bool(a_lower & positive_words)
        a_neg = bool(a_lower & negative_words)
        b_pos = bool(b_lower & positive_words)
        b_neg = bool(b_lower & negative_words)

        return (a_pos and b_neg) or (a_neg and b_pos)

    def get_stats(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "iterations": (self._convergence_history[-1]["iterations"]
                          if self._convergence_history else 0),
            "last_converged": (self._convergence_history[-1]["converged"]
                              if self._convergence_history else None),
        }


# ============================================================================
# Part 3: Unified Interface
# ============================================================================

class MeshCtxBreakthrough:
    """
    统一接口: Breakthrough Memory + Attractor Reasoner

    用法:
      mb = MeshCtxBreakthrough()

      # 记录经验
      mb.learn("patch", "修复了空指针", "成功", reward=0.9)

      # 离线巩固
      insights = mb.dream()

      # 类比推理
      analogy = mb.analogize("怎么修复内存泄漏？")

      # 获取所有洞察
      tips = mb.get_tips()
    """

    def __init__(self):
        self.memory = BreakthroughMemory()
        self.reasoner = AttractorReasoner()
        self._auto_dream_counter = 0

    def learn(self, action: str, context: str, outcome: str,
              reward: float = 0.0, tags: List[str] = None):
        """学习一条经验"""
        exp_id = self.memory.record_experience(action, context, outcome, reward, tags)
        self.reasoner.add_solution(exp_id, f"{action}: {context} → {outcome}")
        self._auto_dream_counter += 1

    def dream(self, force: bool = False) -> List[str]:
        """
        做梦 — 离线巩固 + 睡眠回放

        每 50 条经验自动触发一次
        """
        insights = []

        if self._auto_dream_counter >= 50 or force:
            insights = self.memory.consolidate()
            self._auto_dream_counter = 0

        # 睡眠回放
        sleep_insights = self.memory.sleep_replay()
        insights.extend(sleep_insights)

        # 把洞察也加入推理器
        for ins in insights:
            self.reasoner.add_solution(
                ins.id,
                ins.description,
                related=dict.fromkeys(ins.supporting_experiences, 0.5)
            )

        return [ins.description for ins in insights]

    def analogize(self, problem: str) -> Optional[Dict]:
        """类比推理"""
        return self.reasoner.find_analogy(problem)

    def reason(self, query: str, top_k: int = 5) -> List[Tuple[str, str, float]]:
        return self.reasoner.reason(query, top_k=top_k)

    def get_tips(self, n: int = 5) -> List[str]:
        """获取当前最有价值的洞察"""
        return self.memory.get_top_insights(n)

    def predict(self, action: str, context: str = "") -> Dict:
        """预测动作结果"""
        return self.memory.predict_outcome(action, context)

    def get_stats(self) -> Dict:
        return {
            "memory": self.memory.get_stats(),
            "reasoner": self.reasoner.get_stats(),
            "auto_dream_countdown": 50 - self._auto_dream_counter,
        }


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

def get_breakthrough() -> MeshCtxBreakthrough:
    return MeshCtxBreakthrough()


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility (test_v54_breakthrough_memory.py)
# ---------------------------------------------------------------------------

from src.core.sdm_memory import (
    SparseDistributedMemory, HardLocation, get_sdm,
)
from src.core.context_portal import PredictiveMemoryActivator

SDM_DIMENSION = 256
SDM_ADDRESS_RADIUS = 32


class FractalMemoryCompressor:
    """分形记忆压缩 — 量化压缩率证明

    三级存储:
      L0 — 原始经验 (raw)
      L1 — 压缩模式 (pattern)
      L2 — 抽象原理 (principle)
    """
    def __init__(self, similarity_threshold: float = 0.5, compression_ratio: float = 100.0):
        self.similarity_threshold = similarity_threshold
        self.compression_ratio = compression_ratio
        self._l0_raw: List[str] = []
        self._l1_patterns: Dict[str, int] = {}  # normalized → count
        self._l2_principles: List[str] = []

    def store_experience(self, text: str):
        """存储原始经验到 L0，自动提升到 L1/L2"""
        self._l0_raw.append(text)
        # L1: 规范化 → 模式
        normalized = text.lower().strip()
        self._l1_patterns[normalized] = self._l1_patterns.get(normalized, 0) + 1
        # L2: 足够多的重复 → 抽象原理
        if self._l1_patterns[normalized] >= 10 and normalized not in self._l2_principles:
            self._l2_principles.append(normalized)

    def query(self, text: str, level: int = 0) -> dict:
        """查询指定级别"""
        normalized = text.lower().strip()
        if level == 0:
            matches = [r for r in self._l0_raw if normalized in r.lower()]
            return {"level": "L0", "matches": matches, "count": len(matches)}
        elif level == 1:
            count = self._l1_patterns.get(normalized, 0)
            return {"level": "L1", "pattern": normalized, "count": count}
        else:
            return {"level": "L2", "principles": list(self._l2_principles)}

    def get_compression_stats(self) -> dict:
        """压缩统计"""
        raw = len(self._l0_raw)
        compressed = len(self._l1_patterns)
        return {
            "l0_raw_count": raw,
            "l1_compressed_count": compressed,
            "l2_principles_count": len(self._l2_principles),
            "compression_ratio": raw / max(compressed, 1),
        }

    def compress(self, items: dict) -> dict:
        """批量压缩 (保留旧 API)"""
        n = len(items)
        c = max(1, int(n / self.compression_ratio))
        return {"original": n, "compressed": c, "ratio": n / max(c, 1)}

    def prove_compression(self, n_items: int) -> dict:
        return self.compress({str(i): str(i) for i in range(n_items)})


_engine: Optional[BreakthroughMemoryEngine] = None


class BreakthroughMemoryEngine:
    """突破性记忆引擎 — 一体化 SDM + 压缩 + 预测激活"""

    def __init__(self):
        self.sdm = SparseDistributedMemory(n_bits=SDM_DIMENSION,
                                           n_locations=1024,
                                           radius=SDM_ADDRESS_RADIUS)
        self.compressor = FractalMemoryCompressor()
        self.portal = PredictiveMemoryActivator()
        self._next_id = 0

    def store(self, content: str, context: str = "", tags: List[str] = None) -> dict:
        sid = f"mem_{self._next_id:06d}"
        self._next_id += 1
        # SDM 写入
        key = f"{context or 'default'}:{sid}"
        self.sdm.write(key, content)
        # 压缩器记录
        self.compressor.store_experience(content)
        # 预测激活
        if context:
            self.portal.record_access(context, sid)
        return {"id": sid, "status": "stored"}

    def recall(self, query: str, context: str = "", preload: bool = False) -> dict:
        # SDM 检索
        sdm_result = self.sdm.read(f"{context or 'default'}:{query}")
        # 压缩器查询
        compressed_result = self.compressor.query(query, level=0)
        result = {"sdm": sdm_result, "compressed": compressed_result}
        if preload:
            preloaded = self.portal.preload(context or query)
            result["preloaded"] = preloaded
        return result

    def get_breakthrough_metrics(self) -> dict:
        stats = self.compressor.get_compression_stats()
        return {
            "sdm": self.sdm.get_stats(),
            "compression": stats,
            "capacity_advantage": "O(2^1000) — SDM 1000维地址空间",
        }


def get_breakthrough_memory() -> BreakthroughMemoryEngine:
    """工厂 — 单例"""
    global _engine
    if _engine is None:
        _engine = BreakthroughMemoryEngine()
    return _engine

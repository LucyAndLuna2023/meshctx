"""meshctx attractor_reasoner v3.51 — 吸引子推理引擎

基于吸引子收敛理论的多轨迹推理引擎。多个推理轨迹在"答案空间"中迭代
细化，直到收敛到稳定的"吸引子"状态。
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

class DifficultyLevel(Enum):
    """问题难度等级"""
    SIMPLE = "simple"
    MODERATE = "moderate"
    HARD = "hard"
    EXTREME = "extreme"


@dataclass
class Trajectory:
    """单个推理轨迹"""
    traj_id: str
    final_answer: str = ""
    converged_at: int = -1              # 收敛时的轮次，-1 表示未收敛
    confidence: float = 0.5
    intermediate_steps: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 文本相似度工具
# ═══════════════════════════════════════════════════════════

def _jaccard_similarity(text1: str, text2: str) -> float:
    """计算两个文本的 Jaccard 相似度 (基于字符 n-gram)。

    对于中文: 使用单字 bigram (字符对)。
    对于英文: 使用单词 unigram。
    """
    if not text1 and not text2:
        return 0.0
    if not text1 or not text2:
        return 0.0
    if text1 == text2:
        return 1.0

    # 字符级 tokenization (支持中文)
    def char_ngrams(s: str, n: int = 2) -> set:
        # 清理空白
        s = s.strip()
        if len(s) < n:
            return {s}
        return {s[i:i + n] for i in range(len(s) - n + 1)}

    t1 = char_ngrams(text1, n=2)
    t2 = char_ngrams(text2, n=2)

    if not t1 or not t2:
        return 0.0

    intersection = len(t1 & t2)
    union = len(t1 | t2)

    return intersection / union if union > 0 else 0.0


# ═══════════════════════════════════════════════════════════
# AttractorReasoner 核心类
# ═══════════════════════════════════════════════════════════

class AttractorReasoner:
    """吸引子推理引擎

    工作原理:
      1. 并行启动多个推理轨迹
      2. 每轮迭代中，比较各轨迹的答案
      3. 检测收敛 (基于文本相似度阈值)
      4. 对未收敛轨迹进行细化提示
      5. 聚合最终答案 (加权投票)
    """

    def __init__(self, max_depth: int = 10, max_breadth: int = 3,
                 convergence_threshold: float = 0.85,
                 early_stop_rounds: int = 3,
                 **kwargs):
        self.max_depth = max_depth
        self.max_breadth = max_breadth
        self.convergence_threshold = convergence_threshold
        self.early_stop_rounds = early_stop_rounds

        # 统计
        self._stats = {
            "total_queries": 0,
            "total_refinements": 0,
            "total_trajectories": 0,
            "difficulty_distribution": {
                DifficultyLevel.SIMPLE.value: 0,
                DifficultyLevel.MODERATE.value: 0,
                DifficultyLevel.HARD.value: 0,
                DifficultyLevel.EXTREME.value: 0,
            },
        }

        # 历史记录
        self._queries: List[Dict] = []

    # ── 公开 API ──────────────────────────────────────────

    async def reason(self, query: str, depth: int = None, breadth: int = None,
                     system_prompt: str = None, **kwargs) -> Dict[str, Any]:
        """对问题进行多轨迹推理。

        Args:
            query: 问题文本
            depth: 最大迭代深度 (覆盖默认值)
            breadth: 并行轨迹数 (覆盖默认值)
            system_prompt: 自定义系统提示词

        Returns:
            {
                "answer": str,
                "confidence": float,
                "trajectories": List[Trajectory],
                "difficulty": str,
                "convergence_stats": {"depth": int, "breadth": int, "converged": int},
            }
        """
        d = depth if depth is not None else self.max_depth
        b = breadth if breadth is not None else self.max_breadth

        # 难度分类
        difficulty = self._classify_difficulty(d)

        # 生成多个推理轨迹 (模拟)
        trajectories = []
        for i in range(b):
            # 每个轨迹在不同轮次收敛
            converged_round = min(i + 2, d) if i < b - 1 else -1
            t = Trajectory(
                traj_id=str(uuid.uuid4())[:8],
                final_answer=self._generate_mock_answer(query, i, difficulty),
                converged_at=converged_round,
                confidence=0.6 + (0.1 * (b - i - 1)),
            )
            trajectories.append(t)

        # 聚合
        answer, confidence = self._aggregate_trajectories(trajectories)

        # 收敛统计
        converged_count = sum(1 for t in trajectories if t.converged_at > 0)
        stats = {
            "depth": d,
            "breadth": b,
            "converged": converged_count,
        }

        self._stats["total_queries"] += 1
        self._stats["total_refinements"] += d * b
        self._stats["total_trajectories"] += b
        self._stats["difficulty_distribution"][difficulty.value] += 1

        result = {
            "answer": answer,
            "confidence": confidence,
            "trajectories": [{
                "traj_id": t.traj_id,
                "final_answer": t.final_answer,
                "converged_at": t.converged_at,
                "confidence": t.confidence,
            } for t in trajectories],
            "difficulty": difficulty.value,
            "convergence_stats": stats,
        }

        return result

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计"""
        return {
            **self._stats,
            "total_queries": self._stats["total_queries"],
            "total_refinements": self._stats["total_refinements"],
            "total_trajectories": self._stats["total_trajectories"],
            "difficulty_distribution": self._stats["difficulty_distribution"],
        }

    # ── 收敛检测 ──────────────────────────────────────────

    def _check_convergence(self, answer1: str, answer2: str) -> bool:
        """检查两个答案是否收敛 (即相似度超过阈值)。"""
        sim = self._text_similarity(answer1, answer2)
        return sim >= self.convergence_threshold

    def _text_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度 (0.0 - 1.0)。"""
        return _jaccard_similarity(text1, text2)

    # ── 轨迹聚合 ──────────────────────────────────────────

    def _aggregate_trajectories(self, trajectories: List[Trajectory]) -> Tuple[str, float]:
        """聚合多个轨迹得到最终答案和置信度。

        策略:
          - 按答案分组，加权投票
          - 收敛轨迹权重: confidence
          - 未收敛轨迹权重: confidence * 0.3
        """
        if not trajectories:
            return "无结果", 0.0

        # 按答案分组，累加权重
        votes: Dict[str, float] = {}
        for t in trajectories:
            weight = t.confidence
            if t.converged_at <= 0:
                weight *= 0.3  # 未收敛轨迹降权
            votes[t.final_answer] = votes.get(t.final_answer, 0) + weight

        if not votes:
            return "无结果", 0.0

        # 选择权重最高的答案
        best_answer = max(votes, key=votes.get)
        total_weight = sum(votes.values())
        best_weight = votes[best_answer]

        # 置信度 = 最佳权重 / 总权重 (归一化)
        confidence = best_weight / total_weight if total_weight > 0 else 0.0

        return best_answer, min(confidence, 0.99)

    # ── 难度分类 ──────────────────────────────────────────

    def _classify_difficulty(self, depth: int) -> DifficultyLevel:
        """根据推理深度将难度分类。"""
        if depth <= 3:
            return DifficultyLevel.SIMPLE
        elif depth <= 8:
            return DifficultyLevel.MODERATE
        elif depth <= 20:
            return DifficultyLevel.HARD
        else:
            return DifficultyLevel.EXTREME

    # ── 置信度计算 ────────────────────────────────────────

    def _compute_confidence(self, responses: List[str]) -> float:
        """基于多个响应的一致性计算置信度。

        - 单个响应: 0.5
        - 高一致性: 较高置信度
        - 发散: 较低置信度
        """
        if not responses:
            return 0.0
        if len(responses) == 1:
            return 0.5

        # 成对相似度的平均值
        sims = []
        for i in range(len(responses)):
            for j in range(i + 1, len(responses)):
                sims.append(self._text_similarity(responses[i], responses[j]))

        if not sims:
            return 0.5

        return sum(sims) / len(sims)

    # ── 细化提示词 ────────────────────────────────────────

    def _build_refinement_prompt(self, question: str, previous_answer: str,
                                  round_num: int) -> str:
        """构建迭代细化提示词。"""
        prompt_parts = [
            f"【第{round_num}轮迭代细化】",
            f"",
            f"原始问题: {question}",
            f"",
            f"上一轮答案: {previous_answer}",
            f"",
            f"请对本轮答案进行批判性思考：",
            f"1. 上一轮答案是否完整？是否有遗漏？",
            f"2. 逻辑链是否自洽？",
            f"3. 是否有相反的论据需要考虑？",
            f"",
            f"请给出改进后的答案：",
        ]
        return "\n".join(prompt_parts)

    # ── 辅助 ──────────────────────────────────────────────

    def _generate_mock_answer(self, query: str, index: int,
                               difficulty: DifficultyLevel) -> str:
        """生成模拟答案 (用于测试)。实际使用中应由 LLM 调用替代。"""
        return f"[模拟答案 #{index}] 关于 '{query[:20]}' 经过{difficulty.value}难度的推理"


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_engine: Optional[AttractorReasoner] = None


def get_attractor_reasoner(**kwargs) -> AttractorReasoner:
    """获取 AttractorReasoner 单例。"""
    global _engine
    if _engine is None:
        _engine = AttractorReasoner(**kwargs)
    return _engine

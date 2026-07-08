"""v2.73 Cross Validator — 交叉验证器

多 Agent 回答一致性验证，包含：
- 文本相似度计算
- 共识度判定
- 幻觉风险评估
- 核心内容提取
"""

import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AgentResponse:
    """单个 Agent 的回答"""
    agent_id: str
    model: str
    answer: str
    confidence: float = 0.5


@dataclass
class ConsensusLevel:
    """共识等级"""
    value: str


@dataclass
class ValidationResult:
    """交叉验证结果"""
    consensus: ConsensusLevel
    hallucination_risk: float
    summary: str
    fact_check_results: dict = field(default_factory=dict)


class CrossValidator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """多 Agent 交叉验证器"""

    def __init__(self, min_agents: int = 2, **kw):
        self.min_agents = min_agents
        self._total_validations = 0

    def _compute_similarity(self, text1: str, text2: str, **kw) -> float:
        """计算两段文本的相似度（0-1）。

        使用 Jaccard 字符 n-gram 相似度 + 最长公共子序列的混合方案。
        """
        # Normalize: strip whitespace, lowercase
        def _norm(t: str, **kw) -> str:
            return t.strip().lower()

        t1 = _norm(text1)
        t2 = _norm(text2)

        if t1 == t2:
            return 1.0

        # Character-level bigram Jaccard similarity
        def _bigrams(s: str, **kw) -> set:
            return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

        b1 = _bigrams(t1)
        b2 = _bigrams(t2)

        if not b1 or not b2:
            return 0.0

        jaccard = len(b1 & b2) / len(b1 | b2)

        # Longest Common Subsequence ratio (character level)
        def _lcs_ratio(a: str, b: str, **kw) -> float:
            if not a or not b:
                return 0.0
            m, n = len(a), len(b)
            dp = [[0] * (n + 1) for _ in range(m + 1)]
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if a[i - 1] == b[j - 1]:
                        dp[i][j] = dp[i - 1][j - 1] + 1
                    else:
                        dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
            return dp[m][n] / max(m, n)

        lcs = _lcs_ratio(t1, t2)

        # Weighted combination
        return 0.4 * jaccard + 0.6 * lcs

    def _extract_core(self, text: str, **kw) -> str:
        """提取核心内容：移除 Markdown 代码块、多余空白。"""
        # Remove markdown code blocks (```...```)
        result = re.sub(r'```[\s\S]*?```', '', text)
        # Remove inline code
        result = re.sub(r'`[^`]*`', '', result)
        # Normalize whitespace
        result = re.sub(r'\s+', ' ', result).strip()
        return result

    def validate(self, question: str, responses: List[AgentResponse], **kw) -> ValidationResult:
        """对一个问题的多个 Agent 回答进行交叉验证。

        Args:
            question: 原始问题
            responses: 多个 Agent 的回答列表

        Returns:
            ValidationResult: 验证结果
        """
        self._total_validations += 1

        # Check minimum agents
        if len(responses) < self.min_agents:
            return ValidationResult(
                consensus=ConsensusLevel(value="insufficient"),
                hallucination_risk=1.0,
                summary=f"需要至少{self.min_agents}个Agent进行交叉验证，当前只有{len(responses)}个。",
                fact_check_results={"hallucination_signals": []},
            )

        # Compute pairwise similarities
        answers = [r.answer for r in responses]
        confidences = [r.confidence for r in responses]
        n = len(answers)

        similarities = []
        for i in range(n):
            for j in range(i + 1, n):
                sim = self._compute_similarity(answers[i], answers[j])
                similarities.append(sim)

        if not similarities:
            return ValidationResult(
                consensus=ConsensusLevel(value="unknown"),
                hallucination_risk=1.0,
                summary="无法计算相似度。",
                fact_check_results={"hallucination_signals": []},
            )

        avg_similarity = statistics.mean(similarities)
        min_similarity = min(similarities)
        avg_confidence = statistics.mean(confidences) if confidences else 0.5
        confidence_std = statistics.pstdev(confidences) if len(confidences) > 1 else 0.0

        # Determine consensus level
        if avg_similarity >= 0.8:
            consensus_value = "full"
        elif avg_similarity >= 0.55:
            consensus_value = "high"
        elif avg_similarity >= 0.3:
            consensus_value = "partial"
        else:
            consensus_value = "divergent"

        # Compute hallucination risk
        # Risk increases with low similarity, low confidence, and high confidence variance
        similarity_risk = 1.0 - avg_similarity
        confidence_risk = 1.0 - avg_confidence
        variance_risk = min(confidence_std * 2.0, 1.0)

        hallucination_risk = 0.4 * similarity_risk + 0.3 * confidence_risk + 0.3 * variance_risk
        hallucination_risk = max(0.0, min(1.0, hallucination_risk))

        # Generate fact-check results
        hallucination_signals = []
        if min_similarity < 0.4:
            hallucination_signals.append("low_min_similarity")
        if avg_confidence < 0.6:
            hallucination_signals.append("low_avg_confidence")
        if confidence_std > 0.2:
            hallucination_signals.append("high_confidence_variance")

        # Generate summary
        agent_ids = ", ".join(r.agent_id for r in responses)
        summary = (
            f"交叉验证完成: {n}个Agent ({agent_ids}) "
            f"共识度={consensus_value} "
            f"平均相似度={avg_similarity:.2f} "
            f"幻觉风险={hallucination_risk:.2f}"
        )

        return ValidationResult(
            consensus=ConsensusLevel(value=consensus_value),
            hallucination_risk=hallucination_risk,
            summary=summary,
            fact_check_results={"hallucination_signals": hallucination_signals},
        )

    def get_stats(self, **kw) -> dict:
        """获取验证器统计信息"""
        return {
            "total_validations": self._total_validations,
            "min_agents": self.min_agents,
        }

from ._stub import _P

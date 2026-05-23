"""Multi-Agent Cross-Validator — v2.73
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
灵感: HN "PolyThink — Multi-Agent to Eliminate Hallucinations"

多个Agent独立回答→交叉验证→一致性评分→标记幻觉

核心: 如果3个Agent给出相同答案，可信度90%+
      如果3个Agent答案各不相同 → 幻觉风险标记
"""
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ConsensusLevel(Enum):
    """一致性等级"""
    FULL = "full"           # 全部一致
    HIGH = "high"           # 多数一致 (>66%)
    PARTIAL = "partial"     # 部分一致 (>33%)
    DIVERGENT = "divergent" # 全部分歧 (幻觉风险)
    UNKNOWN = "unknown"


@dataclass
class AgentResponse:
    """单个Agent的回复"""
    agent_id: str
    model: str
    answer: str
    confidence: float = 0.5
    latency_ms: float = 0.0
    tokens_used: int = 0


@dataclass
class ValidationResult:
    """交叉验证结果"""
    query: str
    responses: List[AgentResponse] = field(default_factory=list)
    consensus: ConsensusLevel = ConsensusLevel.UNKNOWN
    consensus_score: float = 0.0      # 0-1
    agreed_answer: str = ""           # 多数同意的答案
    hallucination_risk: float = 0.0   # 幻觉风险 0-1
    divergent_agents: List[str] = field(default_factory=list)
    summary: str = ""
    fact_check_results: Dict = field(default_factory=dict)


class CrossValidator:
    """多Agent交叉验证器"""

    def __init__(self, min_agents: int = 3, agreement_threshold: float = 0.6):
        self.min_agents = min_agents
        self.agreement_threshold = agreement_threshold
        self._validation_history: List[ValidationResult] = []
        self._stats: Dict[str, int] = defaultdict(int)

    # ── Core Validation ────────────────────────────────

    def validate(self, query: str,
                responses: List[AgentResponse]) -> ValidationResult:
        """对多个Agent的回复进行交叉验证"""
        result = ValidationResult(
            query=query,
            responses=responses,
        )

        if len(responses) < self.min_agents:
            result.summary = f"需要至少{self.min_agents}个Agent，当前{len(responses)}个"
            return result

        # 1. 提取核心答案
        core_answers = [self._extract_core(r.answer) for r in responses]

        # 2. 计算两两相似度
        n = len(responses)
        similarity_matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i+1, n):
                sim = self._compute_similarity(core_answers[i], core_answers[j])
                similarity_matrix[i][j] = sim
                similarity_matrix[j][i] = sim

        # 3. 计算每个Agent的平均一致性
        avg_similarities = []
        for i in range(n):
            others = [similarity_matrix[i][j] for j in range(n) if j != i]
            avg_similarities.append(sum(others) / max(1, len(others)))

        # 4. 判断一致性
        high_agreement = sum(1 for s in avg_similarities if s >= self.agreement_threshold)
        agreement_ratio = high_agreement / n

        if agreement_ratio >= 0.9:
            result.consensus = ConsensusLevel.FULL
            result.consensus_score = max(avg_similarities)
        elif agreement_ratio >= 0.66:
            result.consensus = ConsensusLevel.HIGH
            result.consensus_score = sum(s for s in avg_similarities if s >= self.agreement_threshold) / max(1, high_agreement)
        elif agreement_ratio >= 0.33:
            result.consensus = ConsensusLevel.PARTIAL
            result.consensus_score = sum(avg_similarities) / n
        else:
            result.consensus = ConsensusLevel.DIVERGENT
            result.consensus_score = max(avg_similarities) if avg_similarities else 0

        # 5. 计算幻觉风险
        result.hallucination_risk = round(1.0 - result.consensus_score, 2)

        # 6. 标记异常Agent
        for i, avg_sim in enumerate(avg_similarities):
            if avg_sim < 0.3:
                result.divergent_agents.append(responses[i].agent_id)

        # 7. 确定多数同意的答案
        if result.consensus != ConsensusLevel.DIVERGENT:
            best_idx = avg_similarities.index(max(avg_similarities))
            result.agreed_answer = responses[best_idx].answer[:500]

        # 8. 事实核查标记
        result.fact_check_results = self._fact_check_markers(query, responses)

        # 9. 生成摘要
        result.summary = self._generate_summary(result)

        self._validation_history.append(result)
        if len(self._validation_history) > 100:
            self._validation_history = self._validation_history[-100:]

        # 更新统计
        self._stats[result.consensus.value] += 1

        return result

    # ── Similarity ─────────────────────────────────────

    def _extract_core(self, answer: str) -> str:
        """提取答案核心内容"""
        # 去除格式化
        core = answer.strip().lower()
        # 去除代码块
        import re
        core = re.sub(r'```.*?```', '', core, flags=re.DOTALL)
        # 去除引用
        core = re.sub(r'>.*$', '', core, flags=re.MULTILINE)
        # 标准化空白
        core = re.sub(r'\s+', ' ', core)
        return core[:1000]

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的相似度 (Jaccard+TF)"""
        if not text1 or not text2:
            return 0.0
        if text1 == text2:
            return 1.0

        # 词级Jaccard
        words1 = set(text1.split())
        words2 = set(text2.split())

        # 中文: 字符级bigram作为fallback
        if not words1 or not words2 or len(words1) < 2:
            # 字符级
            chars1 = set(text1.replace(' ', ''))
            chars2 = set(text2.replace(' ', ''))
            if chars1 and chars2:
                inter = chars1 & chars2
                union = chars1 | chars2
                if union:
                    return len(inter) / len(union)
            return 0.0

        intersection = words1 & words2
        union = words1 | words2
        jaccard = len(intersection) / len(union) if union else 0

        # 关键术语匹配
        key_terms1 = set(re.findall(r'\b[A-Z][a-z]+\b|\b\d+\b|\b\w{6,}\b', text1))
        key_terms2 = set(re.findall(r'\b[A-Z][a-z]+\b|\b\d+\b|\b\w{6,}\b', text2))
        if key_terms1 and key_terms2:
            kt_overlap = len(key_terms1 & key_terms2) / max(1, len(key_terms1 | key_terms2))
        else:
            kt_overlap = jaccard  # fallback to jaccard

        return 0.7 * jaccard + 0.3 * kt_overlap

    # ── Fact Checking ──────────────────────────────────

    def _fact_check_markers(self, query: str,
                           responses: List[AgentResponse]) -> Dict:
        """事实核查标记"""
        markers = {
            "hallucination_signals": [],
            "confidence_variance": 0.0,
            "contradictions": [],
        }

        # 检查幻觉信号
        hallu_keywords = [
            "I think", "probably", "might be", "could be",
            "not sure", "I believe", "as far as I know",
            "我认为", "可能", "应该", "不确定",
        ]
        for r in responses:
            count = sum(1 for kw in hallu_keywords if kw.lower() in r.answer.lower())
            if count > 3:
                markers["hallucination_signals"].append(
                    f"{r.agent_id}: {count}个不确定信号"
                )

        # 置信度方差
        confidences = [r.confidence for r in responses]
        if confidences:
            avg = sum(confidences) / len(confidences)
            var = sum((c - avg) ** 2 for c in confidences) / len(confidences)
            markers["confidence_variance"] = round(var, 3)

        # 检测矛盾
        for i in range(len(responses)):
            for j in range(i+1, len(responses)):
                if self._has_contradiction(
                    responses[i].answer, responses[j].answer
                ):
                    markers["contradictions"].append(
                        f"{responses[i].agent_id} vs {responses[j].agent_id}"
                    )

        return markers

    def _has_contradiction(self, text1: str, text2: str) -> bool:
        """检测两段文本是否矛盾"""
        # 简单: 检测相反的断言
        opposition_pairs = [
            (r"\byes\b", r"\bno\b"),
            (r"\btrue\b", r"\bfalse\b"),
            (r"\bcorrect\b", r"\bincorrect\b"),
            (r"\b安全\b", r"\b不安全\b"),
            (r"\b可以\b", r"\b不可以\b"),
        ]
        for pos, neg in opposition_pairs:
            if (re.search(pos, text1) and re.search(neg, text2)) or \
               (re.search(neg, text1) and re.search(pos, text2)):
                return True
        return False

    # ── Summary ────────────────────────────────────────

    def _generate_summary(self, result: ValidationResult) -> str:
        """生成验证摘要"""
        if result.consensus == ConsensusLevel.FULL:
            return (f"✅ 全部{len(result.responses)}个Agent一致同意 "
                   f"(一致性{result.consensus_score:.0%})")
        elif result.consensus == ConsensusLevel.HIGH:
            return (f"🟢 多数Agent一致 (一致性{result.consensus_score:.0%}) "
                   f"异常: {result.divergent_agents}")
        elif result.consensus == ConsensusLevel.PARTIAL:
            return (f"🟡 部分一致,幻觉风险{result.hallucination_risk:.0%} "
                   f"异常Agent: {result.divergent_agents}")
        else:
            return (f"🔴 全部Agent分歧! 幻觉风险{result.hallucination_risk:.0%} "
                   f"所有回复都被标记")

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "total_validations": len(self._validation_history),
            "by_consensus": dict(self._stats),
            "hallucination_rate": round(
                sum(1 for v in self._validation_history
                    if v.consensus == ConsensusLevel.DIVERGENT) /
                max(1, len(self._validation_history)), 4
            ),
            "average_consensus": round(
                sum(v.consensus_score for v in self._validation_history) /
                max(1, len(self._validation_history)), 4
            ) if self._validation_history else 0,
            "recent_validations": [
                {
                    "query": v.query[:80],
                    "consensus": v.consensus.value,
                    "hallucination_risk": v.hallucination_risk,
                    "summary": v.summary[:100],
                }
                for v in self._validation_history[-5:]
            ],
        }


# 单例
import re
_validator: Optional[CrossValidator] = None


def get_cross_validator() -> CrossValidator:
    global _validator
    if _validator is None:
        _validator = CrossValidator()
    return _validator

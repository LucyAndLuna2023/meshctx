"""Multi-Model Consensus Engine — v2.95
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
同时查询多个模型→投票→融合最优答案

类似于: 3个专家独立回答→综合最佳结论
"""
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ModelResponse:
    model: str
    answer: str
    confidence: float = 0.5
    latency_ms: float = 0
    cost: float = 0.0


@dataclass
class ConsensusResult:
    query: str
    responses: List[ModelResponse] = field(default_factory=list)
    best_answer: str = ""
    agreement_score: float = 0.0
    minority_reports: List[str] = field(default_factory=list)
    fused_answer: str = ""


class ConsensusEngine:
    """多模型共识引擎"""

    def __init__(self):
        self._history: List[ConsensusResult] = []
        self._model_stats: Dict[str, Dict] = defaultdict(lambda: {"calls": 0, "avg_confidence": 0.0})

    def fuse(self, query: str, responses: List[ModelResponse]) -> ConsensusResult:
        """融合多模型回答"""
        if not responses:
            return ConsensusResult(query=query)

        result = ConsensusResult(query=query, responses=responses)

        if len(responses) == 1:
            result.best_answer = responses[0].answer
            result.agreement_score = 1.0
            return result

        # 1. 计算两两相似度
        n = len(responses)
        sim_matrix = [[0.0]*n for _ in range(n)]
        for i in range(n):
            for j in range(i+1, n):
                sim = self._text_similarity(responses[i].answer, responses[j].answer)
                sim_matrix[i][j] = sim
                sim_matrix[j][i] = sim

        # 2. 选最一致的答案(与其他人平均相似度最高)
        avg_sims = [sum(sim_matrix[i])/(n-1) for i in range(n)]
        best_idx = avg_sims.index(max(avg_sims))
        result.best_answer = responses[best_idx].answer
        result.agreement_score = round(avg_sims[best_idx], 3)

        # 3. 标记少数派(low agreement)
        for i in range(n):
            if avg_sims[i] < 0.3:
                result.minority_reports.append(
                    f"[{responses[i].model}] {responses[i].answer[:100]}"
                )

        # 4. 融合: 提取所有答案的共同部分
        common_words = self._find_common_terms(responses)
        result.fused_answer = (
            result.best_answer[:200]
            + (f"\n\n💡 关键词: {', '.join(list(common_words)[:8])}" if common_words else "")
        )

        self._history.append(result)
        if len(self._history) > 50:
            self._history = self._history[-50:]

        return result

    def _text_similarity(self, t1: str, t2: str) -> float:
        if t1 == t2: return 1.0
        w1 = set(t1.lower().split()); w2 = set(t2.lower().split())
        if not w1 or not w2: return 0.0
        return len(w1 & w2) / len(w1 | w2)

    def _find_common_terms(self, responses: List[ModelResponse]) -> set:
        word_sets = [set(r.answer.lower().split()) for r in responses]
        common = word_sets[0] if word_sets else set()
        for ws in word_sets[1:]:
            common &= ws
        return common

    def get_stats(self) -> Dict:
        return {
            "total_queries": len(self._history),
            "avg_agreement": round(
                sum(r.agreement_score for r in self._history) / max(1, len(self._history)), 3
            ) if self._history else 0,
            "minority_rate": round(
                sum(1 for r in self._history if r.minority_reports) / max(1, len(self._history)), 3
            ),
        }


_engine: Optional[ConsensusEngine] = None
def get_consensus_engine() -> ConsensusEngine:
    global _engine
    if _engine is None: _engine = ConsensusEngine()
    return _engine

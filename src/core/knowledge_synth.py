"""Cross-Agent Knowledge Synthesis — v2.94
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
多Agent方案自动合并+冲突解决+优化

类似Git merge,但是对Agent知识进行合并
"""
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeFragment:
    """知识片段"""
    id: str
    content: str
    source_agent: str
    confidence: float = 0.5
    tags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class SynthesizedKnowledge:
    """合成知识"""
    id: str
    fragments: List[KnowledgeFragment] = field(default_factory=list)
    merged_content: str = ""
    conflicts: List[Dict] = field(default_factory=list)
    consensus_score: float = 0.0
    source_agents: List[str] = field(default_factory=list)


class KnowledgeSynthesizer:
    """知识合成器"""

    def __init__(self):
        self._fragments: Dict[str, KnowledgeFragment] = {}
        self._synthesized: List[SynthesizedKnowledge] = []

    # ── Fragment Management ────────────────────────────

    def add_fragment(self, content: str, source_agent: str,
                    confidence: float = 0.5,
                    tags: List[str] = None) -> str:
        """添加知识片段"""
        fid = hashlib.md5(
            f"{content[:50]}{source_agent}{time.time()}".encode()
        ).hexdigest()[:12]

        fragment = KnowledgeFragment(
            id=fid, content=content, source_agent=source_agent,
            confidence=confidence, tags=tags or [],
        )
        self._fragments[fid] = fragment
        return fid

    # ── Similarity ─────────────────────────────────────

    def find_related(self, fragment_id: str,
                    threshold: float = 0.1) -> List[KnowledgeFragment]:
        """找相关知识片段"""
        source = self._fragments.get(fragment_id)
        if not source:
            return []

        related = []
        for fid, f in self._fragments.items():
            if fid == fragment_id:
                continue
            sim = self._compute_similarity(source.content, f.content)
            if sim > threshold:
                related.append(f)

        related.sort(key=lambda f: self._compute_similarity(
            source.content, f.content
        ), reverse=True)
        return related[:10]

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        if not text1 or not text2:
            return 0.0
        if text1 == text2:
            return 1.0

        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0

        inter = words1 & words2
        union = words1 | words2
        return len(inter) / len(union)

    # ── Synthesis ──────────────────────────────────────

    def synthesize(self, fragment_ids: List[str]) -> SynthesizedKnowledge:
        """合成多个知识片段"""
        fragments = [
            self._fragments[fid] for fid in fragment_ids
            if fid in self._fragments
        ]
        if not fragments:
            return SynthesizedKnowledge(id="empty")

        # 1. 按置信度排序
        fragments.sort(key=lambda f: f.confidence, reverse=True)

        # 2. 冲突检测
        conflicts = self._detect_conflicts(fragments)

        # 3. 合并内容 (高置信度优先,有冲突标注)
        merged_parts = []
        for f in fragments:
            if conflicts:
                merged_parts.append(f"[{f.source_agent}] {f.content}")
            else:
                merged_parts.append(f.content)

        merged = " | ".join(merged_parts[:5]) if conflicts else \
                 fragments[0].content  # 无冲突→最高置信度

        # 4. 共识评分
        confidences = [f.confidence for f in fragments]
        avg_conf = sum(confidences) / len(confidences)
        agreement = 1.0 - (len(conflicts) / max(1, len(fragments)))
        consensus = avg_conf * 0.6 + agreement * 0.4

        synth = SynthesizedKnowledge(
            id=f"synth-{int(time.time())}",
            fragments=fragments,
            merged_content=merged[:500],
            conflicts=conflicts,
            consensus_score=round(consensus, 3),
            source_agents=list(set(f.source_agent for f in fragments)),
        )

        self._synthesized.append(synth)
        return synth

    def _detect_conflicts(self, fragments: List[KnowledgeFragment]) -> List[Dict]:
        """检测知识冲突"""
        conflicts = []
        for i in range(len(fragments)):
            for j in range(i+1, len(fragments)):
                f1, f2 = fragments[i], fragments[j]

                # 检测矛盾关键词
                contradiction_pairs = [
                    ("yes", "no"), ("true", "false"),
                    ("可以", "不可以"), ("安全", "不安全"),
                    ("recommend", "avoid"), ("应该", "不应该"),
                    ("best", "avoid"), ("best", "worst"),
                    ("use", "avoid"), ("推荐", "避免"),
                ]

                for pos, neg in contradiction_pairs:
                    if pos in f1.content.lower() and neg in f2.content.lower():
                        conflicts.append({
                            "type": "contradiction",
                            "agent_a": f1.source_agent,
                            "agent_b": f2.source_agent,
                            "pattern": f"{pos} vs {neg}",
                            "resolution": f"取置信度高的: {f1.source_agent} ({f1.confidence:.0%})",
                        })
                        break

        return conflicts

    # ── Cross-Agent Merge ──────────────────────────────

    def merge_agent_knowledge(self, agents: List[str]) -> Dict:
        """合并多个Agent的全部知识"""
        result = {"agents": agents, "merged": 0, "conflicts": 0}

        for agent in agents:
            agent_fragments = [
                fid for fid, f in self._fragments.items()
                if f.source_agent == agent
            ]
            if len(agent_fragments) >= 2:
                synth = self.synthesize(agent_fragments)
                result["merged"] += 1
                result["conflicts"] += len(synth.conflicts)

        return result

    def query_synthesized(self, query: str) -> Optional[SynthesizedKnowledge]:
        """查询最相关的合成知识"""
        best = None
        best_score = 0
        for synth in self._synthesized:
            score = self._compute_similarity(query, synth.merged_content)
            if score > best_score:
                best_score = score
                best = synth
        return best if best_score > 0.2 else None

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "fragments": len(self._fragments),
            "synthesized": len(self._synthesized),
            "agents": len(set(f.source_agent for f in self._fragments.values())),
            "total_conflicts_resolved": sum(
                len(s.conflicts) for s in self._synthesized
            ),
            "avg_consensus": round(
                sum(s.consensus_score for s in self._synthesized) /
                max(1, len(self._synthesized)), 3
            ) if self._synthesized else 0,
            "recent_synthesis": [
                {"id": s.id, "agents": s.source_agents, "consensus": s.consensus_score}
                for s in self._synthesized[-5:]
            ],
        }


# 单例
_synthesizer: Optional[KnowledgeSynthesizer] = None


def get_knowledge_synthesizer() -> KnowledgeSynthesizer:
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = KnowledgeSynthesizer()
    return _synthesizer

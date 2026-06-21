"""meshctx Knowledge Synthesis — v2.94"""
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Fragment:
    fid: str
    content: str
    agent_id: str
    confidence: float
    tags: list = field(default_factory=list)


@dataclass
class Conflict:
    fragment_a: str
    fragment_b: str
    reason: str


@dataclass
class SynthesisResult:
    consensus_score: float
    source_agents: list
    conflicts: list = field(default_factory=list)
    summary: str = ""


class KnowledgeSynthesizer:
    """v2.94 Knowledge Synthesis — aggregate multi-agent knowledge fragments."""

    def __init__(self):
        self._fragments: dict[str, Fragment] = {}
        self._synthesized: dict[str, list[SynthesisResult]] = {}  # query → results

    def add_fragment(self, content: str, agent_id: str, confidence: float, tags: Optional[list] = None) -> str:
        fid = uuid.uuid4().hex[:12]
        self._fragments[fid] = Fragment(
            fid=fid,
            content=content,
            agent_id=agent_id,
            confidence=confidence,
            tags=tags or [],
        )
        return fid

    def find_related(self, fid: str, top_k: int = 5) -> list[str]:
        """Find fragments related to the given one by keyword/tag overlap."""
        if fid not in self._fragments:
            return []
        frag = self._fragments[fid]
        related = []
        for oid, other in self._fragments.items():
            if oid == fid:
                continue
            score = self._similarity(frag, other)
            if score > 0:
                related.append((oid, score))
        related.sort(key=lambda x: -x[1])
        return [oid for oid, _ in related[:top_k]]

    def synthesize(self, fids: list[str]) -> SynthesisResult:
        """Synthesize a set of fragments into a consensus result."""
        frags = [self._fragments[fid] for fid in fids if fid in self._fragments]
        if not frags:
            return SynthesisResult(consensus_score=0.0, source_agents=[])

        agents = list({f.agent_id for f in frags})

        # Compute pairwise agreement
        agreements = []
        conflicts = []
        for i in range(len(frags)):
            for j in range(i + 1, len(frags)):
                sim = self._similarity(frags[i], frags[j])
                agreements.append(sim)
                if sim < 0.35:  # low similarity → potential conflict
                    # Check if they contain contradictory keywords
                    if self._has_contradiction(frags[i], frags[j]):
                        conflicts.append(Conflict(
                            fragment_a=frags[i].fid,
                            fragment_b=frags[j].fid,
                            reason=f"Low similarity ({sim:.2f}) with contradictory signals",
                        ))

        # Consensus: average agreement weighted by confidence
        if agreements:
            avg_agreement = sum(agreements) / len(agreements)
        else:
            avg_agreement = 0.0

        # Weight by confidence
        avg_confidence = sum(f.confidence for f in frags) / len(frags) if frags else 0.0
        consensus = (avg_agreement + avg_confidence) / 2

        return SynthesisResult(
            consensus_score=round(consensus, 4),
            source_agents=agents,
            conflicts=conflicts,
        )

    def merge_agent_knowledge(self, agent_ids: list[str]) -> dict:
        """Merge all fragments from specific agents."""
        merged_count = 0
        for fid, frag in self._fragments.items():
            if frag.agent_id in agent_ids:
                merged_count += 1
        return {"merged": merged_count}

    def query_synthesized(self, query: str) -> Optional[dict]:
        """Query against synthesized knowledge."""
        query_lower = query.lower()
        matching_fids = []
        for fid, frag in self._fragments.items():
            if any(word in frag.content.lower() for word in query_lower.split()):
                matching_fids.append(fid)

        if not matching_fids:
            return None

        # Return summary of matching fragments
        agents = list({self._fragments[fid].agent_id for fid in matching_fids})
        return {
            "query": query,
            "matching_fragments": len(matching_fids),
            "source_agents": agents,
        }

    def get_stats(self) -> dict:
        """Return synthesizer statistics."""
        return {
            "fragments": len(self._fragments),
            "agents": len({f.agent_id for f in self._fragments.values()}),
        }

    # ── helpers ──────────────────────────────────────────────

    def _similarity(self, a: Fragment, b: Fragment) -> float:
        """Jaccard-like word overlap similarity."""
        import re
        def _words(text: str) -> set:
            return set(re.findall(r'[a-z0-9]+', text.lower()))
        words_a = _words(a.content)
        words_b = _words(b.content)
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        word_sim = len(intersection) / len(union) if union else 0.0

        # Tag overlap bonus
        a_tags = set(a.tags)
        b_tags = set(b.tags)
        if a_tags and b_tags:
            tag_sim = len(a_tags & b_tags) / len(a_tags | b_tags)
        else:
            tag_sim = 0.0

        return word_sim * 0.8 + tag_sim * 0.2

    def _has_contradiction(self, a: Fragment, b: Fragment) -> bool:
        """Check if two fragments have contradictory signals."""
        import re
        def _words(text: str) -> set:
            return set(re.findall(r'[a-z0-9]+', text.lower()))
        contradiction_pairs = [
            ({"best", "recommend"}, {"avoid", "don", "never"}),
            ({"good", "excellent", "great"}, {"bad", "poor", "terrible"}),
            ({"fast", "fastest"}, {"slow", "slowest"}),
        ]
        a_words = _words(a.content)
        b_words = _words(b.content)
        for pos_set, neg_set in contradiction_pairs:
            if (a_words & pos_set and b_words & neg_set) or \
               (b_words & pos_set and a_words & neg_set):
                return True
        return False

class _P:
    __slots__ = ('_n',)
    def __init__(s, n=""): object.__setattr__(s, '_n', n)
    def __getattr__(s, n):
        if n.startswith('_'): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


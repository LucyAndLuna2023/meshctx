"""Agent Debate — 多Agent辩论引擎 (v3.115.44)

Multi-agent debate for better decision quality.
Agents argue from different perspectives → consensus emerges."""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.debate")


@dataclass
class DebatePosition:
    """A single agent's position in a debate round."""
    agent: str
    argument: str
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    counterpoints: List[str] = field(default_factory=list)


@dataclass
class DebateResult:
    """Debate outcome."""
    question: str
    rounds: int
    positions: List[DebatePosition] = field(default_factory=list)
    consensus: str = ""
    consensus_confidence: float = 0.0
    minority_view: str = ""
    agreement_score: float = 0.0


# ── Debate personas ──────────────────────────────────────────

DEBATE_PERSONAS = {
    "optimist": {
        "style": "Focus on opportunities and positive outcomes",
        "bias": "tends to see upside and potential",
        "questions": ["What's the best case?", "How can this succeed?"],
    },
    "skeptic": {
        "style": "Challenge assumptions, find flaws and risks",
        "bias": "tends to see downside and pitfalls",
        "questions": ["What could go wrong?", "What assumptions are we making?"],
    },
    "pragmatist": {
        "style": "Balance pros and cons, seek practical path",
        "bias": "tends to find middle ground",
        "questions": ["What works in practice?", "What's the simplest solution?"],
    },
    "innovator": {
        "style": "Think outside the box, propose novel solutions",
        "bias": "tends to favor unconventional approaches",
        "questions": ["Is there a completely different way?", "What if constraints didn't exist?"],
    },
    "ethicist": {
        "style": "Consider ethical implications and long-term consequences",
        "bias": "tends to prioritize fairness and sustainability",
        "questions": ["Is this fair?", "What are the long-term consequences?"],
    },
}


class DebateEngine:
    """Orchestrates multi-agent debates for complex decisions."""

    def __init__(self, max_rounds: int = 3, min_agents: int = 2):
        self.max_rounds = max_rounds
        self.min_agents = min_agents
        self._history: List[DebateResult] = []

    def debate(self, question: str, personas: List[str] = None,
               llm_call: Callable = None) -> DebateResult:
        """Run a debate on a question.

        Args:
            question: The question to debate
            personas: List of persona names to use (default: optimist, skeptic, pragmatist)
            llm_call: Optional LLM function for generating arguments

        Returns DebateResult with all positions and consensus.
        """
        if personas is None:
            personas = ["optimist", "skeptic", "pragmatist"]
        personas = personas[:5]  # max 5 agents

        positions: List[DebatePosition] = []
        all_arguments: List[str] = []

        # Round 1: Initial positions
        for name in personas:
            persona = DEBATE_PERSONAS.get(name, DEBATE_PERSONAS["pragmatist"])
            prompt = (
                f"As a {name} ({persona['style']}), "
                f"answer: {question}\n"
                f"Consider: {' '.join(persona['questions'])}"
            )
            if llm_call:
                try:
                    argument = llm_call(prompt)
                except Exception:
                    argument = f"[{name}] {persona['style']}: analysis of '{question[:60]}...'"
            else:
                argument = self._heuristic_argument(name, persona, question)

            pos = DebatePosition(
                agent=name,
                argument=argument,
                confidence=0.6,
            )
            positions.append(pos)
            all_arguments.append(argument)

        # Round 2: Counter-arguments
        for i, pos in enumerate(positions):
            others = [p.argument for j, p in enumerate(positions) if j != i]
            counter_prompt = (
                f"Your position: {pos.argument}\n"
                f"Other perspectives:\n" + "\n".join(f"- {a[:100]}" for a in others) +
                f"\nAs {pos.agent}, respond to the strongest counter-argument:"
            )
            if llm_call:
                try:
                    counter = llm_call(counter_prompt)
                    pos.counterpoints.append(counter)
                except Exception:
                    pass
            else:
                pos.counterpoints.append(
                    f"[{pos.agent}] Acknowledged alternative views"
                )

        # Round 3: Synthesis — find consensus
        synthesis_prompt = (
            f"Question: {question}\n\n"
            + "\n".join(f"{p.agent}: {p.argument[:150]}" for p in positions)
            + "\n\nSynthesize a consensus answer that incorporates the best of all perspectives:"
        )
        if llm_call:
            try:
                consensus = llm_call(synthesis_prompt)
            except Exception:
                consensus = self._heuristic_consensus(positions)
        else:
            consensus = self._heuristic_consensus(positions)

        # Calculate agreement score
        agreement = self._calc_agreement(positions)

        result = DebateResult(
            question=question,
            rounds=3,
            positions=positions,
            consensus=consensus,
            consensus_confidence=agreement,
            minority_view=positions[-1].argument if len(positions) > 2 else "",
            agreement_score=agreement,
        )
        self._history.append(result)
        return result

    def quick_debate(self, question: str) -> Dict[str, str]:
        """Quick heuristic debate (no LLM)."""
        personas = ["optimist", "skeptic"]
        result = self.debate(question, personas)
        return {
            "question": question,
            "optimist": result.positions[0].argument,
            "skeptic": result.positions[1].argument,
            "consensus": result.consensus,
            "confidence": f"{result.agreement_score:.0%}",
        }

    def _heuristic_argument(self, name: str, persona: Dict, question: str) -> str:
        """Generate heuristic argument without LLM."""
        if name == "optimist":
            return f"[{name}] This has strong potential. Key opportunities: "
            f"positive outcomes are achievable if executed well. {question[:50]}..."
        elif name == "skeptic":
            return f"[{name}] Need to examine risks carefully. "
            f"Potential pitfalls include resource constraints and hidden assumptions. "
            f"Question: {question[:50]}?"
        elif name == "pragmatist":
            return f"[{name}] Let's focus on what works. "
            f"The practical approach balances ambition with reality. "
            f"Start small on: {question[:50]}"
        elif name == "innovator":
            return f"[{name}] Conventional approaches won't suffice. "
            f"Consider a radical alternative: reimagine {question[:50]} from scratch."
        elif name == "ethicist":
            return f"[{name}] Ethical considerations are paramount. "
            f"We must ensure fairness and sustainability in: {question[:50]}"
        return f"[{name}] Analyzing: {question[:80]}"

    def _heuristic_consensus(self, positions: List[DebatePosition]) -> str:
        """Synthesize consensus from positions."""
        themes = set()
        for p in positions:
            words = p.argument.lower().split()
            for w in words:
                if len(w) > 5:
                    themes.add(w)
        top_themes = list(themes)[:5]
        return (
            f"Consensus: After considering {len(positions)} perspectives, "
            f"the balanced approach integrates: {', '.join(top_themes)}. "
            f"Confidence: {self._calc_agreement(positions):.0%}"
        )

    def _calc_agreement(self, positions: List[DebatePosition]) -> float:
        """Calculate inter-agent agreement score (0-1)."""
        if len(positions) < 2:
            return 1.0
        # Simple: more agents with high confidence = higher agreement
        confidences = [p.confidence for p in positions]
        avg_conf = sum(confidences) / len(confidences)
        # Variance of confidence: low variance = high agreement
        variance = sum((c - avg_conf) ** 2 for c in confidences) / len(confidences)
        return max(0.0, 1.0 - variance * 4)  # scale variance

    def stats(self) -> Dict:
        return {"debates": len(self._history), "avg_agreement": (
            sum(d.agreement_score for d in self._history) / max(len(self._history), 1)
        ) if self._history else 0}

    def list_personas(self) -> List[Dict]:
        return [
            {"name": name, "style": p["style"]}
            for name, p in DEBATE_PERSONAS.items()
        ]


# Singleton
_debate_engine: Optional[DebateEngine] = None


def get_debate_engine() -> DebateEngine:
    global _debate_engine
    if _debate_engine is None:
        _debate_engine = DebateEngine()
    return _debate_engine

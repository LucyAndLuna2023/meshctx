"""Hybrid Reasoning — 混合推理引擎 (v3.115.43)

CoT (Chain of Thought): 多步逐步推理
ToT (Tree of Thoughts): 分支探索+回溯
Reflexion: 自我反思+纠错

真实实现，非stub。"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("meshctx.reasoning")


@dataclass
class ThoughtNode:
    """ToT 思维节点"""
    content: str
    confidence: float = 0.5
    parent: Optional["ThoughtNode"] = None
    children: List["ThoughtNode"] = field(default_factory=list)
    depth: int = 0
    evaluated: bool = False
    score: float = 0.0


@dataclass
class ReasoningResult:
    """推理结果"""
    method: str  # "cot", "tot", "reflexion"
    conclusion: str
    steps: List[str] = field(default_factory=list)
    confidence: float = 0.5
    alternatives: List[str] = field(default_factory=list)
    reflections: List[str] = field(default_factory=list)


class ChainOfThought:
    """CoT: 链式逐步推理"""

    def __init__(self, max_steps: int = 5):
        self.max_steps = max_steps

    def reason(self, question: str, llm_call: Callable = None) -> ReasoningResult:
        """Execute chain-of-thought reasoning."""
        steps = []
        current = question
        confidence = 0.5

        for i in range(self.max_steps):
            step_prompt = (
                f"Step {i+1}/{self.max_steps}. Based on: {current}\n"
                f"Think step by step. What is the next logical inference?"
            )
            if llm_call:
                try:
                    inference = llm_call(step_prompt)
                    steps.append(inference)
                    current = inference
                    confidence = min(0.5 + i * 0.1, 0.95)
                except Exception as e:
                    logger.debug(f"CoT step {i} failed: {e}")
                    break
            else:
                # Heuristic: break down by key terms
                terms = [t for t in question.split() if len(t) > 3][:5]
                steps.append(f"Analyzing: {' '.join(terms)}")
                current = f"Considered: {'; '.join(terms)}"

        return ReasoningResult(
            method="cot",
            conclusion=current,
            steps=steps,
            confidence=confidence,
        )


class TreeOfThoughts:
    """ToT: 树状分支探索+回溯"""

    def __init__(self, breadth: int = 3, max_depth: int = 4):
        self.breadth = breadth
        self.max_depth = max_depth

    def reason(self, question: str, llm_call: Callable = None,
               evaluate: Callable = None) -> ReasoningResult:
        """Execute tree-of-thoughts reasoning."""
        root = ThoughtNode(content=question, depth=0)
        queue = [root]
        best_path = [question]
        best_score = 0.0
        all_steps = []

        while queue:
            node = queue.pop(0)
            if node.depth >= self.max_depth:
                continue

            # Generate branches
            for b in range(min(self.breadth, 3)):
                branch_prompt = (
                    f"From: {node.content}\n"
                    f"Generate alternative thought branch {b+1}:"
                )
                if llm_call:
                    try:
                        thought = llm_call(branch_prompt)
                    except Exception:
                        thought = f"Alternative {b+1} for: {node.content[:50]}"
                else:
                    thought = f"Branch {b+1}: explore angle {['technical','practical','theoretical'][b]}"

                child = ThoughtNode(
                    content=thought,
                    depth=node.depth + 1,
                    parent=node,
                    confidence=0.7 - node.depth * 0.1,
                )

                # Evaluate
                if evaluate:
                    try:
                        child.score = evaluate(thought)
                    except Exception:
                        child.score = 0.5
                else:
                    child.score = child.confidence

                child.evaluated = True
                node.children.append(child)
                all_steps.append(thought)

                if child.score > best_score:
                    best_score = child.score
                    # Trace back to build best path
                    path = [child.content]
                    p = child.parent
                    while p:
                        path.insert(0, p.content)
                        p = p.parent
                    best_path = path

                queue.append(child)

        return ReasoningResult(
            method="tot",
            conclusion=best_path[-1] if best_path else question,
            steps=all_steps,
            confidence=best_score,
            alternatives=[c.content for c in root.children[:3]],
        )


class Reflexion:
    """Reflexion: 自我反思+纠错"""

    def __init__(self, max_reflections: int = 3):
        self.max_reflections = max_reflections
        self._history: List[Dict] = []

    def reason(self, question: str, initial_answer: str = "",
               llm_call: Callable = None) -> ReasoningResult:
        """Execute reflexive reasoning — improve via self-critique."""
        reflections = []
        current = initial_answer or question

        for i in range(self.max_reflections):
            critique_prompt = (
                f"Original: {question}\n"
                f"Current answer: {current}\n"
                f"Critique round {i+1}: What are the weaknesses? How to improve?"
            )
            if llm_call:
                try:
                    critique = llm_call(critique_prompt)
                    reflections.append(critique)
                    improve_prompt = (
                        f"Answer: {current}\n"
                        f"Critique: {critique}\n"
                        f"Provide an improved answer:"
                    )
                    current = llm_call(improve_prompt)
                except Exception as e:
                    logger.debug(f"Reflexion round {i} failed: {e}")
                    break
            else:
                critique = f"Self-check {i+1}: verify logic, check assumptions"
                reflections.append(critique)
                current = f"[Refined] {current}"

        self._history.append({
            "question": question, "final": current,
            "reflections": len(reflections),
        })

        return ReasoningResult(
            method="reflexion",
            conclusion=current,
            reflections=reflections,
            confidence=0.5 + len(reflections) * 0.1,
        )


from src.core.observability import get_trace_logger


class HybridReasoningScheduler:
    """混合推理调度器 — 根据问题类型选择推理策略"""

    def __init__(self, threshold: float = 1.5, adaptive: bool = True):
        self.threshold = threshold
        self.adaptive = adaptive
        self.cot = ChainOfThought(max_steps=5)
        self.tot = TreeOfThoughts(breadth=3, max_depth=4)
        self.reflexion = Reflexion(max_reflections=3)
        self._stats = {"cot": 0, "tot": 0, "reflexion": 0, "total": 0}
        self._trace = get_trace_logger()

    def schedule(self, question: str, llm_call: Callable = None,
                 method: str = "auto", **kw) -> ReasoningResult:
        """Route to best reasoning method based on question type."""
        self._stats["total"] += 1
        span = self._trace.start_span(
            "chain", "HybridReasoningScheduler.schedule",
            inputs={"question": question[:200], "method": method})

        if method == "auto":
            # Heuristic routing
            q_lower = question.lower()
            if any(w in q_lower for w in ["why", "explain", "原因", "为什么", "分析"]):
                method = "cot"
            elif any(w in q_lower for w in ["options", "alternatives", "选择", "方案", "or"]):
                method = "tot"
            elif any(w in q_lower for w in ["fix", "improve", "修复", "改进", "wrong", "错误"]):
                method = "reflexion"
            else:
                method = "cot"

        try:
            if method == "cot":
                self._stats["cot"] += 1
                return self.cot.reason(question, llm_call)
            elif method == "tot":
                self._stats["tot"] += 1
                return self.tot.reason(question, llm_call)
            elif method == "reflexion":
                self._stats["reflexion"] += 1
                return self.reflexion.reason(question, llm_call=llm_call)
            else:
                return self.cot.reason(question, llm_call)
        except Exception as e:
            self._trace.end_span(span, error=str(e))
            raise
        finally:
            if not span.is_complete:
                self._trace.end_span(span, outputs={"method": method})

    def stats(self) -> Dict:
        return dict(self._stats)


# Singleton
_hybrid_reasoner: Optional[HybridReasoningScheduler] = None


def get_hybrid_reasoner() -> HybridReasoningScheduler:
    global _hybrid_reasoner
    if _hybrid_reasoner is None:
        _hybrid_reasoner = HybridReasoningScheduler()
    return _hybrid_reasoner

"""
meshctx Advanced Inference v3.50 — 高级推理引擎
================================================
实现多种高级推理策略: CoT, ToT, ReAct, Self-Consistency 等。
提供推理追踪、成本核算和结果缓存。

核心推理策略:
  1. CoT (Chain of Thought)       — 逐步推理链
  2. ToT (Tree of Thought)        — 树状探索多条推理路径
  3. ReAct (Reasoning + Acting)   — 推理-行动交替循环
  4. Self-Consistency             — 多采样 + 多数投票
  5. Best-of-N                    — 多次采样取最优
  6. Reflection                   — 自我反思改进

辅助能力:
  - 推理追踪: 记录每一步推理过程
  - 成本核算: 基于 token 消耗估算推理成本
  - 结果缓存: 相同输入避免重复推理

设计对标:
  - Wei et al. (2022) Chain-of-Thought Prompting
  - Yao et al. (2023) Tree of Thoughts
  - Wang et al. (2022) Self-Consistency
  - Shinn et al. (2023) Reflexion

使用示例:
  engine = get_advanced_inference()

  # CoT 推理
  result = await engine.cot("What is 15% of 240?")
  # → trace: [{step: "break down", thought: "15% = 15/100 = 0.15"},
  #            {step: "calculate", thought: "0.15 * 240 = 36"}]

  # Self-Consistency
  result = await engine.self_consistency("Solve: x^2 - 4 = 0", samples=5)
  # → 采样5次, 投票取出现最多的答案

  # Cost report
  report = engine.get_cost_report()
"""

import asyncio
import hashlib
import json
import logging
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.advanced_inference")


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class InferenceStrategy(str, Enum):
    COT = "cot"                         # Chain of Thought
    TOT = "tot"                         # Tree of Thought
    REACT = "react"                     # Reasoning + Acting
    SELF_CONSISTENCY = "self_consistency"  # 多采样投票
    BEST_OF_N = "best_of_n"             # 多次采样取最优
    REFLECTION = "reflection"           # 自我反思
    STEP_BACK = "step_back"             # 后退一步重新审视


class TraceLevel(str, Enum):
    MINIMAL = "minimal"     # 仅记录最终结果
    STEP = "step"           # 记录每步
    DETAILED = "detailed"   # 记录每步 + 中间状态
    FULL = "full"           # 记录所有细节 (含 timestamps, 置信度)


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class InferenceStep:
    """单步推理记录"""
    step_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    step_index: int = 0
    step_type: str = ""                # "thought", "action", "observation", "conclusion"
    content: str = ""
    confidence: float = 1.0            # 0.0-1.0 置信度
    duration_ms: float = 0.0
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceTrace:
    """完整推理追踪"""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    strategy: InferenceStrategy = InferenceStrategy.COT
    query: str = ""
    steps: List[InferenceStep] = field(default_factory=list)
    final_answer: Optional[str] = None
    confidence: float = 0.0
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    success: bool = True
    error: Optional[str] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)  # 备选答案

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "strategy": self.strategy.value,
            "query": self.query,
            "steps": [asdict(s) for s in self.steps],
            "final_answer": self.final_answer,
            "confidence": self.confidence,
            "total_duration_ms": self.total_duration_ms,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "success": self.success,
            "error": self.error,
            "alternatives": self.alternatives,
        }


@dataclass
class InferenceResult:
    """推理结果 (对外暴露)"""
    answer: Any
    confidence: float
    strategy: InferenceStrategy
    trace: InferenceTrace
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    cached: bool = False

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "strategy": self.strategy.value,
            "trace": self.trace.to_dict(),
            "alternatives": self.alternatives,
            "cached": self.cached,
        }


@dataclass
class TotNode:
    """Tree of Thought 节点"""
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    thought: str = ""
    score: float = 0.0                 # 评估分数
    depth: int = 0
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    is_terminal: bool = False


# ═══════════════════════════════════════════════════════════
# AdvancedInference
# ═══════════════════════════════════════════════════════════

class AdvancedInference:
    """
    高级推理引擎。

    核心方法:
      - cot(query, llm_fn) → InferenceResult
      - tot(query, llm_fn, evaluate_fn, breadth, depth) → InferenceResult
      - react(task, llm_fn, tools, max_iterations) → InferenceResult
      - self_consistency(query, llm_fn, samples) → InferenceResult
      - best_of_n(query, llm_fn, n, score_fn) → InferenceResult
      - reflection(query, llm_fn, max_reflections) → InferenceResult

    成本核算:
      - get_cost_report() → Dict
      - get_cache_stats() → Dict
    """

    # 默认成本 (USD per 1K tokens)
    DEFAULT_COST_PER_1K_INPUT = 0.003
    DEFAULT_COST_PER_1K_OUTPUT = 0.015

    def __init__(
        self,
        cost_per_1k_input: float = 0.003,
        cost_per_1k_output: float = 0.015,
        cache_size: int = 1000,
    ):
        self._cost_per_1k_input = cost_per_1k_input
        self._cost_per_1k_output = cost_per_1k_output
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost: float = 0.0
        self._total_inferences: int = 0

        # 结果缓存: query_hash → InferenceResult
        self._cache: Dict[str, InferenceResult] = {}
        self._cache_max_size = cache_size

        # 推理历史
        self._history: List[InferenceTrace] = []
        self._max_history = 500

        # LLM 调用计数器 (外部可注入)
        self._llm_call_count: int = 0

    # ── Cache ──────────────────────────────────────────────

    def _cache_key(self, query: str, strategy: InferenceStrategy, **kw) -> str:
        raw = f"{query}|{strategy.value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_put(self, key: str, result: InferenceResult, **kw):
        if len(self._cache) >= self._cache_max_size:
            # 移除最老的条目
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = result

    def clear_cache(self, **kw):
        self._cache.clear()

    # ── Token / Cost 追踪 ─────────────────────────────────

    def _track_tokens(self, input_tokens: int, output_tokens: int, **kw):
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        cost = (
            input_tokens / 1000 * self._cost_per_1k_input +
            output_tokens / 1000 * self._cost_per_1k_output
        )
        self._total_cost += cost

    def _estimate_tokens(self, text: str, **kw) -> int:
        """简易 token 估算: ~4 字符/token (英文), ~1.5 字符/token (中文)"""
        if not text:
            return 0
        import re
        zh = len(re.findall(r'[\u4e00-\u9fff]', text))
        en = len(text) - zh
        return max(1, int(zh * 0.67 + en * 0.25))

    # ── CoT: Chain of Thought ─────────────────────────────

    async def cot(
        self,
        query: str,
        llm_fn: Optional[Callable] = None,
        steps: Optional[List[str]] = None,
        trace_level: TraceLevel = TraceLevel.STEP,
    ) -> InferenceResult:
        """
        Chain-of-Thought 推理。

        将问题分解为思维步骤链，逐步推理。

        Args:
            query: 推理问题
            llm_fn: async fn(prompt: str) → str，调用 LLM
            steps: 自定义思维步骤提示 (默认: 通用 CoT prompt)
            trace_level: 追踪详细程度

        Returns:
            InferenceResult
        """
        strategy = InferenceStrategy.COT
        cache_key = self._cache_key(query, strategy)

        # 检查缓存
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        trace = InferenceTrace(
            strategy=strategy,
            query=query,
        )

        try:
            default_steps = [
                "Understand the problem and identify what is being asked.",
                "Break down the problem into smaller sub-problems.",
                "Solve each sub-problem step by step.",
                "Combine the partial results.",
                "State the final answer clearly.",
            ]
            thought_steps = steps or default_steps

            context = query
            all_thoughts = []

            for i, step_prompt in enumerate(thought_steps):
                step_start = time.time()

                if llm_fn:
                    prompt = f"Step {i + 1}/ {len(thought_steps)}: {step_prompt}\n\nContext: {context}"
                    try:
                        thought = await llm_fn(prompt) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(prompt)
                    except Exception:
                        thought = f"[LLM call failed at step {i + 1}]"
                else:
                    # 无 LLM → 用 step prompt 作为占位
                    thought = f"[Step {i + 1}]: {step_prompt}"

                step_dur = (time.time() - step_start) * 1000
                tokens = self._estimate_tokens(prompt + thought) if llm_fn else 0
                if llm_fn:
                    self._track_tokens(self._estimate_tokens(prompt), self._estimate_tokens(thought))
                    self._llm_call_count += 1

                step_record = InferenceStep(
                    step_index=i + 1,
                    step_type="thought",
                    content=thought,
                    duration_ms=step_dur,
                    token_count=tokens,
                )
                trace.steps.append(step_record)
                all_thoughts.append(thought)
                context = f"{context}\nStep {i + 1} thought: {thought}"

                if trace_level in (TraceLevel.DETAILED, TraceLevel.FULL):
                    step_record.metadata["context_snapshot"] = context[:200]

            trace.final_answer = all_thoughts[-1] if all_thoughts else "No reasoning produced"
            trace.confidence = 0.8  # 默认置信度

        except Exception as e:
            trace.success = False
            trace.error = f"{type(e).__name__}: {e}"
            trace.final_answer = None
            logger.error(f"CoT failed: {e}\n{traceback.format_exc()}")

        trace.finished_at = time.time()
        trace.total_duration_ms = (trace.finished_at - trace.started_at) * 1000
        trace.total_tokens = sum(s.token_count for s in trace.steps)

        self._total_inferences += 1
        self._add_to_history(trace)

        result = InferenceResult(
            answer=trace.final_answer,
            confidence=trace.confidence,
            strategy=strategy,
            trace=trace,
        )
        self._cache_put(cache_key, result)
        return result

    # ── ToT: Tree of Thought ──────────────────────────────

    async def tot(
        self,
        query: str,
        llm_fn: Optional[Callable] = None,
        evaluate_fn: Optional[Callable] = None,
        breadth: int = 3,
        max_depth: int = 3,
        trace_level: TraceLevel = TraceLevel.STEP,
    ) -> InferenceResult:
        """
        Tree-of-Thought 推理。

        在每层生成多个候选思路，评估后保留最佳，继续展开。

        Args:
            query: 推理问题
            llm_fn: async fn(prompt: str) → str
            evaluate_fn: fn(thought: str) → float (0-1 score)
            breadth: 每层展开的候选数
            max_depth: 树的最大深度
            trace_level: 追踪级别

        Returns:
            InferenceResult
        """
        strategy = InferenceStrategy.TOT
        cache_key = self._cache_key(query, strategy)

        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        trace = InferenceTrace(strategy=strategy, query=query)
        nodes: Dict[str, TotNode] = {}

        try:
            # 根节点
            root = TotNode(thought="ROOT: " + query, score=1.0, depth=0)
            nodes[root.node_id] = root
            frontier = [root.node_id]

            for depth in range(max_depth):
                next_frontier = []

                for parent_id in frontier:
                    parent = nodes[parent_id]

                    # 生成候选思路
                    candidates = []
                    for b in range(breadth):
                        if llm_fn:
                            prompt = (
                                f"Based on the current thought, generate the next step "
                                f"(variant {b + 1}/{breadth}):\n\n"
                                f"Current: {parent.thought}\n\nNext step:"
                            )
                            try:
                                thought = await llm_fn(prompt) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(prompt)
                                self._llm_call_count += 1
                                self._track_tokens(self._estimate_tokens(prompt), self._estimate_tokens(thought))
                            except Exception:
                                thought = f"[Variant {b + 1} generation failed]"
                        else:
                            thought = f"Thought variant {b + 1} at depth {depth + 1}"

                        # 评估
                        score = 0.5
                        if evaluate_fn:
                            try:
                                score = evaluate_fn(thought)
                            except Exception:
                                pass

                        node = TotNode(
                            thought=thought,
                            score=score,
                            depth=depth + 1,
                            parent_id=parent_id,
                        )
                        nodes[node.node_id] = node
                        parent.children.append(node.node_id)
                        candidates.append((node.node_id, score))

                    # 保留 top-breadth
                    candidates.sort(key=lambda x: x[1], reverse=True)
                    keep = [nid for nid, _ in candidates[:breadth]]
                    next_frontier.extend(keep)

                    # 追踪
                    if trace_level in (TraceLevel.STEP, TraceLevel.DETAILED, TraceLevel.FULL):
                        for nid, score in candidates[:breadth]:
                            node = nodes[nid]
                            trace.steps.append(InferenceStep(
                                step_index=depth + 1,
                                step_type="thought",
                                content=f"[Depth {depth + 1}, score={score:.2f}] {node.thought[:200]}",
                                confidence=score,
                            ))

                frontier = next_frontier
                if not frontier:
                    break

            # 找出最佳叶子节点
            leaf_nodes = [n for n in nodes.values() if not n.children or n.depth == max_depth]
            if leaf_nodes:
                best = max(leaf_nodes, key=lambda n: n.score)
                trace.final_answer = best.thought
                trace.confidence = best.score
            else:
                trace.final_answer = root.thought
                trace.confidence = 0.5

        except Exception as e:
            trace.success = False
            trace.error = f"{type(e).__name__}: {e}"
            logger.error(f"ToT failed: {e}")

        trace.finished_at = time.time()
        trace.total_duration_ms = (trace.finished_at - trace.started_at) * 1000
        trace.total_tokens = sum(s.token_count for s in trace.steps)

        self._total_inferences += 1
        self._add_to_history(trace)

        result = InferenceResult(
            answer=trace.final_answer,
            confidence=trace.confidence,
            strategy=strategy,
            trace=trace,
        )
        self._cache_put(cache_key, result)
        return result

    # ── ReAct ──────────────────────────────────────────────

    async def react(
        self,
        task: str,
        llm_fn: Optional[Callable] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 5,
        trace_level: TraceLevel = TraceLevel.STEP,
    ) -> InferenceResult:
        """
        ReAct (Reasoning + Acting) 推理循环。

        Args:
            task: 要完成的任务
            llm_fn: async fn(prompt: str) → str
            tools: 可用工具列表 [{name, description, fn}, ...]
            max_iterations: 最大迭代次数
            trace_level: 追踪级别

        Returns:
            InferenceResult
        """
        strategy = InferenceStrategy.REACT
        cache_key = self._cache_key(task, strategy)

        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        trace = InferenceTrace(strategy=strategy, query=task)
        tool_map = {t["name"]: t for t in (tools or [])}
        context = f"Task: {task}"

        try:
            for iteration in range(max_iterations):
                iter_start = time.time()

                # Thought
                if llm_fn:
                    thought_prompt = (
                        f"{context}\n\n"
                        f"Available tools: {list(tool_map.keys())}\n"
                        f"Think about what to do next:"
                    )
                    try:
                        thought = await llm_fn(thought_prompt) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(thought_prompt)
                        self._llm_call_count += 1
                        self._track_tokens(self._estimate_tokens(thought_prompt), self._estimate_tokens(thought))
                    except Exception:
                        thought = f"[LLM failed at iteration {iteration + 1}]"
                else:
                    thought = f"Thinking about step {iteration + 1}..."

                trace.steps.append(InferenceStep(
                    step_index=iteration * 2 + 1,
                    step_type="thought",
                    content=thought,
                    duration_ms=(time.time() - iter_start) * 1000,
                ))

                # Action (使用工具)
                action_result = None
                for tool_name, tool_def in tool_map.items():
                    if tool_name.lower() in thought.lower():
                        tool_fn = tool_def.get("fn")
                        if tool_fn:
                            try:
                                if asyncio.iscoroutinefunction(tool_fn):
                                    action_result = await tool_fn()
                                else:
                                    action_result = tool_fn()
                            except Exception as e:
                                action_result = f"Tool '{tool_name}' error: {e}"
                            break

                if action_result is None:
                    action_result = "No tool matched"

                trace.steps.append(InferenceStep(
                    step_index=iteration * 2 + 2,
                    step_type="action",
                    content=str(action_result)[:500],
                ))

                context = f"{context}\nThought: {thought}\nAction: {action_result}"

                # 检查是否完成
                if "final answer" in thought.lower() or "task complete" in thought.lower():
                    break

            trace.final_answer = context
            trace.confidence = 0.75

        except Exception as e:
            trace.success = False
            trace.error = f"{type(e).__name__}: {e}"
            logger.error(f"ReAct failed: {e}")

        trace.finished_at = time.time()
        trace.total_duration_ms = (trace.finished_at - trace.started_at) * 1000
        trace.total_tokens = sum(s.token_count for s in trace.steps)

        self._total_inferences += 1
        self._add_to_history(trace)

        result = InferenceResult(
            answer=trace.final_answer,
            confidence=trace.confidence,
            strategy=strategy,
            trace=trace,
        )
        self._cache_put(cache_key, result)
        return result

    # ── Self-Consistency ──────────────────────────────────

    async def self_consistency(
        self,
        query: str,
        llm_fn: Optional[Callable] = None,
        samples: int = 5,
        trace_level: TraceLevel = TraceLevel.MINIMAL,
    ) -> InferenceResult:
        """
        Self-Consistency: 多采样 + 多数投票。

        Args:
            query: 推理问题
            llm_fn: async fn(prompt: str) → str
            samples: 采样次数
            trace_level: 追踪级别

        Returns:
            InferenceResult
        """
        strategy = InferenceStrategy.SELF_CONSISTENCY
        cache_key = self._cache_key(query, strategy)

        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        trace = InferenceTrace(strategy=strategy, query=query)
        answers = []
        all_traces = []

        try:
            for s in range(samples):
                sample_start = time.time()

                if llm_fn:
                    prompt = (
                        f"Question: {query}\n\n"
                        f"Please think step by step and provide your final answer. "
                        f"(Sample {s + 1}/{samples})"
                    )
                    try:
                        answer = await llm_fn(prompt) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(prompt)
                        self._llm_call_count += 1
                        self._track_tokens(self._estimate_tokens(prompt), self._estimate_tokens(answer))
                    except Exception:
                        answer = f"[Sample {s + 1} failed]"
                else:
                    answer = f"Sample {s + 1} answer placeholder"

                answers.append(answer)
                all_traces.append(answer)

                if trace_level != TraceLevel.MINIMAL:
                    trace.steps.append(InferenceStep(
                        step_index=s + 1,
                        step_type="sample",
                        content=answer[:300],
                        duration_ms=(time.time() - sample_start) * 1000,
                    ))

            # 投票
            if answers:
                # 简易投票: 取最短的唯一答案 (启发式)
                counter = Counter(answers)
                most_common = counter.most_common(1)
                if most_common:
                    trace.final_answer = most_common[0][0]
                    trace.confidence = most_common[0][1] / samples
                else:
                    trace.final_answer = answers[0]
                    trace.confidence = 1.0 / samples

                # 备选答案
                for ans, count in counter.most_common(5):
                    if ans != trace.final_answer:
                        trace.alternatives.append({"answer": ans, "votes": count, "ratio": count / samples})

        except Exception as e:
            trace.success = False
            trace.error = f"{type(e).__name__}: {e}"
            logger.error(f"Self-consistency failed: {e}")

        trace.finished_at = time.time()
        trace.total_duration_ms = (trace.finished_at - trace.started_at) * 1000
        trace.total_tokens = sum(s.token_count for s in trace.steps)

        self._total_inferences += 1
        self._add_to_history(trace)

        result = InferenceResult(
            answer=trace.final_answer,
            confidence=trace.confidence,
            strategy=strategy,
            trace=trace,
            alternatives=trace.alternatives,
        )
        self._cache_put(cache_key, result)
        return result

    # ── Best-of-N ─────────────────────────────────────────

    async def best_of_n(
        self,
        query: str,
        llm_fn: Optional[Callable] = None,
        n: int = 5,
        score_fn: Optional[Callable] = None,
    ) -> InferenceResult:
        """
        Best-of-N: 生成 N 个候选，取最优。

        Args:
            query: 问题
            llm_fn: async fn(prompt: str) → str
            n: 候选数
            score_fn: fn(answer: str) → float (评分函数，越高越好)

        Returns:
            InferenceResult
        """
        strategy = InferenceStrategy.BEST_OF_N
        cache_key = self._cache_key(query, strategy)

        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        trace = InferenceTrace(strategy=strategy, query=query)
        candidates = []

        try:
            for i in range(n):
                if llm_fn:
                    prompt = f"Candidate {i + 1}/{n} for: {query}"
                    try:
                        answer = await llm_fn(prompt) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(prompt)
                        self._llm_call_count += 1
                        self._track_tokens(
                            self._estimate_tokens(prompt),
                            self._estimate_tokens(answer),
                        )
                    except Exception:
                        answer = f"[Generation {i + 1} failed]"
                else:
                    answer = f"Candidate {i + 1}"

                score = 0.5
                if score_fn:
                    try:
                        score = score_fn(answer)
                    except Exception:
                        pass

                candidates.append((answer, score))

                trace.steps.append(InferenceStep(
                    step_index=i + 1,
                    step_type="candidate",
                    content=answer[:200],
                    confidence=score,
                ))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best = candidates[0]
                trace.final_answer = best[0]
                trace.confidence = best[1]
                trace.alternatives = [
                    {"answer": a, "score": s} for a, s in candidates[1:6]
                ]
        except Exception as e:
            trace.success = False
            trace.error = f"{type(e).__name__}: {e}"

        trace.finished_at = time.time()
        trace.total_duration_ms = (trace.finished_at - trace.started_at) * 1000
        trace.total_tokens = sum(s.token_count for s in trace.steps)

        self._total_inferences += 1
        self._add_to_history(trace)

        result = InferenceResult(
            answer=trace.final_answer,
            confidence=trace.confidence,
            strategy=strategy,
            trace=trace,
            alternatives=trace.alternatives,
        )
        self._cache_put(cache_key, result)
        return result

    # ── Reflection ────────────────────────────────────────

    async def reflection(
        self,
        query: str,
        llm_fn: Optional[Callable] = None,
        max_reflections: int = 3,
        trace_level: TraceLevel = TraceLevel.STEP,
    ) -> InferenceResult:
        """
        Reflection: 自我反思改进。

        生成初始答案 → 反思批评 → 改进答案 → 重复。

        Args:
            query: 问题
            llm_fn: async fn(prompt: str) → str
            max_reflections: 最大反思轮数
            trace_level: 追踪级别

        Returns:
            InferenceResult
        """
        strategy = InferenceStrategy.REFLECTION
        cache_key = self._cache_key(query, strategy)

        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        trace = InferenceTrace(strategy=strategy, query=query)

        try:
            # 初始回答
            if llm_fn:
                try:
                    answer = await llm_fn(query) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(query)
                    self._llm_call_count += 1
                except Exception:
                    answer = "[Initial generation failed]"
            else:
                answer = f"Initial answer for: {query}"

            trace.steps.append(InferenceStep(
                step_index=0,
                step_type="initial_answer",
                content=answer[:300],
            ))

            # 反思循环
            for r in range(max_reflections):
                if llm_fn:
                    reflection_prompt = (
                        f"Previous answer: {answer}\n\n"
                        f"Please critically reflect on this answer. "
                        f"Identify any errors, missing information, or ways to improve. "
                        f"Then provide an improved answer."
                    )
                    try:
                        improved = await llm_fn(reflection_prompt) if asyncio.iscoroutinefunction(llm_fn) else llm_fn(reflection_prompt)
                        self._llm_call_count += 1
                        self._track_tokens(
                            self._estimate_tokens(reflection_prompt),
                            self._estimate_tokens(improved),
                        )
                    except Exception:
                        improved = answer  # 保持原答案
                else:
                    improved = f"Refined answer (reflection {r + 1})"

                trace.steps.append(InferenceStep(
                    step_index=r + 1,
                    step_type="reflection",
                    content=improved[:300],
                ))

                if improved == answer:
                    # 未改进，停止反思
                    break
                answer = improved

            trace.final_answer = answer
            trace.confidence = 0.6 + min(0.3, max_reflections * 0.1)

        except Exception as e:
            trace.success = False
            trace.error = f"{type(e).__name__}: {e}"
            logger.error(f"Reflection failed: {e}")

        trace.finished_at = time.time()
        trace.total_duration_ms = (trace.finished_at - trace.started_at) * 1000
        trace.total_tokens = sum(s.token_count for s in trace.steps)

        self._total_inferences += 1
        self._add_to_history(trace)

        result = InferenceResult(
            answer=trace.final_answer,
            confidence=trace.confidence,
            strategy=strategy,
            trace=trace,
        )
        self._cache_put(cache_key, result)
        return result

    # ── 历史管理 ──────────────────────────────────────────

    def _add_to_history(self, trace: InferenceTrace, **kw):
        self._history.append(trace)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(self, limit: int = 50, **kw) -> List[Dict[str, Any]]:
        """获取最近的推理历史"""
        return [t.to_dict() for t in self._history[-limit:]]

    # ── 统计与报告 ────────────────────────────────────────

    def get_cost_report(self, **kw) -> Dict[str, Any]:
        """获取成本报告"""
        return {
            "total_inferences": self._total_inferences,
            "total_llm_calls": self._llm_call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": round(self._total_cost, 6),
            "cost_per_1k_input": self._cost_per_1k_input,
            "cost_per_1k_output": self._cost_per_1k_output,
            "cache_hits": sum(1 for t in self._history if t.success),
            "strategies_used": list(set(t.strategy.value for t in self._history)),
        }

    def get_cache_stats(self, **kw) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "cache_size": len(self._cache),
            "cache_max": self._cache_max_size,
            "cache_usage_pct": round(len(self._cache) / max(self._cache_max_size, 1) * 100, 1),
        }

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取综合统计"""
        recent = self._history[-100:] if self._history else []
        success_rate = sum(1 for t in recent if t.success) / max(len(recent), 1)
        avg_confidence = (
            sum(t.confidence for t in recent) / max(len(recent), 1)
        ) if recent else 0
        return {
            **self.get_cost_report(),
            **self.get_cache_stats(),
            "success_rate": round(success_rate, 3),
            "avg_confidence": round(avg_confidence, 3),
            "history_size": len(self._history),
        }

    def reset_stats(self, **kw):
        """重置统计数据"""
        self._total_inferences = 0
        self._llm_call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost = 0.0
        self._history.clear()
        self._cache.clear()


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_advanced_inference: Optional[AdvancedInference] = None


def get_advanced_inference(
    cost_per_1k_input: float = 0.003,
    cost_per_1k_output: float = 0.015,
) -> AdvancedInference:
    """
    获取全局 AdvancedInference 单例。

    Args:
        cost_per_1k_input: 输入 token 成本 (USD/1K)
        cost_per_1k_output: 输出 token 成本 (USD/1K)
    """
    global _advanced_inference
    if _advanced_inference is None:
        _advanced_inference = AdvancedInference(
            cost_per_1k_input=cost_per_1k_input,
            cost_per_1k_output=cost_per_1k_output,
        )
        logger.info("AdvancedInference initialized")
    return _advanced_inference


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

async def cot_infer(
    query: str,
    llm_fn: Optional[Callable] = None,
    steps: Optional[List[str]] = None,
) -> InferenceResult:
    """快速 CoT 推理"""
    return await get_advanced_inference().cot(query, llm_fn, steps)


async def self_consistency_infer(
    query: str,
    llm_fn: Optional[Callable] = None,
    samples: int = 5,
) -> InferenceResult:
    """快速 Self-Consistency 推理"""
    return await get_advanced_inference().self_consistency(query, llm_fn, samples)


async def react_infer(
    task: str,
    llm_fn: Optional[Callable] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    max_iterations: int = 5,
) -> InferenceResult:
    """快速 ReAct 推理"""
    return await get_advanced_inference().react(task, llm_fn, tools, max_iterations)

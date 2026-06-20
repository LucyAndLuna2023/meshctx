"""
meshctx Chain Engine v3.50 — 链式推理执行引擎
=============================================
提供 Chain/Step 抽象层，支持顺序执行、条件分支、错误恢复，
以及 CoT / ReAct / Plan-Execute 等多种推理模式。

核心概念:
  - Step: 最小的推理/工具调用单元，可配置重试、跳过策略
  - Chain: 有序 Step 序列，支持中间结果传递和条件跳转
  - 内置三种推理模式: chain_of_thought, react, plan_execute

设计对标:
  - LangChain 的 Chain/Agent 概念
  - Hermes Agent 的工具链执行
  - AutoGPT 的 step-by-step 执行循环

使用示例:
  engine = get_chain_engine()

  # 顺序链
  chain = engine.create_chain("my_chain")
  chain.add_step("parse", parse_fn)
  chain.add_step("analyze", analyze_fn, depends_on=["parse"])
  result = await chain.run(context={"text": "hello"})

  # ReAct 模式
  result = await engine.react_loop("找出最大的文件", tools=[...])

  # Plan-Execute 模式
  result = await engine.plan_execute("重构代码库的安全性")
"""

import asyncio
import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.chain_engine")


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class ChainMode(str, Enum):
    SEQUENTIAL = "sequential"        # 严格顺序执行
    CONDITIONAL = "conditional"      # 带条件分支
    PARALLEL = "parallel"            # 无依赖步骤并行
    CHAIN_OF_THOUGHT = "cot"         # Chain of Thought
    REACT = "react"                  # Reasoning + Acting
    PLAN_EXECUTE = "plan_execute"    # 先规划再执行


class ErrorPolicy(str, Enum):
    RETRY = "retry"         # 重试后继续
    SKIP = "skip"           # 跳过该步骤
    ABORT = "abort"         # 中止整条链
    FALLBACK = "fallback"   # 使用回退步骤


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class StepResult:
    """单步执行结果"""
    step_id: str
    step_name: str
    status: StepStatus = StepStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    retry_count: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Step:
    """链中的单个执行步骤"""
    step_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    fn: Optional[Callable] = None                 # async callable(ctx) → result
    depends_on: List[str] = field(default_factory=list)  # 前置 step_id 列表
    max_retries: int = 2
    retry_delay: float = 0.5
    skip_on_error: bool = False                   # True 时失败后跳过而非中止
    fallback_fn: Optional[Callable] = None        # 失败回退函数
    timeout: float = 60.0                         # 步骤超时 (秒)
    condition: Optional[Callable] = None          # 条件函数(chain_ctx)→bool，False 则跳过
    tags: List[str] = field(default_factory=list)


@dataclass
class ChainDefinition:
    """链定义 — 描述一条完整的执行链"""
    chain_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    mode: ChainMode = ChainMode.SEQUENTIAL
    steps: List[Step] = field(default_factory=list)
    global_timeout: float = 300.0         # 整链超时
    default_error_policy: ErrorPolicy = ErrorPolicy.RETRY
    context_schema: Dict[str, Any] = field(default_factory=dict)  # 预期的上下文键
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChainRunResult:
    """链执行完整结果"""
    chain_id: str
    chain_name: str
    mode: ChainMode
    step_results: List[StepResult] = field(default_factory=list)
    final_output: Any = None
    total_duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "mode": self.mode.value,
            "step_results": [sr.to_dict() for sr in self.step_results],
            "final_output": self.final_output,
            "total_duration_ms": self.total_duration_ms,
            "success": self.success,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════
# ChainEngine
# ═══════════════════════════════════════════════════════════

class ChainEngine:
    """
    链式推理执行引擎。

    核心方法:
      - create_chain(name) → ChainDefinition
      - run(chain, context) → ChainRunResult
      - execute_step(step, context) → StepResult
      - chain_of_thought(question, context) → ChainRunResult
      - react_loop(task, tools, max_iterations) → ChainRunResult
      - plan_execute(goal, tools, context) → ChainRunResult
    """

    def __init__(self):
        self._chains: Dict[str, ChainDefinition] = {}
        self._run_history: List[ChainRunResult] = []
        self._max_history: int = 200
        self._total_runs: int = 0
        self._total_errors: int = 0

    # ── Chain 管理 ─────────────────────────────────────────

    def create_chain(
        self,
        name: str,
        description: str = "",
        mode: ChainMode = ChainMode.SEQUENTIAL,
        global_timeout: float = 300.0,
        default_error_policy: ErrorPolicy = ErrorPolicy.RETRY,
    ) -> ChainDefinition:
        """创建新的链定义"""
        chain = ChainDefinition(
            name=name,
            description=description,
            mode=mode,
            global_timeout=global_timeout,
            default_error_policy=default_error_policy,
        )
        self._chains[chain.chain_id] = chain
        logger.debug(f"Created chain '{name}' (id={chain.chain_id}, mode={mode.value})")
        return chain

    def get_chain(self, chain_id: str) -> Optional[ChainDefinition]:
        """获取链定义"""
        return self._chains.get(chain_id)

    def delete_chain(self, chain_id: str) -> bool:
        """删除链定义"""
        if chain_id in self._chains:
            del self._chains[chain_id]
            return True
        return False

    def list_chains(self) -> List[Dict[str, Any]]:
        """列出所有链"""
        return [
            {
                "chain_id": c.chain_id,
                "name": c.name,
                "mode": c.mode.value,
                "step_count": len(c.steps),
                "description": c.description,
            }
            for c in self._chains.values()
        ]

    def add_step(
        self,
        chain_id: str,
        name: str,
        fn: Callable,
        depends_on: Optional[List[str]] = None,
        max_retries: int = 2,
        skip_on_error: bool = False,
        timeout: float = 60.0,
        description: str = "",
        condition: Optional[Callable] = None,
        fallback_fn: Optional[Callable] = None,
    ) -> Optional[Step]:
        """向链中添加步骤"""
        chain = self._chains.get(chain_id)
        if not chain:
            logger.error(f"Chain '{chain_id}' not found")
            return None
        step = Step(
            name=name,
            description=description,
            fn=fn,
            depends_on=depends_on or [],
            max_retries=max_retries,
            skip_on_error=skip_on_error,
            timeout=timeout,
            condition=condition,
            fallback_fn=fallback_fn,
        )
        chain.steps.append(step)
        logger.debug(f"Added step '{name}' to chain '{chain.name}'")
        return step

    # ── 步骤执行 ───────────────────────────────────────────

    async def execute_step(
        self, step: Step, context: Dict[str, Any]
    ) -> StepResult:
        """
        执行单个步骤，包含重试和错误处理。

        Args:
            step: 要执行的步骤
            context: 执行上下文 (包含前面步骤的输出)

        Returns:
            StepResult 包含状态、输出或错误
        """
        result = StepResult(
            step_id=step.step_id,
            step_name=step.name,
            status=StepStatus.PENDING,
        )

        # 检查条件
        if step.condition:
            try:
                should_run = step.condition(context)
                if not should_run:
                    result.status = StepStatus.SKIPPED
                    result.output = None
                    logger.debug(f"Step '{step.name}' skipped by condition")
                    return result
            except Exception as e:
                logger.warning(f"Condition check failed for step '{step.name}': {e}")

        if step.fn is None:
            result.status = StepStatus.SUCCESS
            result.output = None
            return result

        result.started_at = time.time()
        last_error = None

        for attempt in range(step.max_retries + 1):
            try:
                result.status = StepStatus.RUNNING if attempt == 0 else StepStatus.RETRYING
                result.retry_count = attempt

                # 带超时执行
                task = step.fn(context)
                if asyncio.iscoroutine(task):
                    output = await asyncio.wait_for(task, timeout=step.timeout)
                elif asyncio.iscoroutinefunction(step.fn):
                    output = await asyncio.wait_for(step.fn(context), timeout=step.timeout)
                else:
                    output = task

                result.status = StepStatus.SUCCESS
                result.output = output
                result.finished_at = time.time()
                result.duration_ms = (result.finished_at - result.started_at) * 1000
                return result

            except asyncio.TimeoutError:
                last_error = f"Step '{step.name}' timed out after {step.timeout}s"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"Step '{step.name}' failed (attempt {attempt + 1}/{step.max_retries + 1}): {e}"
                )

            if attempt < step.max_retries:
                await asyncio.sleep(step.retry_delay)
            else:
                break

        # 所有重试均失败
        result.status = StepStatus.FAILED
        result.error = last_error
        result.finished_at = time.time()
        result.duration_ms = (result.finished_at - result.started_at) * 1000

        # 尝试回退
        if step.fallback_fn and not step.skip_on_error:
            try:
                logger.info(f"Executing fallback for step '{step.name}'")
                fallback_output = step.fallback_fn(context)
                if asyncio.iscoroutine(fallback_output):
                    fallback_output = await fallback_output
                result.output = fallback_output
                result.status = StepStatus.SUCCESS
                result.error = None
            except Exception as fe:
                logger.error(f"Fallback also failed for step '{step.name}': {fe}")

        return result

    # ── 链执行 ─────────────────────────────────────────────

    async def run(
        self,
        chain: ChainDefinition,
        context: Optional[Dict[str, Any]] = None,
    ) -> ChainRunResult:
        """
        执行完整链。

        Args:
            chain: 链定义
            context: 初始上下文

        Returns:
            ChainRunResult
        """
        self._total_runs += 1
        ctx = dict(context or {})
        ctx["_chain_id"] = chain.chain_id
        ctx["_chain_name"] = chain.name

        run_result = ChainRunResult(
            chain_id=chain.chain_id,
            chain_name=chain.name,
            mode=chain.mode,
        )
        run_result.started_at = time.time()

        try:
            # 按模式分发
            if chain.mode == ChainMode.SEQUENTIAL:
                await self._run_sequential(chain, ctx, run_result)
            elif chain.mode == ChainMode.CONDITIONAL:
                await self._run_sequential(chain, ctx, run_result)
            elif chain.mode == ChainMode.PARALLEL:
                await self._run_parallel(chain, ctx, run_result)
            else:
                await self._run_sequential(chain, ctx, run_result)

            # 聚合最终输出
            if run_result.step_results:
                last_ok = None
                for sr in reversed(run_result.step_results):
                    if sr.ok and sr.output is not None:
                        last_ok = sr.output
                        break
                run_result.final_output = last_ok
            else:
                run_result.final_output = ctx

            run_result.success = all(sr.ok for sr in run_result.step_results)

        except asyncio.TimeoutError:
            run_result.success = False
            run_result.error = f"Chain timed out after {chain.global_timeout}s"
            self._total_errors += 1
        except Exception as e:
            run_result.success = False
            run_result.error = f"{type(e).__name__}: {e}"
            self._total_errors += 1
            logger.error(f"Chain '{chain.name}' failed: {e}\n{traceback.format_exc()}")

        run_result.finished_at = time.time()
        run_result.total_duration_ms = (run_result.finished_at - run_result.started_at) * 1000

        self._add_to_history(run_result)
        return run_result

    async def _run_sequential(
        self,
        chain: ChainDefinition,
        ctx: Dict[str, Any],
        run_result: ChainRunResult,
    ):
        """顺序执行步骤"""
        for step in chain.steps:
            sr = await self.execute_step(step, ctx)
            run_result.step_results.append(sr)

            # 将输出写入上下文供后续步骤使用
            if sr.ok and sr.output is not None:
                ctx[step.name] = sr.output

            # 错误处理
            if sr.status == StepStatus.FAILED:
                if step.skip_on_error or chain.default_error_policy == ErrorPolicy.SKIP:
                    sr.status = StepStatus.SKIPPED
                    logger.info(f"Step '{step.name}' skipped due to error policy")
                elif chain.default_error_policy == ErrorPolicy.ABORT:
                    run_result.error = sr.error or f"Aborted at step '{step.name}'"
                    logger.warning(f"Chain aborted at step '{step.name}'")
                    break

    async def _run_parallel(
        self,
        chain: ChainDefinition,
        ctx: Dict[str, Any],
        run_result: ChainRunResult,
    ):
        """并行执行无依赖的步骤"""
        # 按依赖关系分组: 无依赖的步骤可并行
        completed = set()
        remaining = list(chain.steps)

        while remaining:
            # 找出所有依赖已满足的步骤
            ready = [
                s for s in remaining
                if all(d in completed for d in s.depends_on)
            ]

            if not ready:
                # 死锁检测: 有剩余步骤但依赖无法满足
                stuck = [s.name for s in remaining]
                run_result.error = f"Dependency deadlock: steps {stuck} have unsatisfied dependencies"
                break

            # 并行执行就绪步骤
            tasks = [self.execute_step(s, ctx) for s in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(ready, results):
                if isinstance(result, Exception):
                    sr = StepResult(
                        step_id=step.step_id,
                        step_name=step.name,
                        status=StepStatus.FAILED,
                        error=str(result),
                    )
                else:
                    sr = result
                    if sr.ok and sr.output is not None:
                        ctx[step.name] = sr.output

                run_result.step_results.append(sr)
                completed.add(step.step_id)

            remaining = [s for s in remaining if s.step_id not in completed]

    # ── 推理模式 ───────────────────────────────────────────

    async def chain_of_thought(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        thought_steps: Optional[List[str]] = None,
        step_timeout: float = 30.0,
    ) -> ChainRunResult:
        """
        Chain-of-Thought 推理模式。

        将问题分解为思考步骤序列，逐步推理得到最终答案。
        """
        chain = self.create_chain(
            name=f"cot_{uuid.uuid4().hex[:6]}",
            description=f"CoT: {question[:60]}",
            mode=ChainMode.SEQUENTIAL,
            global_timeout=step_timeout * 10,
        )

        steps = thought_steps or ["analyze", "decompose", "reason", "synthesize", "conclude"]
        ctx = dict(context or {})
        ctx["_original_question"] = question
        ctx["_thought_chain"] = []

        for i, step_name in enumerate(steps):
            async def cot_step_fn(ctx_inner, _sn=step_name, _idx=i):
                """CoT 推理步骤 — 由外部 LLM 调用填充"""
                # 此函数由外部通过上下文注入实际推理逻辑
                # 内置只做基本的上下文传递
                thought = ctx_inner.get(f"_thought_{_sn}", f"Thinking step: {_sn}")
                ctx_inner["_thought_chain"].append({f"step_{_idx}": _sn, "thought": thought})
                return thought

            chain.steps.append(Step(
                name=step_name,
                description=f"CoT step {i + 1}: {step_name}",
                fn=cot_step_fn,
                max_retries=1,
                timeout=step_timeout,
            ))

        return await self.run(chain, ctx)

    async def react_loop(
        self,
        task: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 10,
        context: Optional[Dict[str, Any]] = None,
        step_timeout: float = 60.0,
    ) -> ChainRunResult:
        """
        ReAct (Reasoning + Acting) 循环模式。

        交替进行推理(think)和行动(act)，直到任务完成。
        """
        chain = self.create_chain(
            name=f"react_{uuid.uuid4().hex[:6]}",
            description=f"ReAct: {task[:60]}",
            mode=ChainMode.SEQUENTIAL,
            global_timeout=step_timeout * max_iterations * 2,
        )

        ctx = dict(context or {})
        ctx["_task"] = task
        ctx["_tools"] = tools or []
        ctx["_react_trace"] = []
        ctx["_iteration"] = 0

        for i in range(max_iterations):
            # Think 步骤
            async def think_fn(ctx_inner, _i=i):
                ctx_inner["_iteration"] = _i + 1
                thought = ctx_inner.get(f"_thought_{_i}", f"Observation at step {_i + 1}")
                trace_entry = {"iteration": _i + 1, "type": "thought", "content": thought}
                ctx_inner["_react_trace"].append(trace_entry)
                return thought

            # Act 步骤
            async def act_fn(ctx_inner, _i=i):
                action = ctx_inner.get(f"_action_{_i}", None)
                if action is None:
                    return {"done": True, "reason": "no action specified"}
                trace_entry = {"iteration": _i + 1, "type": "action", "content": action}
                ctx_inner["_react_trace"].append(trace_entry)
                return action

            chain.steps.append(Step(
                name=f"think_{i}",
                description=f"ReAct think iteration {i + 1}",
                fn=think_fn,
                max_retries=0,
                timeout=step_timeout,
            ))
            chain.steps.append(Step(
                name=f"act_{i}",
                description=f"ReAct act iteration {i + 1}",
                fn=act_fn,
                max_retries=0,
                timeout=step_timeout,
            ))

        return await self.run(chain, ctx)

    async def plan_execute(
        self,
        goal: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        step_timeout: float = 60.0,
    ) -> ChainRunResult:
        """
        Plan-Execute 模式。

        先制定计划 (plan)，再逐步执行 (execute)，必要时重新规划。
        """
        ctx = dict(context or {})
        ctx["_goal"] = goal
        ctx["_tools"] = tools or []
        ctx["_plan"] = ctx.get("_plan", [])
        ctx["_execution_trace"] = []

        chain = self.create_chain(
            name=f"plan_exec_{uuid.uuid4().hex[:6]}",
            description=f"Plan-Execute: {goal[:60]}",
            mode=ChainMode.SEQUENTIAL,
            global_timeout=step_timeout * 20,
        )

        # Plan 步骤
        async def plan_fn(ctx_inner):
            if ctx_inner.get("_plan"):
                return ctx_inner["_plan"]  # 已有计划则跳过
            plan_steps = ctx_inner.get("_plan_steps", ["analyze", "design", "implement", "verify"])
            plan = [{"step": i + 1, "name": s, "status": "pending"} for i, s in enumerate(plan_steps)]
            ctx_inner["_plan"] = plan
            return plan

        # Execute 步骤 — 对每个计划步骤生成执行步骤
        async def execute_plan_fn(ctx_inner):
            plan = ctx_inner.get("_plan", [])
            results = []
            for item in plan:
                item["status"] = "executing"
                exec_result = ctx_inner.get(f"_exec_{item['name']}", f"Executed: {item['name']}")
                item["status"] = "done"
                item["result"] = exec_result
                results.append(item)
                ctx_inner["_execution_trace"].append(item)
            return results

        # Verify 步骤
        async def verify_fn(ctx_inner):
            plan = ctx_inner.get("_plan", [])
            all_done = all(p.get("status") == "done" for p in plan)
            return {"verified": all_done, "completed_steps": sum(1 for p in plan if p.get("status") == "done")}

        chain.steps.append(Step(name="plan", description="Create execution plan", fn=plan_fn, max_retries=1, timeout=step_timeout))
        chain.steps.append(Step(name="execute", description="Execute plan steps", fn=execute_plan_fn, max_retries=1, timeout=step_timeout * 5))
        chain.steps.append(Step(name="verify", description="Verify execution results", fn=verify_fn, max_retries=1, timeout=step_timeout))

        return await self.run(chain, ctx)

    # ── 历史与统计 ─────────────────────────────────────────

    def _add_to_history(self, result: ChainRunResult):
        self._run_history.append(result)
        if len(self._run_history) > self._max_history:
            self._run_history = self._run_history[-self._max_history:]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的链执行历史"""
        return [r.to_dict() for r in self._run_history[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计信息"""
        recent = self._run_history[-100:] if self._run_history else []
        success_count = sum(1 for r in recent if r.success)
        return {
            "total_runs": self._total_runs,
            "total_errors": self._total_errors,
            "active_chains": len(self._chains),
            "recent_success_rate": success_count / max(len(recent), 1),
            "avg_duration_ms": (
                sum(r.total_duration_ms for r in recent) / max(len(recent), 1)
            ) if recent else 0,
        }

    def clear_history(self):
        """清除运行历史"""
        self._run_history.clear()


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_chain_engine: Optional[ChainEngine] = None


def get_chain_engine() -> ChainEngine:
    """获取全局 ChainEngine 单例"""
    global _chain_engine
    if _chain_engine is None:
        _chain_engine = ChainEngine()
        logger.info("ChainEngine initialized")
    return _chain_engine


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

async def run_chain(
    name: str,
    steps: List[Tuple[str, Callable]],
    context: Optional[Dict[str, Any]] = None,
    mode: ChainMode = ChainMode.SEQUENTIAL,
) -> ChainRunResult:
    """
    快速创建并运行一条链。

    Args:
        name: 链名称
        steps: [(step_name, fn), ...] 步骤列表
        context: 初始上下文
        mode: 执行模式

    Returns:
        ChainRunResult
    """
    engine = get_chain_engine()
    chain = engine.create_chain(name=name, mode=mode)
    for step_name, fn in steps:
        engine.add_step(chain.chain_id, name=step_name, fn=fn)
    return await engine.run(chain, context)


async def chain_of_thought(
    question: str,
    steps: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> ChainRunResult:
    """快速 CoT 推理"""
    engine = get_chain_engine()
    return await engine.chain_of_thought(question, context, thought_steps=steps)


async def react_loop(
    task: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    max_iterations: int = 10,
    context: Optional[Dict[str, Any]] = None,
) -> ChainRunResult:
    """快速 ReAct 循环"""
    engine = get_chain_engine()
    return await engine.react_loop(task, tools, max_iterations, context)


async def plan_execute(
    goal: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> ChainRunResult:
    """快速 Plan-Execute"""
    engine = get_chain_engine()
    return await engine.plan_execute(goal, tools, context)

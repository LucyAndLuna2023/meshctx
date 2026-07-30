"""
meshctx Task Planner — 任务规划与执行引擎
==========================================

将高层目标拆解为可执行的子任务, 管理任务依赖图 (DAG),
并行度控制和进度跟踪。支持动态重规划和预估/实际时间追踪。

核心功能:
  1. Plan/TaskStep — 计划与任务步骤抽象
  2. decompose — 目标拆解为子任务 DAG
  3. 依赖图 — DAG 拓扑排序, 循环检测
  4. 并行度控制 — 最大并发任务数
  5. 进度跟踪 — 实时进度百分比
  6. 动态重规划 — 运行时调整任务
  7. 预估 vs 实际时间追踪 — 用于优化未来规划

使用示例:
  planner = get_task_planner()
  plan = planner.create_plan("Deploy web service", max_parallel=3)
  planner.add_task(plan.id, "build_docker", estimate=30)
  planner.add_task(plan.id, "run_tests", estimate=60, depends_on=["build_docker"])
  await planner.execute(plan.id)

代码量: ~650 行
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, Awaitable

logger = logging.getLogger("meshctx.task_planner")


# ═══════════════════════════════════════════════════════════
# 枚举与常量
# ═══════════════════════════════════════════════════════════

class PlanTaskStatus(str, Enum):
    """任务状态。"""
    PENDING = "pending"          # 等待依赖完成
    READY = "ready"              # 依赖满足, 可执行
    RUNNING = "running"          # 正在执行
    COMPLETED = "completed"      # 成功完成
    FAILED = "failed"            # 执行失败
    SKIPPED = "skipped"          # 被跳过 (依赖失败/条件不满足)
    CANCELLED = "cancelled"      # 被取消


class PlanStatus(str, Enum):
    """计划整体状态。"""
    DRAFT = "draft"              # 草稿, 尚未执行
    RUNNING = "running"          # 执行中
    COMPLETED = "completed"      # 全部成功
    PARTIAL = "partial"          # 部分成功 (有的 skipped)
    FAILED = "failed"            # 存在致命失败
    CANCELLED = "cancelled"      # 被取消
    REPLANNING = "replanning"    # 重规划中


DEFAULT_MAX_PARALLEL = 4
DEFAULT_TASK_TIMEOUT = 300.0  # 秒


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class TaskStep:
    """任务步骤 — 计划中的单个可执行单元。

    Attributes:
        id: 唯一任务 ID
        name: 任务名称
        status: 当前状态
        depends_on: 依赖的任务 ID 列表
        estimate_seconds: 预估执行时间 (秒)
        actual_seconds: 实际执行时间 (秒), 完成后填充
        handler: 异步执行函数 (可选)
        handler_args: handler 参数
        result: 执行结果
        error: 错误信息
        started_at: 开始时间
        completed_at: 完成时间
        retry_count: 重试次数
        max_retries: 最大重试次数
        priority: 优先级 (越小越优先)
        metadata: 额外元数据
    """
    id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    name: str = ""
    status: PlanTaskStatus = PlanTaskStatus.PENDING
    depends_on: List[str] = field(default_factory=list)
    estimate_seconds: float = 0.0
    actual_seconds: float = 0.0
    handler: Optional[Callable[..., Awaitable[Any]]] = field(default=None, repr=False)
    handler_args: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    retry_count: int = 0
    max_retries: int = 1
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "estimate_seconds": self.estimate_seconds,
            "actual_seconds": round(self.actual_seconds, 2),
            "error": self.error,
            "retry_count": self.retry_count,
            "priority": self.priority,
            "metadata": self.metadata,
        }

    @property
    def is_terminal(self, **kw) -> bool:
        """是否处于终态。"""
        return self.status in (
            PlanTaskStatus.COMPLETED,
            PlanTaskStatus.FAILED,
            PlanTaskStatus.SKIPPED,
            PlanTaskStatus.CANCELLED,
        )

    @property
    def is_blocked(self, **kw) -> bool:
        """是否被阻塞 (等待依赖)。"""
        return self.status == PlanTaskStatus.PENDING


@dataclass
class Plan:
    """计划容器 — 一组有依赖关系的 TaskStep。

    Attributes:
        id: 唯一计划 ID
        name: 计划名称 / 目标描述
        status: 整体状态
        tasks: 任务列表 (key=task_id)
        max_parallel: 最大并行度
        started_at: 计划开始时间
        completed_at: 计划完成时间
        total_estimate_seconds: 预估总时间
        total_actual_seconds: 实际总时间
        metadata: 额外元数据
    """
    id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    name: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    tasks: Dict[str, TaskStep] = field(default_factory=dict)
    max_parallel: int = DEFAULT_MAX_PARALLEL
    started_at: float = 0.0
    completed_at: float = 0.0
    total_estimate_seconds: float = 0.0
    total_actual_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "task_count": len(self.tasks),
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "progress_pct": self.progress_pct,
            "max_parallel": self.max_parallel,
            "total_estimate_seconds": round(self.total_estimate_seconds, 2),
            "total_actual_seconds": round(self.total_actual_seconds, 2),
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
            "metadata": self.metadata,
        }

    @property
    def completed_count(self, **kw) -> int:
        return sum(1 for t in self.tasks.values() if t.status == PlanTaskStatus.COMPLETED)

    @property
    def failed_count(self, **kw) -> int:
        return sum(1 for t in self.tasks.values() if t.status == PlanTaskStatus.FAILED)

    @property
    def progress_pct(self, **kw) -> float:
        if not self.tasks:
            return 100.0
        terminal = sum(1 for t in self.tasks.values() if t.is_terminal)
        return round((terminal / len(self.tasks)) * 100, 1)

    @property
    def is_running(self, **kw) -> bool:
        return self.status == PlanStatus.RUNNING


# ═══════════════════════════════════════════════════════════
# DAG 工具
# ═══════════════════════════════════════════════════════════

class DAGError(Exception):
    """DAG 操作错误 (循环依赖等)。"""
    pass


def _topological_sort(tasks: Dict[str, TaskStep]) -> List[str]:
    """DAG 拓扑排序 (Kahn 算法)。

    Returns:
        List[str]: 拓扑排序后的 task ID 列表

    Raises:
        DAGError: 存在循环依赖
    """
    in_degree: Dict[str, int] = defaultdict(int)
    outgoing: Dict[str, List[str]] = defaultdict(list)
    task_ids = set(tasks.keys())

    for tid, task in tasks.items():
        for dep_id in task.depends_on:
            if dep_id not in task_ids:
                raise DAGError(f"Task '{tid}' depends on unknown task '{dep_id}'")
            outgoing[dep_id].append(tid)
            in_degree[tid] += 1

    # 入度为 0 的节点
    queue: List[str] = [tid for tid in task_ids if in_degree[tid] == 0]
    result: List[str] = []

    while queue:
        # 按优先级排序
        queue.sort(key=lambda tid: tasks[tid].priority)
        node = queue.pop(0)
        result.append(node)

        for neighbor in outgoing[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(task_ids):
        remaining = task_ids - set(result)
        raise DAGError(f"Circular dependency detected involving: {remaining}")

    return result


def _find_ready_tasks(tasks: Dict[str, TaskStep], running_ids: Set[str]) -> List[str]:
    """查找所有依赖已满足的任务 (READY 状态)。

    将 PENDING 且所有依赖已 COMPLETED 的任务标记为 READY。
    """
    ready = []
    for tid, task in tasks.items():
        if task.status != PlanTaskStatus.PENDING:
            continue
        if tid in running_ids:
            continue

        # 检查依赖是否全部完成
        if not task.depends_on:
            task.status = PlanTaskStatus.READY
            ready.append(tid)
        else:
            all_deps_done = all(
                tasks[dep].status == PlanTaskStatus.COMPLETED
                for dep in task.depends_on
            )
            if all_deps_done:
                task.status = PlanTaskStatus.READY
                ready.append(tid)
            # 如果有依赖失败, 标记当前任务为 SKIPPED
            elif any(
                tasks[dep].status == PlanTaskStatus.FAILED
                for dep in task.depends_on
            ):
                task.status = PlanTaskStatus.SKIPPED
                task.error = "Skipped: dependency failed"

    return ready


# ═══════════════════════════════════════════════════════════
# TaskPlanner — 任务规划器
# ═══════════════════════════════════════════════════════════

class TaskPlanner:
    """任务规划与执行引擎。

    核心职责:
    - 创建和管理 Plan
    - DAG 拓扑排序
    - 并行执行控制
    - 进度跟踪和时间追踪
    - 动态重规划

    线程安全: 内部使用 asyncio.Lock + threading.Lock。
    """

    def __init__(self, **kw):
        self._plans: Dict[str, Plan] = {}
        self._plan_lock = threading.Lock()
        self._running_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._execution_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

        # 统计
        self.total_plans_created: int = 0
        self.total_plans_completed: int = 0
        self.total_tasks_executed: int = 0
        self._stats_lock = threading.Lock()

    # ── Plan 管理 ──────────────────────────────────────────

    def create_plan(
        self,
        name: str,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        metadata: Dict[str, Any] = None,
    ) -> Plan:
        """创建新计划。

        Args:
            name: 计划名称 / 目标描述
            max_parallel: 最大并行任务数
            metadata: 额外元数据

        Returns:
            Plan: 新创建的计划
        """
        plan = Plan(
            name=name,
            max_parallel=max_parallel,
            metadata=metadata or {},
        )

        with self._plan_lock:
            self._plans[plan.id] = plan
            self.total_plans_created += 1

        logger.info(f"Created plan: {plan.id} '{name}' (max_parallel={max_parallel})")
        return plan

    def get_plan(self, plan_id: str, **kw) -> Optional[Plan]:
        """获取计划。"""
        with self._plan_lock:
            return self._plans.get(plan_id)

    def list_plans(self, status: PlanStatus = None, **kw) -> List[Plan]:
        """列出计划 (可按状态过滤)。"""
        with self._plan_lock:
            plans = list(self._plans.values())
        if status:
            plans = [p for p in plans if p.status == status]
        return plans

    def delete_plan(self, plan_id: str, **kw) -> bool:
        """删除计划 (仅 DRAFT/COMPLETED/FAILED/CANCELLED 状态可删除)。"""
        with self._plan_lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            if plan.status == PlanStatus.RUNNING:
                logger.warning(f"Cannot delete running plan: {plan_id}")
                return False
            del self._plans[plan_id]

        logger.info(f"Deleted plan: {plan_id}")
        return True

    # ── Task 管理 ──────────────────────────────────────────

    def add_task(
        self,
        plan_id: str,
        name: str,
        handler: Callable[..., Awaitable[Any]] = None,
        handler_args: Dict[str, Any] = None,
        depends_on: List[str] = None,
        estimate_seconds: float = 0.0,
        max_retries: int = 1,
        priority: int = 0,
        metadata: Dict[str, Any] = None,
    ) -> TaskStep:
        """向计划添加任务。

        Args:
            plan_id: 目标计划 ID
            name: 任务名称
            handler: 异步执行函数
            handler_args: handler 参数
            depends_on: 依赖的任务 ID 列表
            estimate_seconds: 预估执行时间
            max_retries: 最大重试次数
            priority: 优先级 (越小越优先)
            metadata: 额外元数据

        Returns:
            TaskStep: 新创建的任务

        Raises:
            ValueError: 计划不存在或已开始执行
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan not found: {plan_id}")
        if plan.status not in (PlanStatus.DRAFT, PlanStatus.REPLANNING):
            raise ValueError(f"Cannot add tasks to plan in '{plan.status.value}' state")

        task = TaskStep(
            name=name,
            handler=handler,
            handler_args=handler_args or {},
            depends_on=depends_on or [],
            estimate_seconds=estimate_seconds,
            max_retries=max_retries,
            priority=priority,
            metadata=metadata or {},
        )

        plan.tasks[task.id] = task
        plan.total_estimate_seconds += estimate_seconds

        logger.debug(f"Added task: {task.id} '{name}' to plan {plan_id}")
        return task

    def remove_task(self, plan_id: str, task_id: str, **kw) -> bool:
        """从计划中移除任务。"""
        plan = self.get_plan(plan_id)
        if plan is None:
            return False
        if plan.status not in (PlanStatus.DRAFT, PlanStatus.REPLANNING):
            logger.warning(f"Cannot remove tasks from plan in '{plan.status.value}' state")
            return False

        task = plan.tasks.pop(task_id, None)
        if task:
            plan.total_estimate_seconds -= task.estimate_seconds

            # 清理其他任务对此任务的依赖
            for t in plan.tasks.values():
                if task_id in t.depends_on:
                    t.depends_on.remove(task_id)

            logger.debug(f"Removed task: {task_id} from plan {plan_id}")
            return True
        return False

    # ── 执行 ───────────────────────────────────────────────

    async def execute(
        self,
        plan_id: str,
        task_timeout: float = DEFAULT_TASK_TIMEOUT,
    ) -> Plan:
        """执行计划中的所有任务。

        按 DAG 拓扑顺序 + 并行度控制执行任务。

        Args:
            plan_id: 计划 ID
            task_timeout: 单个任务超时 (秒)

        Returns:
            Plan: 执行完成后的计划
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan not found: {plan_id}")

        async with self._lock:
            if plan_id in self._execution_tasks:
                logger.warning(f"Plan {plan_id} is already executing")
                return plan

        # 验证 DAG
        if plan.tasks:
            try:
                _topological_sort(plan.tasks)
            except DAGError as e:
                plan.status = PlanStatus.FAILED
                logger.error(f"Invalid DAG for plan {plan_id}: {e}")
                raise

        # 重置所有任务状态
        for task in plan.tasks.values():
            if task.status not in (PlanTaskStatus.COMPLETED, PlanTaskStatus.SKIPPED):
                task.status = PlanTaskStatus.PENDING
                task.result = None
                task.error = ""
                task.actual_seconds = 0.0
                task.retry_count = 0

        plan.status = PlanStatus.RUNNING
        plan.started_at = time.time()

        # 创建信号量控制并行度
        semaphore = asyncio.Semaphore(plan.max_parallel)
        self._running_semaphores[plan_id] = semaphore

        logger.info(
            f"Executing plan {plan_id}: {len(plan.tasks)} tasks, "
            f"max_parallel={plan.max_parallel}"
        )

        try:
            await self._execute_plan(plan, semaphore, task_timeout)
        except asyncio.CancelledError:
            plan.status = PlanStatus.CANCELLED
            logger.warning(f"Plan {plan_id} cancelled")
        finally:
            plan.completed_at = time.time()
            plan.total_actual_seconds = plan.completed_at - plan.started_at

            # 清理
            self._running_semaphores.pop(plan_id, None)
            async with self._lock:
                self._execution_tasks.pop(plan_id, None)

            # 确定最终状态
            if plan.status == PlanStatus.RUNNING:
                if plan.failed_count > 0 and plan.completed_count == 0:
                    plan.status = PlanStatus.FAILED
                elif plan.failed_count > 0:
                    plan.status = PlanStatus.PARTIAL
                else:
                    plan.status = PlanStatus.COMPLETED

            with self._stats_lock:
                self.total_plans_completed += 1
                self.total_tasks_executed += plan.completed_count

            logger.info(
                f"Plan {plan_id} finished: status={plan.status.value}, "
                f"completed={plan.completed_count}/{len(plan.tasks)}, "
                f"time={plan.total_actual_seconds:.1f}s"
            )

        return plan

    async def _execute_plan(
        self,
        plan: Plan,
        semaphore: asyncio.Semaphore,
        task_timeout: float,
    ) -> None:
        """内部: 执行计划主循环。"""
        running_tasks: Dict[str, asyncio.Task] = {}

        while plan.status == PlanStatus.RUNNING:
            # 查找就绪任务
            ready_ids = _find_ready_tasks(plan.tasks, set(running_tasks.keys()))

            if not ready_ids and not running_tasks:
                # 没有就绪任务也没有运行中的任务 → 全部完成
                break

            if not ready_ids and running_tasks:
                # 等待任意运行中的任务完成
                done, _ = await asyncio.wait(
                    running_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=1.0,
                )
                for t in done:
                    tid = None
                    for key, val in list(running_tasks.items()):
                        if val is t:
                            tid = key
                            break
                    if tid:
                        del running_tasks[tid]
                continue

            # 启动就绪任务 (受并行度限制)
            for tid in ready_ids:
                task = plan.tasks[tid]

                # 检查是否有 handler (无 handler 视为立即完成)
                if task.handler is None:
                    task.status = PlanTaskStatus.COMPLETED
                    task.completed_at = time.time()
                    logger.debug(f"No handler for task {tid}, marking completed")
                    continue

                async def _run_with_sem(tid=tid):
                    async with semaphore:
                        await self._run_single_task(plan, tid, task_timeout)

                coro = _run_with_sem()
                running_tasks[tid] = asyncio.create_task(coro)

    async def _run_single_task(
        self,
        plan: Plan,
        task_id: str,
        timeout: float,
    ) -> None:
        """执行单个任务, 包含重试逻辑。"""
        task = plan.tasks[task_id]
        task.status = PlanTaskStatus.RUNNING
        task.started_at = time.time()

        for attempt in range(task.max_retries + 1):
            try:
                task.retry_count = attempt
                logger.debug(f"Running task {task_id} '{task.name}' (attempt {attempt + 1})")

                result = await asyncio.wait_for(
                    task.handler(**task.handler_args),
                    timeout=timeout,
                )

                task.result = result
                task.status = PlanTaskStatus.COMPLETED
                task.completed_at = time.time()
                task.actual_seconds = task.completed_at - task.started_at

                logger.debug(
                    f"Task {task_id} completed: "
                    f"estimate={task.estimate_seconds:.1f}s actual={task.actual_seconds:.1f}s"
                )
                return

            except asyncio.TimeoutError:
                error_msg = f"Timeout after {timeout}s"
                logger.error(f"Task {task_id} '{task.name}': {error_msg}")
                if attempt < task.max_retries:
                    logger.info(f"Retrying task {task_id} (attempt {attempt + 2})")
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                else:
                    task.status = PlanTaskStatus.FAILED
                    task.error = error_msg
                    task.completed_at = time.time()
                    task.actual_seconds = task.completed_at - task.started_at

            except asyncio.CancelledError:
                task.status = PlanTaskStatus.CANCELLED
                task.error = "Cancelled"
                task.completed_at = time.time()
                return

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Task {task_id} '{task.name}' failed: {error_msg}",
                    exc_info=True,
                )
                if attempt < task.max_retries:
                    logger.info(f"Retrying task {task_id} (attempt {attempt + 2})")
                    await asyncio.sleep(2 ** attempt)
                else:
                    task.status = PlanTaskStatus.FAILED
                    task.error = error_msg
                    task.completed_at = time.time()
                    task.actual_seconds = task.completed_at - task.started_at

    # ── 动态重规划 ─────────────────────────────────────────

    async def replan(
        self,
        plan_id: str,
        new_max_parallel: int = None,
        additional_tasks: List[TaskStep] = None,
        remove_task_ids: List[str] = None,
    ) -> Plan:
        """动态重规划 — 运行时调整计划。

        Args:
            plan_id: 计划 ID
            new_max_parallel: 新的最大并行度
            additional_tasks: 要添加的新任务
            remove_task_ids: 要移除的 PENDING 任务 ID

        Returns:
            Plan: 更新后的计划

        Raises:
            ValueError: 计划不存在
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"Plan not found: {plan_id}")

        if plan.status not in (PlanStatus.RUNNING, PlanStatus.PARTIAL):
            logger.warning(f"Plan {plan_id} is not in replannable state: {plan.status.value}")
            return plan

        prev_status = plan.status
        plan.status = PlanStatus.REPLANNING

        # 调整并行度
        if new_max_parallel is not None and new_max_parallel > 0:
            plan.max_parallel = new_max_parallel
            # 更新信号量
            if plan_id in self._running_semaphores:
                # 创建一个新的信号量 (不能直接更新现有信号量的值)
                self._running_semaphores[plan_id] = asyncio.Semaphore(new_max_parallel)

        # 移除任务 (仅 PENDING)
        if remove_task_ids:
            for tid in remove_task_ids:
                if tid in plan.tasks and plan.tasks[tid].status == PlanTaskStatus.PENDING:
                    self.remove_task(plan_id, tid)

        # 添加新任务
        if additional_tasks:
            for task in additional_tasks:
                plan.tasks[task.id] = task
                plan.total_estimate_seconds += task.estimate_seconds

        plan.status = prev_status
        logger.info(
            f"Replan complete for {plan_id}: {len(plan.tasks)} tasks, "
            f"max_parallel={plan.max_parallel}"
        )
        return plan

    # ── 取消 ───────────────────────────────────────────────

    async def cancel_plan(self, plan_id: str) -> bool:
        """取消计划执行。

        Returns:
            bool: 是否成功取消
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            return False
        if plan.status not in (PlanStatus.RUNNING, PlanStatus.REPLANNING):
            return False

        plan.status = PlanStatus.CANCELLED

        # 取消执行中的任务
        async with self._lock:
            exec_task = self._execution_tasks.pop(plan_id, None)
        if exec_task and not exec_task.done():
            exec_task.cancel()
            try:
                await exec_task
            except (asyncio.CancelledError, Exception):
                pass

        # 标记所有非终态任务为 CANCELLED
        for task in plan.tasks.values():
            if not task.is_terminal:
                task.status = PlanTaskStatus.CANCELLED

        plan.completed_at = time.time()
        logger.info(f"Plan {plan_id} cancelled")
        return True

    # ── 进度跟踪 ───────────────────────────────────────────

    def get_progress(self, plan_id: str, **kw) -> Dict[str, Any]:
        """获取计划执行进度。

        Returns:
            Dict: 包含 progress_pct, completed_count, task_statuses 等
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            return {"error": "Plan not found"}

        status_counts = defaultdict(int)
        for task in plan.tasks.values():
            status_counts[task.status.value] += 1

        return {
            "plan_id": plan.id,
            "plan_name": plan.name,
            "status": plan.status.value,
            "progress_pct": plan.progress_pct,
            "completed_count": plan.completed_count,
            "failed_count": plan.failed_count,
            "total_count": len(plan.tasks),
            "max_parallel": plan.max_parallel,
            "task_statuses": dict(status_counts),
            "elapsed_seconds": round(
                time.time() - plan.started_at, 2
            ) if plan.started_at else 0,
            "total_estimate_seconds": round(plan.total_estimate_seconds, 2),
        }

    def get_time_estimates(self, plan_id: str, **kw) -> Dict[str, Any]:
        """获取预估 vs 实际时间比较。

        Returns:
            Dict: 包含每任务和总体的预估/实际时间
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            return {"error": "Plan not found"}

        task_times = {}
        for tid, task in plan.tasks.items():
            task_times[tid] = {
                "name": task.name,
                "estimate_seconds": task.estimate_seconds,
                "actual_seconds": round(task.actual_seconds, 2),
                "delta": round(task.actual_seconds - task.estimate_seconds, 2),
            }

        return {
            "plan_id": plan.id,
            "total_estimate_seconds": round(plan.total_estimate_seconds, 2),
            "total_actual_seconds": round(plan.total_actual_seconds, 2),
            "total_delta": round(
                plan.total_actual_seconds - plan.total_estimate_seconds, 2
            ),
            "tasks": task_times,
        }

    # ── 验证 ───────────────────────────────────────────────

    def validate_plan(self, plan_id: str, **kw) -> Tuple[bool, str]:
        """验证计划 DAG 完整性。

        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        plan = self.get_plan(plan_id)
        if plan is None:
            return False, f"Plan not found: {plan_id}"

        if not plan.tasks:
            return True, "Plan has no tasks"

        try:
            _topological_sort(plan.tasks)
        except DAGError as e:
            return False, str(e)

        return True, "Valid"

    # ── 统计 ───────────────────────────────────────────────

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取规划器统计信息。"""
        with self._stats_lock:
            active_plans = sum(
                1 for p in self._plans.values() if p.status == PlanStatus.RUNNING
            )
            return {
                "total_plans_created": self.total_plans_created,
                "total_plans_completed": self.total_plans_completed,
                "total_tasks_executed": self.total_tasks_executed,
                "active_plans": active_plans,
                "stored_plans": len(self._plans),
            }


# ═══════════════════════════════════════════════════════════
# 全局实例管理
# ═══════════════════════════════════════════════════════════

_global_task_planner: Optional[TaskPlanner] = None
_global_lock = threading.Lock()


def get_task_planner() -> TaskPlanner:
    """惰性初始化全局 TaskPlanner 单例。

    线程安全, 确保整个进程只有一个 TaskPlanner 实例。

    Returns:
        TaskPlanner: 全局任务规划器
    """
    global _global_task_planner
    if _global_task_planner is None:
        with _global_lock:
            if _global_task_planner is None:
                _global_task_planner = TaskPlanner()
                logger.info("Created global TaskPlanner instance")
    return _global_task_planner


# ═══════════════════════════════════════════════════════════
# CLI 诊断工具
# ═══════════════════════════════════════════════════════════

async def _cli_main():
    """CLI 诊断入口。"""
    print("=" * 60)
    print("  meshctx Task Planner — 诊断工具")
    print("=" * 60)

    planner = TaskPlanner()

    # 1. 创建计划
    plan = planner.create_plan("Deploy web application", max_parallel=3)
    print(f"\n[1] 创建计划: {plan.id} '{plan.name}'")

    # 2. 定义 handler
    async def build_docker_task(**kwargs):
        await asyncio.sleep(0.1)
        return {"image": "app:v1.0", "size_mb": 42}

    async def run_tests_task(**kwargs):
        await asyncio.sleep(0.15)
        return {"passed": 42, "failed": 0}

    async def deploy_task(**kwargs):
        await asyncio.sleep(0.1)
        return {"endpoint": "https://app.example.com"}

    async def notify_task(**kwargs):
        await asyncio.sleep(0.05)
        return {"notified": ["slack", "email"]}

    # 3. 添加任务
    t1 = planner.add_task(plan.id, "build_docker", build_docker_task, estimate_seconds=30)
    t2 = planner.add_task(plan.id, "run_tests", run_tests_task, estimate_seconds=60, depends_on=[t1.id])
    t3 = planner.add_task(plan.id, "deploy", deploy_task, estimate_seconds=30, depends_on=[t2.id])
    t4 = planner.add_task(plan.id, "notify", notify_task, estimate_seconds=5, depends_on=[t3.id])

    print(f"\n[2] 添加了 {len(plan.tasks)} 个任务:")
    for t in plan.tasks.values():
        deps = ",".join(t.depends_on) or "none"
        print(f"    {t.id[:12]}: {t.name} (depends_on={deps})")

    # 4. 验证
    valid, msg = planner.validate_plan(plan.id)
    print(f"\n[3] DAG 验证: {'✅' if valid else '❌'} {msg}")

    # 5. 拓扑排序
    order = _topological_sort(plan.tasks)
    print(f"\n[4] 拓扑排序: {' → '.join([plan.tasks[tid].name for tid in order])}")

    # 6. 执行
    print(f"\n[5] 执行计划...")
    start = time.time()
    result = await planner.execute(plan.id)
    elapsed = time.time() - start

    print(f"\n[6] 结果:")
    print(f"    状态: {result.status.value}")
    print(f"    进度: {result.progress_pct}%")
    print(f"    完成: {result.completed_count}/{len(result.tasks)}")
    print(f"    耗时: {elapsed:.2f}s")

    # 7. 进度报告
    progress = planner.get_progress(plan.id)
    print(f"\n[7] 进度报告:")
    for k, v in progress.items():
        print(f"    {k}: {v}")

    # 8. 时间追踪
    times = planner.get_time_estimates(plan.id)
    print(f"\n[8] 时间追踪:")
    print(f"    预估总时间: {times['total_estimate_seconds']}s")
    print(f"    实际总时间: {times['total_actual_seconds']}s")
    print(f"    delta: {times['total_delta']}s")

    print("\n✅ TaskPlanner 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_cli_main())

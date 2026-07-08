"""
meshctx Error Recovery — 错误分类与自动恢复引擎
================================================

智能错误分类系统, 将错误分为 retryable/fatal/degradable 三类,
提供指数退避重试、状态回滚和降级策略。

核心功能:
  1. 错误分类 — retryable / fatal / degradable
  2. RecoveryPlan — 恢复步骤序列
  3. 指数退避 + 抖动 — jittered exponential backoff
  4. 状态回滚 — checkpoint/snapshot + restore
  5. 降级策略 — 优雅降级 fallback
  6. 部分成功处理 — 记录已完成步骤, 避免重复

使用示例:
  recovery = get_error_recovery()
  recovery.register_strategy("api_call", retryable_check, max_retries=3)
  try:
      result = await call_api()
  except Exception as e:
      plan = recovery.classify_and_plan("api_call", e)
      result = await recovery.execute_recovery(plan)

代码量: ~550 行
"""

import asyncio
import copy
import json
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, Awaitable

logger = logging.getLogger("meshctx.error_recovery")


# ═══════════════════════════════════════════════════════════
# 枚举与常量
# ═══════════════════════════════════════════════════════════

class ErrorCategory(str, Enum):
    """错误分类。"""
    RETRYABLE = "retryable"        # 可重试 (网络超时, 临时故障)
    FATAL = "fatal"                # 致命 (配置错误, 认证失败)
    DEGRADABLE = "degradable"      # 可降级 (部分功能不可用)


class RecoveryStepType(str, Enum):
    """恢复步骤类型。"""
    RETRY = "retry"                # 重试原操作
    BACKOFF_WAIT = "backoff_wait"  # 等待指数退避
    ROLLBACK = "rollback"          # 回滚到 checkpoint
    DEGRADE = "degrade"            # 执行降级策略
    CUSTOM = "custom"              # 自定义恢复步骤
    NOTIFY = "notify"              # 发送通知
    LOG = "log"                    # 记录日志


class RecoveryStatus(str, Enum):
    """恢复计划状态。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"            # 部分恢复成功


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0           # 退避基延迟 (秒)
DEFAULT_MAX_DELAY = 60.0           # 退避最大延迟 (秒)
DEFAULT_JITTER_FACTOR = 0.1        # 抖动因子 (10%)


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class RecoveryStep:
    """单个恢复步骤。

    Attributes:
        step_type: 步骤类型
        description: 步骤描述
        handler: 可选执行函数 (CUSTOM 步骤必填)
        handler_args: 执行函数参数
        timeout: 超时 (秒)
        metadata: 额外数据
    """
    step_type: RecoveryStepType
    description: str = ""
    handler: Optional[Callable[..., Awaitable[Any]]] = None
    handler_args: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 运行时状态
    status: RecoveryStatus = field(default=RecoveryStatus.PENDING, repr=False)
    result: Any = field(default=None, repr=False)
    error: str = field(default="", repr=False)
    started_at: float = field(default=0.0, repr=False)
    completed_at: float = field(default=0.0, repr=False)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "step_type": self.step_type.value,
            "description": self.description,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class RecoveryPlan:
    """恢复计划 — 面对错误的完整恢复策略。

    Attributes:
        id: 唯一计划 ID
        error_category: 错误的分类
        original_error: 原始异常
        context: 错误上下文 (e.g. "api_call", "db_write")
        steps: 恢复步骤列表
        status: 计划整体状态
        max_retries: 最大重试次数
        current_retry: 当前重试计数
        created_at: 创建时间
        metadata: 额外元数据
    """
    id: str = field(default_factory=lambda: f"recovery_{uuid.uuid4().hex[:12]}")
    error_category: ErrorCategory = ErrorCategory.RETRYABLE
    original_error: Optional[Exception] = field(default=None, repr=False)
    context: str = ""
    steps: List[RecoveryStep] = field(default_factory=list)
    status: RecoveryStatus = RecoveryStatus.PENDING
    max_retries: int = DEFAULT_MAX_RETRIES
    current_retry: int = 0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "id": self.id,
            "error_category": self.error_category.value,
            "original_error": str(self.original_error) if self.original_error else "",
            "context": self.context,
            "status": self.status.value,
            "max_retries": self.max_retries,
            "current_retry": self.current_retry,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
        }

    @property
    def completed_steps(self, **kw) -> int:
        return sum(
            1 for s in self.steps if s.status == RecoveryStatus.COMPLETED
        )

    @property
    def failed_steps(self, **kw) -> int:
        return sum(
            1 for s in self.steps if s.status == RecoveryStatus.FAILED
        )

    @property
    def progress_pct(self, **kw) -> float:
        if not self.steps:
            return 100.0
        return round((self.completed_steps / len(self.steps)) * 100, 1)


@dataclass
class StateCheckpoint:
    """状态快照 — 用于回滚。

    Attributes:
        context: 上下文标识
        state: 状态数据 (深拷贝)
        timestamp: 创建时间
        metadata: 额外元数据
    """
    context: str
    state: Any
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# 错误分类器
# ═══════════════════════════════════════════════════════════

class ErrorClassifier:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """错误分类器 — 将异常归入 retryable/fatal/degradable。

    内置常见异常分类规则, 支持注册自定义分类函数。
    """

    # 内置: 异常类型名 → ErrorCategory
    BUILTIN_CLASSIFICATIONS: Dict[str, ErrorCategory] = {
        # 可重试
        "TimeoutError": ErrorCategory.RETRYABLE,
        "asyncio.TimeoutError": ErrorCategory.RETRYABLE,
        "ConnectionError": ErrorCategory.RETRYABLE,
        "ConnectionRefusedError": ErrorCategory.RETRYABLE,
        "ConnectionResetError": ErrorCategory.RETRYABLE,
        "BrokenPipeError": ErrorCategory.RETRYABLE,
        "TimeoutExpired": ErrorCategory.RETRYABLE,
        "RequestException": ErrorCategory.RETRYABLE,
        "TooManyRedirects": ErrorCategory.RETRYABLE,
        "TemporaryError": ErrorCategory.RETRYABLE,
        "TransientError": ErrorCategory.RETRYABLE,
        # 可降级
        "PermissionError": ErrorCategory.DEGRADABLE,
        "ResourceExhausted": ErrorCategory.DEGRADABLE,
        "QuotaExceeded": ErrorCategory.DEGRADABLE,
        "RateLimitError": ErrorCategory.DEGRADABLE,
        "ServiceUnavailable": ErrorCategory.DEGRADABLE,
        # 致命
        "ValueError": ErrorCategory.FATAL,
        "TypeError": ErrorCategory.FATAL,
        "KeyError": ErrorCategory.FATAL,
        "AttributeError": ErrorCategory.FATAL,
        "SyntaxError": ErrorCategory.FATAL,
        "ImportError": ErrorCategory.FATAL,
        "NameError": ErrorCategory.FATAL,
        "AuthenticationError": ErrorCategory.FATAL,
        "AuthorizationError": ErrorCategory.FATAL,
        "ConfigurationError": ErrorCategory.FATAL,
        "ValidationError": ErrorCategory.FATAL,
    }

    def __init__(self, **kw):
        self._custom_rules: List[Tuple[str, Callable[[Exception], Optional[ErrorCategory]]]] = []

    def classify(self, error: Exception, context: str = "", **kw) -> ErrorCategory:
        """分类异常。

        优先级: 自定义规则 > 内置规则 > 默认 FATAL

        Args:
            error: 异常实例
            context: 错误上下文

        Returns:
            ErrorCategory
        """
        # 1. 检查自定义规则
        for ctx_pattern, rule_func in self._custom_rules:
            if self._match_context(context, ctx_pattern):
                result = rule_func(error)
                if result is not None:
                    logger.debug(
                        f"Custom rule matched for '{context}': {type(error).__name__} → {result.value}"
                    )
                    return result

        # 2. 检查内置规则
        error_type_name = type(error).__name__
        if error_type_name in self.BUILTIN_CLASSIFICATIONS:
            category = self.BUILTIN_CLASSIFICATIONS[error_type_name]
            logger.debug(f"Builtin: {error_type_name} → {category.value}")
            return category

        # 3. 检查基类链
        for cls in type(error).__mro__:
            if cls.__name__ in self.BUILTIN_CLASSIFICATIONS:
                category = self.BUILTIN_CLASSIFICATIONS[cls.__name__]
                logger.debug(f"Builtin (MRO): {error_type_name} → {category.value}")
                return category

        # 4. 默认 FATAL
        logger.debug(f"Unclassified: {error_type_name} → FATAL (default)")
        return ErrorCategory.FATAL

    def register_rule(
        self,
        context_pattern: str,
        rule_func: Callable[[Exception], Optional[ErrorCategory]],
    ) -> None:
        """注册自定义分类规则。

        Args:
            context_pattern: 上下文匹配模式 (支持通配符 "*"), e.g. "api_*"
            rule_func: 分类函数, 接收异常, 返回 ErrorCategory 或 None (不匹配时)
        """
        self._custom_rules.append((context_pattern, rule_func))
        logger.info(f"Registered custom error rule for context: {context_pattern}")

    def unregister_rules(self, context_pattern: str = None, **kw) -> int:
        """注销自定义规则。"""
        if context_pattern is None:
            count = len(self._custom_rules)
            self._custom_rules.clear()
            return count

        count = 0
        self._custom_rules = [
            (p, f) for p, f in self._custom_rules
            if not (p == context_pattern)
        ]
        return count

    @staticmethod
    def _match_context(context: str, pattern: str, **kw) -> bool:
        """简单通配符匹配。"""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return context.startswith(pattern[:-1])
        return context == pattern


# ═══════════════════════════════════════════════════════════
# 退避计算
# ═══════════════════════════════════════════════════════════

def calculate_backoff(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter_factor: float = DEFAULT_JITTER_FACTOR,
) -> float:
    """计算指数退避 + 抖动延迟。

    delay = min(base_delay * 2^attempt, max_delay)
    jitter = delay * jitter_factor * random
    total = delay + jitter

    Args:
        attempt: 当前尝试次数 (0-based)
        base_delay: 基延迟 (秒)
        max_delay: 最大延迟 (秒)
        jitter_factor: 抖动因子 (0.0 ~ 1.0)

    Returns:
        float: 应等待的秒数
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = delay * jitter_factor * random.random()
    total = delay + jitter
    logger.debug(f"Backoff attempt={attempt}: delay={delay:.2f}s + jitter={jitter:.2f}s = {total:.2f}s")
    return total


# ═══════════════════════════════════════════════════════════
# ErrorRecovery — 错误恢复引擎
# ═══════════════════════════════════════════════════════════

class ErrorRecovery:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """错误恢复引擎。

    核心职责:
    - 错误分类
    - 生成 RecoveryPlan
    - 执行恢复步骤 (重试/回滚/降级)
    - 状态快照管理
    - 部分成功处理

    线程安全: 内部使用 asyncio.Lock + threading.Lock。
    """

    def __init__(self, **kw):
        self.classifier = ErrorClassifier()
        self._strategies: Dict[str, Dict[str, Any]] = {}
        self._strategies_lock = threading.Lock()

        # 降级 handler 注册表: context → fallback_handler
        self._degradation_handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._degradation_lock = threading.Lock()

        # 状态快照存储: context → List[StateCheckpoint]
        self._checkpoints: Dict[str, List[StateCheckpoint]] = {}
        self._checkpoints_lock = threading.Lock()

        # 锁
        self._lock = asyncio.Lock()

        # 部分成功追踪
        self._partial_results: Dict[str, List[Any]] = {}
        self._partial_lock = threading.Lock()

        # 统计
        self.total_recoveries = 0
        self.successful_recoveries = 0
        self.failed_recoveries = 0
        self._stats_lock = threading.Lock()

    # ── 策略注册 ───────────────────────────────────────────

    def register_strategy(
        self,
        context: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter_factor: float = DEFAULT_JITTER_FACTOR,
        retry_on: Optional[Callable[[Exception], bool]] = None,
        degrade_on: Optional[Callable[[Exception], bool]] = None,
        fallback_handler: Optional[Callable[..., Awaitable[Any]]] = None,
    ) -> None:
        """注册错误恢复策略。

        Args:
            context: 上下文标识, e.g. "api_call", "db_write"
            max_retries: 最大重试次数
            base_delay: 退避基延迟
            max_delay: 退避最大延迟
            jitter_factor: 抖动因子
            retry_on: 判定是否可重试的函数 (Exception → bool)
            degrade_on: 判定是否应降级的函数 (Exception → bool)
            fallback_handler: 降级处理函数
        """
        with self._strategies_lock:
            self._strategies[context] = {
                "max_retries": max_retries,
                "base_delay": base_delay,
                "max_delay": max_delay,
                "jitter_factor": jitter_factor,
                "retry_on": retry_on,
                "degrade_on": degrade_on,
            }

        if fallback_handler:
            with self._degradation_lock:
                self._degradation_handlers[context] = fallback_handler

        logger.info(
            f"Registered recovery strategy for '{context}': "
            f"max_retries={max_retries}, base_delay={base_delay}s"
        )

    def unregister_strategy(self, context: str, **kw) -> bool:
        """注销策略。"""
        removed = False
        with self._strategies_lock:
            if context in self._strategies:
                del self._strategies[context]
                removed = True
        with self._degradation_lock:
            self._degradation_handlers.pop(context, None)
        return removed

    # ── 错误分类 + 计划生成 ────────────────────────────────

    def classify_and_plan(
        self,
        context: str,
        error: Exception,
        state_for_rollback: Any = None,
        metadata: Dict[str, Any] = None,
    ) -> RecoveryPlan:
        """分类错误并生成恢复计划。

        Args:
            context: 错误上下文
            error: 原始异常
            state_for_rollback: 需要回滚的状态数据 (可选)
            metadata: 额外元数据

        Returns:
            RecoveryPlan: 恢复计划
        """
        # 分类
        category = self.classifier.classify(error, context)

        # 获取策略
        strategy = self._get_strategy(context)
        max_retries = strategy.get("max_retries", DEFAULT_MAX_RETRIES)
        base_delay = strategy.get("base_delay", DEFAULT_BASE_DELAY)
        max_delay = strategy.get("max_delay", DEFAULT_MAX_DELAY)
        jitter_factor = strategy.get("jitter_factor", DEFAULT_JITTER_FACTOR)
        retry_on = strategy.get("retry_on")
        degrade_on = strategy.get("degrade_on")

        # 自定义判定覆盖
        if retry_on and retry_on(error):
            category = ErrorCategory.RETRYABLE
        if degrade_on and degrade_on(error):
            category = ErrorCategory.DEGRADABLE

        plan = RecoveryPlan(
            error_category=category,
            original_error=error,
            context=context,
            max_retries=max_retries,
            metadata=metadata or {},
        )

        # 根据分类生成恢复步骤
        if category == ErrorCategory.RETRYABLE:
            plan.steps = self._build_retry_steps(
                max_retries, base_delay, max_delay, jitter_factor
            )
        elif category == ErrorCategory.DEGRADABLE:
            plan.steps = self._build_degrade_steps(context, error)
        elif category == ErrorCategory.FATAL:
            plan.steps = self._build_fatal_steps(error)
            plan.status = RecoveryStatus.FAILED

        # 如果有回滚状态, 在步骤前面插入 snapshot + rollback
        if state_for_rollback is not None:
            checkpoint = self.save_checkpoint(context, state_for_rollback)

            rollback_step = RecoveryStep(
                step_type=RecoveryStepType.ROLLBACK,
                description=f"Rollback to checkpoint at {checkpoint.timestamp}",
                handler=self._create_rollback_handler(context, checkpoint),
                metadata={"checkpoint_timestamp": checkpoint.timestamp},
            )
            plan.steps.insert(0, rollback_step)

        logger.info(
            f"Recovery plan {plan.id} for '{context}': "
            f"category={category.value}, steps={len(plan.steps)}"
        )
        return plan

    def _build_retry_steps(
        self,
        max_retries: int,
        base_delay: float,
        max_delay: float,
        jitter_factor: float,
    ) -> List[RecoveryStep]:
        """构建重试步骤序列。"""
        steps = []
        for attempt in range(max_retries):
            delay = calculate_backoff(attempt, base_delay, max_delay, jitter_factor)
            steps.append(RecoveryStep(
                step_type=RecoveryStepType.BACKOFF_WAIT,
                description=f"Backoff wait {attempt + 1}/{max_retries}",
                timeout=delay + 5,
                metadata={"attempt": attempt + 1, "delay_seconds": delay},
            ))
            steps.append(RecoveryStep(
                step_type=RecoveryStepType.RETRY,
                description=f"Retry attempt {attempt + 1}/{max_retries}",
                metadata={"attempt": attempt + 1},
            ))
        return steps

    def _build_degrade_steps(self, context: str, error: Exception, **kw) -> List[RecoveryStep]:
        """构建降级步骤。"""
        steps = [
            RecoveryStep(
                step_type=RecoveryStepType.LOG,
                description=f"Logging degradable error: {str(error)[:100]}",
            ),
        ]
        if context in self._degradation_handlers:
            steps.append(RecoveryStep(
                step_type=RecoveryStepType.DEGRADE,
                description=f"Execute fallback for '{context}'",
                handler=self._degradation_handlers[context],
                metadata={"context": context},
            ))
        else:
            steps.append(RecoveryStep(
                step_type=RecoveryStepType.DEGRADE,
                description=f"No fallback registered for '{context}' — graceful skip",
            ))
        return steps

    def _build_fatal_steps(self, error: Exception, **kw) -> List[RecoveryStep]:
        """构建致命错误步骤 (仅记录日志 + 通知)。"""
        return [
            RecoveryStep(
                step_type=RecoveryStepType.LOG,
                description=f"Fatal error: {str(error)[:200]}",
            ),
            RecoveryStep(
                step_type=RecoveryStepType.NOTIFY,
                description="Notify on-call about fatal error",
            ),
        ]

    # ── 恢复执行 ───────────────────────────────────────────

    async def execute_recovery(
        self,
        plan: RecoveryPlan,
        retry_handler: Optional[Callable[..., Awaitable[Any]]] = None,
        retry_args: Dict[str, Any] = None,
    ) -> Any:
        """执行恢复计划。

        Args:
            plan: RecoveryPlan 实例
            retry_handler: 重试时调用的原始操作函数
            retry_args: 重试函数的参数

        Returns:
            Any: 最后一个成功步骤的结果, 或降级结果, 或 None (致命错误)
        """
        if plan.status in (RecoveryStatus.COMPLETED, RecoveryStatus.FAILED):
            if plan.status == RecoveryStatus.COMPLETED:
                return plan.steps[-1].result if plan.steps else None
            raise RuntimeError(f"Recovery plan {plan.id} already failed: {plan.original_error}")

        plan.status = RecoveryStatus.RUNNING
        last_result = None

        logger.info(f"Executing recovery plan {plan.id}: {len(plan.steps)} steps")

        for i, step in enumerate(plan.steps):
            step.status = RecoveryStatus.RUNNING
            step.started_at = time.time()

            try:
                if step.step_type == RecoveryStepType.BACKOFF_WAIT:
                    delay = step.metadata.get("delay_seconds", DEFAULT_BASE_DELAY)
                    logger.debug(f"Backoff wait: {delay:.2f}s")
                    await asyncio.sleep(delay)
                    step.result = {"waited": delay}
                    step.status = RecoveryStatus.COMPLETED

                elif step.step_type == RecoveryStepType.RETRY:
                    if retry_handler:
                        result = await asyncio.wait_for(
                            retry_handler(**(retry_args or {})),
                            timeout=step.timeout,
                        )
                        step.result = result
                        last_result = result
                        step.status = RecoveryStatus.COMPLETED
                        # 重试成功 → 计划完成
                        plan.status = RecoveryStatus.COMPLETED
                        self._record_success()
                        logger.info(
                            f"Recovery plan {plan.id} succeeded at step {i + 1}/{len(plan.steps)}"
                        )
                        return result
                    else:
                        step.error = "No retry handler provided"
                        step.status = RecoveryStatus.FAILED

                elif step.step_type == RecoveryStepType.DEGRADE:
                    if step.handler:
                        result = await asyncio.wait_for(
                            step.handler(),
                            timeout=step.timeout,
                        )
                        step.result = result
                        last_result = result
                    step.status = RecoveryStatus.COMPLETED
                    plan.status = RecoveryStatus.COMPLETED
                    self._record_success()
                    logger.info(f"Recovery plan {plan.id} completed via degradation")
                    return last_result

                elif step.step_type == RecoveryStepType.ROLLBACK:
                    if step.handler:
                        await asyncio.wait_for(
                            step.handler(),
                            timeout=step.timeout,
                        )
                    step.status = RecoveryStatus.COMPLETED
                    logger.info(f"Rollback completed for plan {plan.id}")

                elif step.step_type == RecoveryStepType.CUSTOM:
                    if step.handler:
                        result = await asyncio.wait_for(
                            step.handler(**step.handler_args),
                            timeout=step.timeout,
                        )
                        step.result = result
                        last_result = result
                    step.status = RecoveryStatus.COMPLETED

                elif step.step_type == RecoveryStepType.LOG:
                    logger.error(f"[Recovery {plan.id}] {step.description}")
                    step.status = RecoveryStatus.COMPLETED

                elif step.step_type == RecoveryStepType.NOTIFY:
                    logger.warning(f"[Recovery {plan.id}] NOTIFICATION: {step.description}")
                    step.status = RecoveryStatus.COMPLETED

            except asyncio.TimeoutError:
                step.error = f"Timeout after {step.timeout}s"
                step.status = RecoveryStatus.FAILED
                logger.error(f"Recovery step {i} timeout: {step.description}")

            except Exception as e:
                step.error = str(e)
                step.status = RecoveryStatus.FAILED
                logger.error(
                    f"Recovery step {i} failed: {step.description} — {e}",
                    exc_info=True,
                )

            finally:
                step.completed_at = time.time()

            # 如果步骤失败且是致命步骤, 整个计划失败
            if step.status == RecoveryStatus.FAILED:
                if plan.error_category == ErrorCategory.FATAL:
                    plan.status = RecoveryStatus.FAILED
                    self._record_failure()
                    raise RuntimeError(
                        f"Recovery plan {plan.id} failed at step {i + 1}: {step.error}"
                    )

        # 所有步骤执行完毕
        if plan.status == RecoveryStatus.RUNNING:
            plan.status = RecoveryStatus.PARTIAL

        self._record_failure()
        return last_result

    # ── 状态回滚 ───────────────────────────────────────────

    def save_checkpoint(self, context: str, state: Any, **kw) -> StateCheckpoint:
        """保存状态快照 (用于后续回滚)。

        Args:
            context: 上下文标识
            state: 需要保存的状态 (会被深拷贝)

        Returns:
            StateCheckpoint
        """
        try:
            state_copy = copy.deepcopy(state)
        except Exception:
            # 深拷贝失败时使用浅拷贝
            state_copy = copy.copy(state)
            logger.warning(f"Deep copy failed for checkpoint '{context}', using shallow copy")

        checkpoint = StateCheckpoint(context=context, state=state_copy)

        with self._checkpoints_lock:
            if context not in self._checkpoints:
                self._checkpoints[context] = []
            self._checkpoints[context].append(checkpoint)

        logger.debug(f"Saved checkpoint for '{context}': {len(self._checkpoints[context])} total")
        return checkpoint

    def restore_checkpoint(self, context: str, index: int = -1, **kw) -> Optional[Any]:
        """恢复到指定 checkpoint。

        Args:
            context: 上下文标识
            index: checkpoint 索引 (-1 = 最新)

        Returns:
            Any: 恢复后的状态, 或 None
        """
        with self._checkpoints_lock:
            checkpoints = self._checkpoints.get(context, [])
            if not checkpoints:
                logger.warning(f"No checkpoints for '{context}'")
                return None

            try:
                checkpoint = checkpoints[index]
            except IndexError:
                logger.warning(f"Invalid checkpoint index {index} for '{context}'")
                return None

            logger.info(f"Restored checkpoint for '{context}': {checkpoint.timestamp}")
            return copy.deepcopy(checkpoint.state)

    def clear_checkpoints(self, context: str = None, **kw) -> int:
        """清除 checkpoint。

        Args:
            context: 指定上下文 (None = 全部)

        Returns:
            int: 清除的 checkpoint 数
        """
        with self._checkpoints_lock:
            if context is None:
                count = sum(len(c) for c in self._checkpoints.values())
                self._checkpoints.clear()
            else:
                count = len(self._checkpoints.pop(context, []))
        logger.info(f"Cleared {count} checkpoints")
        return count

    def _create_rollback_handler(self, context: str, checkpoint: StateCheckpoint, **kw):
        """创建回滚 handler 闭包。"""
        async def _rollback():
            self.restore_checkpoint(context)
        return _rollback

    # ── 部分成功处理 ───────────────────────────────────────

    def record_partial_result(self, context: str, result: Any, **kw) -> None:
        """记录部分成功的结果。"""
        with self._partial_lock:
            if context not in self._partial_results:
                self._partial_results[context] = []
            self._partial_results[context].append(result)
        logger.debug(f"Recorded partial result for '{context}': {len(self._partial_results[context])} total")

    def get_partial_results(self, context: str, **kw) -> List[Any]:
        """获取部分成功的结果。"""
        with self._partial_lock:
            return list(self._partial_results.get(context, []))

    def clear_partial_results(self, context: str = None, **kw) -> int:
        """清除部分成功记录。"""
        with self._partial_lock:
            if context is None:
                count = sum(len(r) for r in self._partial_results.values())
                self._partial_results.clear()
            else:
                count = len(self._partial_results.pop(context, []))
        return count

    # ── 统计 ───────────────────────────────────────────────

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取恢复统计。"""
        with self._stats_lock:
            total = self.total_recoveries
            success_rate = (
                self.successful_recoveries / total * 100
            ) if total > 0 else 0.0

        return {
            "total_recoveries": total,
            "successful_recoveries": self.successful_recoveries,
            "failed_recoveries": self.failed_recoveries,
            "success_rate_pct": round(success_rate, 1),
            "active_strategies": len(self._strategies),
            "active_degradation_handlers": len(self._degradation_handlers),
            "checkpoint_contexts": len(self._checkpoints),
        }

    # ── 内部 ───────────────────────────────────────────────

    def _get_strategy(self, context: str, **kw) -> Dict[str, Any]:
        """获取上下文策略 (带默认值)。"""
        with self._strategies_lock:
            return self._strategies.get(context, {})

    def _record_success(self, **kw) -> None:
        with self._stats_lock:
            self.total_recoveries += 1
            self.successful_recoveries += 1

    def _record_failure(self, **kw) -> None:
        with self._stats_lock:
            self.total_recoveries += 1
            self.failed_recoveries += 1


# ═══════════════════════════════════════════════════════════
# 全局实例管理
# ═══════════════════════════════════════════════════════════

_global_error_recovery: Optional[ErrorRecovery] = None
_global_lock = threading.Lock()


def get_error_recovery() -> ErrorRecovery:
    """惰性初始化全局 ErrorRecovery 单例。

    线程安全, 确保整个进程只有一个 ErrorRecovery 实例。

    Returns:
        ErrorRecovery: 全局错误恢复引擎
    """
    global _global_error_recovery
    if _global_error_recovery is None:
        with _global_lock:
            if _global_error_recovery is None:
                _global_error_recovery = ErrorRecovery()
                logger.info("Created global ErrorRecovery instance")
    return _global_error_recovery


# ═══════════════════════════════════════════════════════════
# CLI 诊断工具
# ═══════════════════════════════════════════════════════════

async def _cli_main():
    """CLI 诊断入口。"""
    print("=" * 60)
    print("  meshctx Error Recovery — 诊断工具")
    print("=" * 60)

    recovery = ErrorRecovery()

    # 1. 错误分类
    print("\n[1] 错误分类测试:")
    test_errors = [
        TimeoutError("connection timed out"),
        ConnectionRefusedError("port 5432 refused"),
        ValueError("invalid config format"),
        PermissionError("access denied to /etc/shadow"),
    ]
    for err in test_errors:
        category = recovery.classifier.classify(err, "api_call")
        print(f"    {type(err).__name__}: {err} → {category.value}")

    # 2. 注册策略
    print("\n[2] 注册恢复策略...")
    recovery.register_strategy("api_call", max_retries=3, base_delay=0.5, max_delay=10)

    # 3. 生成恢复计划
    print("\n[3] 生成恢复计划...")
    error = TimeoutError("API request timed out")
    plan = recovery.classify_and_plan("api_call", error)
    print(f"    计划: {plan.id}")
    print(f"    分类: {plan.error_category.value}")
    print(f"    步骤数: {len(plan.steps)}")
    for s in plan.steps:
        print(f"      - {s.step_type.value}: {s.description}")

    # 4. 退避计算
    print("\n[4] 指数退避 + 抖动:")
    for i in range(5):
        delay = calculate_backoff(i, base_delay=1.0)
        print(f"    attempt {i}: {delay:.2f}s")

    # 5. 状态快照
    print("\n[5] 状态快照/回滚:")
    original_state = {"db": "connected", "cache": {"key1": "val1"}, "counter": 42}
    recovery.save_checkpoint("transaction_1", original_state)
    restored = recovery.restore_checkpoint("transaction_1")
    print(f"    原始: {original_state}")
    print(f"    恢复: {restored}")
    print(f"    一致: {original_state == restored}")

    # 6. Recovery plan execution
    print("\n[6] 执行恢复计划 (重试场景)...")
    attempts = []

    async def simulate_api():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("Simulated timeout")
        return {"status": "ok", "data": "response"}

    plan2 = recovery.classify_and_plan("api_call", TimeoutError("simulated"))
    try:
        result = await recovery.execute_recovery(plan2, retry_handler=simulate_api)
        print(f"    结果: {result}")
        print(f"    尝试次数: {len(attempts)}")
    except RuntimeError as e:
        print(f"    失败: {e}")

    # 7. 统计
    stats = recovery.get_stats()
    print(f"\n[7] 统计: {stats}")

    print("\n✅ ErrorRecovery 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_cli_main())

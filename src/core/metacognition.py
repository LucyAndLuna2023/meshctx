"""
meshctx Meta-Cognition Loop — full implementation (v3.115.16)
Self-evaluation → pattern extraction → knowledge graph update → behavior adjustment.
Implements the core "gets smarter every time" claim from meshctx.com.

真实开源实现（2026-08 批次B 审计）：任务评估 / 模式学习 / 策略置信度 /
行为调整 / 内核插件。纯 stdlib。
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.metacognition")

# jieba 中文分词：可用则用，不可用则回退到英文单词 + 中文 bigram
try:
    import jieba  # type: ignore

    _HAS_JIEBA = True
except ImportError:  # pragma: no cover - 依赖环境
    jieba = None  # type: ignore[assignment]
    _HAS_JIEBA = False

# 关键词提取用的停用词
_STOPWORDS = set(
    """
    的 了 是 在 我 你 他 她 它 们 这 那 有 和 与 就 都 而 及 或 被 把 让 对 从 向 为 等 之 其
    一个 我们 你们 他们 这个 那个 这些 那些 可以 进行 以及 因为 所以 但是 如果 没有 不是 就是
    还是 已经 什么 怎么 为什么 这样 那样 自己 时候 现在 今天 明天 目前 当前 请 帮 需要 任务
    the a an and or of to in on for with by at from is are was were be been being it its this that
    these those you your we our they their i me my he him his she her do does did done not no yes
    """.split()
)


class TaskStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    PARTIAL = 'partial'


class Strategy(str, Enum):
    """Learned strategies for task execution."""

    DECOMPOSE = 'decompose'
    PARALLEL = 'parallel'
    SEQUENTIAL = 'sequential'
    DELEGATE = 'delegate'
    RETRY = 'retry'
    FALLBACK = 'fallback'


@dataclass
class LearnedPattern:
    """A pattern extracted from task execution history."""

    pattern_id: str = None
    trigger_keywords: List[str] = None
    successful_strategy: Strategy = None
    failure_reasons: List[str] = None
    success_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float = 0.0
    last_seen: float = None
    confidence: float = 0.0

    def __post_init__(self):
        if not self.pattern_id:
            self.pattern_id = uuid.uuid4().hex[:12]
        if self.trigger_keywords is None:
            self.trigger_keywords = []
        if self.failure_reasons is None:
            self.failure_reasons = []

    def success_rate(self) -> float:
        """成功率（Laplace 平滑，避免 0/0）。"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return (self.success_count + 1.0) / (total + 2.0)


@dataclass
class MetaEvaluation:
    """Result of a meta-cognition evaluation cycle."""

    task_id: str = None
    task_description: str = None
    status: TaskStatus = None
    duration_ms: float = None
    patterns_matched: List[str] = None
    patterns_learned: List[str] = None
    strategy_used: Optional[Strategy] = None
    insights: List[str] = None
    improvement_suggestions: List[str] = None
    timestamp: float = None

    def __post_init__(self):
        if self.patterns_matched is None:
            self.patterns_matched = []
        if self.patterns_learned is None:
            self.patterns_learned = []
        if self.insights is None:
            self.insights = []
        if self.improvement_suggestions is None:
            self.improvement_suggestions = []
        if self.timestamp is None:
            self.timestamp = time.time()


@dataclass
class TaskEvaluation:
    """A task evaluation record (kernel / dashboard facing view)."""

    task_id: str = ''
    description: str = ''
    status: TaskStatus = TaskStatus.PENDING
    duration_ms: float = 0.0
    quality_score: float = 0.0
    strategy_used: Optional[Strategy] = None
    evaluation: Optional[MetaEvaluation] = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class ErrorCategory(str, Enum):
    """错误分类：权限 / 网络 / 超时 / 工具 / 知识不足 / 未知。"""

    PERMISSION = 'permission'
    NETWORK = 'network'
    TIMEOUT = 'timeout'
    TOOL_ERROR = 'tool_error'
    KNOWLEDGE_GAP = 'knowledge_gap'
    UNKNOWN = 'unknown'


class MetaCognitionEngine:
    """Post-task self-evaluation and continuous learning engine."""

    # 策略连续失败次数达到该值 → 建议切换
    _STRATEGY_FAIL_STREAK = 3
    # 单任务耗时阈值（ms）：超过则建议分解
    _SLOW_TASK_MS = 300_000.0

    def __init__(self):
        self.patterns: Dict[str, LearnedPattern] = {}
        self.strategy_outcomes: Dict[str, List[bool]] = {}
        self.evaluations: List[MetaEvaluation] = []
        self._evaluation_count = 0
        self._lock = threading.RLock()
        self._pattern_seq = 0

    # ── 主入口 ────────────────────────────────────────────
    def evaluate(
        self,
        task_id: str,
        task_description: str,
        status: TaskStatus,
        duration_ms: float,
        strategy_used: Strategy = None,
        error_message: str = None,
        tool_calls: List[str] = None,
    ) -> MetaEvaluation:
        """Run a meta-cognition cycle on a completed task."""
        with self._lock:
            keywords = self._extract_keywords(task_description or "")
            matched = self._match_patterns(keywords)
            insights = self._self_evaluate(
                task_description or "", status, duration_ms, error_message
            )
            strategy = strategy_used or self._infer_strategy(
                task_description or "", status
            )
            learned = self._learn_from_outcome(
                task_description or "",
                keywords,
                status,
                strategy,
                duration_ms,
                error_message,
            )
            suggestions = self._adjust_strategies(status, strategy, duration_ms)
            evaluation = MetaEvaluation(
                task_id=task_id,
                task_description=task_description,
                status=status,
                duration_ms=duration_ms,
                patterns_matched=matched,
                patterns_learned=[p.pattern_id for p in learned],
                strategy_used=strategy,
                insights=insights,
                improvement_suggestions=suggestions,
            )
            self.evaluations.append(evaluation)
            self._evaluation_count += 1
            return evaluation

    def _infer_strategy(self, description: str, status: TaskStatus) -> Strategy:
        """无显式策略时，按任务描述与状态推断一个初始策略。"""
        text = (description or "").lower()
        if status in (TaskStatus.FAILED, TaskStatus.PARTIAL):
            return Strategy.RETRY
        if any(k in text for k in ("分析", "调研", "研究", "研究", "analyze", "research")):
            return Strategy.SEQUENTIAL
        if any(k in text for k in ("并行", "批量", "多个", "parallel", "batch")):
            return Strategy.PARALLEL
        if any(k in text for k in ("委派", "分发", "delegate")):
            return Strategy.DELEGATE
        if len(text) >= 40:
            return Strategy.DECOMPOSE
        return Strategy.SEQUENTIAL

    # ── 自我评估 ──────────────────────────────────────────
    def _self_evaluate(self, description: str, status: TaskStatus, duration_ms: float, error: str) -> List[str]:
        """Generate self-evaluation insights."""
        insights: List[str] = []
        if status == TaskStatus.SUCCESS:
            insights.append("任务成功完成，当前执行策略有效，可继续保持。")
            insights.append("记录成功路径以便复用。")
        elif status == TaskStatus.FAILED:
            insights.append("任务失败，需要复盘失败原因并调整策略。")
            if error:
                insights.append(f"失败线索: {error[:200]}")
            else:
                insights.append("无明确错误信息，建议增加验证步骤定位问题。")
        elif status == TaskStatus.PARTIAL:
            insights.append("任务部分完成，存在遗漏项，需补充检查。")
        else:
            insights.append("任务状态未明确，建议补充结果校验。")
        if duration_ms is not None and duration_ms > self._SLOW_TASK_MS:
            insights.append(
                f"任务耗时 {duration_ms / 1000:.1f}s 偏长，建议分解为更小的子任务并行推进。"
            )
        if description and "复杂" in description:
            insights.append("任务描述含'复杂'，已建议使用分解策略降低认知负载。")
        return insights

    # ── 关键词 / 模式 ─────────────────────────────────────
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords for pattern matching.

        中文用 jieba 分词（缺失时回退为英文单词 + 中文 bigram）。
        """
        text = (text or "").lower()
        tokens: List[str] = []
        if _HAS_JIEBA and jieba is not None:
            for piece in jieba.cut(text):
                piece = piece.strip().lower()
                if not piece:
                    continue
                if re.search(r"[\u4e00-\u9fff]", piece):
                    tokens.append(piece)
                else:
                    tokens.extend(re.findall(r"[a-z0-9]+", piece))
        else:  # pragma: no cover - jieba 缺失回退
            tokens.extend(re.findall(r"[a-z0-9]{2,}", text))
            for cjk in re.findall(r"[\u4e00-\u9fff]+", text):
                if len(cjk) == 1:
                    tokens.append(cjk)
                else:
                    for i in range(len(cjk) - 1):
                        tokens.append(cjk[i:i + 2])
        seen: List[str] = []
        for t in tokens:
            if t in _STOPWORDS:
                continue
            if t.isdigit() and len(t) > 6:
                continue
            if len(t) == 1 and not re.search(r"[\u4e00-\u9fff]", t):
                continue
            if t not in seen:
                seen.append(t)
        return seen[:20]

    def _match_patterns(self, keywords: List[str]) -> List[str]:
        """Find existing patterns matching the keywords."""
        kw_set = set(keywords)
        scored: List[Tuple[int, str]] = []
        for pid, pattern in self.patterns.items():
            overlap = len(kw_set & set(pattern.trigger_keywords))
            if overlap > 0:
                scored.append((overlap, pid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [pid for _, pid in scored]

    # ── 学习 ──────────────────────────────────────────────
    def _learn_from_outcome(
        self,
        description: str,
        keywords: List[str],
        status: TaskStatus,
        strategy: Strategy,
        duration_ms: float,
        error: str,
    ) -> List[LearnedPattern]:
        """Learn new patterns from task outcome."""
        kw_set = set(keywords)
        best_pid: Optional[str] = None
        best_overlap = 0
        for pid, pattern in self.patterns.items():
            overlap = len(kw_set & set(pattern.trigger_keywords))
            if overlap > best_overlap:
                best_overlap = overlap
                best_pid = pid

        if best_pid is not None and best_overlap >= 2:
            pattern = self.patterns[best_pid]
        else:
            self._pattern_seq += 1
            pattern = LearnedPattern(
                pattern_id=f"pat_{self._pattern_seq}",
                trigger_keywords=keywords,
                successful_strategy=strategy,
            )
            self.patterns[pattern.pattern_id] = pattern

        # 更新统计
        if status == TaskStatus.SUCCESS:
            pattern.success_count += 1
            pattern.successful_strategy = strategy
        elif status == TaskStatus.FAILED:
            pattern.failure_count += 1
            if error and error not in pattern.failure_reasons:
                pattern.failure_reasons.append(error[:200])
        # 平均耗时（增量均值）
        n = pattern.success_count + pattern.failure_count
        if duration_ms is not None and n > 0:
            pattern.avg_duration_ms = (
                pattern.avg_duration_ms * (n - 1) + float(duration_ms)
            ) / n
        pattern.last_seen = time.time()
        pattern.confidence = self._calc_confidence(pattern)
        return [pattern]

    def _adjust_strategies(self, status: TaskStatus, strategy: Strategy, duration_ms: float) -> List[str]:
        """Adjust strategy confidence scores based on outcome."""
        suggestions: List[str] = []
        if strategy is not None:
            self.strategy_outcomes.setdefault(strategy.value, []).append(
                status == TaskStatus.SUCCESS
            )
        if status == TaskStatus.FAILED:
            if strategy is not None:
                streak = self._strategy_fail_streak(strategy)
                if streak >= self._STRATEGY_FAIL_STREAK:
                    alt = self.best_strategy()
                    if alt is not None and alt != strategy:
                        suggestions.append(
                            f"策略 '{strategy.value}' 连续失败 {streak} 次，"
                            f"建议切换为当前最优策略 '{alt.value}'。"
                        )
                    else:
                        suggestions.append(
                            f"策略 '{strategy.value}' 连续失败 {streak} 次，"
                            "建议切换为简单顺序执行(sequential)并增加验证步骤。"
                        )
                elif strategy == Strategy.RETRY:
                    suggestions.append("重试仍未成功，建议改用备用方案(fallback)。")
                else:
                    suggestions.append(
                        f"策略 '{strategy.value}' 失败，建议重试(retry)或拆解(decompose)。"
                    )
            if duration_ms is not None and duration_ms > self._SLOW_TASK_MS:
                suggestions.append("失败任务耗时过长，建议拆分为更小步骤并增加中间校验。")
        elif status == TaskStatus.SUCCESS:
            if strategy is not None:
                suggestions.append(f"策略 '{strategy.value}' 成功，强化该策略置信度。")
        return suggestions

    def _strategy_fail_streak(self, strategy: Strategy) -> int:
        outcomes = self.strategy_outcomes.get(strategy.value, [])
        streak = 0
        for ok in reversed(outcomes):
            if ok:
                break
            streak += 1
        return streak

    def _calc_confidence(self, pattern: LearnedPattern) -> float:
        """Bayesian confidence estimate for a pattern."""
        total = pattern.success_count + pattern.failure_count
        if total == 0:
            return 0.0
        # Beta 后验均值 (α=success+1, β=failure+1)
        alpha = pattern.success_count + 1.0
        beta = pattern.failure_count + 1.0
        return round(alpha / (alpha + beta), 4)

    # ── 策略推荐 ──────────────────────────────────────────
    def best_strategy(self) -> Optional[Strategy]:
        """Get the current best-performing strategy."""
        best: Optional[Strategy] = None
        best_rate = -1.0
        for value, outcomes in self.strategy_outcomes.items():
            if not outcomes:
                continue
            rate = sum(1 for o in outcomes if o) / len(outcomes)
            if rate > best_rate:
                best_rate = rate
                best = Strategy(value)
        return best

    def recommend_strategy(self, task_description: str) -> Tuple[Strategy, float]:
        """Recommend best strategy for a new task based on learned patterns."""
        keywords = self._extract_keywords(task_description or "")
        kw_set = set(keywords)
        best_pattern: Optional[LearnedPattern] = None
        best_score = -1.0
        for pattern in self.patterns.values():
            overlap = len(kw_set & set(pattern.trigger_keywords))
            if overlap <= 0:
                continue
            score = pattern.confidence * (1.0 + overlap * 0.2)
            if score > best_score:
                best_score = score
                best_pattern = pattern
        if best_pattern is not None and best_pattern.successful_strategy is not None:
            return best_pattern.successful_strategy, best_pattern.confidence
        fallback = self.best_strategy()
        if fallback is not None:
            return fallback, 0.6
        return Strategy.SEQUENTIAL, 0.5

    # ── 统计 / 重置 ───────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            strategy_stats: Dict[str, dict] = {}
            for value, outcomes in self.strategy_outcomes.items():
                total = len(outcomes)
                ok = sum(1 for o in outcomes if o)
                strategy_stats[value] = {
                    "attempts": total,
                    "successes": ok,
                    "success_rate": round(ok / total, 4) if total else 0.0,
                }
            total_eval = max(1, self._evaluation_count)
            overall_ok = sum(
                1 for e in self.evaluations if e.status == TaskStatus.SUCCESS
            )
            return {
                "evaluations": self._evaluation_count,
                "patterns": len(self.patterns),
                "strategies": strategy_stats,
                "overall_success_rate": round(overall_ok / total_eval, 4),
                "best_strategy": (
                    self.best_strategy().value if self.best_strategy() else None
                ),
            }

    def reset(self):
        with self._lock:
            self.patterns.clear()
            self.strategy_outcomes.clear()
            self.evaluations.clear()
            self._evaluation_count = 0
            self._pattern_seq = 0


class PatternEngine:
    """独立模式引擎：存储与匹配 LearnedPattern（kernel 集成用）。"""

    def __init__(self):
        self.engine = MetaCognitionEngine()

    def match(self, keywords: List[str]) -> List[str]:
        return self.engine._match_patterns(list(keywords or []))

    def learn(
        self,
        description: str,
        status: TaskStatus,
        strategy: Strategy = None,
        duration_ms: float = 0.0,
        error: str = None,
    ) -> List[LearnedPattern]:
        keywords = self.engine._extract_keywords(description or "")
        return self.engine._learn_from_outcome(
            description or "",
            keywords,
            status,
            strategy or Strategy.SEQUENTIAL,
            duration_ms,
            error,
        )

    def patterns(self) -> List[LearnedPattern]:
        return list(self.engine.patterns.values())

    def stats(self) -> dict:
        return {
            "patterns": len(self.engine.patterns),
            "evaluations": self.engine._evaluation_count,
        }


class BehaviorAdjuster:
    """行为调整器 — 根据工具成功率调整执行行为参数。"""

    def __init__(self):
        self.tool_stats: Dict[str, Dict[str, int]] = {}
        self._lock = threading.RLock()

    def record_tool_result(self, tool_name: str, success: bool):
        """记录一次工具调用结果。"""
        with self._lock:
            stats = self.tool_stats.setdefault(
                str(tool_name), {"success": 0, "failure": 0}
            )
            if success:
                stats["success"] += 1
            else:
                stats["failure"] += 1

    def get_tool_stats(self) -> dict:
        """返回各工具成功率统计。"""
        with self._lock:
            out: Dict[str, dict] = {}
            for name, s in self.tool_stats.items():
                total = s["success"] + s["failure"]
                out[name] = {
                    "success": s["success"],
                    "failure": s["failure"],
                    "total": total,
                    "rate": round(s["success"] / total, 4) if total else 0.0,
                }
            return out

    def get_strategy(self) -> dict:
        """根据工具成功率生成执行策略参数。"""
        with self._lock:
            rates = [
                s["success"] / (s["success"] + s["failure"])
                for s in self.tool_stats.values()
                if (s["success"] + s["failure"]) > 0
            ]
            if not rates:
                worst = 1.0
            else:
                worst = min(rates)
            if worst < 0.3:
                return {
                    "parallelism": "low",
                    "verification": "high",
                    "retry": "enabled",
                    "fallback": "prefer_simple",
                    "reason": f"工具成功率偏低({worst:.0%})，降低并行度、加强验证",
                }
            if worst < 0.6:
                return {
                    "parallelism": "medium",
                    "verification": "medium",
                    "retry": "enabled",
                    "fallback": "normal",
                    "reason": f"部分工具成功率一般({worst:.0%})，适度收敛并行",
                }
            return {
                "parallelism": "normal",
                "verification": "normal",
                "retry": "disabled",
                "fallback": "normal",
                "reason": f"工具状态健康(最低成功率{worst:.0%})，可保持当前行为",
            }


class MetaCognitionPlugin:
    """内核插件：订阅 task.completed 事件，驱动元认知闭环。

    兼容 src.core.kernel 的 Plugin 生命周期（on_load / on_event /
    generate_report）。
    """

    info = type(
        "Info",
        (),
        {
            "name": "metacognition",
            "version": "3.115.16",
            "dependencies": [],
            "category": "cognition",
            "description": "Post-task self-evaluation and continuous learning",
        },
    )()

    state = "active"

    def __init__(self):
        self.engine = MetaCognitionEngine()
        self.behavior = BehaviorAdjuster()
        self._evaluation_count = 0
        self._task_evaluations: Dict[str, TaskEvaluation] = {}
        self._kernel = None

    async def on_load(self, kernel) -> bool:
        """加载：尝试订阅事件总线（内核 stub 时仅记录）。"""
        self._kernel = kernel
        self.state = "active"
        try:
            bus = getattr(kernel, "bus", None) or getattr(kernel, "event_bus", None)
            if bus is not None and hasattr(bus, "subscribe"):
                bus.subscribe("task.completed", self.on_event, plugin_name="metacognition")
        except NotImplementedError:
            logger.info("metacognition: 内核为 stub 模式，事件订阅跳过")
        except Exception as e:  # 事件总线异常不影响插件可用性
            logger.warning("metacognition: 事件订阅失败: %s", e)
        return True

    async def on_unload(self):
        self.state = "inactive"
        return True

    async def on_event(self, event):
        """处理 task.completed 事件 → 元认知评估。"""
        try:
            if getattr(event, "type", None) != "task.completed":
                return
            data = getattr(event, "data", None) or {}
            task_id = str(data.get("task_id", "") or "unknown")
            description = str(data.get("description", "") or "")
            duration_seconds = float(data.get("duration_seconds", 0) or 0)
            tool_calls = data.get("tool_calls", []) or []
            # tool_calls 可能是数量(int)或调用列表(list)
            if isinstance(tool_calls, int):
                tool_calls_list: List[str] = []
                tool_call_count = max(0, tool_calls)
            else:
                tool_calls_list = [str(t) for t in tool_calls]
                tool_call_count = len(tool_calls_list)
            tool_failures = int(data.get("tool_failures", 0) or 0)
            if data.get("error") is not None:
                status = TaskStatus.FAILED
                error = str(data.get("error"))
            elif tool_failures > 0:
                status = TaskStatus.PARTIAL
                error = f"{tool_failures} 次工具调用失败"
            else:
                status = TaskStatus.SUCCESS
                error = None
            evaluation = self.engine.evaluate(
                task_id=task_id,
                task_description=description,
                status=status,
                duration_ms=duration_seconds * 1000.0,
                error_message=error,
                tool_calls=tool_calls_list,
            )
            self._evaluation_count += 1
            self._task_evaluations[task_id] = TaskEvaluation(
                task_id=task_id,
                description=description,
                status=status,
                duration_ms=duration_seconds * 1000.0,
                quality_score=(
                    0.0 if status == TaskStatus.FAILED
                    else (0.5 if status == TaskStatus.PARTIAL else 1.0)
                ),
                strategy_used=evaluation.strategy_used,
                evaluation=evaluation,
            )
        except Exception as e:
            logger.warning("metacognition: 事件处理失败: %s", e)

    def _categorize_error(self, error) -> Tuple[ErrorCategory, str]:
        """对错误信息分类（权限/网络/超时/工具/知识/未知）。"""
        if error is None:
            return ErrorCategory.UNKNOWN, "无错误信息"
        if isinstance(error, dict):
            text = " ".join(str(v) for v in error.values())
        else:
            text = str(error)
        low = text.lower()
        if any(k in low for k in (
            "permission denied", "permission", "access denied", "forbidden",
            "not authorized", "unauthorized", "403",
        )):
            return ErrorCategory.PERMISSION, text[:200]
        if any(k in low for k in (
            "connection", "network", "socket", "dns", "refused",
            "unreachable", "host down", "connect timed out",
        )):
            return ErrorCategory.NETWORK, text[:200]
        if any(k in low for k in ("timed out", "timeout", "deadline exceeded")):
            return ErrorCategory.TIMEOUT, text[:200]
        if any(k in low for k in ("tool", "command failed", "exit code", "traceback", "exception")):
            return ErrorCategory.TOOL_ERROR, text[:200]
        if any(k in low for k in ("not found", "missing", "unknown", "no such", "don't know", "不清楚", "不知道")):
            return ErrorCategory.KNOWLEDGE_GAP, text[:200]
        return ErrorCategory.UNKNOWN, text[:200]

    def generate_report(self) -> dict:
        """生成元认知状态报告。"""
        stats = self.engine.stats()
        return {
            "evaluation_count": self._evaluation_count,
            "status": self.state,
            "patterns": stats["patterns"],
            "best_strategy": stats["best_strategy"],
            "overall_success_rate": stats["overall_success_rate"],
            "strategies": stats["strategies"],
            "behavior": self.behavior.get_strategy(),
            "recent_evaluations": [
                {
                    "task_id": e.task_id,
                    "status": e.status.value,
                    "duration_ms": e.duration_ms,
                    "strategy": e.strategy_used.value if e.strategy_used else None,
                    "insights": e.insights,
                }
                for e in self.engine.evaluations[-10:]
            ],
        }


_engine: Optional[MetaCognitionEngine] = None
_engine_lock = threading.Lock()


def get_meta_cognition() -> MetaCognitionEngine:
    """获取全局 MetaCognitionEngine 单例。"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = MetaCognitionEngine()
    return _engine


# ── 模块级便捷函数（__all__ 兼容）───────────────────────────
def success_rate(pattern: LearnedPattern) -> float:
    return pattern.success_rate()


def evaluate(
    task_id: str,
    task_description: str,
    status: TaskStatus,
    duration_ms: float,
    strategy_used: Strategy = None,
    error_message: str = None,
    tool_calls: List[str] = None,
) -> MetaEvaluation:
    return get_meta_cognition().evaluate(
        task_id, task_description, status, duration_ms,
        strategy_used=strategy_used, error_message=error_message,
        tool_calls=tool_calls,
    )


def best_strategy() -> Optional[Strategy]:
    return get_meta_cognition().best_strategy()


def recommend_strategy(task_description: str) -> Tuple[Strategy, float]:
    return get_meta_cognition().recommend_strategy(task_description)


def stats() -> dict:
    return get_meta_cognition().stats()


def reset():
    return get_meta_cognition().reset()


__all__ = [
    "TaskStatus", "Strategy", "LearnedPattern", "success_rate",
    "MetaEvaluation", "TaskEvaluation", "ErrorCategory", "PatternEngine",
    "BehaviorAdjuster", "MetaCognitionPlugin", "MetaCognitionEngine",
    "evaluate", "best_strategy", "recommend_strategy", "stats", "reset",
    "get_meta_cognition",
]

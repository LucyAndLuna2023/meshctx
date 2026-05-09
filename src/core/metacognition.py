"""
meshctx v1.0 元认知引擎 (Meta-Cognition Engine)

核心循环:
1. Self-Evaluate: 任务后自评(成功/质量/耗时/错误分类)
2. Pattern Extract: 成功模式→自动Skill / 失败模式→防护规则
3. Knowledge Update: 知识图谱自动更新
4. Behavior Adjust: 调整策略权重

这是 meshctx 超越所有竞品的核心差异化能力。
"""
import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.meta")


# ═══════════════════════════════════════════════════════════
# 评估模型
# ═══════════════════════════════════════════════════════════

class TaskStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ErrorCategory(Enum):
    TOOL = "tool_error"           # 工具调用失败
    REASONING = "reasoning_error"  # 推理错误
    KNOWLEDGE = "knowledge_gap"    # 知识不足
    PERMISSION = "permission"      # 权限不足
    NETWORK = "network"           # 网络错误
    RESOURCE = "resource"         # 资源耗尽
    UNKNOWN = "unknown"


@dataclass
class TaskEvaluation:
    """任务评估结果"""
    task_id: str
    task_description: str
    status: TaskStatus
    quality_score: float        # 0-1
    duration_seconds: float
    tool_calls: int
    tool_failures: int
    error_category: Optional[ErrorCategory] = None
    error_detail: str = ""
    success_pattern: str = ""   # 成功的关键因素
    failure_cause: str = ""     # 失败的根本原因
    suggestions: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
# 模式识别引擎
# ═══════════════════════════════════════════════════════════

class PatternEngine:
    """
    模式识别引擎
    - 从成功任务中提取可复用模式
    - 从失败任务中提取防护规则
    - 自动创建Skill / 更新防护
    """

    def __init__(self, min_samples: int = 3):
        self.min_samples = min_samples  # 最少样本数才生成模式
        self._success_history: List[TaskEvaluation] = []
        self._failure_history: List[TaskEvaluation] = []
        self._extracted_patterns: Dict[str, Dict] = {}
        self._guard_rules: List[Dict] = []

    def add_evaluation(self, ev: TaskEvaluation):
        """添加评估结果"""
        if ev.status == TaskStatus.SUCCESS:
            self._success_history.append(ev)
            if len(self._success_history) > 100:
                self._success_history = self._success_history[-100:]
        else:
            self._failure_history.append(ev)
            if len(self._failure_history) > 100:
                self._failure_history = self._failure_history[-100:]

        # 尝试提取模式
        self._extract_patterns()

    def _extract_patterns(self):
        """从历史中提取模式"""
        # 聚类相似成功任务
        success_clusters = self._cluster_by_description(self._success_history)

        for cluster_key, evs in success_clusters.items():
            if len(evs) >= self.min_samples:
                pattern = self._generalize_pattern(evs, "success")
                self._extracted_patterns[cluster_key] = pattern

        # 聚类失败任务
        failure_clusters = self._cluster_by_description(self._failure_history)

        for cluster_key, evs in failure_clusters.items():
            if len(evs) >= self.min_samples:
                pattern = self._generalize_pattern(evs, "failure")
                # 生成防护规则
                rule = self._create_guard_rule(pattern, evs)
                self._guard_rules.append(rule)

    def _cluster_by_description(self, evaluations: List[TaskEvaluation]
                                ) -> Dict[str, List[TaskEvaluation]]:
        """基于任务描述的关键词聚类"""
        clusters = defaultdict(list)
        for ev in evaluations:
            # 提取核心动词+名词
            words = set(ev.task_description.lower().split())
            # 取前3个关键词作为聚类key
            key_words = sorted(words)[:3]
            key = "|".join(key_words)
            clusters[key].append(ev)
        return dict(clusters)

    def _generalize_pattern(self, evs: List[TaskEvaluation],
                            pattern_type: str) -> Dict:
        """泛化模式"""
        avg_duration = sum(e.duration_seconds for e in evs) / len(evs)
        avg_quality = sum(e.quality_score for e in evs) / len(evs)
        common_tools = self._find_common_tools(evs)

        # 提取共同的成功因素
        success_factors = []
        for e in evs:
            if e.success_pattern:
                success_factors.append(e.success_pattern)

        return {
            "type": pattern_type,
            "task_pattern": evs[0].task_description[:100],
            "frequency": len(evs),
            "avg_duration": round(avg_duration, 1),
            "avg_quality": round(avg_quality, 2),
            "common_tools": common_tools,
            "success_factors": list(set(success_factors))[:5],
            "last_seen": max(e.timestamp for e in evs),
        }

    def _find_common_tools(self, evs: List[TaskEvaluation]) -> List[str]:
        """找出共同使用的工具"""
        # 简化实现: 从描述中提取
        tool_keywords = ["read", "write", "search", "terminal", "browser",
                        "deploy", "test", "build", "git", "api"]
        tool_counts = defaultdict(int)
        for ev in evs:
            for tk in tool_keywords:
                if tk in ev.task_description.lower():
                    tool_counts[tk] += 1

        threshold = len(evs) * 0.5
        return [t for t, c in tool_counts.items() if c >= threshold]

    def _create_guard_rule(self, pattern: Dict,
                           evs: List[TaskEvaluation]) -> Dict:
        """从失败模式创建防护规则"""
        common_errors = defaultdict(int)
        for e in evs:
            if e.error_category:
                common_errors[e.error_category.value] += 1

        most_common_error = (
            max(common_errors, key=common_errors.get)
            if common_errors else "unknown"
        )

        return {
            "pattern": pattern["task_pattern"],
            "error_type": most_common_error,
            "frequency": len(evs),
            "suggestion": self._generate_suggestion(most_common_error, evs),
            "created_at": time.time(),
        }

    def _generate_suggestion(self, error_type: str,
                             evs: List[TaskEvaluation]) -> str:
        """生成防护建议"""
        suggestions = {
            "tool_error": "执行前验证工具可用性，添加重试逻辑",
            "reasoning_error": "分解任务为更小步骤，每步验证结果",
            "knowledge_gap": "检索记忆库补充相关知识",
            "permission": "检查权限配置，提示用户授权",
            "network": "添加指数退避重试，使用备用端点",
            "resource": "分批处理，添加资源监控",
        }
        return suggestions.get(error_type, "人工审查此任务类型")

    def get_top_patterns(self, n: int = 5) -> List[Dict]:
        """获取最常用的成功模式"""
        sorted_patterns = sorted(
            self._extracted_patterns.values(),
            key=lambda p: p["frequency"],
            reverse=True,
        )
        return sorted_patterns[:n]

    def get_guard_rules(self) -> List[Dict]:
        return self._guard_rules


# ═══════════════════════════════════════════════════════════
# 行为调整引擎
# ═══════════════════════════════════════════════════════════

class BehaviorAdjuster:
    """
    行为调整引擎
    - 基于历史表现调整策略权重
    - 工具选择优化
    - 上下文组装策略调整
    """

    def __init__(self):
        # 工具成功率
        self._tool_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0}
        )
        # 策略权重
        self._strategy_weights: Dict[str, float] = {
            "tool_selection": 1.0,
            "context_depth": 1.0,        # 上下文深度偏好
            "parallelism": 0.5,          # 并行度偏好
            "verification": 0.7,         # 验证偏好
            "retry_aggressiveness": 0.3, # 重试激进程度
        }
        # 学习率
        self._learning_rate = 0.1

    def record_tool_result(self, tool_name: str, success: bool):
        """记录工具调用结果"""
        key = "success" if success else "failure"
        self._tool_stats[tool_name][key] += 1

        # 调整并行度: 连续失败→降低并行度
        total_failures = sum(
            s["failure"] for s in self._tool_stats.values()
        )
        total_calls = sum(
            s["success"] + s["failure"]
            for s in self._tool_stats.values()
        )
        if total_calls > 10:
            failure_rate = total_failures / total_calls
            # 失败率高→降低并行度,增加验证
            target_parallelism = max(0.1, 1.0 - failure_rate)
            target_verification = min(1.0, 0.5 + failure_rate)

            self._strategy_weights["parallelism"] += (
                self._learning_rate *
                (target_parallelism - self._strategy_weights["parallelism"])
            )
            self._strategy_weights["verification"] += (
                self._learning_rate *
                (target_verification - self._strategy_weights["verification"])
            )

    def get_best_tool(self, task_description: str,
                      available_tools: List[str]) -> List[str]:
        """基于历史成功率推荐最佳工具"""
        scored = []
        for tool in available_tools:
            stats = self._tool_stats.get(tool, {"success": 0, "failure": 0})
            total = stats["success"] + stats["failure"]
            if total == 0:
                scored.append((tool, 0.5))  # 未知工具给中等分数
            else:
                success_rate = stats["success"] / total
                # Wilson score for small samples
                score = (success_rate + 1.96**2 / (2*total)) / (1 + 1.96**2/total)
                scored.append((tool, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in scored]

    def get_strategy(self) -> Dict[str, float]:
        """获取当前策略权重"""
        return dict(self._strategy_weights)

    def get_tool_stats(self) -> Dict[str, Dict]:
        """获取工具统计"""
        return {
            tool: {
                "success": stats["success"],
                "failure": stats["failure"],
                "rate": (
                    stats["success"] / (stats["success"] + stats["failure"])
                    if (stats["success"] + stats["failure"]) > 0 else 0
                ),
            }
            for tool, stats in self._tool_stats.items()
        }


# ═══════════════════════════════════════════════════════════
# 元认知插件
# ═══════════════════════════════════════════════════════════

class MetaCognitionPlugin(Plugin):
    """
    元认知插件
    每个任务执行后自动运行评估→学习→调整循环
    """

    info = PluginInfo(
        name="metacognition",
        version="1.0.0",
        description="元认知引擎 — 自我评估+模式识别+行为调整",
        author="meshctx",
    )

    def __init__(self):
        self.pattern_engine = PatternEngine()
        self.behavior_adjuster = BehaviorAdjuster()
        self._evaluation_count = 0

    async def on_load(self):
        """注册事件处理器"""
        bus = self.kernel.bus

        bus.subscribe("task.completed", self._on_task_completed,
                      plugin_name="metacognition")
        bus.subscribe("tool.called", self._on_tool_called,
                      plugin_name="metacognition")
        bus.subscribe("metacognition.report", self._on_report_request,
                      plugin_name="metacognition")

        logger.info("元认知引擎已加载")

    async def on_unload(self):
        logger.info("元认知引擎已卸载")

    # ── 事件处理器 ────────────────────────────────────────

    async def _on_task_completed(self, event: Event):
        """任务完成: 执行元认知循环"""
        data = event.data

        # 1. 评估
        evaluation = self._evaluate_task(data)
        self.pattern_engine.add_evaluation(evaluation)
        self._evaluation_count += 1

        # 2. 模式提取(每10次任务)
        if self._evaluation_count % 10 == 0:
            top_patterns = self.pattern_engine.get_top_patterns()
            guard_rules = self.pattern_engine.get_guard_rules()

            # 发布自动Skill建议
            for pattern in top_patterns:
                await self.kernel.bus.publish(Event(
                    type="skill.suggested",
                    source="metacognition",
                    data={
                        "pattern": pattern,
                        "suggestion": (
                            f"检测到重复成功模式: {pattern['task_pattern'][:50]}..."
                            f" (出现{pattern['frequency']}次, "
                            f"平均质量{pattern['avg_quality']})"
                        ),
                    },
                ))

            # 发布防护规则
            for rule in guard_rules:
                await self.kernel.bus.publish(Event(
                    type="guard_rule.created",
                    source="metacognition",
                    data=rule,
                ))

        # 3. 知识图谱更新
        await self._update_knowledge_graph(evaluation)

        # 4. 发布评估结果
        await self.kernel.bus.publish(Event(
            type="task.evaluated",
            source="metacognition",
            correlation_id=event.id,
            data={
                "task_id": evaluation.task_id,
                "status": evaluation.status.value,
                "quality": evaluation.quality_score,
                "duration": evaluation.duration_seconds,
                "suggestions": evaluation.suggestions,
            },
        ))

        logger.debug(
            f"元认知: 任务 [{evaluation.task_id[:8]}] "
            f"评分={evaluation.quality_score:.2f} "
            f"状态={evaluation.status.value}"
        )

    async def _on_tool_called(self, event: Event):
        """工具调用: 更新工具统计"""
        data = event.data
        tool_name = data.get("tool", "unknown")
        success = data.get("success", True)
        self.behavior_adjuster.record_tool_result(tool_name, success)

    async def _on_report_request(self, event: Event):
        """生成元认知报告"""
        report = self.generate_report()
        await self.kernel.bus.publish(Event(
            type="metacognition.report_result",
            source="metacognition",
            correlation_id=event.id,
            data=report,
        ))

    # ── 评估逻辑 ──────────────────────────────────────────

    def _evaluate_task(self, data: Dict) -> TaskEvaluation:
        """评估单个任务"""
        task_id = data.get("task_id", str(uuid.uuid4()))
        description = data.get("description", "")
        duration = data.get("duration_seconds", 0)
        tool_calls = data.get("tool_calls", 0)
        tool_failures = data.get("tool_failures", 0)
        user_feedback = data.get("user_feedback")  # 可选

        # 判断状态
        if data.get("cancelled"):
            status = TaskStatus.CANCELLED
        elif data.get("timeout"):
            status = TaskStatus.TIMEOUT
        elif tool_failures > 0 and tool_failures >= tool_calls:
            status = TaskStatus.FAILED
        elif data.get("error"):
            status = TaskStatus.FAILED
        elif tool_failures > 0:
            status = TaskStatus.PARTIAL
        else:
            status = TaskStatus.SUCCESS

        # 质量评分
        quality = self._calculate_quality(data, status, tool_calls, tool_failures)

        # 错误分类
        error_cat = None
        error_detail = ""
        if status != TaskStatus.SUCCESS:
            error_cat, error_detail = self._categorize_error(data)

        # 成功因素/失败原因
        success_pattern = ""
        failure_cause = ""
        if status == TaskStatus.SUCCESS:
            success_pattern = self._identify_success_factor(data)
        else:
            failure_cause = self._identify_failure_cause(data, error_cat)

        # 建议
        suggestions = self._generate_suggestions(status, error_cat, quality)

        return TaskEvaluation(
            task_id=task_id,
            task_description=description,
            status=status,
            quality_score=quality,
            duration_seconds=duration,
            tool_calls=tool_calls,
            tool_failures=tool_failures,
            error_category=error_cat,
            error_detail=error_detail,
            success_pattern=success_pattern,
            failure_cause=failure_cause,
            suggestions=suggestions,
        )

    def _calculate_quality(self, data: Dict, status: TaskStatus,
                           tool_calls: int, tool_failures: int) -> float:
        """计算质量分数"""
        if status == TaskStatus.CANCELLED:
            return 0.0
        if status == TaskStatus.TIMEOUT:
            return 0.1

        base = {
            TaskStatus.SUCCESS: 0.85,
            TaskStatus.PARTIAL: 0.5,
            TaskStatus.FAILED: 0.1,
        }.get(status, 0.5)

        # 工具成功率调整
        if tool_calls > 0:
            tool_success_rate = (tool_calls - tool_failures) / tool_calls
            base += (tool_success_rate - 0.5) * 0.15

        # 效率调整(根据预期时间)
        expected_duration = data.get("expected_duration", 60)
        actual_duration = data.get("duration_seconds", expected_duration)
        if actual_duration > 0:
            efficiency = min(1.0, expected_duration / actual_duration)
            base += (efficiency - 0.5) * 0.1

        # 用户反馈
        if data.get("user_rating"):
            base = (base + data["user_rating"]) / 2

        return max(0.0, min(1.0, round(base, 2)))

    def _categorize_error(self, data: Dict) -> Tuple[ErrorCategory, str]:
        """分类错误"""
        error_msg = data.get("error", "").lower()

        if any(kw in error_msg for kw in
               ["permission", "denied", "unauthorized", "access"]):
            return ErrorCategory.PERMISSION, "权限不足"
        if any(kw in error_msg for kw in
               ["timeout", "connection", "network", "dns"]):
            return ErrorCategory.NETWORK, "网络错误"
        if any(kw in error_msg for kw in
               ["memory", "oom", "resource", "limit"]):
            return ErrorCategory.RESOURCE, "资源耗尽"
        if any(kw in error_msg for kw in
               ["tool", "command not found", "executable"]):
            return ErrorCategory.TOOL, "工具调用失败"
        if any(kw in error_msg for kw in
               ["not found", "no such file", "unknown"]):
            return ErrorCategory.KNOWLEDGE, "知识不足"
        return ErrorCategory.UNKNOWN, error_msg[:100]

    def _identify_success_factor(self, data: Dict) -> str:
        """识别成功因素"""
        factors = []
        if data.get("delegation_used"):
            factors.append("使用子Agent分解")
        if data.get("verification_steps", 0) > 2:
            factors.append("多次验证")
        if data.get("retry_count", 0) > 0:
            factors.append("智能重试")
        if data.get("parallel_tools", 0) > 1:
            factors.append("并行执行")
        return ", ".join(factors) if factors else "标准执行"

    def _identify_failure_cause(self, data: Dict,
                                 error_cat: Optional[ErrorCategory]) -> str:
        """识别失败原因"""
        causes = {
            ErrorCategory.TOOL: "工具不可用或参数错误",
            ErrorCategory.REASONING: "任务分解不充分",
            ErrorCategory.KNOWLEDGE: "缺少必要的上下文知识",
            ErrorCategory.PERMISSION: "权限配置不足",
            ErrorCategory.NETWORK: "网络连接不稳定",
            ErrorCategory.RESOURCE: "系统资源不足",
        }
        return causes.get(error_cat, f"未知错误: {data.get('error', '')[:100]}")

    def _generate_suggestions(self, status: TaskStatus,
                               error_cat: Optional[ErrorCategory],
                               quality: float) -> List[str]:
        """生成改进建议"""
        suggestions = []

        if quality < 0.5:
            suggestions.append("建议分解为更小的子任务")
            suggestions.append("每个步骤后验证结果")

        if error_cat == ErrorCategory.TOOL:
            suggestions.append("执行前检查工具可用性")
            suggestions.append("添加重试逻辑(指数退避)")
        elif error_cat == ErrorCategory.NETWORK:
            suggestions.append("使用备用端点")
            suggestions.append("添加离线回退方案")
        elif error_cat == ErrorCategory.KNOWLEDGE:
            suggestions.append("检索记忆库获取相关上下文")
        elif error_cat == ErrorCategory.RESOURCE:
            suggestions.append("分批处理大数据集")
            suggestions.append("监控资源使用")

        if status == TaskStatus.TIMEOUT:
            suggestions.append("设置合理的超时时间")
            suggestions.append("使用后台任务处理长时间操作")

        return suggestions

    async def _update_knowledge_graph(self, evaluation: TaskEvaluation):
        """更新知识图谱"""
        # 发布事件让memory插件处理
        await self.kernel.bus.publish(Event(
            type="knowledge.update_from_task",
            source="metacognition",
            data={
                "task_id": evaluation.task_id,
                "description": evaluation.task_description,
                "status": evaluation.status.value,
                "quality": evaluation.quality_score,
                "error_category": (
                    evaluation.error_category.value
                    if evaluation.error_category else None
                ),
                "success_pattern": evaluation.success_pattern,
            },
            priority=EventPriority.LOW,
        ))

    # ── 报告 ──────────────────────────────────────────────

    def generate_report(self) -> Dict[str, Any]:
        """生成元认知报告"""
        top_patterns = self.pattern_engine.get_top_patterns(5)
        guard_rules = self.pattern_engine.get_guard_rules()

        return {
            "evaluation_count": self._evaluation_count,
            "top_success_patterns": [
                {
                    "pattern": p["task_pattern"][:80],
                    "frequency": p["frequency"],
                    "avg_quality": p["avg_quality"],
                }
                for p in top_patterns
            ],
            "guard_rules": [
                {
                    "pattern": r["pattern"][:80],
                    "error_type": r["error_type"],
                    "suggestion": r["suggestion"],
                }
                for r in guard_rules[-5:]
            ],
            "strategy_weights": self.behavior_adjuster.get_strategy(),
            "top_tools": self.behavior_adjuster.get_tool_stats(),
            "learning_summary": (
                f"已学习 {self._evaluation_count} 次任务, "
                f"提取 {len(top_patterns)} 个成功模式, "
                f"{len(guard_rules)} 条防护规则"
            ),
        }

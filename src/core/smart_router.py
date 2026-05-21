"""
Smart Model Router & Usage Analyzer — v2.62
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
直接解决行业#2痛点: Token成本失控+模型选择焦虑

功能:
1. 智能路由: 根据任务复杂度自动选择最便宜的胜任模型
2. 用量追踪: 每个模型/任务类型的token消耗统计
3. 成本预测: 预估任务成本，防止意外超支
4. 降级策略: 昂贵模型不可用时自动fallback

设计原则:
- 简单任务(<100 tokens) → 用最便宜的模型
- 复杂推理(需要多步思考) → 用中等模型
- 极复杂任务(代码生成/架构设计) → 用最强模型
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """任务复杂度分级"""
    TRIVIAL = 1      # 简短回答、yes/no
    SIMPLE = 2       # 基础编程、解释
    MODERATE = 3     # 代码审查、调试
    COMPLEX = 4      # 架构设计、多文件编辑
    EXPERT = 5       # 需要最强推理


class ModelTier(Enum):
    """模型层级"""
    BUDGET = 1       # 最便宜 (<$1/M tokens)
    STANDARD = 2     # 标准 ($1-5/M)
    PREMIUM = 3      # 高级 ($5-15/M)
    EXPERT = 4       # 最强 ($15+/M)


@dataclass
class ModelInfo:
    """模型信息"""
    model_id: str
    tier: ModelTier
    cost_per_1k_input: float  # 美元/1000输入token
    cost_per_1k_output: float
    context_window: int
    capabilities: List[str] = field(default_factory=list)
    provider: str = ""


@dataclass
class RoutingDecision:
    """路由决策"""
    task_type: str
    complexity: TaskComplexity
    selected_model: str
    fallback_model: str
    estimated_cost: float
    reasoning: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class UsageRecord:
    """用量记录"""
    model_id: str
    task_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


class SmartModelRouter:
    """智能模型路由器"""

    # 默认模型定价 (2026年5月参考价)
    _DEFAULT_MODELS: Dict[str, ModelInfo] = {}

    def __init__(self):
        self._usage: List[UsageRecord] = []
        self._decisions: List[RoutingDecision] = []
        self._stats: Dict[str, Dict] = defaultdict(
            lambda: {"calls": 0, "total_tokens": 0, "total_cost": 0.0}
        )
        self._budget_cap: Optional[float] = None
        self._spent_today: float = 0.0

        # 初始化默认模型列表
        self._init_models()

    def _init_models(self):
        """初始化模型定价表"""
        defaults = [
            ("deepseek-chat",       ModelTier.BUDGET,   0.14, 0.28, 128000,
             ["chat","reasoning","code"], "deepseek"),
            ("deepseek-reasoner",   ModelTier.STANDARD, 0.55, 2.19, 128000,
             ["reasoning","code","math"], "deepseek"),
            ("claude-haiku-4",      ModelTier.BUDGET,   1.0,  5.0,  200000,
             ["chat","code","fast"], "anthropic"),
            ("claude-sonnet-4",     ModelTier.PREMIUM,  3.0,  15.0, 200000,
             ["reasoning","code","architecture"], "anthropic"),
            ("claude-opus-4",       ModelTier.EXPERT,   15.0, 75.0, 200000,
             ["expert","reasoning","code","research"], "anthropic"),
            ("gpt-4o-mini",         ModelTier.BUDGET,   0.15, 0.60, 128000,
             ["chat","code","fast"], "openai"),
            ("gpt-4o",              ModelTier.STANDARD, 2.5,  10.0, 128000,
             ["reasoning","code","multimodal"], "openai"),
            ("o4-mini",             ModelTier.STANDARD, 1.1,  4.4,  200000,
             ["reasoning","code","math"], "openai"),
            ("gemini-2.5-flash",    ModelTier.BUDGET,   0.15, 0.60, 1048576,
             ["chat","code","fast","multimodal"], "google"),
            ("gemini-2.5-pro",      ModelTier.PREMIUM,  1.25, 10.0, 1048576,
             ["reasoning","code","architecture"], "google"),
            ("llama-4-maverick",    ModelTier.BUDGET,   0.2,  0.6,  1000000,
             ["chat","code","open-source"], "meta"),
            ("llama-4-scout",       ModelTier.EXPERT,   0.4,  1.2,  10000000,
             ["expert","code","research"], "meta"),
        ]
        for m in defaults:
            info = ModelInfo(
                model_id=m[0], tier=m[1],
                cost_per_1k_input=m[2], cost_per_1k_output=m[3],
                context_window=m[4], capabilities=m[5],
                provider=m[6],
            )
            self._DEFAULT_MODELS[m[0]] = info

    # ── Complexity Estimation ──────────────────────────

    def estimate_complexity(self, prompt: str,
                           task_type: str = "general") -> TaskComplexity:
        """估算任务复杂度"""
        prompt_lower = prompt.lower()
        token_estimate = len(prompt) // 4  # 粗略token估算

        # 极复杂信号
        expert_signals = [
            "architecture", "design system", "multi-agent",
            "distributed", "security audit", "quantum",
            "从零设计", "系统架构", "多智能体", "架构设计",
            "分布式", "微服务", "安全审计",
        ]
        # 复杂信号
        complex_signals = [
            "refactor", "debug", "optimize", "implement",
            "code review", "database", "api design",
            "重构", "优化", "实现", "调试", "代码审查",
            "数据库设计", "api设计",
        ]
        # 中等信号
        moderate_signals = [
            "explain", "how to", "compare", "analyze",
            "解释", "对比", "分析", "sql", "query",
        ]

        for sig in expert_signals:
            if sig.lower() in prompt_lower:
                return TaskComplexity.EXPERT

        for sig in complex_signals:
            if sig.lower() in prompt_lower:
                return TaskComplexity.COMPLEX if token_estimate > 500 \
                    else TaskComplexity.MODERATE

        if token_estimate > 2000:
            return TaskComplexity.COMPLEX

        for sig in moderate_signals:
            if sig.lower() in prompt_lower:
                return TaskComplexity.MODERATE

        if token_estimate < 50:
            return TaskComplexity.TRIVIAL

        return TaskComplexity.SIMPLE

    # ── Model Selection ────────────────────────────────

    def route(self, prompt: str, task_type: str = "general",
              preferred_provider: Optional[str] = None,
              max_budget: Optional[float] = None,
              require_capability: Optional[str] = None
              ) -> RoutingDecision:
        """选择最优模型"""
        complexity = self.estimate_complexity(prompt, task_type)

        # 复杂度→层级映射
        tier_map = {
            TaskComplexity.TRIVIAL:  ModelTier.BUDGET,
            TaskComplexity.SIMPLE:   ModelTier.BUDGET,
            TaskComplexity.MODERATE: ModelTier.STANDARD,
            TaskComplexity.COMPLEX:  ModelTier.PREMIUM,
            TaskComplexity.EXPERT:   ModelTier.EXPERT,
        }
        target_tier = tier_map[complexity]

        # 筛选候选人
        candidates = [
            m for m in self._DEFAULT_MODELS.values()
            if m.tier.value <= target_tier.value + 1
        ]

        if preferred_provider:
            provider_candidates = [
                m for m in candidates
                if m.provider == preferred_provider
            ]
            if provider_candidates:
                candidates = provider_candidates

        if require_capability:
            candidates = [
                m for m in candidates
                if require_capability in m.capabilities
            ]

        if not candidates:
            # 回退到deepseek
            candidates = [
                m for m in self._DEFAULT_MODELS.values()
                if m.provider == "deepseek"
            ]

        # 选最便宜的
        candidates.sort(key=lambda m: m.cost_per_1k_input)
        selected = candidates[0]
        fallback = candidates[-1] if len(candidates) > 1 else selected

        # 估算成本
        est_tokens = max(100, len(prompt) // 3)
        est_cost = (est_tokens / 1000) * (
            selected.cost_per_1k_input + selected.cost_per_1k_output
        )

        decision = RoutingDecision(
            task_type=task_type,
            complexity=complexity,
            selected_model=selected.model_id,
            fallback_model=fallback.model_id,
            estimated_cost=round(est_cost, 6),
            reasoning=(
                f"任务复杂度={complexity.name} → "
                f"选择{selected.model_id} "
                f"(${selected.cost_per_1k_input}/1k in, "
                f"${selected.cost_per_1k_output}/1k out) "
                f"预计费用=${est_cost:.6f}"
            ),
        )
        self._decisions.append(decision)
        return decision

    # ── Usage Tracking ─────────────────────────────────

    def record_usage(self, model_id: str, task_type: str,
                    input_tokens: int, output_tokens: int,
                    latency_ms: float = 0.0):
        """记录用量"""
        model = self._DEFAULT_MODELS.get(model_id)
        if not model:
            cost = 0.0
        else:
            cost = (input_tokens / 1000) * model.cost_per_1k_input + \
                   (output_tokens / 1000) * model.cost_per_1k_output

        record = UsageRecord(
            model_id=model_id, task_type=task_type,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=round(cost, 6), latency_ms=latency_ms,
        )
        self._usage.append(record)

        # 更新统计
        s = self._stats[model_id]
        s["calls"] += 1
        s["total_tokens"] += input_tokens + output_tokens
        s["total_cost"] += cost
        s["avg_latency"] = (
            (s.get("avg_latency", 0) * (s["calls"] - 1) + latency_ms)
            / s["calls"]
        )

        self._spent_today += cost

    # ── Budget Control ────────────────────────────────

    def set_budget(self, daily_cap_usd: float):
        """设置每日预算上限"""
        self._budget_cap = daily_cap_usd

    def can_afford(self, estimated_cost: float) -> bool:
        """检查是否在预算内"""
        if self._budget_cap is None:
            return True
        return self._spent_today + estimated_cost <= self._budget_cap

    # ── Analysis ───────────────────────────────────────

    def get_usage_report(self) -> Dict[str, Any]:
        """生成用量分析报告"""
        total_cost = sum(r.cost_usd for r in self._usage)
        total_tokens = sum(
            r.input_tokens + r.output_tokens for r in self._usage
        )
        total_calls = len(self._usage)

        # 按模型分组
        by_model = defaultdict(lambda: {"calls": 0, "cost": 0.0, "tokens": 0})
        for r in self._usage:
            m = by_model[r.model_id]
            m["calls"] += 1
            m["cost"] += r.cost_usd
            m["tokens"] += r.input_tokens + r.output_tokens

        # 按任务分组
        by_task = defaultdict(lambda: {"calls": 0, "cost": 0.0})
        for r in self._usage:
            by_task[r.task_type]["calls"] += 1
            by_task[r.task_type]["cost"] += r.cost_usd

        # 最大单笔
        most_expensive = max(self._usage, key=lambda r: r.cost_usd,
                            default=None)

        return {
            "period": "today",
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "budget_cap": self._budget_cap,
            "remaining_budget": (
                round(self._budget_cap - self._spent_today, 4)
                if self._budget_cap else "unlimited"
            ),
            "by_model": dict(by_model),
            "by_task": dict(by_task),
            "most_expensive_call": {
                "model": most_expensive.model_id if most_expensive else None,
                "cost": round(most_expensive.cost_usd, 6) if most_expensive else 0,
                "task": most_expensive.task_type if most_expensive else None,
            } if most_expensive else None,
            "savings_estimate": (
                f"如果用最便宜模型: ~${round(total_cost * 0.3, 4)} "
                f"(节省 {round((1 - 0.3) * 100)}%)"
            ),
        }

    def get_optimization_tips(self) -> List[str]:
        """生成成本优化建议"""
        tips = []
        report = self.get_usage_report()

        # 1. 检查是否过度使用高级模型
        for model, stats in report["by_model"].items():
            model_info = self._DEFAULT_MODELS.get(model)
            if model_info and model_info.tier in (
                ModelTier.PREMIUM, ModelTier.EXPERT
            ):
                if stats["calls"] > 10:
                    tips.append(
                        f"💡 {model}用了{stats['calls']}次(${stats['cost']:.2f})"
                        f" — 简单任务用BUDGET层级模型可省钱"
                    )

        # 2. 最多成本的模型
        sorted_models = sorted(
            report["by_model"].items(),
            key=lambda x: x[1]["cost"], reverse=True
        )
        if sorted_models:
            top = sorted_models[0]
            tips.append(
                f"📊 最大开销: {top[0]} (${top[1]['cost']:.2f}, "
                f"{top[1]['calls']}次调用)"
            )

        # 3. 预算警告
        if self._budget_cap and self._spent_today > self._budget_cap * 0.8:
            tips.append(
                f"⚠️ 已用预算的{round(self._spent_today/self._budget_cap*100)}%"
            )

        return tips


# 单例
_router: Optional[SmartModelRouter] = None


def get_model_router() -> SmartModelRouter:
    global _router
    if _router is None:
        _router = SmartModelRouter()
    return _router

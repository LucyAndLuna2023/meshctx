"""
meshctx v3.50 — Feedback Loop Engine (反馈闭环引擎)

闭环最后一环: 执行→学习→优化
SubconsciousObserver(v3.48) → ActionEngine(v3.49) → FeedbackLoop(v3.50)

功能:
  1. Action结果分析: 成功率/失败模式/超时模式
  2. 自适应风险容忍: 成功率高→降低审批门槛
  3. 超时优化: 根据历史调整timeout
  4. 重试策略: 临时失败自动重试
  5. 学习报告: 趋势分析+优化建议
"""
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.feedback_loop")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class FeedbackPhase(Enum):
    """反馈阶段"""
    COLLECT = "collect"       # 收集执行结果
    ANALYZE = "analyze"       # 分析模式
    ADAPT = "adapt"           # 调整策略
    REPORT = "report"         # 生成报告


@dataclass
class ExecutionRecord:
    """单次执行记录"""
    action_name: str = ""
    command: str = ""
    risk_level: int = 0        # RiskLevel.value
    status: str = ""           # ActionStatus.value
    exit_code: int = -1
    duration_ms: float = 0
    output_len: int = 0
    error_len: int = 0
    was_approved: bool = False
    was_auto: bool = False     # 自动执行vs人工审批
    retry_count: int = 0
    timestamp: float = field(default_factory=time.time)
    error_type: str = ""       # TIMEOUT / NONZERO / EXCEPTION / NONE


@dataclass 
class ActionProfile:
    """操作画像 — 某类操作的历史表现"""
    name: str = ""
    total: int = 0
    success: int = 0
    failed: int = 0
    avg_duration_ms: float = 0
    timeout_count: int = 0
    last_success: float = 0
    last_failure: float = 0
    consecutive_success: int = 0
    consecutive_failure: int = 0
    
    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total > 0 else 1.0
    
    @property
    def is_reliable(self) -> bool:
        """是否足够可靠可自动审批"""
        return self.total >= 3 and self.success_rate >= 0.9 and self.consecutive_failure == 0


class AdaptiveConfig:
    """自适应配置 — 根据反馈动态调整"""
    
    def __init__(self):
        self.auto_approve_threshold: float = 0.85    # 自动审批成功率门槛
        self.default_timeout: int = 30               # 默认超时(秒)
        self.max_retries: int = 2                    # 最大重试次数
        self.retry_delay: int = 5                    # 重试间隔(秒)
        self.consecutive_fail_limit: int = 3         # 连续失败上限(触发警报)
        self.min_samples_for_adapt: int = 5          # 最小样本数才能自适应
        self.timeout_multiplier: float = 1.5         # 超时倍数(根据历史调整)
        self.cooldown_after_failure: int = 60        # 失败后冷却(秒)
    
    def adapt_from_profile(self, profiles: Dict[str, 'ActionProfile']):
        """根据执行画像自适应调整"""
        reliable_count = sum(1 for p in profiles.values() if p.is_reliable)
        total = len(profiles)
        
        # 可靠操作多 → 降低审批门槛
        if total > 0 and reliable_count / total > 0.7:
            self.auto_approve_threshold = max(0.7, self.auto_approve_threshold - 0.05)
        
        # 高失败率 → 提高审批门槛
        for p in profiles.values():
            if p.total >= self.min_samples_for_adapt:
                if p.timeout_count > p.total * 0.3:
                    self.default_timeout = min(120, int(self.default_timeout * self.timeout_multiplier))
                if p.consecutive_failure >= self.consecutive_fail_limit:
                    self.auto_approve_threshold = min(0.95, self.auto_approve_threshold + 0.1)


# ═══════════════════════════════════════════════════════════
# Feedback Loop Engine
# ═══════════════════════════════════════════════════════════

class FeedbackLoopEngine:
    """
    反馈闭环引擎
    
    输入: ActionEngine执行结果
    处理: 记录→分析→自适应调整
    输出: 优化后的配置+学习报告
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._records: deque = deque(maxlen=500)
        self._profiles: Dict[str, ActionProfile] = {}
        self._adaptive_config = AdaptiveConfig()
        self._phase_history: List[Dict] = []
        
        # 错误分类模式
        self._error_patterns = {
            "TIMEOUT": ["timed out", "timeout", "TimeoutExpired"],
            "PERMISSION": ["permission denied", "access denied", "not permitted"],
            "NOT_FOUND": ["not found", "no such file", "ModuleNotFoundError"],
            "NETWORK": ["connection refused", "network", "unreachable", "DNS"],
            "MEMORY": ["out of memory", "MemoryError", "OOM"],
            "SYNTAX": ["syntax error", "invalid syntax", "unexpected token"],
        }
    
    # ═══ 收集阶段 ═══
    
    def record(self, action_result: Any) -> ExecutionRecord:
        """
        记录一次执行结果
        action_result: Action对象(来自ActionEngine)或dict
        """
        # Handle both Action objects and dict results
        if hasattr(action_result, 'name'):
            name = action_result.name
            cmd = getattr(action_result, 'command', '')
            risk = getattr(action_result, 'risk_level', None)
            risk_val = risk.value if hasattr(risk, 'value') else (risk or 0)
            status = getattr(action_result, 'status', None)
            status_val = status.value if hasattr(status, 'value') else str(status)
            exit_code = getattr(action_result, 'exit_code', -1)
            output = getattr(action_result, 'output', '')
            error = getattr(action_result, 'error', '')
            duration = (getattr(action_result, 'executed_at', 0) - getattr(action_result, 'created_at', 0)) * 1000
            retry = getattr(action_result, 'retry_count', 0)
        elif isinstance(action_result, dict):
            name = action_result.get("name", "unknown")
            cmd = action_result.get("command", "")
            risk_val = action_result.get("risk", 0)
            status_val = action_result.get("status", "unknown")
            exit_code = action_result.get("exit_code", -1)
            output = action_result.get("output", "")
            error = action_result.get("error", "")
            duration = action_result.get("duration_ms", 0)
            retry = action_result.get("retry_count", 0)
        else:
            name = str(action_result)
            cmd = ""
            risk_val = 0
            status_val = "unknown"
            exit_code = -1
            output = ""
            error = ""
            duration = 0
            retry = 0
        
        # 分类错误
        error_type = "NONE"
        if status_val == "failed":
            error_lower = str(error).lower()
            for etype, patterns in self._error_patterns.items():
                if any(p.lower() in error_lower for p in patterns):
                    error_type = etype
                    break
            if error_type == "NONE" and exit_code != 0:
                error_type = "NONZERO"
        
        record = ExecutionRecord(
            action_name=name,
            command=cmd,
            risk_level=risk_val,
            status=status_val,
            exit_code=exit_code,
            duration_ms=max(0, duration),
            output_len=len(str(output)),
            error_len=len(str(error)),
            retry_count=retry,
            error_type=error_type,
        )
        
        self._records.append(record)
        self._update_profile(record)
        
        logger.debug(f"Recorded: {name} → {status_val} ({error_type})")
        return record
    
    def _update_profile(self, record: ExecutionRecord):
        """更新操作画像"""
        profile = self._profiles.get(record.action_name)
        if profile is None:
            profile = ActionProfile(name=record.action_name)
            self._profiles[record.action_name] = profile
        
        profile.total += 1
        if record.status == "success":
            profile.success += 1
            profile.consecutive_success += 1
            profile.consecutive_failure = 0
            profile.last_success = record.timestamp
        else:
            profile.failed += 1
            profile.consecutive_failure += 1
            profile.consecutive_success = 0
            profile.last_failure = record.timestamp
        
        if record.error_type == "TIMEOUT":
            profile.timeout_count += 1
        
        # 加权平均时长
        profile.avg_duration_ms = (
            profile.avg_duration_ms * (profile.total - 1) + record.duration_ms
        ) / profile.total
    
    # ═══ 分析阶段 ═══
    
    def analyze(self) -> Dict[str, Any]:
        """分析执行模式"""
        if not self._records:
            return {"status": "no_data"}
        
        recent = list(self._records)[-50:]
        
        total = len(recent)
        success = sum(1 for r in recent if r.status == "success")
        failed = sum(1 for r in recent if r.status == "failed")
        
        # 错误分布
        error_dist = defaultdict(int)
        for r in recent:
            if r.error_type != "NONE":
                error_dist[r.error_type] += 1
        
        # 趋势: 最近10次 vs 全部
        last10 = recent[-10:] if len(recent) >= 10 else recent
        recent_rate = sum(1 for r in last10 if r.status == "success") / len(last10)
        overall_rate = success / total if total > 0 else 1.0
        trending = "improving" if recent_rate > overall_rate else ("declining" if recent_rate < overall_rate else "stable")
        
        # 发现可靠操作
        reliable = [name for name, p in self._profiles.items() if p.is_reliable]
        # 发现问题操作
        problematic = [name for name, p in self._profiles.items() 
                       if p.total >= 3 and p.success_rate < 0.5]
        
        return {
            "total_records": len(self._records),
            "recent_window": total,
            "success_rate": f"{success/total*100:.1f}%" if total > 0 else "N/A",
            "error_distribution": dict(error_dist),
            "trend": trending,
            "recent_rate": f"{recent_rate*100:.1f}%",
            "reliable_actions": reliable,
            "problematic_actions": problematic,
            "profiles_count": len(self._profiles),
            "avg_duration_ms": round(sum(r.duration_ms for r in recent) / len(recent)) if recent else 0,
        }
    
    # ═══ 自适应阶段 ═══
    
    def adapt(self) -> Dict[str, Any]:
        """根据历史自适应调整配置"""
        old_config = {
            "auto_approve_threshold": self._adaptive_config.auto_approve_threshold,
            "default_timeout": self._adaptive_config.default_timeout,
        }
        
        self._adaptive_config.adapt_from_profile(self._profiles)
        
        new_config = {
            "auto_approve_threshold": self._adaptive_config.auto_approve_threshold,
            "default_timeout": self._adaptive_config.default_timeout,
        }
        
        changes = {}
        for key in old_config:
            if old_config[key] != new_config[key]:
                changes[key] = {"from": old_config[key], "to": new_config[key]}
        
        if changes:
            logger.info(f"Adaptive changes: {changes}")
        
        return {"changes": changes, "current": new_config}
    
    def should_retry(self, action_name: str) -> Tuple[bool, int]:
        """判断是否应该重试及延迟"""
        profile = self._profiles.get(action_name)
        if not profile:
            return False, 0
        
        # 连续失败→重试但要等待
        if profile.consecutive_failure > 0:
            if time.time() - profile.last_failure > self._adaptive_config.cooldown_after_failure:
                return True, self._adaptive_config.retry_delay * profile.consecutive_failure
            return False, 0
        
        return False, 0
    
    def get_optimal_timeout(self, action_name: str) -> int:
        """根据历史计算最优超时"""
        profile = self._profiles.get(action_name)
        if not profile or profile.total < 3:
            return self._adaptive_config.default_timeout
        
        # 平均时长 × 2倍安全边际
        optimal = int(profile.avg_duration_ms / 1000 * 2) + 5
        return max(10, min(120, optimal))
    
    # ═══ 报告阶段 ═══
    
    def generate_report(self) -> Dict[str, Any]:
        """生成学习报告"""
        analysis = self.analyze()
        adaptation = self.adapt()
        
        report = {
            "timestamp": time.time(),
            "analysis": analysis,
            "adaptation": adaptation,
            "top_actions": self._get_top_actions(5),
            "recommendations": self._generate_recommendations(),
        }
        
        self._phase_history.append({
            "phase": FeedbackPhase.REPORT.value,
            "time": time.time(),
            "findings": len(report.get("recommendations", [])),
        })
        
        return report
    
    def _get_top_actions(self, n: int = 5) -> List[Dict]:
        """最常用的操作"""
        sorted_profiles = sorted(self._profiles.values(), 
                                key=lambda p: p.total, reverse=True)
        return [{
            "name": p.name,
            "total": p.total,
            "success_rate": f"{p.success_rate*100:.1f}%",
            "avg_duration": f"{p.avg_duration_ms:.0f}ms",
            "is_reliable": p.is_reliable,
        } for p in sorted_profiles[:n]]
    
    def _generate_recommendations(self) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        for name, profile in self._profiles.items():
            if profile.total < 3:
                continue
            
            if profile.timeout_count > profile.total * 0.5:
                recommendations.append(
                    f"Increase timeout for '{name}': {profile.timeout_count}/{profile.total} timeouts"
                )
            
            if profile.consecutive_failure >= 3:
                recommendations.append(
                    f"Investigate '{name}': {profile.consecutive_failure} consecutive failures"
                )
            
            if profile.is_reliable and profile.total >= 5:
                recommendations.append(
                    f"Auto-approve '{name}': {profile.success_rate*100:.0f}% success over {profile.total} runs"
                )
        
        # 全局建议
        total_records = len(self._records)
        if total_records >= 10:
            timeout_rate = sum(1 for r in list(self._records)[-20:] 
                             if r.error_type == "TIMEOUT") / min(20, total_records)
            if timeout_rate > 0.3:
                recommendations.append(
                    f"Global: {timeout_rate*100:.0f}% timeout rate — consider increasing default timeout"
                )
        
        return recommendations
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_records": len(self._records),
            "profiles": len(self._profiles),
            "config": {
                "auto_approve_threshold": self._adaptive_config.auto_approve_threshold,
                "default_timeout": self._adaptive_config.default_timeout,
                "max_retries": self._adaptive_config.max_retries,
            },
            "latest_report": self.generate_report() if self._records else None,
        }


# ═══════════════════════════════════════════════════════════
# 完整闭环: 观察→行动→反馈
# ═══════════════════════════════════════════════════════════

class AutonomousPipeline:
    """
    完整自主管道: 观察(v3.48) → 行动(v3.49) → 反馈(v3.50)
    三模块串联,实现从被动到完全自主
    """
    
    def __init__(self, observer=None, action_engine=None, feedback_engine=None):
        self.observer = observer
        self.action_engine = action_engine
        self.feedback = feedback_engine or FeedbackLoopEngine()
    
    async def cycle(self) -> Dict[str, Any]:
        """执行一个完整自主周期"""
        results = {"nudges": 0, "actions": 0, "executed": 0, "learned": False}
        
        # Phase 1: 观察
        nudges = []
        if self.observer:
            try:
                nudges = await self.observer.cycle()
                results["nudges"] = len(nudges)
            except Exception as e:
                logger.error(f"Observer phase failed: {e}")
        
        # Phase 2: 决策+行动
        if self.action_engine and nudges:
            try:
                from .autonomous_action import ActionEngine
                actions = []
                for nudge in nudges:
                    mapped = self.action_engine.map_nudge_to_actions(nudge)
                    actions.extend(mapped)
                
                executed = await self.action_engine.execute_batch(actions, auto_approve=True)
                results["actions"] = len(actions)
                results["executed"] = len(executed)
                
                # Phase 3: 反馈学习
                for result in executed:
                    self.feedback.record(result)
                results["learned"] = True
                
                # 自适应调整
                if len(executed) > 0:
                    self.feedback.adapt()
                    
            except Exception as e:
                logger.error(f"Action phase failed: {e}")
        
        return results
    
    def get_report(self) -> Dict[str, Any]:
        return self.feedback.generate_report()


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_feedback_engine: Optional[FeedbackLoopEngine] = None


def get_feedback_engine(config: Optional[Dict] = None) -> FeedbackLoopEngine:
    global _feedback_engine
    if _feedback_engine is None:
        _feedback_engine = FeedbackLoopEngine(config)
    return _feedback_engine


# ═══════════════════════════════════════════════════════════
# v3.98 — FeedbackLoop 用户反馈闭环引擎
# ═══════════════════════════════════════════════════════════

class FeedbackSentiment(Enum):
    """用户反馈情感"""
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    NEUTRAL = "neutral"


@dataclass
class UserFeedback:
    """单条用户反馈记录"""
    feedback_id: str = ""
    user_id: str = ""
    session_id: str = ""
    sentiment: str = FeedbackSentiment.NEUTRAL.value  # thumbs_up / thumbs_down / neutral
    category: str = ""          # 反馈分类: "response_quality", "speed", "accuracy", "tone", "usefulness"
    action_context: str = ""    # 触发该反馈的操作上下文
    comment: str = ""           # 用户备注
    is_critical: bool = False   # 是否为严重问题
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailurePattern:
    """失败模式分析结果"""
    pattern_name: str = ""
    category: str = ""
    category_counts: Dict[str, int] = field(default_factory=dict)
    total_occurrences: int = 0
    thumbs_down_count: int = 0
    thumbs_up_count: int = 0
    example_feedbacks: List[str] = field(default_factory=list)
    severity: str = "low"       # low / medium / high / critical
    recommendation: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0

    @property
    def dissatisfaction_rate(self) -> float:
        total = self.thumbs_down_count + self.thumbs_up_count
        return self.thumbs_down_count / total if total > 0 else 0.0

    @property
    def is_active(self) -> bool:
        """最近24小时内是否仍活跃"""
        return (time.time() - self.last_seen) < 86400


@dataclass
class StrategyAdjustment:
    """策略调整记录"""
    strategy_name: str = ""
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    trigger_count: int = 0
    category: str = ""
    timestamp: float = field(default_factory=time.time)
    reverted: bool = False


@dataclass
class FeedbackLoopReport:
    """反馈闭环报告"""
    report_id: str = ""
    generated_at: float = field(default_factory=time.time)
    period_start: float = 0.0
    period_end: float = 0.0
    total_feedback: int = 0
    thumbs_up: int = 0
    thumbs_down: int = 0
    neutral: int = 0
    satisfaction_rate: float = 0.0
    top_failure_patterns: List[FailurePattern] = field(default_factory=list)
    recent_adjustments: List[StrategyAdjustment] = field(default_factory=list)
    category_breakdown: Dict[str, Dict[str, int]] = field(default_factory=dict)
    trend_direction: str = "stable"  # improving / declining / stable
    critical_issues: int = 0
    recommendations: List[str] = field(default_factory=list)


class FeedbackLoop:
    """
    v3.98 用户反馈闭环引擎

    完整闭环: 收集用户反馈 → 分析失败模式 → 策略自动调整 → 生成闭环报告

    功能:
      1. 用户反馈收集: thumbs_up / thumbs_down / neutral + 分类 + 上下文
      2. 自动分析失败模式: 聚合相似反馈, 识别趋势, 严重度评估
      3. 策略自动调整: 基于反馈动态调整响应策略
      4. 反馈闭环报告: 综合报告 + 趋势分析 + 改进建议
    """

    # 可调整的策略项及其默认值
    DEFAULT_STRATEGIES = {
        "verbosity": "balanced",         # concise / balanced / verbose
        "tone": "professional",          # casual / professional / formal
        "creativity": 0.7,               # 0.0-1.0
        "max_response_length": 4096,
        "include_examples": True,
        "auto_explain_code": True,
        "check_facts_before_answer": False,
        "suggest_followups": True,
    }

    # 策略调整规则: (条件, 调整)
    ADJUSTMENT_RULES = [
        (
            lambda stats: stats.get("too_verbose", 0) > stats.get("too_concise", 0) * 2,
            {"verbosity": "concise"},
            "Users prefer shorter responses"
        ),
        (
            lambda stats: stats.get("too_concise", 0) > stats.get("too_verbose", 0) * 2,
            {"verbosity": "verbose"},
            "Users want more detailed responses"
        ),
        (
            lambda stats: stats.get("inaccurate", 0) >= 3,
            {"check_facts_before_answer": True},
            "Accuracy complaints triggered fact-checking"
        ),
        (
            lambda stats: stats.get("slow", 0) >= 5,
            {"max_response_length": 2048},
            "Speed complaints — reducing max response length"
        ),
        (
            lambda stats: stats.get("too_formal", 0) >= 2,
            {"tone": "casual"},
            "Users find tone too formal"
        ),
        (
            lambda stats: stats.get("too_casual", 0) >= 2,
            {"tone": "professional"},
            "Users want more professional tone"
        ),
        (
            lambda stats: stats.get("unhelpful", 0) >= 5,
            {"creativity": 0.85, "include_examples": True, "suggest_followups": True},
            "Low helpfulness — boosting creativity and examples"
        ),
        (
            lambda stats: stats.get("code_wrong", 0) >= 3,
            {"auto_explain_code": True, "check_facts_before_answer": True},
            "Code errors reported — enabling auto-explain and fact-checking"
        ),
    ]

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._feedbacks: List[UserFeedback] = []
        self._failure_patterns: List[FailurePattern] = []
        self._adjustments: List[StrategyAdjustment] = []
        self._strategies: Dict[str, Any] = dict(self.DEFAULT_STRATEGIES)
        self._strategy_history: deque = deque(maxlen=50)

        # 反馈计数器（用于触发策略调整）
        self._category_counter: Dict[str, int] = defaultdict(int)
        self._thumbs_down_categories: Dict[str, int] = defaultdict(int)

        # 报告历史
        self._report_history: deque = deque(maxlen=20)

    # ═══ 1) 用户反馈收集 ═══

    def collect_feedback(
        self,
        sentiment: str,
        category: str = "",
        action_context: str = "",
        comment: str = "",
        user_id: str = "",
        session_id: str = "",
        is_critical: bool = False,
        metadata: Optional[Dict] = None,
    ) -> UserFeedback:
        """
        收集一条用户反馈

        Args:
            sentiment: 'thumbs_up' / 'thumbs_down' / 'neutral'
            category: 反馈分类 (response_quality, speed, accuracy, tone, usefulness 等)
            action_context: 触发反馈的操作上下文
            comment: 用户评论
            user_id: 用户标识
            session_id: 会话标识
            is_critical: 是否为严重问题
            metadata: 附加元数据

        Returns:
            UserFeedback 记录
        """
        # 验证 sentiment
        try:
            FeedbackSentiment(sentiment)
        except ValueError:
            sentiment = FeedbackSentiment.NEUTRAL.value

        feedback = UserFeedback(
            feedback_id=f"fb_{int(time.time() * 1000)}_{len(self._feedbacks)}",
            user_id=user_id,
            session_id=session_id,
            sentiment=sentiment,
            category=category,
            action_context=action_context,
            comment=comment,
            is_critical=is_critical,
            metadata=metadata or {},
        )

        self._feedbacks.append(feedback)

        # 更新计数器
        if sentiment == FeedbackSentiment.THUMBS_DOWN.value:
            self._thumbs_down_categories[category] += 1
            self._category_counter[category] += 1
            if comment:
                # 从评论中提取关键词作为子类别
                self._extract_comment_signals(comment)
        elif sentiment == FeedbackSentiment.THUMBS_UP.value:
            # 正向反馈可以抵消部分负向信号
            self._category_counter[category] = max(0, self._category_counter[category] - 1)

        logger.debug(
            f"Feedback collected: {sentiment} | {category} | critical={is_critical}"
        )
        return feedback

    def collect_thumbs_up(
        self, category: str = "", action_context: str = "", comment: str = "", **kwargs
    ) -> UserFeedback:
        """快捷方法: 赞"""
        return self.collect_feedback(
            sentiment=FeedbackSentiment.THUMBS_UP.value,
            category=category,
            action_context=action_context,
            comment=comment,
            **kwargs,
        )

    def collect_thumbs_down(
        self, category: str = "", action_context: str = "", comment: str = "",
        is_critical: bool = False, **kwargs
    ) -> UserFeedback:
        """快捷方法: 踩"""
        return self.collect_feedback(
            sentiment=FeedbackSentiment.THUMBS_DOWN.value,
            category=category,
            action_context=action_context,
            comment=comment,
            is_critical=is_critical,
            **kwargs,
        )

    def _extract_comment_signals(self, comment: str):
        """从用户评论中提取信号词"""
        signal_map = {
            "太啰嗦": "too_verbose", "太长": "too_verbose", "啰嗦": "too_verbose",
            "太短": "too_concise", "不够详细": "too_concise", "简略": "too_concise",
            "太慢": "slow", "慢": "slow", "卡": "slow", "等太久": "slow",
            "不对": "inaccurate", "错误": "inaccurate", "错的": "inaccurate",
            "没用": "unhelpful", "没用处": "unhelpful", "帮不上": "unhelpful",
            "太正式": "too_formal", "生硬": "too_formal",
            "太随意": "too_casual", "不够专业": "too_casual",
            "代码错": "code_wrong", "bug": "code_wrong", "报错": "code_wrong",
            "格式": "formatting", "排版": "formatting",
        }
        for keyword, signal in signal_map.items():
            if keyword in comment.lower():
                self._category_counter[signal] += 1

    # ═══ 2) 自动分析失败模式 ═══

    def analyze_failure_patterns(self, min_occurrences: int = 2) -> List[FailurePattern]:
        """
        自动分析失败模式: 聚合相似反馈, 识别高频失败模式

        Args:
            min_occurrences: 最少出现次数才算有效模式

        Returns:
            FailurePattern 列表, 按严重度排序
        """
        patterns: Dict[str, FailurePattern] = {}

        thumbs_down_feedbacks = [
            f for f in self._feedbacks
            if f.sentiment == FeedbackSentiment.THUMBS_DOWN.value
        ]

        if not thumbs_down_feedbacks:
            self._failure_patterns = []
            return []

        # 按 category 聚合
        for fb in thumbs_down_feedbacks:
            key = fb.category or "uncategorized"
            if key not in patterns:
                patterns[key] = FailurePattern(
                    pattern_name=key,
                    category=key,
                    first_seen=fb.timestamp,
                )
            p = patterns[key]
            p.thumbs_down_count += 1
            p.total_occurrences += 1
            p.last_seen = max(p.last_seen, fb.timestamp)
            p.first_seen = min(p.first_seen, fb.timestamp)
            if fb.comment:
                p.example_feedbacks.append(fb.comment)
            if fb.is_critical and p.severity != "critical":
                p.severity = "critical"

        # 跨类别: 从评论信号聚合
        for fb in thumbs_down_feedbacks:
            if not fb.comment:
                continue
            for keyword, signal in {
                "太慢": "performance_slow",
                "不对": "accuracy_issue",
                "啰嗦": "verbosity_too_long",
                "太短": "verbosity_too_short",
                "格式": "formatting_issue",
            }.items():
                if keyword in fb.comment.lower():
                    if signal not in patterns:
                        patterns[signal] = FailurePattern(
                            pattern_name=signal,
                            category=signal,
                            first_seen=fb.timestamp,
                        )
                    ps = patterns[signal]
                    ps.thumbs_down_count += 1
                    ps.total_occurrences += 1
                    ps.last_seen = max(ps.last_seen, fb.timestamp)

        # 过滤掉低频模式
        filtered = [p for p in patterns.values() if p.total_occurrences >= min_occurrences]

        # 计算严重度
        for p in filtered:
            if p.severity != "critical":
                if p.total_occurrences >= 10:
                    p.severity = "high"
                elif p.total_occurrences >= 5:
                    p.severity = "medium"

        # 生成建议
        for p in filtered:
            p.recommendation = self._generate_pattern_recommendation(p)

        # 按严重度和出现次数排序
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        filtered.sort(
            key=lambda x: (severity_order.get(x.severity, 4), -x.total_occurrences)
        )

        self._failure_patterns = filtered
        return filtered

    def _generate_pattern_recommendation(self, pattern: FailurePattern) -> str:
        """为失败模式生成改进建议"""
        recommendations = {
            "response_quality": "Review response templates and improve answer quality checks",
            "accuracy_issue": "Enable fact-checking and source verification before responding",
            "speed": "Optimize response generation pipeline; consider model tier adjustment",
            "performance_slow": "Profile response pipeline, reduce latency bottlenecks",
            "tone": "Adjust communication style based on user preference signals",
            "usefulness": "Add concrete examples and actionable steps to responses",
            "verbosity_too_long": "Trim responses to essential information; use concise format",
            "verbosity_too_short": "Expand responses with relevant details and examples",
            "formatting_issue": "Apply consistent formatting rules; improve markdown rendering",
            "code_wrong": "Add syntax validation and test execution before suggesting code",
            "uncategorized": "Request more detailed feedback from users for this category",
        }
        return recommendations.get(
            pattern.category,
            f"Investigate '{pattern.category}' — {pattern.total_occurrences} negative reports"
        )

    def get_active_patterns(self) -> List[FailurePattern]:
        """获取最近24小时活跃的失败模式"""
        if not self._failure_patterns:
            self.analyze_failure_patterns()
        return [p for p in self._failure_patterns if p.is_active]

    def get_critical_patterns(self) -> List[FailurePattern]:
        """获取严重/紧急的失败模式"""
        if not self._failure_patterns:
            self.analyze_failure_patterns()
        return [p for p in self._failure_patterns if p.severity in ("critical", "high")]

    # ═══ 3) 策略自动调整 ═══

    def auto_adjust_strategies(self) -> List[StrategyAdjustment]:
        """
        基于反馈自动调整策略

        根据收集的反馈信号, 自动调整响应策略
        (verbosity, tone, creativity, max_response_length 等)

        Returns:
            本次调整的策略列表
        """
        adjustments: List[StrategyAdjustment] = []

        # 聚合统计
        stats = dict(self._category_counter)

        for condition, changes, reason in self.ADJUSTMENT_RULES:
            try:
                if condition(stats):
                    for key, new_value in changes.items():
                        old_value = self._strategies.get(key)
                        if old_value == new_value:
                            continue  # 已经调整过

                        adjustment = StrategyAdjustment(
                            strategy_name=key,
                            old_value=old_value,
                            new_value=new_value,
                            reason=reason,
                            trigger_count=stats.get(key, 0),
                            category=key,
                        )
                        self._strategies[key] = new_value
                        self._adjustments.append(adjustment)
                        self._strategy_history.append(adjustment)
                        adjustments.append(adjustment)

                        logger.info(
                            f"Strategy adjusted: {key} {old_value} → {new_value} ({reason})"
                        )
            except Exception as e:
                logger.warning(f"Adjustment rule failed: {e}")

        # 调整后清零计数器（防止重复触发）
        # 但保留前值用于趋势对比
        self._category_counter.clear()

        return adjustments

    def revert_adjustment(self, strategy_name: str) -> bool:
        """回滚某个策略调整到上一个值"""
        # 查找该策略的上一次调整
        for adj in reversed(list(self._strategy_history)):
            if adj.strategy_name == strategy_name and not adj.reverted:
                self._strategies[strategy_name] = adj.old_value
                adj.reverted = True
                logger.info(f"Reverted strategy: {strategy_name} → {adj.old_value}")
                return True
        return False

    def get_current_strategies(self) -> Dict[str, Any]:
        """获取当前生效的策略配置"""
        return dict(self._strategies)

    def get_strategy_adjustments(self, limit: int = 20) -> List[StrategyAdjustment]:
        """获取最近的策略调整记录"""
        return list(self._adjustments[-limit:])

    # ═══ 4) 反馈闭环报告 ═══

    def generate_report(
        self,
        period_hours: Optional[int] = None,
        include_patterns: bool = True,
        include_adjustments: bool = True,
    ) -> FeedbackLoopReport:
        """
        生成反馈闭环报告

        Args:
            period_hours: 报告周期(小时), None=全部
            include_patterns: 是否包含失败模式
            include_adjustments: 是否包含策略调整

        Returns:
            FeedbackLoopReport 综合报告
        """
        now = time.time()
        period_start = now - (period_hours * 3600) if period_hours else 0.0

        # 筛选时间范围内的反馈
        feedbacks = [
            f for f in self._feedbacks
            if f.timestamp >= period_start
        ]

        total = len(feedbacks)
        thumbs_up = sum(1 for f in feedbacks if f.sentiment == FeedbackSentiment.THUMBS_UP.value)
        thumbs_down = sum(1 for f in feedbacks if f.sentiment == FeedbackSentiment.THUMBS_DOWN.value)
        neutral = total - thumbs_up - thumbs_down

        satisfaction = thumbs_up / (thumbs_up + thumbs_down) if (thumbs_up + thumbs_down) > 0 else 1.0

        # 分类分解
        category_breakdown: Dict[str, Dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0, "neutral": 0})
        for f in feedbacks:
            cat = f.category or "uncategorized"
            if f.sentiment == FeedbackSentiment.THUMBS_UP.value:
                category_breakdown[cat]["up"] += 1
            elif f.sentiment == FeedbackSentiment.THUMBS_DOWN.value:
                category_breakdown[cat]["down"] += 1
            else:
                category_breakdown[cat]["neutral"] += 1

        # 失败模式
        patterns = self.analyze_failure_patterns() if include_patterns else []

        # 策略调整
        adjustments = (
            [a for a in self._adjustments if a.timestamp >= period_start]
            if include_adjustments else []
        )

        # 趋势
        trend = self._compute_trend(feedbacks)

        # 严重问题
        critical = sum(1 for f in feedbacks if f.is_critical)

        # 建议
        recommendations = self._generate_report_recommendations(
            satisfaction, patterns, critical, trend
        )

        report = FeedbackLoopReport(
            report_id=f"rpt_{int(now)}_{len(self._report_history)}",
            generated_at=now,
            period_start=period_start,
            period_end=now,
            total_feedback=total,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            neutral=neutral,
            satisfaction_rate=round(satisfaction, 4),
            top_failure_patterns=patterns[:5],
            recent_adjustments=adjustments,
            category_breakdown=dict(category_breakdown),
            trend_direction=trend,
            critical_issues=critical,
            recommendations=recommendations,
        )

        self._report_history.append(report)
        return report

    def _compute_trend(self, feedbacks: List[UserFeedback]) -> str:
        """计算反馈趋势"""
        if len(feedbacks) < 6:
            return "insufficient_data"

        # 分前后两半比较
        mid = len(feedbacks) // 2
        first_half = feedbacks[:mid]
        second_half = feedbacks[mid:]

        def calc_rate(fbs):
            ups = sum(1 for f in fbs if f.sentiment == FeedbackSentiment.THUMBS_UP.value)
            downs = sum(1 for f in fbs if f.sentiment == FeedbackSentiment.THUMBS_DOWN.value)
            return ups / (ups + downs) if (ups + downs) > 0 else 1.0

        first_rate = calc_rate(first_half)
        second_rate = calc_rate(second_half)

        if second_rate > first_rate + 0.05:
            return "improving"
        elif second_rate < first_rate - 0.05:
            return "declining"
        return "stable"

    def _generate_report_recommendations(
        self, satisfaction: float, patterns: List[FailurePattern],
        critical_count: int, trend: str
    ) -> List[str]:
        """生成报告级别的改进建议"""
        recs = []

        if satisfaction < 0.6:
            recs.append("CRITICAL: Satisfaction rate below 60% — immediate review needed")
        elif satisfaction < 0.8:
            recs.append("WARNING: Satisfaction rate below 80% — investigate top failure patterns")

        if critical_count > 0:
            recs.append(f"Address {critical_count} critical issues reported by users")

        if trend == "declining":
            recs.append("Satisfaction trending downward — consider reverting recent strategy changes")
            # 建议回滚最近调整
            for adj in reversed(self._adjustments[-3:]):
                recs.append(f"  Consider reverting: {adj.strategy_name} ({adj.old_value} → {adj.new_value})")

        for p in patterns[:3]:
            if p.recommendation:
                recs.append(f"[{p.severity.upper()}] {p.pattern_name}: {p.recommendation}")

        # 无反馈时的建议
        if not self._feedbacks:
            recs.append("No feedback collected yet — enable feedback prompts for users")

        return recs

    def get_feedback_stats(self) -> Dict[str, Any]:
        """快速统计"""
        total = len(self._feedbacks)
        ups = sum(1 for f in self._feedbacks if f.sentiment == FeedbackSentiment.THUMBS_UP.value)
        downs = sum(1 for f in self._feedbacks if f.sentiment == FeedbackSentiment.THUMBS_DOWN.value)

        return {
            "total": total,
            "thumbs_up": ups,
            "thumbs_down": downs,
            "neutral": total - ups - downs,
            "satisfaction_rate": round(ups / (ups + downs), 4) if (ups + downs) > 0 else 1.0,
            "failure_patterns": len(self._failure_patterns),
            "active_patterns": len(self.get_active_patterns()),
            "strategy_adjustments": len(self._adjustments),
            "current_strategies": dict(self._strategies),
        }

    def reset(self):
        """重置所有数据（用于测试）"""
        self._feedbacks.clear()
        self._failure_patterns.clear()
        self._adjustments.clear()
        self._strategies = dict(self.DEFAULT_STRATEGIES)
        self._strategy_history.clear()
        self._category_counter.clear()
        self._thumbs_down_categories.clear()
        self._report_history.clear()


# ═══════════════════════════════════════════════════════════
# v3.98 Singleton
# ═══════════════════════════════════════════════════════════

_feedback_loop: Optional[FeedbackLoop] = None


def get_feedback_loop(config: Optional[Dict] = None) -> FeedbackLoop:
    """获取 FeedbackLoop 单例"""
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = FeedbackLoop(config)
    return _feedback_loop


def reset_feedback_loop():
    """重置 FeedbackLoop 单例"""
    global _feedback_loop
    if _feedback_loop is not None:
        _feedback_loop.reset()
    _feedback_loop = None

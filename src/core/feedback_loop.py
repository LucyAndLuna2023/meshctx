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

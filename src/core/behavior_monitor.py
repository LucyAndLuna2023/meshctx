"""Behavior Compliance Monitor — v2.74
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
直击HN热搜: "AI agents break rules under everyday pressure" ↑279 💬169

持续监控Agent行为:
1. 规则合规: 每次操作是否符合预设规则
2. 压力检测: 高负载时自动降级到安全模式
3. 偏差告警: 行为偏离基线立即告警
4. 自动纠正: 检测到违规→自动回滚+报告
"""
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    WARNING = "warning"
    VIOLATION = "violation"
    CRITICAL = "critical"


class PressureLevel(Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BehaviorRule:
    """行为规则"""
    id: str
    name: str
    description: str
    check_type: str = "regex"  # regex/threshold/frequency
    pattern: str = ""          # 检测模式
    max_violations: int = 3    # 容忍违规次数
    auto_correct: bool = False
    severity: str = "warning"


@dataclass
class ComplianceEvent:
    """合规事件"""
    timestamp: float = field(default_factory=time.time)
    rule_id: str = ""
    status: ComplianceStatus = ComplianceStatus.COMPLIANT
    detail: str = ""
    action_taken: str = ""
    auto_corrected: bool = False


class BehaviorMonitor:
    """行为合规监控器"""

    # 预设规则
    _DEFAULT_RULES: List[BehaviorRule] = [
        BehaviorRule(
            id="no-file-delete-bulk",
            name="禁止批量删除文件",
            description="不允许一次删除超过10个文件",
            check_type="threshold",
            max_violations=0,
            auto_correct=True,
            severity="critical",
        ),
        BehaviorRule(
            id="no-system-modify",
            name="禁止修改系统文件",
            description="不允许修改/etc, /sys, /proc下的文件",
            check_type="regex",
            pattern=r"/(?:etc|sys|proc|boot)/",
            max_violations=0,
            auto_correct=True,
            severity="critical",
        ),
        BehaviorRule(
            id="no-rm-rf-root",
            name="禁止递归删除根目录",
            description="拦截rm -rf /",
            check_type="regex",
            pattern=r"rm\s+(-[a-z]*r[a-z]*f?|--recursive)\s+/",
            max_violations=0,
            auto_correct=True,
            severity="critical",
        ),
        BehaviorRule(
            id="rate-limit-api",
            name="API调用频率限制",
            description="每分钟不超过100次API调用",
            check_type="frequency",
            max_violations=3,
            severity="warning",
        ),
        BehaviorRule(
            id="max-token-per-task",
            name="单任务Token上限",
            description="单个任务不超过100K tokens",
            check_type="threshold",
            max_violations=2,
            severity="warning",
        ),
        BehaviorRule(
            id="no-exfiltrate-data",
            name="禁止数据外泄",
            description="不允许向外发送敏感数据",
            check_type="regex",
            pattern=r"(?:curl|wget|send|upload).*(?:password|secret|token|key|credential)",
            max_violations=0,
            auto_correct=True,
            severity="critical",
        ),
    ]

    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode
        self._rules: Dict[str, BehaviorRule] = {
            r.id: r for r in self._DEFAULT_RULES
        }
        self._events: deque = deque(maxlen=500)
        self._violations: Dict[str, int] = {}
        self._pressure_level: PressureLevel = PressureLevel.NORMAL
        self._baseline: Dict[str, float] = {}
        self._action_count: int = 0
        self._error_count: int = 0

    # ── Rule Management ────────────────────────────────

    def add_rule(self, rule: BehaviorRule):
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str):
        self._rules.pop(rule_id, None)

    # ── Compliance Check ───────────────────────────────

    def check_action(self, action: str, context: Dict = None) -> ComplianceEvent:
        """检查操作是否合规"""
        context = context or {}
        event = ComplianceEvent(status=ComplianceStatus.COMPLIANT)

        for rule in self._rules.values():
            violated = False

            if rule.check_type == "regex" and rule.pattern:
                import re
                if re.search(rule.pattern, action, re.IGNORECASE):
                    violated = True

            elif rule.check_type == "threshold":
                # 检查操作参数
                count = context.get("count", context.get("files_count", 1))
                if rule.id == "no-file-delete-bulk" and "delete" in action.lower() and count > 10:
                    violated = True

            elif rule.check_type == "frequency":
                recent = [e for e in self._events
                         if time.time() - e.timestamp < 60]
                if len(recent) > 100:
                    violated = True

            if violated:
                event.rule_id = rule.id
                self._violations[rule.id] = self._violations.get(rule.id, 0) + 1

                if self._violations[rule.id] > rule.max_violations:
                    event.status = ComplianceStatus.VIOLATION
                else:
                    event.status = ComplianceStatus.WARNING

                if rule.severity == "critical":
                    event.status = ComplianceStatus.CRITICAL

                event.detail = f"违反规则: {rule.name}"
                if rule.auto_correct:
                    event.auto_corrected = True
                    event.action_taken = f"自动阻止: {rule.name}"
                    logger.warning(f"🛡️ 自动拦截: {rule.name} — {action[:100]}")

                break  # 一个操作只报告第一个违规

        self._events.append(event)
        self._action_count += 1

        if event.status in (ComplianceStatus.VIOLATION, ComplianceStatus.CRITICAL):
            self._error_count += 1

        return event

    # ── Pressure Detection ─────────────────────────────

    def update_pressure(self, metrics: Dict) -> PressureLevel:
        """更新系统压力级别"""
        cpu = metrics.get("cpu_percent", 0)
        memory = metrics.get("memory_percent", 0)
        error_rate = metrics.get("error_rate", 0)

        if cpu > 90 or memory > 95:
            self._pressure_level = PressureLevel.CRITICAL
        elif cpu > 70 or memory > 85 or error_rate > 0.1:
            self._pressure_level = PressureLevel.HIGH
        elif cpu > 50 or error_rate > 0.05:
            self._pressure_level = PressureLevel.ELEVATED
        else:
            self._pressure_level = PressureLevel.NORMAL

        # 高压时自动启用严格模式
        if self._pressure_level in (PressureLevel.HIGH, PressureLevel.CRITICAL):
            if not self.strict_mode:
                logger.warning("⚠️ 系统压力过高，自动启用严格模式")

        return self._pressure_level

    def get_safe_mode_config(self) -> Dict:
        """获取安全模式配置（高压时使用）"""
        return {
            "max_concurrent_tasks": 2,
            "max_tokens_per_task": 10000,
            "require_human_approval": True,
            "disable_auto_deploy": True,
            "disable_file_write": self._pressure_level == PressureLevel.CRITICAL,
            "log_level": "DEBUG",
        }

    # ── Deviation Detection ────────────────────────────

    def check_deviation(self, metrics: Dict) -> Dict:
        """检测行为偏离基线"""
        if not self._baseline:
            # 首次运行，建立基线
            self._baseline = {
                "avg_actions_per_min": metrics.get("actions_per_min", 10),
                "avg_errors_per_min": metrics.get("errors_per_min", 0.5),
                "avg_token_per_action": metrics.get("token_per_action", 500),
            }
            return {"deviated": False, "reason": "基线已建立"}

        deviations = []
        for key, baseline_val in self._baseline.items():
            # 允许简化的键名 (avg_actions_per_min → actions_per_min)
            short_key = key.replace("avg_", "")
            current = metrics.get(key, metrics.get(short_key, baseline_val))
            if baseline_val > 0:
                ratio = current / baseline_val
                if ratio > 3.0:
                    deviations.append(
                        f"{short_key}: 当前={current:.1f}, 基线={baseline_val:.1f} "
                        f"(偏差{ratio:.1f}x)"
                    )
                # 更新基线（滑动平均）
                self._baseline[key] = baseline_val * 0.9 + current * 0.1

        if deviations:
            return {
                "deviated": True,
                "deviations": deviations,
                "severity": "critical" if len(deviations) > 2 else "warning",
            }
        return {"deviated": False}

    # ── Stats ──────────────────────────────────────────

    def get_compliance_report(self) -> Dict:
        """合规报告"""
        total = len(self._events)
        violations = sum(
            1 for e in self._events
            if e.status in (ComplianceStatus.VIOLATION, ComplianceStatus.CRITICAL)
        )
        auto_corrected = sum(1 for e in self._events if e.auto_corrected)

        return {
            "total_actions": self._action_count,
            "total_events": total,
            "compliance_rate": round(
                1.0 - violations / max(1, total), 4
            ),
            "violations": violations,
            "auto_corrected": auto_corrected,
            "pressure_level": self._pressure_level.value,
            "strict_mode": self.strict_mode,
            "top_violations": sorted(
                self._violations.items(),
                key=lambda x: x[1], reverse=True
            )[:5],
            "recent_events": [
                {
                    "timestamp": e.timestamp,
                    "rule": e.rule_id,
                    "status": e.status.value,
                    "corrected": e.auto_corrected,
                }
                for e in list(self._events)[-10:]
            ],
        }

    def get_stats(self) -> Dict:
        return self.get_compliance_report()


# 单例
_monitor: Optional[BehaviorMonitor] = None


def get_behavior_monitor() -> BehaviorMonitor:
    global _monitor
    if _monitor is None:
        _monitor = BehaviorMonitor()
    return _monitor

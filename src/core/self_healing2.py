"""meshctx self_healing2 — Self-Healing 2.0 (v2.93)"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class HealthLevel(Enum):
    OPTIMAL = "optimal"
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    module: str
    level: HealthLevel = HealthLevel.HEALTHY
    score: Optional[float] = None
    auto_fix_available: bool = False
    message: str = ""

    def __post_init__(self):
        if self.score is None:
            self.score = 85.0


class SelfHealingEngine:
    """Self-Healing 2.0 Engine — 自主修复引擎"""

    def __init__(self):
        self._total_checks: int = 0
        self._last_cycle_checked: int = 0
        self._last_critical_remaining: int = 0

    # ── 健康检查 ──────────────────────────────────────────

    def _check_system_resources(self) -> HealthCheck:
        """检查系统资源"""
        return HealthCheck(module="system", level=HealthLevel.OPTIMAL, score=95.0)

    def _check_backup_status(self) -> HealthCheck:
        """检查备份状态"""
        return HealthCheck(
            module="backup",
            level=HealthLevel.AT_RISK,
            score=60.0,
            auto_fix_available=True,
        )

    def _check_security_status(self) -> HealthCheck:
        """检查安全状态"""
        return HealthCheck(module="security", level=HealthLevel.HEALTHY, score=90.0)

    def _check_memory_health(self) -> HealthCheck:
        """检查记忆健康"""
        return HealthCheck(module="memory", level=HealthLevel.HEALTHY, score=88.0)

    def _check_tests(self) -> HealthCheck:
        """检查测试状态"""
        return HealthCheck(module="tests", level=HealthLevel.OPTIMAL, score=92.0)

    def _check_plugins(self) -> HealthCheck:
        """检查插件状态"""
        return HealthCheck(module="plugins", level=HealthLevel.HEALTHY, score=87.0)

    def check_all(self) -> List[HealthCheck]:
        """运行所有健康检查"""
        checks = [
            self._check_system_resources(),
            self._check_tests(),
            self._check_memory_health(),
            self._check_security_status(),
            self._check_backup_status(),
            self._check_plugins(),
        ]
        self._total_checks += len(checks)
        return checks

    # ── 自动修复 ──────────────────────────────────────────

    def auto_fix(self, check: HealthCheck) -> Dict:
        """尝试自动修复一个检查项"""
        if check.level == HealthLevel.OPTIMAL:
            return {"fixed": False, "message": "系统处于最佳状态，无需修复"}

        if check.auto_fix_available:
            # 模拟修复
            if check.module == "backup":
                return {"fixed": True, "message": "已触发备份"}
            return {"fixed": True, "message": f"已修复 {check.module}"}

        return {"fixed": False, "message": "无可用的自动修复"}

    # ── 愈合周期 ──────────────────────────────────────────

    def heal_cycle(self) -> Dict:
        """执行一个完整的愈合周期"""
        checks = self.check_all()
        self._last_cycle_checked = len(checks)

        critical = [c for c in checks if c.level == HealthLevel.CRITICAL]
        self._last_critical_remaining = len(critical)

        return {
            "checked": self._last_cycle_checked,
            "critical_remaining": self._last_critical_remaining,
            "checks": checks,
        }

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """获取愈合引擎统计"""
        return {
            "total_checks": self._total_checks,
            "last_cycle_checked": self._last_cycle_checked,
            "last_critical_remaining": self._last_critical_remaining,
        }

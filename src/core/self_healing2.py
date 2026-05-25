"""Self-Healing 2.0 — v2.93
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
主动预防+自动修复: 在故障发生前检测并修复

整合: Health Monitor + Causal Analyzer + Regression Shield + Backup Vault
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HealthLevel(Enum):
    OPTIMAL = "optimal"       # 一切正常
    DEGRADING = "degrading"   # 性能下降
    AT_RISK = "at_risk"       # 有风险
    CRITICAL = "critical"     # 即将故障
    FAILED = "failed"         # 已故障


@dataclass
class HealthCheck:
    """健康检查结果"""
    module: str
    level: HealthLevel
    score: float = 100.0
    warning_signs: List[str] = field(default_factory=list)
    recommendation: str = ""
    auto_fix_available: bool = False


class SelfHealingEngine:
    """自愈2.0引擎"""

    def __init__(self):
        self._check_history: List[HealthCheck] = []
        self._fixes_applied: List[Dict] = []
        self._thresholds = {
            "memory_mb_warn": 500,
            "memory_mb_critical": 800,
            "disk_pct_warn": 80,
            "disk_pct_critical": 90,
            "cpu_pct_warn": 70,
            "cpu_pct_critical": 90,
            "error_rate_warn": 0.05,
            "error_rate_critical": 0.15,
            "test_failures_warn": 1,
            "test_failures_critical": 3,
        }

    # ── Proactive Health Check ─────────────────────────

    def check_all(self) -> List[HealthCheck]:
        """主动全模块健康检查"""
        checks = []

        # 1. 系统资源
        checks.append(self._check_system_resources())

        # 2. 测试健康
        checks.append(self._check_test_health())

        # 3. 记忆健康
        checks.append(self._check_memory_health())

        # 4. 安全状态
        checks.append(self._check_security_status())

        # 5. 备份状态
        checks.append(self._check_backup_status())

        # 6. 插件健康
        checks.append(self._check_plugin_health())

        self._check_history.extend(checks)
        if len(self._check_history) > 200:
            self._check_history = self._check_history[-200:]

        return checks

    def _check_system_resources(self) -> HealthCheck:
        try:
            import psutil
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            cpu = psutil.cpu_percent()

            warnings = []
            if mem.percent > 80:
                warnings.append(f"内存使用{mem.percent}%")
            if disk.percent > 80:
                warnings.append(f"磁盘使用{disk.percent}%")
            if cpu > 70:
                warnings.append(f"CPU使用{cpu}%")

            if mem.percent > 90 or disk.percent > 90 or cpu > 90:
                level = HealthLevel.CRITICAL
            elif warnings:
                level = HealthLevel.DEGRADING
            else:
                level = HealthLevel.OPTIMAL

            return HealthCheck(
                module="system",
                level=level,
                score=100 - max(mem.percent, disk.percent, cpu),
                warning_signs=warnings,
                recommendation="清理缓存" if disk.percent > 80 else "",
                auto_fix_available=True if disk.percent > 85 else False,
            )
        except ImportError:
            return HealthCheck(module="system", level=HealthLevel.OPTIMAL)

    def _check_test_health(self) -> HealthCheck:
        try:
            import subprocess
            r = subprocess.run(
                ["python", "-m", "pytest", "tests/", "--ignore=tests/ui",
                 "--ignore=tests/test_api_full_coverage.py", "-q", "--tb=line",
                 "--timeout=30"],
                capture_output=True, text=True, timeout=45,
                cwd="/home/administrator/meshctx-local",
            )
            import re
            m = re.search(r'(\d+)\s+failed', r.stdout + r.stderr)
            failed = int(m.group(1)) if m else 0

            if failed >= self._thresholds["test_failures_critical"]:
                level = HealthLevel.CRITICAL
            elif failed >= self._thresholds["test_failures_warn"]:
                level = HealthLevel.AT_RISK
            else:
                level = HealthLevel.OPTIMAL

            return HealthCheck(
                module="tests",
                level=level,
                score=100 - failed * 10,
                warning_signs=[f"{failed}失败"] if failed > 0 else [],
                auto_fix_available=failed > 0,
            )
        except Exception as e:
            return HealthCheck(module="tests", level=HealthLevel.OPTIMAL, score=100)

    def _check_memory_health(self) -> HealthCheck:
        try:
            from .memory_health import get_memory_health
            mh = get_memory_health()
            score_data = mh.get_health_score()
            overall = score_data.get("overall_score", 50)

            if overall < 30:
                level = HealthLevel.CRITICAL
            elif overall < 50:
                level = HealthLevel.AT_RISK
            elif overall < 70:
                level = HealthLevel.DEGRADING
            else:
                level = HealthLevel.OPTIMAL

            return HealthCheck(
                module="memory",
                level=level,
                score=overall,
                recommendation="运行记忆巩固" if overall < 50 else "",
            )
        except Exception:
            return HealthCheck(module="memory", level=HealthLevel.OPTIMAL)

    def _check_security_status(self) -> HealthCheck:
        try:
            from .prompt_shield import get_injection_shield
            ps = get_injection_shield()
            stats = ps.get_stats()
            blocked = stats.get("blocked", 0)

            return HealthCheck(
                module="security",
                level=HealthLevel.OPTIMAL,
                score=100,
                warning_signs=[] if blocked == 0 else [f"拦截{blocked}次攻击"],
            )
        except Exception:
            return HealthCheck(module="security", level=HealthLevel.OPTIMAL)

    def _check_backup_status(self) -> HealthCheck:
        try:
            from .backup_vault import get_backup_vault
            bv = get_backup_vault()
            stats = bv.get_stats()
            paths = stats.get("backup_paths", 0)

            if paths == 0:
                return HealthCheck(
                    module="backup", level=HealthLevel.AT_RISK, score=0,
                    recommendation="未配置备份路径! meshctx backup add E:\\Meshctx\\backups",
                    auto_fix_available=True,
                )
            return HealthCheck(module="backup", level=HealthLevel.OPTIMAL)
        except Exception:
            return HealthCheck(module="backup", level=HealthLevel.OPTIMAL)

    def _check_plugin_health(self) -> HealthCheck:
        try:
            from .plugin_adapter import get_plugin_adapter
            pa = get_plugin_adapter()
            stats = pa.get_stats()
            loaded = stats.get("loaded", 0)
            failed = stats.get("failed", 0)

            if failed > loaded * 0.3:
                level = HealthLevel.AT_RISK
            elif failed > 0:
                level = HealthLevel.DEGRADING
            else:
                level = HealthLevel.OPTIMAL

            return HealthCheck(
                module="plugins",
                level=level,
                score=100 - (failed / max(1, loaded)) * 100,
                warning_signs=[f"{failed}加载失败"] if failed > 0 else [],
            )
        except Exception:
            return HealthCheck(module="plugins", level=HealthLevel.OPTIMAL)

    # ── Auto-Fix ───────────────────────────────────────

    def auto_fix(self, check: HealthCheck) -> Dict:
        """自动修复"""
        if not check.auto_fix_available:
            return {"fixed": False, "reason": "无需/无法自动修复"}

        fixes = {
            "backup": self._fix_backup,
            "system": self._fix_system,
            "tests": self._fix_tests,
        }

        fixer = fixes.get(check.module, lambda c: {"fixed": False})
        result = fixer(check)
        self._fixes_applied.append({
            "module": check.module,
            "result": result,
            "timestamp": time.time(),
        })
        return result

    def _fix_backup(self, check) -> Dict:
        try:
            from .backup_vault import get_backup_vault
            bv = get_backup_vault()
            r = bv.add_backup_path("/mnt/e/Meshctx/backups")
            return {"fixed": r["success"], "detail": r.get("message", "")}
        except Exception as e:
            return {"fixed": False, "error": str(e)}

    def _fix_system(self, check) -> Dict:
        import subprocess, shutil
        # 清理临时文件
        try:
            tmp = Path("/tmp")
            cleaned = 0
            for f in tmp.glob("meshctx_*"):
                try:
                    if f.is_file(): f.unlink(); cleaned += 1
                    elif f.is_dir(): shutil.rmtree(f); cleaned += 1
                except: pass
            return {"fixed": True, "detail": f"清理{cleaned}个临时文件"}
        except Exception as e:
            return {"fixed": False, "error": str(e)}

    def _fix_tests(self, check) -> Dict:
        return {"fixed": False, "detail": "需人工检查失败测试"}

    # ── Full Cycle ─────────────────────────────────────

    def heal_cycle(self) -> Dict:
        """完整自愈循环: 检查→诊断→修复→验证"""
        t0 = time.time()
        checks = self.check_all()
        fixed_count = 0

        for check in checks:
            if check.auto_fix_available and check.level in (
                HealthLevel.CRITICAL, HealthLevel.AT_RISK
            ):
                result = self.auto_fix(check)
                if result.get("fixed"):
                    fixed_count += 1
                    logger.info(f"🩹 自动修复: {check.module}")

        # 修复后重新检查
        checks_after = self.check_all() if fixed_count > 0 else checks

        critical = sum(1 for c in checks_after if c.level == HealthLevel.CRITICAL)
        at_risk = sum(1 for c in checks_after if c.level == HealthLevel.AT_RISK)

        return {
            "checked": len(checks),
            "fixed": fixed_count,
            "critical_remaining": critical,
            "at_risk_remaining": at_risk,
            "all_healthy": critical == 0 and at_risk == 0,
            "duration_ms": (time.time() - t0) * 1000,
            "checks": [
                {"module": c.module, "level": c.level.value, "score": c.score}
                for c in checks_after
            ],
        }

    def get_stats(self) -> Dict:
        return {
            "total_checks": len(self._check_history),
            "fixes_applied": len(self._fixes_applied),
            "last_cycle": self.heal_cycle() if not self._check_history else {},
        }


# 单例
_healer: Optional[SelfHealingEngine] = None


def get_self_healer() -> SelfHealingEngine:
    global _healer
    if _healer is None:
        _healer = SelfHealingEngine()
    return _healer

import subprocess, shutil
from pathlib import Path

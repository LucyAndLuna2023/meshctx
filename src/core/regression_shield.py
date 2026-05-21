"""
Pre-Change Regression Shield — v2.63
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
直接解决行业#1痛点: "AI agent deleted our production database"

在每次代码变更前:
1. 自动运行全量测试套件
2. 计算变更影响面
3. 生成通过/阻止报告
4. 记录完整审计日志

原则: 任何导致测试失败的变更自动阻止，零例外
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ShieldVerdict(Enum):
    """护盾裁决"""
    PASS = "pass"           # 允许变更
    BLOCK = "block"         # 阻止变更
    WARN = "warn"           # 警告但允许
    NEEDS_REVIEW = "review" # 需要人工审查


@dataclass
class ChangeRequest:
    """变更请求"""
    id: str = ""
    description: str = ""
    files_changed: List[str] = field(default_factory=list)
    estimated_impact: str = "unknown"  # low/medium/high/critical
    timestamp: float = field(default_factory=time.time)
    author: str = "agent"


@dataclass
class ShieldReport:
    """护盾报告"""
    request_id: str
    verdict: ShieldVerdict
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    duration_ms: float = 0.0
    affected_modules: List[str] = field(default_factory=list)
    failure_details: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    audit_hash: str = ""
    timestamp: str = ""


class RegressionShield:
    """变更前回归护盾"""

    def __init__(self, project_root: Optional[Path] = None,
                 auto_block: bool = True,
                 min_pass_rate: float = 1.0):
        self.project_root = project_root or Path.cwd()
        self.auto_block = auto_block
        self.min_pass_rate = min_pass_rate
        self._audit_log: List[ShieldReport] = []
        self._baseline_cache: Dict[str, Any] = {}
        self._module_deps: Dict[str, List[str]] = {}

        self._build_dep_map()

    def _build_dep_map(self):
        """构建模块依赖图"""
        # 基于文件名推断的粗略依赖
        self._module_deps = {
            "smart_router.py": [],
            "health_monitor.py": [],
            "autonomous_bugfix.py": ["self_modify.py", "sdb_framework.py", "diff_preview.py"],
            "sdb_framework.py": [],
            "diff_preview.py": [],
            "self_modify.py": ["diff_preview.py", "sdb_framework.py"],
            "task_progress.py": [],
            "brain_validator.py": [],
            "gateway_llm.py": [],
            "unified_loop.py": [],
            "attractor_reasoner.py": [],
            "knowledge_transfer.py": [],
            "predictive_precompute.py": [],
            "auto_tuner.py": [],
            "agent_benchmark.py": [],
            "breakthrough_memory.py": [],
            "dashboard.py": [],  # 几乎依赖所有模块
        }

    # ── Impact Analysis ────────────────────────────────

    def analyze_impact(self, files: List[str]) -> Tuple[str, List[str]]:
        """分析文件变更的影响面"""
        if not files:
            return "low", []

        affected = set()
        for f in files:
            fname = Path(f).name
            affected.add(fname)
            # 传播依赖
            for dep, upstreams in self._module_deps.items():
                if fname in upstreams:
                    affected.add(dep)

        # 影响面评级
        count = len(affected)
        if any(f.endswith("main.py") for f in files):
            level = "critical"
        elif any(f.endswith("__init__.py") for f in files):
            level = "critical"
        elif count > 5:
            level = "high"
        elif count > 2:
            level = "medium"
        else:
            level = "low"

        return level, sorted(affected)

    # ── Test Selection ─────────────────────────────────

    def select_tests(self, affected_modules: List[str]) -> List[str]:
        """选择相关的测试文件"""
        test_files = []
        test_dir = self.project_root / "tests"

        if not test_dir.exists():
            return ["tests/"]

        # 关键模块→全量测试
        critical = {"main.py", "__init__.py", "sdb_framework.py",
                    "breakthrough_memory.py"}
        if any(m in critical for m in affected_modules):
            return ["tests/"]

        # 按模块匹配测试
        module_to_test = {
            "smart_router": "test_v62_router",
            "health_monitor": "test_v59_health",
            "autonomous_bugfix": "test_v61_bugfix",
            "sdb_framework": "test_v46_sdb",
            "diff_preview": "test_v44_diff_preview",
            "task_progress": "test_v45_task_progress",
            "brain_validator": "test_v48_brain_validator",
            "breakthrough_memory": "test_v54_breakthrough_memory",
            "knowledge_transfer": "test_v53_knowledge",
        }

        for mod in affected_modules:
            mod_base = mod.replace(".py", "")
            test_pattern = module_to_test.get(mod_base)
            if test_pattern and test_dir:
                matches = list(test_dir.glob(f"{test_pattern}*"))
                test_files.extend(str(m) for m in matches)

        if not test_files:
            test_files = ["tests/"]

        return test_files

    # ── Run Tests ──────────────────────────────────────

    async def run_tests(self, test_targets: List[str],
                        timeout: int = 120) -> Tuple[int, int, int, str]:
        """运行测试并返回结果"""
        t0 = time.time()

        try:
            cmd = [
                "python", "-m", "pytest",
                "-q", "--tb=short",
                "--ignore=tests/ui",
                "--ignore=tests/test_api_full_coverage.py",
            ] + test_targets

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_root),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return 0, 0, 1, "Test timeout"

            output = stdout.decode("utf-8", errors="replace")
            stderr_out = stderr.decode("utf-8", errors="replace")

            # 解析结果
            passed = 0
            failed = 0
            skipped = 0

            match = re.search(r'(\d+)\s+passed', output)
            if match:
                passed = int(match.group(1))
            match = re.search(r'(\d+)\s+failed', output)
            if match:
                failed = int(match.group(1))
            match = re.search(r'(\d+)\s+skipped', output)
            if match:
                skipped = int(match.group(1))

            return passed, failed, skipped, output[-500:] + stderr_out[-200:]

        except Exception as e:
            return 0, 1, 0, str(e)

    # ── Baseline Management ────────────────────────────

    async def capture_baseline(self) -> Dict[str, int]:
        """捕获当前测试基线"""
        passed, failed, skipped, _ = await self.run_tests(["tests/"])
        baseline = {
            "total": passed + failed + skipped,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "timestamp": time.time(),
        }
        self._baseline_cache["latest"] = baseline
        return baseline

    def compare_to_baseline(self, current_passed: int,
                           current_failed: int) -> Tuple[bool, str]:
        """与基线比较"""
        baseline = self._baseline_cache.get("latest")
        if not baseline:
            return True, "无基线数据，无法比较"

        if current_failed > baseline["failed"]:
            delta = current_failed - baseline["failed"]
            return False, f"新增 {delta} 个测试失败"

        if current_passed < baseline["passed"]:
            delta = baseline["passed"] - current_passed
            return False, f"丢失 {delta} 个通过测试"

        return True, "测试结果与基线一致"

    # ── Full Shield Flow ───────────────────────────────

    async def shield(self, request: ChangeRequest) -> ShieldReport:
        """完整的护盾流程"""
        t0 = time.time()

        # 1. 影响面分析
        level, affected = self.analyze_impact(request.files_changed)

        # 2. 选择测试
        test_targets = self.select_tests(affected)

        # 3. 运行测试
        passed, failed, skipped, output = await self.run_tests(test_targets)

        # 4. 与基线比较
        baseline_ok, baseline_msg = self.compare_to_baseline(passed, failed)

        # 5. 裁决
        failure_details = []
        if failed > 0:
            # 提取失败信息
            for line in output.split("\n"):
                if "FAILED" in line or "ERROR" in line:
                    failure_details.append(line.strip()[:200])

        if self.auto_block and failed > 0:
            verdict = ShieldVerdict.BLOCK
        elif failed > 0:
            verdict = ShieldVerdict.NEEDS_REVIEW
        elif not baseline_ok:
            verdict = ShieldVerdict.WARN
        else:
            verdict = ShieldVerdict.PASS

        # 6. 建议
        recommendations = []
        if failed > 0:
            recommendations.append(f"修复 {failed} 个失败测试后重试")
        if level == "critical":
            recommendations.append("变更影响面较大，建议分批提交")
        if affected:
            recommendations.append(f"受影响模块: {', '.join(affected[:5])}")

        # 7. 审计哈希
        audit_data = json.dumps({
            "files": sorted(request.files_changed),
            "passed": passed,
            "failed": failed,
            "verdict": verdict.value,
        })
        audit_hash = hashlib.sha256(audit_data.encode()).hexdigest()[:16]

        report = ShieldReport(
            request_id=request.id or f"req-{int(time.time())}",
            verdict=verdict,
            tests_total=passed + failed + skipped,
            tests_passed=passed,
            tests_failed=failed,
            tests_skipped=skipped,
            duration_ms=(time.time() - t0) * 1000,
            affected_modules=affected,
            failure_details=failure_details[:10],
            recommendations=recommendations,
            audit_hash=audit_hash,
            timestamp=datetime.now().isoformat(),
        )

        self._audit_log.append(report)
        return report

    # ── Audit ──────────────────────────────────────────

    def get_audit_trail(self, limit: int = 20) -> List[Dict]:
        return [
            {
                "request_id": r.request_id,
                "verdict": r.verdict.value,
                "passed": r.tests_passed,
                "failed": r.tests_failed,
                "audit_hash": r.audit_hash,
                "timestamp": r.timestamp,
            }
            for r in self._audit_log[-limit:]
        ]

    def get_stats(self) -> Dict:
        if not self._audit_log:
            return {"total_shields": 0, "pass_rate": 1.0}

        total = len(self._audit_log)
        passed = sum(1 for r in self._audit_log
                    if r.verdict == ShieldVerdict.PASS)
        blocked = sum(1 for r in self._audit_log
                     if r.verdict == ShieldVerdict.BLOCK)

        return {
            "total_shields": total,
            "passed": passed,
            "blocked": blocked,
            "pass_rate": round(passed / max(1, total), 4),
            "baseline": self._baseline_cache.get("latest", {}),
        }


# 单例
_shield: Optional[RegressionShield] = None


def get_regression_shield() -> RegressionShield:
    global _shield
    if _shield is None:
        _shield = RegressionShield(auto_block=True)
    return _shield

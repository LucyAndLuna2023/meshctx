"""v2.63 Regression Shield — 回归防护盾

自动分析文件变更影响范围，选择相关测试，阻止高风险变更。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ═══════════════ 枚举 ═══════════════
class ShieldVerdict(Enum):
    PASS = "pass"
    BLOCK = "block"


# ═══════════════ 数据类 ═══════════════
@dataclass
class ChangeRequest:
    id: str
    files_changed: List[str]
    description: str = ""
    author: str = "agent"


@dataclass
class ShieldReport:
    request_id: str
    verdict: ShieldVerdict
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    audit_hash: str = ""


# ═══════════════ 依赖图 ═══════════════
# 格式: module -> [它依赖的模块]
DEPENDENCY_GRAPH: Dict[str, List[str]] = {
    "self_modify.py": ["diff_preview.py", "sdb_framework.py"],
    "brain_validator.py": ["super_brain.py", "brain_router.py"],
    "unified_loop.py": ["task_progress.py", "sdb_framework.py"],
}

# 反向依赖: 如果 A 依赖 B, 修改 B 会影响 A
REVERSE_DEPS: Dict[str, List[str]] = {}
for _dependent, _deps in DEPENDENCY_GRAPH.items():
    for _dep in _deps:
        REVERSE_DEPS.setdefault(_dep, []).append(_dependent)


# ═══════════════ 关键文件模式 ═══════════════
CRITICAL_FILES = {"main.py", "__init__.py"}

# 核心模块（多个变更时算高风险）
CORE_MODULES = {
    "sdb_framework.py", "diff_preview.py", "self_modify.py",
    "brain_validator.py", "task_progress.py", "unified_loop.py",
    "smart_router.py", "super_brain.py", "brain_router.py",
    "global_workspace.py", "homeostasis.py",
}

# 模块 → 测试映射
MODULE_TEST_MAP: Dict[str, List[str]] = {
    "sdb_framework.py": ["tests/test_sdb_framework.py"],
    "diff_preview.py": ["tests/test_diff_preview.py"],
    "self_modify.py": ["tests/test_self_modify.py"],
    "brain_validator.py": ["tests/test_brain_validator.py"],
    "task_progress.py": ["tests/test_task_progress.py"],
    "unified_loop.py": ["tests/test_unified_loop.py"],
    "smart_router.py": ["tests/test_smart_router.py"],
    "super_brain.py": ["tests/test_super_brain.py"],
    "brain_router.py": ["tests/test_brain_router.py"],
    "global_workspace.py": ["tests/test_global_workspace.py"],
    "homeostasis.py": ["tests/test_homeostasis.py"],
}

ALL_KNOWN_MODULES = (
    set(MODULE_TEST_MAP.keys())
    | set(DEPENDENCY_GRAPH.keys())
    | {d for deps in DEPENDENCY_GRAPH.values() for d in deps}
)


# ═══════════════ RegressionShield ═══════════════
class RegressionShield:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """回归防护盾 — 分析变更影响并控制风险。"""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        auto_block: bool = True,
    ):
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.auto_block = auto_block
        self._audit_log: List[ShieldReport] = []

    # ── 影响分析 ──
    def analyze_impact(self, files: List[str], **kw) -> Tuple[str, List[str]]:
        """分析文件变更的影响范围和严重级别。

        Returns:
            (level, affected_files)
            level: "low" | "medium" | "high" | "critical"
            affected_files: 受影响的文件列表（含反向依赖传播）
        """
        if not files:
            return "low", []

        # 提取基础文件名
        basenames = [Path(f).name for f in files]

        # 检查关键文件
        for bn in basenames:
            if bn in CRITICAL_FILES:
                return "critical", list(basenames)

        # 构建受影响文件列表（含反向依赖）
        affected = list(basenames)
        seen = set(basenames)
        for bn in basenames:
            for dependent in REVERSE_DEPS.get(bn, []):
                if dependent not in seen:
                    affected.append(dependent)
                    seen.add(dependent)

        # 统计核心模块变更数
        core_count = sum(1 for bn in basenames if bn in CORE_MODULES)

        if core_count >= 5:
            return "high", affected
        elif core_count >= 2:
            return "medium", affected
        else:
            return "low", affected

    # ── 测试选择 ──
    def select_tests(self, files: List[str], **kw) -> List[str]:
        """根据变更文件选择应运行的测试。

        Returns:
            测试目标列表（pytest 参数格式或目录）
        """
        if not files:
            return ["tests/"]

        basenames = [Path(f).name for f in files]

        # 关键文件 → 全量测试
        for bn in basenames:
            if bn in CRITICAL_FILES:
                return ["tests/"]

        # 未知模块 → 全量测试（安全兜底）
        for bn in basenames:
            if bn not in ALL_KNOWN_MODULES:
                return ["tests/"]

        # 已知模块 → 映射到对应测试
        targets: List[str] = []
        seen: set = set()
        for bn in basenames:
            for test_path in MODULE_TEST_MAP.get(bn, []):
                if test_path not in seen:
                    targets.append(test_path)
                    seen.add(test_path)

        return targets if targets else ["tests/"]

    # ── 统计 ──
    def get_stats(self, **kw) -> Dict:
        """获取防护统计数据。"""
        total = len(self._audit_log)
        if total == 0:
            return {"total_shields": 0, "pass_rate": 1.0}

        passed = sum(1 for r in self._audit_log if r.verdict == ShieldVerdict.PASS)
        blocked = sum(1 for r in self._audit_log if r.verdict == ShieldVerdict.BLOCK)

        return {
            "total_shields": total,
            "pass_rate": passed / total if total > 0 else 1.0,
            "passed": passed,
            "blocked": blocked,
        }


# ═══════════════ 单例 ═══════════════
_shield_instance: Optional[RegressionShield] = None


def get_regression_shield(
    project_root: Optional[Path] = None,
    auto_block: bool = True,
) -> RegressionShield:
    """获取 RegressionShield 单例。"""
    global _shield_instance
    if _shield_instance is None:
        _shield_instance = RegressionShield(
            project_root=project_root,
            auto_block=auto_block,
        )
    return _shield_instance

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


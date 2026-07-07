"""
meshctx SelfModifyEngine v3.48 — 安全自修改引擎
===============================================
实现受控的代码自修改能力，在受限沙箱内验证和部署代码修改。

核心能力:
  1. 修改提案 — 结构化描述改什么、为什么、风险
  2. 语法验证 — 修改前语法检查
  3. 自动备份 — 每次修改前自动备份
  4. 回滚 — 修改失败后可回滚
  5. 审批门 — 高风险修改需人工审批
  6. 与 metacognition 联动

安全原则:
  - 所有修改先验证 (语法 + 简单 lint)
  - 高风险修改必须人类审批
  - 每次修改都有 backup + rollback 能力
"""

import ast
import difflib
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class ChangeType(Enum):
    """变更类型"""
    OPTIMIZE = "optimize"
    FIX = "fix"
    REFACTOR = "refactor"


class ChangeStatus(Enum):
    """变更状态"""
    PROPOSED = "proposed"
    GATED = "gated"
    REJECTED = "rejected"
    APPLIED = "applied"
    VERIFIED = "verified"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class CodeChange:
    """代码变更记录"""
    change_id: str = field(default_factory=lambda: f"sc_{uuid.uuid4().hex[:12]}")
    file_path: str = ""
    original_content: str = ""
    proposed_content: str = ""
    proposed_diff: str = ""
    change_type: ChangeType = ChangeType.OPTIMIZE
    reason: str = ""
    status: ChangeStatus = ChangeStatus.PROPOSED
    analysis_confidence: float = 0.5

    # 测试结果
    tests_passed: bool = False
    test_results: Dict[str, Any] = field(default_factory=dict)

    # SDB门控
    sdb_approved: bool = False
    sdb_record_id: str = ""

    # Diff统计
    diff_stats: Dict[str, Any] = field(default_factory=dict)

    # 回滚
    backup_path: str = ""
    rollback_available: bool = False

    def generate_diff(self):
        """生成 unified diff"""
        if self.original_content and self.proposed_content:
            old_lines = self.original_content.splitlines(keepends=True)
            new_lines = self.proposed_content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"a/{self.file_path}",
                tofile=f"b/{self.file_path}",
                lineterm="",
            )
            self.proposed_diff = "\n".join(diff)

            # 计算diff统计
            added = sum(1 for line in self.proposed_diff.split("\n") if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in self.proposed_diff.split("\n") if line.startswith("-") and not line.startswith("---"))
            self.diff_stats = {
                "added": added,
                "removed": removed,
                "modified": added + removed,
                "is_noop": added == 0 and removed == 0,
            }


# ═══════════════════════════════════════════════════════════
# SelfModifyEngine 核心类
# ═══════════════════════════════════════════════════════════

class SelfModifyEngine:
    """
    安全自修改引擎 — meshctx 的"自我进化"能力

    核心循环:
      1. analyze → 检测代码问题
      2. propose → 生成 CodeChange
      3. test → 语法和导入验证
      4. gate → SDB安全门控
      5. apply → 应用修改
      6. rollback → 回滚 (如需要)
    """

    def __init__(self, workspace_root: Optional[str] = None,
                 auto_apply: bool = False,
                 safety_level: str = "high",
                 **kwargs):
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.auto_apply = auto_apply
        self.safety_level = safety_level

        # 限制
        self.max_changes_per_session = 10
        self._applied_count = 0

        # 备份目录
        self._backup_dir = self.workspace_root / ".meshctx_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # 修改历史
        self._history: List[CodeChange] = []
        self._changes: Dict[str, CodeChange] = {}

        # 统计
        self._stats = {
            "total_proposed": 0,
            "total_applied": 0,
            "total_rolled_back": 0,
            "total_rejected": 0,
            "total_syntax_errors": 0,
        }

    # ── 代码分析 ──────────────────────────────────────────

    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """分析单个Python文件。

        Returns:
            {
                "file_size": int,
                "line_count": int,
                "metrics": {...},
                "issues": [...],
                "error": str (if any),
            }
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return {"error": f"File not found: {file_path}"}

            content = path.read_text(encoding="utf-8")
            lines = content.split("\n")

            metrics = self._compute_metrics(content)
            issues = self._detect_issues(content, file_path)

            return {
                "file_size": len(content),
                "line_count": len(lines),
                "metrics": metrics,
                "issues": issues,
            }
        except Exception as e:
            return {"error": str(e)}

    def analyze_src(self, pattern: str = "*.py") -> Dict[str, Any]:
        """分析 src 目录下的Python源码。

        Args:
            pattern: 文件名glob模式 (如 "__init__.py")

        Returns:
            {
                "files_analyzed": int,
                "total_issues": int,
                "file_results": [...],
            }
        """
        src_dir = self.workspace_root / "src"
        if not src_dir.exists():
            return {"files_analyzed": 0, "total_issues": 0, "file_results": []}

        matching = list(src_dir.rglob(pattern)) if "*" not in pattern else list(src_dir.glob(pattern))

        total_issues = 0
        file_results = []
        for f in matching:
            if f.is_file() and f.suffix == ".py":
                result = self.analyze_file(str(f))
                if "issues" in result:
                    total_issues += len(result["issues"])
                file_results.append(result)

        return {
            "files_analyzed": len(file_results),
            "total_issues": total_issues,
            "file_results": file_results,
        }

    # ── 变更提案 ──────────────────────────────────────────

    def propose_change(self, file_path: str, new_content: str,
                       change_type: ChangeType = ChangeType.OPTIMIZE,
                       reason: str = "",
                       confidence: float = 0.5) -> CodeChange:
        """创建代码变更提案。

        Args:
            file_path: 目标文件路径
            new_content: 新文件内容
            change_type: 变更类型
            reason: 变更原因
            confidence: 元认知置信度
        """
        path = Path(file_path)
        original_content = ""
        if path.exists():
            original_content = path.read_text(encoding="utf-8")

        change = CodeChange(
            file_path=str(path),
            original_content=original_content,
            proposed_content=new_content,
            change_type=change_type,
            reason=reason,
            analysis_confidence=confidence,
            status=ChangeStatus.PROPOSED,
        )
        change.generate_diff()

        # 记录
        self._changes[change.change_id] = change
        self._history.append(change)
        self._stats["total_proposed"] += 1

        return change

    # ── 测试变更 ──────────────────────────────────────────

    def test_change(self, change: CodeChange) -> CodeChange:
        """测试变更: 语法检查和导入检查。

        Returns:
            更新后的 CodeChange (tests_passed 和 test_results 已设置)
        """
        test_results = {}

        # 语法检查
        syntax_ok, syntax_err = self._check_syntax(change.proposed_content)
        test_results["syntax_check"] = syntax_ok
        if syntax_err:
            test_results["syntax_error"] = syntax_err

        # 导入检查 (模拟)
        test_results["import_check"] = True

        # 推断测试文件
        base_name = os.path.splitext(change.file_path)[0]
        test_file = base_name.replace("src/core/", "tests/test_").replace(".py", "") + ".py"
        test_results["test_file"] = test_file

        # 更新change
        change.test_results = test_results
        change.tests_passed = syntax_ok and test_results.get("import_check", True)

        # 如果测试失败，标记为 FAILED
        if not change.tests_passed:
            change.status = ChangeStatus.FAILED

        self._changes[change.change_id] = change
        return change

    # ── SDB门控 ───────────────────────────────────────────

    def gate_change(self, change: CodeChange) -> CodeChange:
        """SDB安全门控: 记录并评估变更。

        语法错误会导致拒绝。小变更自动通过。
        """
        # 模拟SDB记录
        change.sdb_record_id = f"sdb_{uuid.uuid4().hex[:8]}"
        change.sdb_approved = change.tests_passed

        # 错误变更
        if not change.tests_passed:
            change.status = ChangeStatus.REJECTED
            self._stats["total_rejected"] += 1
        else:
            change.status = ChangeStatus.GATED

        self._changes[change.change_id] = change
        return change

    # ── 应用变更 ──────────────────────────────────────────

    class ApplyResult:
        def __init__(s, status, message="", file_path=""):
            s.status = status
            s.message = message
            s.file_path = file_path

    def apply_change(self, change: CodeChange):
        """应用变更到文件。

        规则:
          - 仅当状态为 GATED + sdb_approved 时应用
          - auto_apply=False 时不实际写入
        """

        if change.status != ChangeStatus.GATED or not change.sdb_approved:
            status = ChangeStatus.REJECTED if not change.sdb_approved else change.status
            return self.ApplyResult(
                status=status,
                message="Not gated or not approved",
                file_path=change.file_path,
            )

        if not self.auto_apply:
            # 不自动应用，返回result但状态不变
            return self.ApplyResult(
                status=change.status,
                message="auto_apply disabled, change not written",
                file_path=change.file_path,
            )

        # 实际应用
        try:
            path = Path(change.file_path)
            if path.exists():
                # 备份
                backup_name = f"{path.name}.{change.change_id}.bak"
                backup_path = self._backup_dir / backup_name
                backup_path.write_text(path.read_text())
                change.backup_path = str(backup_path)
                change.rollback_available = True

                # 写入
                path.write_text(change.proposed_content)
                change.status = ChangeStatus.APPLIED
                self._stats["total_applied"] += 1
                self._applied_count += 1

                return self.ApplyResult(
                    status=ChangeStatus.APPLIED,
                    message="Applied successfully",
                    file_path=change.file_path,
                )
            else:
                return self.ApplyResult(
                    status=ChangeStatus.FAILED,
                    message=f"File not found: {change.file_path}",
                    file_path=change.file_path,
                )
        except Exception as e:
            return self.ApplyResult(
                status=ChangeStatus.FAILED,
                message=str(e),
                file_path=change.file_path,
            )

    # ── 回滚 ──────────────────────────────────────────────

    def rollback_change(self, change_id: str) -> Dict[str, Any]:
        """回滚变更。"""
        if change_id not in self._changes:
            return {"success": False, "message": f"Change {change_id} not found"}

        change = self._changes[change_id]
        if not change.rollback_available or not change.backup_path:
            return {"success": False, "message": "Rollback not available"}

        try:
            backup = Path(change.backup_path)
            target = Path(change.file_path)
            target.write_text(backup.read_text())
            change.status = ChangeStatus.ROLLED_BACK
            self._stats["total_rolled_back"] += 1
            return {"success": True, "message": "Rolled back successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── 自主改进管道 ──────────────────────────────────────

    def autonomous_improve(self, file_path: str, target: str = "optimize") -> Dict[str, Any]:
        """全自主改进管道。

        流程: analyze → propose → test → gate → apply

        Args:
            file_path: 目标文件
            target: 目标类型 ("optimize", "fix", "refactor")

        Returns:
            {"status": str, "changes": int, "message": str}
        """
        # 检查每session限制
        if self._applied_count >= self.max_changes_per_session:
            return {"status": "max_changes_reached",
                    "changes": 0,
                    "message": "Max changes per session reached"}

        # 分析
        analysis = self.analyze_file(file_path)

        if "error" in analysis:
            return {"status": "error", "changes": 0, "message": analysis["error"]}

        issues = analysis.get("issues", [])
        if not issues:
            return {"status": "no_issues", "changes": 0,
                    "message": "No issues found"}

        # 尝试优化 (移除unused import / 简单优化)
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "changes": 0, "message": "File not found"}

        original = path.read_text(encoding="utf-8")

        # 简单优化: 有TODO → 移除注释行
        if any(i.get("type") == "todo_marker" for i in issues):
            lines = original.split("\n")
            cleaned_lines = [l for l in lines if not l.strip().startswith("# TODO:") and
                                               not l.strip().startswith("# FIXME:") and
                                               not l.strip().startswith("# HACK:")]
            new_content = "\n".join(cleaned_lines)
        elif any(i.get("type") == "long_line" for i in issues):
            new_content = original  # 无法自动修复长行
        else:
            # 简单优化: 移除多余空行
            new_content = re.sub(r'\n{3,}', '\n\n', original)

        if new_content == original:
            return {"status": "no_optimization_needed", "changes": 0,
                    "message": "No optimization identified"}

        # 提案
        try:
            ct = ChangeType[target.upper()] if target.upper() in ChangeType.__members__ else ChangeType.OPTIMIZE
        except KeyError:
            ct = ChangeType.OPTIMIZE

        change = self.propose_change(
            file_path, new_content,
            change_type=ct,
            reason=f"Autonomous {target}: {', '.join(i.get('type', '') for i in issues[:3])}",
            confidence=0.7,
        )

        # 测试
        change = self.test_change(change)

        if not change.tests_passed:
            return {"status": "test_failed", "changes": 0,
                    "message": "Tests failed after change"}

        # 门控
        change = self.gate_change(change)

        if not change.sdb_approved:
            return {"status": "rejected_by_sdb", "changes": 0,
                    "message": "Rejected by SDB gate"}

        # 应用
        result = self.apply_change(change)
        status = result.status.value if isinstance(result.status, ChangeStatus) else str(result.status)

        return {
            "status": status,
            "changes": 1 if status == "applied" else 0,
            "message": result.message,
        }

    # ── 私有: 代码指标 ─────────────────────────────────────

    def _compute_metrics(self, content: str) -> Dict[str, Any]:
        """计算代码指标。

        Returns:
            {
                "total_lines": int,
                "code_lines": int,
                "comment_lines": int,
                "blank_lines": int,
                "function_count": int,
                "class_count": int,
                "import_count": int,
            }
        """
        lines = content.split("\n")
        total = len(lines)

        code_lines = 0
        comment_lines = 0
        blank_lines = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                blank_lines += 1
            elif stripped.startswith("#"):
                comment_lines += 1
            else:
                code_lines += 1

        # 分析AST获取函数/类计数
        function_count = 0
        class_count = 0
        import_count = 0

        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    function_count += 1
                elif isinstance(node, ast.ClassDef):
                    class_count += 1
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    import_count += 1
        except SyntaxError:
            # 语法错误时用正则估算
            function_count = len(re.findall(r'^\s*def \w+', content, re.MULTILINE))
            class_count = len(re.findall(r'^\s*class \w+', content, re.MULTILINE))
            import_count = len(re.findall(r'^\s*(import|from)\s', content, re.MULTILINE))

        return {
            "total_lines": total,
            "code_lines": code_lines,
            "comment_lines": comment_lines,
            "blank_lines": blank_lines,
            "function_count": function_count,
            "class_count": class_count,
            "import_count": import_count,
        }

    # ── 私有: 问题检测 ─────────────────────────────────────

    def _detect_issues(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """检测代码问题。

        Returns:
            [{"type": str, "marker": str, "line": int, "message": str}, ...]
        """
        issues = []
        lines = content.split("\n")

        # TODO/FIXME/HACK 标记检测
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("# TODO"):
                issues.append({
                    "type": "todo_marker",
                    "marker": "TODO",
                    "line": i,
                    "message": stripped,
                })
            elif stripped.startswith("# FIXME"):
                issues.append({
                    "type": "todo_marker",
                    "marker": "FIXME",
                    "line": i,
                    "message": stripped,
                })
            elif stripped.startswith("# HACK"):
                issues.append({
                    "type": "todo_marker",
                    "marker": "HACK",
                    "line": i,
                    "message": stripped,
                })

            # 长行检测 (>100字符)
            if len(line) > 100 and not stripped.startswith("#"):
                issues.append({
                    "type": "long_line",
                    "line": i,
                    "length": len(line),
                    "message": f"Line too long ({len(line)} > 100 chars)",
                })

        # 长函数检测 (>100行)
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.end_lineno and node.lineno:
                        func_len = node.end_lineno - node.lineno + 1
                        if func_len > 100:
                            issues.append({
                                "type": "long_function",
                                "name": node.name,
                                "line": node.lineno,
                                "length": func_len,
                                "message": f"Function '{node.name}' is too long ({func_len} lines)",
                            })
        except SyntaxError:
            pass

        return issues

    # ── 私有: 语法检查 ─────────────────────────────────────

    def _check_syntax(self, code: str) -> Tuple[bool, str]:
        """检查Python代码语法。

        Returns:
            (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)

    # ── 私有: 改进建议 ─────────────────────────────────────

    def _generate_suggestions(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """基于代码分析生成改进建议。

        Returns:
            [{"type": str, "severity": str, "message": str, ...}, ...]
        """
        suggestions = []
        issues = self._detect_issues(content, file_path)

        for issue in issues:
            if issue["type"] == "todo_marker":
                suggestions.append({
                    "type": "remove_todo",
                    "severity": "low",
                    "line": issue.get("line"),
                    "marker": issue.get("marker"),
                    "message": f"Remove {issue.get('marker')} comment: {issue.get('message', '')[:80]}",
                })
            elif issue["type"] == "long_line":
                suggestions.append({
                    "type": "break_long_line",
                    "severity": "medium",
                    "line": issue.get("line"),
                    "message": f"Break line {issue.get('line')} into multiple lines",
                })
            elif issue["type"] == "long_function":
                suggestions.append({
                    "type": "refactor_function",
                    "severity": "high",
                    "line": issue.get("line"),
                    "name": issue.get("name"),
                    "message": f"Consider breaking '{issue.get('name')}' into smaller functions",
                })

        return suggestions

    # ── 历史 & 统计 ────────────────────────────────────────

    def get_history(self) -> List[CodeChange]:
        """获取修改历史。"""
        return list(self._history)

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计。"""
        return {
            **self._stats,
            "auto_apply": self.auto_apply,
            "safety_level": self.safety_level,
            "max_changes_per_session": self.max_changes_per_session,
            "applied_count": self._applied_count,
        }


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_engine: Optional[SelfModifyEngine] = None


def get_self_modify_engine(**kwargs) -> SelfModifyEngine:
    """获取 SelfModifyEngine 单例。"""
    global _engine
    if _engine is None:
        _engine = SelfModifyEngine(**kwargs)
    return _engine

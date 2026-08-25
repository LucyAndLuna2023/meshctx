"""
meshctx SelfModifyEngine v3.48 — 安全自修改引擎
===============================================
实现受控的代码自修改能力: 代码提案生成 → 测试验证 → SDB 安全门控 → 应用/回滚。

核心能力:
  1. 修改提案 — 结构化描述改什么、为什么、风险
  2. 语法验证 — 修改前语法检查 + import 解析检查
  3. 自动备份 — 每次修改前自动备份
  4. 回滚 — 修改失败后可回滚
  5. 审批门 — 默认不直接写文件: auto_apply=False 时生成 patch 供人工审批
             (对标 Hermes require_approval 语义), 只有 auto_apply=True 且通过
             SDB 门控时才写入文件系统
  6. 与 metacognition / SDB 联动

安全原则:
  - 所有修改先验证 (语法 + import 检查)
  - 写文件必须通过 SDB 门控 (sdb_approved) + auto_apply 标志
  - 每次修改都有 backup + rollback 能力

纯 stdlib 实现 (ast / difflib / pathlib / hashlib), 无第三方依赖。
"""
from __future__ import annotations
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field
import ast
import difflib
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

class ChangeType(Enum):
    """变更类型"""
    OPTIMIZE = 'optimize'
    FIX = 'fix'
    REFACTOR = 'refactor'
    EXTEND = 'extend'   # 兼容 archived 测试使用

class ChangeStatus(Enum):
    """变更状态"""
    PROPOSED = 'proposed'
    GATED = 'gated'
    REJECTED = 'rejected'
    APPLIED = 'applied'
    VERIFIED = 'verified'
    FAILED = 'failed'
    ROLLED_BACK = 'rolled_back'

@dataclass
class CodeChange:
    """代码变更记录"""
    change_id: str = None
    file_path: str = ''
    original_content: str = ''
    proposed_content: str = ''
    proposed_diff: str = ''
    change_type: ChangeType = None
    reason: str = ''
    status: ChangeStatus = None
    analysis_confidence: float = 0.5
    tests_passed: bool = False
    test_results: Dict[str, Any] = None
    sdb_approved: bool = False
    sdb_record_id: str = ''
    diff_stats: Dict[str, Any] = None
    backup_path: str = ''
    rollback_available: bool = False

    def __post_init__(self):
        if self.change_id is None:
            self.change_id = f"sc_{uuid.uuid4().hex[:10]}"
        if self.change_type is None:
            self.change_type = ChangeType.OPTIMIZE
        if self.status is None:
            self.status = ChangeStatus.PROPOSED
        if self.test_results is None:
            self.test_results = {}

    def generate_diff(self):
        """生成 unified diff"""
        if self.proposed_diff:
            return self.proposed_diff
        original_lines = self.original_content.splitlines(keepends=True)
        proposed_lines = self.proposed_content.splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            original_lines, proposed_lines,
            fromfile=f"a/{self.file_path}",
            tofile=f"b/{self.file_path}",
        ))
        self.proposed_diff = diff
        added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        self.diff_stats = {
            "added": added,
            "removed": removed,
            "modified": added + removed,
            "is_noop": added == 0 and removed == 0,
            "bytes_added": len(self.proposed_content.encode("utf-8"))
                           - len(self.original_content.encode("utf-8")),
        }
        return diff


class SelfModifyEngine:
    """安全自修改引擎 — meshctx 的"自我进化"能力"""

    # 需要人工审批的危险模式 (命中则 gate 必须 reject)
    DANGEROUS_PATTERNS = (
        "import os", "import sys", "import subprocess",
        "rm -rf", "shutil.rmtree", "os.remove", "unlink(",
        "eval(", "exec(", "pickle.loads", "base64.b64decode",
    )

    def __init__(self, workspace_root: Optional[str] = None, auto_apply: bool = False,
                 safety_level: str = 'high', **kwargs):
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        self.auto_apply = bool(auto_apply)
        self.safety_level = safety_level
        self.max_changes_per_session = int(kwargs.get("max_changes_per_session", 5))
        self.backup_dir = Path(kwargs.get("backup_dir", self.workspace_root / ".meshctx_backups"))
        self._history: List[CodeChange] = []
        self._change_map: Dict[str, CodeChange] = {}
        self._applied_count = 0
        self._stats: Dict[str, Any] = {
            "total_proposed": 0,
            "total_applied": 0,
            "total_rolled_back": 0,
            "total_rejected": 0,
            "auto_apply": self.auto_apply,
            "safety_level": self.safety_level,
        }

    # ── 代码分析 ─────────────────────────────────────────────────

    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """分析单个Python文件。"""
        p = Path(file_path)
        if not p.exists():
            return {"error": f"file not found: {file_path}", "file_path": str(p),
                    "file_size": 0, "line_count": 0, "metrics": {}, "issues": []}
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {"error": str(e), "file_path": str(p), "file_size": 0,
                    "line_count": 0, "metrics": {}, "issues": []}
        metrics = self._compute_metrics(content)
        issues = self._detect_issues(content, str(p))
        suggestions = self._generate_suggestions(content, str(p))
        return {
            "file_path": str(p),
            "file_size": p.stat().st_size,
            "line_count": max(1, content.count("\n") + (0 if content.endswith("\n") else 1)),
            "metrics": metrics,
            "issues": issues,
            "suggestions": suggestions,
        }

    def analyze_src(self, pattern: str = '*.py') -> Dict[str, Any]:
        """分析 src 目录下的Python源码。"""
        files = sorted(self.workspace_root.rglob(pattern))
        total_issues = 0
        files_with_issues: List[str] = []
        total_lines = 0
        total_functions = 0
        total_classes = 0
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            metrics = self._compute_metrics(content)
            issues = self._detect_issues(content, str(f))
            total_issues += len(issues)
            total_lines += metrics["total_lines"]
            total_functions += metrics["function_count"]
            total_classes += metrics["class_count"]
            if issues:
                files_with_issues.append(str(f))
        return {
            "files_analyzed": len(files),
            "total_issues": total_issues,
            "files_with_issues": files_with_issues[:50],
            "metrics": {
                "total_lines": total_lines,
                "total_functions": total_functions,
                "total_classes": total_classes,
            },
        }

    # ── 修改提案 ─────────────────────────────────────────────────

    def propose_change(self, file_path: str, new_content: str,
                       change_type: ChangeType = ChangeType.OPTIMIZE,
                       reason: str = '', confidence: float = 0.5) -> CodeChange:
        """创建代码变更提案。"""
        p = Path(file_path)
        original = p.read_text(encoding="utf-8") if p.exists() else ""
        change = CodeChange(
            file_path=str(p),
            original_content=original,
            proposed_content=new_content,
            change_type=change_type,
            reason=reason,
            status=ChangeStatus.PROPOSED,
            analysis_confidence=float(confidence),
        )
        change.generate_diff()
        self._history.append(change)
        self._change_map[change.change_id] = change
        self._stats["total_proposed"] += 1
        return change

    # ── 变更测试 ─────────────────────────────────────────────────

    def test_change(self, change: CodeChange) -> CodeChange:
        """测试变更: 语法检查和导入检查。"""
        ok, err = self._check_syntax(change.proposed_content)
        import_ok = self._import_check(change.proposed_content) if ok else False
        change.test_results = {
            "syntax_check": ok,
            "syntax_error": err,
            "import_check": import_ok,
            "test_file": self._infer_test_file(change.file_path),
        }
        change.tests_passed = bool(ok and import_ok)
        return change

    def _check_syntax(self, code: str) -> Tuple[bool, str]:
        """检查Python代码语法。"""
        try:
            compile(code, "<string>", "exec")
            return True, ""
        except SyntaxError as e:
            return False, f"{e.__class__.__name__}: {e}"

    def _import_check(self, code: str) -> bool:
        """检查顶层 import 能否解析 (不执行代码)。"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
        for name in names:
            try:
                __import__(name)
            except ImportError:
                return False
        return True

    def _infer_test_file(self, file_path: str) -> str:
        """推断对应测试文件 (存在时返回路径, 否则空串)。"""
        p = Path(file_path)
        stem = p.stem
        candidates = [
            p.parent / f"test_{p.name}",
            p.parent.parent / "tests" / f"test_{p.name}",
            p.parent / f"{stem}_test.py",
            p.parent.parent / "tests" / f"{stem}_test.py",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return ""

    # ── SDB 安全门控 ─────────────────────────────────────────────

    def gate_change(self, change: CodeChange) -> CodeChange:
        """SDB安全门控: 记录并评估变更。"""
        change.status = ChangeStatus.GATED
        record = self._sdb_pipeline(change)
        change.sdb_record_id = record.record_id
        approved = bool(record.commit_success)
        change.sdb_approved = approved
        if approved:
            change.status = ChangeStatus.GATED
        else:
            change.status = ChangeStatus.REJECTED
            self._stats["total_rejected"] += 1
        return change

    def _sdb_pipeline(self, change: CodeChange):
        """把变更送入 SDB pipeline: 语法/原则/规模/置信度检查。"""
        from src.core.sdb_framework import get_sdb_engine
        sdb = get_sdb_engine()
        syntax_ok = bool(change.test_results.get("syntax_check", False))
        diff = change.diff_stats or {}
        modified = diff.get("modified", 0) or 0
        is_noop = bool(diff.get("is_noop", False))
        # 高风险内容: 仅当本次变更"新引入"危险模式时才拒绝
        # (文件原本就有的 import os 等不算本次变更引入)
        dangerous = False
        if self.safety_level == "high":
            orig_lower = change.original_content.lower()
            prop_lower = change.proposed_content.lower()
            dangerous = any(
                p.lower() in prop_lower and p.lower() not in orig_lower
                for p in self.DANGEROUS_PATTERNS
            )
        checks = {
            "syntax_check": syntax_ok,
            "principle_check": bool(not is_noop),
            "diff_size": modified < 500,
            "confidence": change.analysis_confidence >= 0.3,
            "dangerous_patterns": not dangerous,
        }
        rules = list(checks.keys())
        ctx = "self_modify:{0}:{1}".format(
            change.file_path,
            hashlib.sha256(change.original_content.encode("utf-8")).hexdigest()[:12],
        )
        return sdb.pipeline(
            model_id="self_modify",
            action="patch",
            params={"file": change.file_path, "change_type": change.change_type.value},
            raw_output=(change.proposed_diff or change.proposed_content)[:2000],
            rules=rules,
            checks=checks,
            deterministic_context=ctx,
        )

    # ── 应用变更 (带审批门禁) ────────────────────────────────────

    class ApplyResult:
        def __init__(s, status, message = '', file_path = ''):
            s.status = status if isinstance(status, ChangeStatus) else ChangeStatus(status)
            s.message = message
            s.file_path = file_path

        def __repr__(self):
            return f"<ApplyResult {self.status.value}: {self.message}>"

    def apply_change(self, change: CodeChange):
        """应用变更到文件。

        审批门禁:
          1. 必须通过 SDB 门控 (sdb_approved=True)
          2. 必须满足 auto_apply=True — 否则不写文件, 仅生成 patch 供人工审批
        """
        if not change.sdb_approved:
            change.status = ChangeStatus.REJECTED
            self._stats["total_rejected"] += 1
            return self.ApplyResult(ChangeStatus.REJECTED, "变更未通过SDB安全门控", change.file_path)
        if change.status not in (ChangeStatus.GATED, ChangeStatus.PROPOSED):
            return self.ApplyResult(ChangeStatus.REJECTED,
                                    f"当前状态不允许应用: {change.status.value}", change.file_path)
        if not self.auto_apply:
            # 默认行为: 不直接改文件, 生成 patch 等待人工审批 (对标 require_approval)
            change.rollback_available = False
            return self.ApplyResult(
                ChangeStatus.GATED,
                "auto_apply=False: 变更已生成 patch, 等待人工审批后手动应用",
                change.file_path,
            )
        if self._applied_count >= self.max_changes_per_session:
            change.status = ChangeStatus.REJECTED
            return self.ApplyResult(ChangeStatus.REJECTED, "达到每session最大变更数", change.file_path)
        try:
            self._apply_to_file(change)
            change.status = ChangeStatus.APPLIED
            change.rollback_available = True
            self._applied_count += 1
            self._stats["total_applied"] += 1
            return self.ApplyResult(ChangeStatus.APPLIED, "变更已应用", change.file_path)
        except Exception as e:
            change.status = ChangeStatus.FAILED
            return self.ApplyResult(ChangeStatus.FAILED, str(e), change.file_path)

    def _apply_to_file(self, change: CodeChange):
        """实际写文件: 先备份, 再原子写入。"""
        p = Path(change.file_path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = self.backup_dir / f"{p.stem}_{change.change_id}.bak"
        backup_path.write_text(change.original_content, encoding="utf-8")
        change.backup_path = str(backup_path)
        # 原子替换: 写临时文件再 rename, 避免写一半
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(change.proposed_content, encoding="utf-8")
        tmp.replace(p)

    def rollback_change(self, change_id: str) -> Dict[str, Any]:
        """回滚变更。"""
        change = self._change_map.get(change_id)
        if change is None:
            return {"success": False, "message": f"change not found: {change_id}"}
        if change.status not in (ChangeStatus.APPLIED, ChangeStatus.VERIFIED):
            return {"success": False,
                    "message": f"change {change_id} 尚未应用 (status={change.status.value}), 无需回滚"}
        if not change.backup_path or not Path(change.backup_path).exists():
            return {"success": False, "message": "无备份文件, 无法回滚"}
        try:
            backup = Path(change.backup_path).read_text(encoding="utf-8")
            Path(change.file_path).write_text(backup, encoding="utf-8")
        except OSError as e:
            return {"success": False, "message": str(e)}
        change.status = ChangeStatus.ROLLED_BACK
        change.rollback_available = False
        self._stats["total_rolled_back"] += 1
        return {"success": True, "change_id": change_id,
                "file_path": change.file_path, "status": change.status.value}

    # ── 自主改进管道 ─────────────────────────────────────────────

    def autonomous_improve(self, file_path: str, target: str = 'optimize') -> Dict[str, Any]:
        """全自主改进管道: 分析 → 提议 → 测试 → 门控 → 应用。"""
        p = Path(file_path)
        if not p.exists():
            return {"status": "file_not_found", "file_path": str(p)}
        if self._applied_count >= self.max_changes_per_session:
            return {"status": "max_changes_reached", "file_path": str(p)}
        analysis = self.analyze_file(str(p))
        issues = analysis.get("issues", [])
        if not issues:
            return {"status": "no_issues", "file_path": str(p)}
        content = p.read_text(encoding="utf-8")
        new_content = content
        for issue in issues:
            candidate = self._apply_suggestion(content, issue, target)
            if candidate != content:
                new_content = candidate
                break
        if new_content == content:
            return {"status": "no_optimization_needed", "file_path": str(p)}
        change = self.propose_change(
            str(p), new_content,
            ChangeType.OPTIMIZE if target == "optimize" else ChangeType.FIX,
            reason=f"autonomous {target} improvement",
            confidence=0.6,
        )
        change = self.test_change(change)
        if not change.tests_passed:
            return {"status": "test_failed", "change_id": change.change_id}
        change = self.gate_change(change)
        if not change.sdb_approved:
            return {"status": "rejected_by_sdb", "change_id": change.change_id}
        result = self.apply_change(change)
        status = result.status.value if isinstance(result.status, ChangeStatus) else result.status
        return {"status": status, "change_id": change.change_id,
                "message": result.message, "file_path": str(p)}

    def _apply_suggestion(self, content: str, issue: Dict[str, Any], target: str) -> str:
        """根据一条 issue 生成改进后的内容 (无法自动修复时返回原内容)。"""
        if target != "optimize":
            return content
        if issue.get("type") == "unused_function":
            return self._remove_unused_functions(content)
        return content  # todo_marker / long_line / long_function 需要人工重构, 不自动改

    def _top_level_unused(self, content: str) -> List[ast.FunctionDef]:
        """找出顶层未被引用的函数 (排除 main/run/setup/teardown 等入口名)。"""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        reserved = {"main", "run", "setup", "teardown", "test"}
        unused = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in reserved:
                continue
            total = sum(
                1 for n in ast.walk(tree)
                if isinstance(n, ast.Name) and n.id == node.name
            )
            # 只有定义处自身出现 → 从未被调用/引用
            if total <= 1:
                unused.append(node)
        return unused

    def _remove_unused_functions(self, content: str) -> str:
        """从源文件中删除未被引用的顶层函数 (dead-code elimination)。"""
        unused = self._top_level_unused(content)
        if not unused:
            return content
        lines = content.splitlines(keepends=True)
        skip = set()
        for node in unused:
            start = node.lineno - 1
            end = (getattr(node, "end_lineno", node.lineno) or node.lineno) - 1
            skip.update(range(start, end + 1))
        return "".join(l for i, l in enumerate(lines) if i not in skip)

    # ── 指标与问题检测 ───────────────────────────────────────────

    def _compute_metrics(self, content: str) -> Dict[str, Any]:
        """计算代码指标。"""
        lines = content.splitlines()
        total = len(lines)
        code = comments = blank = 0
        for line in lines:
            s = line.strip()
            if not s:
                blank += 1
            elif s.startswith("#"):
                comments += 1
            else:
                code += 1
        functions = classes = imports = 0
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions += 1
                elif isinstance(node, ast.ClassDef):
                    classes += 1
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports += 1
        return {
            "total_lines": total,
            "code_lines": code,
            "comment_lines": comments,
            "blank_lines": blank,
            "function_count": functions,
            "class_count": classes,
            "import_count": imports,
            "avg_line_length": round(sum(len(l) for l in lines) / total, 2) if total else 0.0,
            "max_line_length": max((len(l) for l in lines), default=0),
        }

    def _detect_issues(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """检测代码问题。"""
        issues: List[Dict[str, Any]] = []
        lines = content.splitlines()

        # TODO / FIXME / HACK 标记
        for i, line in enumerate(lines, 1):
            upper = line.upper()
            for marker in ("TODO", "FIXME", "HACK"):
                if marker in upper:
                    issues.append({
                        "type": "todo_marker", "line": i, "marker": marker,
                        "message": f"{marker} 标记位于第 {i} 行", "severity": "info",
                    })
                    break

        # 超长行 (>100 字符)
        for i, line in enumerate(lines, 1):
            if len(line) > 100:
                issues.append({
                    "type": "long_line", "line": i, "length": len(line),
                    "message": f"第 {i} 行过长 ({len(line)} > 100)", "severity": "warning",
                })

        # AST 级问题: 过长函数 / 未使用函数
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(node, "end_lineno", node.lineno) or node.lineno
                    nlines = end - node.lineno + 1
                    if nlines > 50:
                        issues.append({
                            "type": "long_function", "name": node.name, "lines": nlines,
                            "line": node.lineno,
                            "message": f"函数 '{node.name}' 有 {nlines} 行 (建议 < 50)",
                            "severity": "warning",
                        })
            for node in self._top_level_unused(content):
                issues.append({
                    "type": "unused_function", "name": node.name, "line": node.lineno,
                    "message": f"顶层函数 '{node.name}' 未被引用, 可删除",
                    "severity": "warning",
                })
        return issues

    def _generate_suggestions(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """基于代码分析生成改进建议。"""
        suggestions: List[Dict[str, Any]] = []
        for issue in self._detect_issues(content, file_path):
            itype = issue["type"]
            if itype == "todo_marker":
                suggestions.append({
                    "type": "todo",
                    "message": f"处理第 {issue['line']} 行的 {issue['marker']} 标记",
                    "priority": "low",
                })
            elif itype == "long_line":
                suggestions.append({
                    "type": "format",
                    "message": f"拆分第 {issue['line']} 行的超长行",
                    "priority": "medium",
                })
            elif itype == "long_function":
                suggestions.append({
                    "type": "refactor",
                    "message": f"将函数 '{issue['name']}' 拆分为更小的函数",
                    "priority": "medium",
                })
            elif itype == "unused_function":
                suggestions.append({
                    "type": "remove",
                    "message": f"删除未使用的函数 '{issue['name']}'",
                    "priority": "medium",
                })
        return suggestions

    # ── 历史与统计 ───────────────────────────────────────────────

    def get_history(self) -> List[CodeChange]:
        """获取修改历史。"""
        return list(self._history)

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计。"""
        return dict(self._stats)


_engine = None


def get_self_modify_engine(**kwargs) -> SelfModifyEngine:
    """获取 SelfModifyEngine 单例。"""
    global _engine
    if _engine is None:
        _engine = SelfModifyEngine(**kwargs)
    return _engine


__all__ = ["ChangeType", "ChangeStatus", "CodeChange", "SelfModifyEngine", "get_self_modify_engine"]

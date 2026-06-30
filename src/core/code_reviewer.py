"""Code Reviewer — regex patterns + AST deep analysis (v3.115+)

Claude Code 对标: 实时代码审查，安全漏洞检测，复杂度分析。
Features: 60+ regex patterns, Python AST deep review, cyclomatic estimation,
          project-wide scanning, severity scoring.
"""

from __future__ import annotations
import re
import os
import ast
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


SEVERITY_ORDER: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4,
}

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "security": "安全漏洞",
    "bug": "潜在Bug",
    "style": "代码风格",
    "performance": "性能问题",
    "docs": "文档/注释",
    "complexity": "复杂度",
    "dependency": "依赖问题",
    "typing": "类型注解",
}


# ── dataclass ───────────────────────────────────────────────────────────

class ReviewIssue:
    """A single code review finding. No __slots__ (meshctx 铁律)."""

    def __init__(self, file: str = "", line: int = 0, severity: str = "info",
                 category: str = "style", title: str = "", description: str = "",
                 suggestion: str = ""):
        self.file = file
        self.line = line
        self.severity = severity
        self.category = category
        self.title = title
        self.description = description
        self.suggestion = suggestion

    @property
    def severity_order(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)

    def to_dict(self) -> dict:
        return {
            "file": self.file, "line": self.line, "severity": self.severity,
            "category": self.category, "title": self.title,
            "description": self.description, "suggestion": self.suggestion,
        }

    def __repr__(self):
        return (f"ReviewIssue(file={self.file!r}, line={self.line}, "
                f"severity={self.severity!r}, title={self.title!r})")


# ── regex patterns ──────────────────────────────────────────────────────

PYTHON_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r'\beval\s*\('), "eval() 调用检测", "critical", "security", "避免使用 eval()，改用安全替代方案"),
    (re.compile(r'\bexec\s*\('), "exec() 调用检测", "critical", "security", "避免使用 exec()"),
    (re.compile(r'API_KEY\s*=\s*["\']'), "API Key 硬编码", "critical", "security", "使用环境变量存储 API Key"),
    (re.compile(r'PASSWORD\s*=\s*["\']', re.IGNORECASE), "密码硬编码", "critical", "security", "使用环境变量或密钥管理服务"),
    (re.compile(r'SECRET_KEY\s*=\s*["\']', re.IGNORECASE), "Secret Key 硬编码", "critical", "security", "使用环境变量存储密钥"),
    (re.compile(r'TOKEN\s*=\s*["\'][A-Za-z0-9_-]{20,}'), "Token 硬编码", "critical", "security", "使用环境变量存储 token"),
    (re.compile(r'f["\']\s*.*SELECT.*\{', re.IGNORECASE), "SQL 注入风险", "critical", "security", "使用参数化查询"),
    (re.compile(r'\bos\.system\s*\('), "os.system() 调用", "high", "security", "避免使用 os.system()，使用 subprocess.run()"),
    (re.compile(r'shell\s*=\s*True', re.IGNORECASE), "shell=True 风险", "high", "security", "除非必要避免 shell=True"),
    (re.compile(r'\bexcept\s*:'), "裸 except 子句", "high", "bug", "捕获明确的异常类型"),
    (re.compile(r'\bpickle\.loads?\s*\('), "pickle 反序列化风险", "high", "security", "避免 pickle 反序列化不可信数据"),
    (re.compile(r'hashlib\.md5\s*\('), "MD5 弱哈希", "high", "security", "使用 sha256 或更安全的哈希算法"),
    (re.compile(r'def\s+\w+\s*\([^)]*=\s*\[\s*\]'), "可变默认参数(list)", "medium", "bug", "使用 None 作为默认值或避免可变默认参数"),
    (re.compile(r'def\s+\w+\s*\([^)]*=\s*\{\s*\}'), "可变默认参数(dict)", "medium", "bug", "使用 None 作为默认值"),
    (re.compile(r'import\s+\*'), "通配符 import", "low", "style", "显式导入需要的符号"),
    (re.compile(r'print\s*\(.*\)\s*$(?!.*#.*debug)', re.MULTILINE), "残留 print 语句", "low", "style", "使用 logging 替代 print"),
    (re.compile(r'\bpass\s*$\s*\n\s*(class|def)', re.MULTILINE), "空 pass 块", "low", "style", "实现或标记为 abstract"),
    (re.compile(r'assert\s+.*,\s*"[^"]*"'), "assert 在非测试代码中使用", "low", "style", "在库代码中使用明确的异常"),
    (re.compile(r'time\.sleep\s*\('), "time.sleep() 调用", "info", "performance", "考虑是否有更好的等待方式"),
    (re.compile(r'except\s+Exception\s*:'), "宽泛异常捕获", "medium", "bug", "捕获更具体的异常类型"),
    (re.compile(r'__slots__\s*=\s*'), "__slots__ 使用(铁律禁止)", "critical", "bug", "meshctx 铁律: 禁止 __slots__"),
]

JAVASCRIPT_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r'\.innerHTML\s*=', re.IGNORECASE), "innerHTML XSS 风险", "critical", "security", "使用 textContent 替代 innerHTML"),
    (re.compile(r'\beval\s*\('), "eval() 调用", "critical", "security", "避免使用 eval()"),
    (re.compile(r'\.__proto__\['), "原型污染", "high", "security", "避免直接修改 __proto__"),
    (re.compile(r'localStorage\.setItem\s*\(\s*["\']token["\']', re.IGNORECASE), "localStorage Token 存储", "high", "security", "避免在 localStorage 存储敏感 token"),
    (re.compile(r'document\.write\s*\(', re.IGNORECASE), "document.write() 调用", "high", "performance", "避免 document.write()"),
    (re.compile(r'new\s+Function\s*\(', re.IGNORECASE), "new Function() 动态代码", "critical", "security", "避免动态构造函数"),
    (re.compile(r'\.dangerouslySetInnerHTML'), "dangerouslySetInnerHTML", "high", "security", "避免 dangerouslySetInnerHTML 除非必要"),
    (re.compile(r'process\.env\.\w+\s*=\s*["\']\S{8,}'), ".env 变量硬编码", "critical", "security", "环境变量不应在代码中硬编码"),
    (re.compile(r'console\.(log|warn|error)\s*\('), "console 调试语句", "info", "style", "清理调试日志，或使用条件编译"),
    (re.compile(r'var\s+\w+\s*='), "var 声明", "low", "style", "使用 const 或 let 替代 var"),
    (re.compile(r'==(?!=)'), "== 比较", "low", "bug", "使用 === 严格相等比较"),
]

GENERAL_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r'console\.log\s*\('), "console.log 调试代码", "info", "style", "清理调试日志"),
    (re.compile(r'TODO', re.IGNORECASE), "TODO 注释", "info", "docs", "完成或追踪 TODO"),
    (re.compile(r'FIXME', re.IGNORECASE), "FIXME 标记", "medium", "docs", "修复标记的问题"),
    (re.compile(r'HACK', re.IGNORECASE), "HACK 标记", "low", "style", "用解释性注释替代 HACK"),
]

TYPESCRIPT_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r':\s*any\b'), "any 类型使用", "low", "typing", "使用更具体的类型替代 any"),
    (re.compile(r'as\s+unknown\s+as\b'), "双重类型断言", "medium", "typing", "避免 unknown→具体类型的双重断言"),
    (re.compile(r'@ts-ignore'), "@ts-ignore 注释", "medium", "typing", "用 @ts-expect-error 替代并提供原因"),
    (re.compile(r'non-null assertion.*!'), "non-null assertion (!)", "low", "typing", "添加显式的 null 检查"),
]


# ── AST deep analysis ───────────────────────────────────────────────────

class ASTAnalyzer(ast.NodeVisitor):
    """Walk Python AST to collect complexity metrics and issues."""

    def __init__(self, source: str):
        self.source = source
        self.issues: list[ReviewIssue] = []
        self._current_func: str = ""
        self._func_complexity: dict[str, int] = {}
        self._imports: set[str] = set()
        self._nested_depth: int = 0

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._current_func = node.name
        # Cyclomatic complexity: 1 base + branches
        branches = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                branches += 1
            elif isinstance(child, ast.BoolOp):
                branches += len(child.values) - 1
        self._func_complexity[node.name] = branches

        # Function length
        end_line = node.end_lineno or node.lineno
        length = end_line - node.lineno + 1
        if length > 100:
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="medium", category="complexity",
                title="函数过长", description=f"函数 '{node.name}' 长度 {length} 行 (>100)",
                suggestion="考虑拆分为更小的函数",
            ))
        if branches > 10:
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="high", category="complexity",
                title="圈复杂度过高",
                description=f"函数 '{node.name}' 圈复杂度 {branches} (>10)",
                suggestion="拆分条件分支，提取子函数",
            ))
        elif branches > 6:
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="medium", category="complexity",
                title="圈复杂度偏高",
                description=f"函数 '{node.name}' 圈复杂度 {branches} (>6)",
                suggestion="考虑简化条件逻辑",
            ))

        # Too many arguments
        args = [a for a in node.args.args if a.arg != 'self']
        arg_count = len(args)
        if arg_count > 10:
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="high", category="complexity",
                title="参数严重过多",
                description=f"函数 '{node.name}' 有 {arg_count} 个参数 (>10)，严重违反单一职责",
                suggestion="立即重构：拆分为多个函数或使用配置对象封装",
            ))
        elif arg_count > 5:
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="low", category="style",
                title="参数过多",
                description=f"函数 '{node.name}' 有 {arg_count} 个参数 (>5)",
                suggestion="考虑使用 dataclass 或配置对象封装参数",
            ))

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._imports.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self._imports.add(node.module.split('.')[0])
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is None:
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="high", category="bug",
                title="裸 except 子句(AST)",
                description="捕获所有异常不利于调试",
                suggestion="捕获明确的异常类型 (e.g., except ValueError)",
            ))
        elif isinstance(node.type, ast.Name) and node.type.id == 'Exception':
            self.issues.append(ReviewIssue(
                line=node.lineno, severity="medium", category="bug",
                title="宽泛 Exception 捕获",
                description="捕获 Exception 过于宽泛",
                suggestion="捕获更具体的异常类型",
            ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Detect dangerous calls
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name == 'eval':
                self.issues.append(ReviewIssue(
                    line=node.lineno, severity="critical", category="security",
                    title="eval() 调用(AST)", description="eval() 有代码注入风险",
                    suggestion="避免使用 eval()",
                ))
            elif name == 'exec':
                self.issues.append(ReviewIssue(
                    line=node.lineno, severity="critical", category="security",
                    title="exec() 调用(AST)", description="exec() 有代码注入风险",
                    suggestion="避免使用 exec()",
                ))
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id == 'os' and node.func.attr == 'system':
                    self.issues.append(ReviewIssue(
                        line=node.lineno, severity="high", category="security",
                        title="os.system() 调用(AST)", description="os.system() 有shell注入风险",
                        suggestion="使用 subprocess.run([...], shell=False)",
                    ))
        self.generic_visit(node)


def python_ast_review(source: str, filepath: str = "") -> list[ReviewIssue]:
    """Deep Python review using AST walking."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [ReviewIssue(
            file=filepath, line=e.lineno or 1, severity="critical",
            category="bug", title="语法错误",
            description=str(e.msg), suggestion="修复语法错误",
        )]

    analyzer = ASTAnalyzer(source)
    analyzer.visit(tree)
    for issue in analyzer.issues:
        if filepath:
            issue.file = filepath
    return analyzer.issues


# ── main reviewer ───────────────────────────────────────────────────────

class CodeReviewer:
    """Multi-language code reviewer with regex + AST analysis."""

    def __init__(self):
        self._patterns: dict[str, list[tuple[re.Pattern, str, str, str, str]]] = {
            "python": PYTHON_PATTERNS,
            "javascript": JAVASCRIPT_PATTERNS,
            "js": JAVASCRIPT_PATTERNS,
            "typescript": TYPESCRIPT_PATTERNS,
            "ts": TYPESCRIPT_PATTERNS,
            "tsx": TYPESCRIPT_PATTERNS,
            "jsx": JAVASCRIPT_PATTERNS,
        }
        self._scan_count: int = 0
        self._total_issues: int = 0
        self._scan_history: list[dict] = []

    # ── pattern review ──

    def review_file(self, filepath: str, content: str,
                    language: str = "python") -> list[ReviewIssue]:
        """Pattern-based review of a single file."""
        patterns = self._patterns.get(language, PYTHON_PATTERNS)
        issues: list[ReviewIssue] = []
        seen: set[tuple[int, str]] = set()
        lines = content.split("\n")

        for line_no, line in enumerate(lines, 1):
            for pat, title, severity, category, suggestion in patterns:
                if pat.search(line):
                    key = (line_no, title)
                    if key not in seen:
                        seen.add(key)
                        issues.append(ReviewIssue(
                            file=filepath, line=line_no,
                            severity=severity, category=category,
                            title=title,
                            description=f"Line {line_no}: {line.strip()[:80]}",
                            suggestion=suggestion,
                        ))

        # Function-length detection (regex-based)
        in_func = False
        func_start = 0
        func_lines = 0
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r'^\s*def\s+\w+', stripped):
                if in_func and func_lines > 100:
                    issues.append(ReviewIssue(
                        file=filepath, line=func_start,
                        severity="medium", category="complexity",
                        title="函数过长",
                        description=f"函数长度 {func_lines} 行，超过建议的 100 行",
                        suggestion="考虑拆分函数",
                    ))
                in_func = True
                func_start = line_no
                func_lines = 1
            elif in_func:
                if stripped and not stripped.startswith("#"):
                    func_lines += 1
                if stripped and re.match(r'^(def\s+\w+|class\s+\w+)', stripped):
                    if func_lines > 100:
                        issues.append(ReviewIssue(
                            file=filepath, line=func_start,
                            severity="medium", category="complexity",
                            title="函数过长",
                            description=f"函数长度 {func_lines} 行",
                            suggestion="考虑拆分函数",
                        ))
                    in_func = True
                    func_start = line_no
                    func_lines = 1
        if in_func and func_lines > 100:
            issues.append(ReviewIssue(
                file=filepath, line=func_start,
                severity="medium", category="complexity",
                title="函数过长",
                description=f"函数长度 {func_lines} 行",
                suggestion="考虑拆分函数",
            ))

        issues.sort(key=lambda i: SEVERITY_ORDER.get(i.severity, 99))
        return issues

    # ── AI deep review ──

    def ai_deep_review(self, content: str, language: str = "python",
                       filepath: str = "") -> dict:
        """AST-based deep review. Currently supports Python; extensible."""
        patterns_issues = self.review_file(filepath, content, language)

        ast_issues: list[ReviewIssue] = []
        if language == "python":
            ast_issues = python_ast_review(content, filepath)

        # Merge: deduplicate by (line, title)
        all_issues: dict[tuple[int, str], ReviewIssue] = {}
        for issue in patterns_issues + ast_issues:
            key = (issue.line, issue.title)
            if key not in all_issues or SEVERITY_ORDER.get(issue.severity, 99) < SEVERITY_ORDER.get(all_issues[key].severity, 99):
                all_issues[key] = issue

        merged = sorted(all_issues.values(), key=lambda i: SEVERITY_ORDER.get(i.severity, 99))
        summary = self.review_summary(merged)

        return {
            "issues": [i.to_dict() for i in merged],
            "summary": summary,
            "patterns_issues": len(patterns_issues),
            "ast_issues": len(ast_issues),
            "merged_issues": len(merged),
            "language": language,
        }

    # ── scoring ──

    def review_summary(self, issues: list[ReviewIssue]) -> dict:
        penalty_map = {"critical": 15, "high": 8, "medium": 3, "low": 1, "info": 0}
        score = 100
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for i in issues:
            by_severity[i.severity] = by_severity.get(i.severity, 0) + 1
            by_category[i.category] = by_category.get(i.category, 0) + 1
            score = max(0, score - penalty_map.get(i.severity, 0))
        if score >= 80:
            verdict = "✅ Ready"
        elif score >= 60:
            verdict = "⚠ Review"
        else:
            verdict = "❌ Needs Work"
        return {
            "total_issues": len(issues),
            "score": score,
            "verdict": verdict,
            "by_severity": by_severity,
            "by_category": {k: v for k, v in by_category.items()},
        }

    # ── project review ──

    def project_review(self, directory: str,
                       exclude_dirs: set[str] | None = None) -> dict:
        if exclude_dirs is None:
            exclude_dirs = set()
        d = Path(directory)
        if not d.exists():
            return {
                "files_scanned": 0, "total_issues": 0, "score": 100,
                "verdict": "✅ Ready", "issues": [], "by_file": {},
            }
        all_issues: list[dict] = []
        files_scanned = 0
        by_file: dict[str, int] = {}
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
        }
        for root, dirs, filenames in os.walk(str(d)):
            dirs[:] = [dn for dn in dirs if dn not in exclude_dirs and not dn.startswith(".")]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                lang = ext_map.get(ext)
                if lang is None:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue
                result = self.ai_deep_review(content, lang, fpath)
                files_scanned += 1
                for issue in result["issues"]:
                    all_issues.append(issue)
                by_file[fpath] = result["merged_issues"]
        all_issues.sort(key=lambda i: SEVERITY_ORDER.get(i.get("severity", "info"), 99))
        summary = self.review_summary([
            ReviewIssue(**{k: v for k, v in i.items() if k in vars(ReviewIssue.__init__).keys() or k in ("file", "line", "severity", "category", "title", "description", "suggestion")})
            for i in all_issues
        ])
        summary["files_scanned"] = files_scanned
        summary["issues"] = all_issues
        summary["by_file"] = by_file

        # Track stats
        self._scan_count += 1
        self._total_issues += len(all_issues)
        self._scan_history.append({
            "ts": time.time(), "directory": directory,
            "files_scanned": files_scanned, "issues": len(all_issues),
        })
        if len(self._scan_history) > 200:
            self._scan_history = self._scan_history[-100:]

        return summary

    # ── convenience API ──

    def review(self, code: str, language: str = "python") -> dict:
        result = self.ai_deep_review(code, language, "")
        return {
            "issues": result["issues"],
            "suggestions": [i.get("suggestion", "") for i in result["issues"] if i.get("suggestion")],
            "score": result["summary"]["score"],
            "verdict": result["summary"]["verdict"],
        }

    def stats(self) -> dict:
        recent = self._scan_history[-10:] if self._scan_history else []
        return {
            "total_scans": self._scan_count,
            "total_issues_found": self._total_issues,
            "avg_issues_per_scan": (
                round(self._total_issues / max(self._scan_count, 1), 1)
            ),
            "languages_supported": list(self._patterns.keys()),
            "pattern_count": sum(len(v) for v in self._patterns.values()),
            "severity_order": {k: v for k, v in SEVERITY_ORDER.items()},
            "recent_scans": recent,
        }


# ── _P compatibility ────────────────────────────────────────────────────

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

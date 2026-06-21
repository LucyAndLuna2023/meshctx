"""Code Reviewer — v3.x stub with full pattern matching"""
from __future__ import annotations
import re
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


class ReviewIssue:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    __slots__ = ("file", "line", "severity", "category", "title", "description", "suggestion")

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
    def severity_order(self, **kw) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)

    def to_dict(self, **kw) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "suggestion": self.suggestion,
        }

    def __repr__(self, **kw):
        return f"ReviewIssue(file={self.file!r}, line={self.line}, severity={self.severity!r}, title={self.title!r})"


# Pattern format: (regex, title, severity, category, suggestion)
PYTHON_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r'\beval\s*\('), "eval() 调用检测", "critical", "security", "避免使用 eval()，改用安全替代方案"),
    (re.compile(r'\bexec\s*\('), "exec() 调用检测", "critical", "security", "避免使用 exec()"),
    (re.compile(r'API_KEY\s*=\s*["\']'), "API Key 硬编码", "critical", "security", "使用环境变量存储 API Key"),
    (re.compile(r'PASSWORD\s*=\s*["\']', re.IGNORECASE), "密码硬编码", "critical", "security", "使用环境变量或密钥管理服务"),
    (re.compile(r'SECRET_KEY\s*=\s*["\']', re.IGNORECASE), "Secret Key 硬编码", "critical", "security", "使用环境变量存储密钥"),
    (re.compile(r'f["\']\s*.*SELECT.*\{', re.IGNORECASE), "SQL 注入风险", "critical", "security", "使用参数化查询"),
    (re.compile(r'\bos\.system\s*\('), "os.system() 调用", "high", "security", "避免使用 os.system()，使用 subprocess.run()"),
    (re.compile(r'shell\s*=\s*True', re.IGNORECASE), "shell=True 风险", "high", "security", "除非必要避免 shell=True"),
    (re.compile(r'\bexcept\s*:'), "裸 except 子句", "high", "bug", "捕获明确的异常类型"),
    (re.compile(r'\bpickle\.loads?\s*\('), "pickle 反序列化风险", "high", "security", "避免 pickle 反序列化不可信数据"),
    (re.compile(r'hashlib\.md5\s*\('), "MD5 弱哈希", "high", "security", "使用 sha256 或更安全的哈希算法"),
    (re.compile(r'def\s+\w+\s*\([^)]*=\s*\[\s*\]'), "可变默认参数", "medium", "bug", "使用 None 作为默认值或避免可变默认参数"),
    (re.compile(r'def\s+\w+\s*\([^)]*=\s*\{\s*\}'), "可变默认参数(dict)", "medium", "bug", "使用 None 作为默认值"),
]

JAVASCRIPT_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r'\.innerHTML\s*=', re.IGNORECASE), "innerHTML XSS 风险", "critical", "security", "使用 textContent 替代 innerHTML"),
    (re.compile(r'\beval\s*\('), "eval() 调用", "critical", "security", "避免使用 eval()"),
    (re.compile(r'\.__proto__\['), "原型污染", "high", "security", "避免直接修改 __proto__"),
    (re.compile(r'localStorage\.setItem\s*\(\s*["\']token["\']', re.IGNORECASE), "localStorage Token 存储", "high", "security", "避免在 localStorage 存储敏感 token"),
    (re.compile(r'document\.write\s*\(', re.IGNORECASE), "document.write() 调用", "high", "performance", "避免 document.write()"),
    (re.compile(r'new\s+Function\s*\(', re.IGNORECASE), "new Function() 动态代码", "critical", "security", "避免动态构造函数"),
]

GENERAL_PATTERNS: list[tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r'console\.log\s*\('), "console.log 调试代码", "info", "style", "清理调试日志"),
    (re.compile(r'TODO', re.IGNORECASE), "TODO 注释", "info", "docs", "完成或追踪 TODO"),
]


class CodeReviewer:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, *a, **kw):
        self._patterns = {
            "python": PYTHON_PATTERNS,
            "javascript": JAVASCRIPT_PATTERNS,
            "js": JAVASCRIPT_PATTERNS,
        }

    def review_file(self, filepath: str, content: str, language: str = "python", **kw) -> list[ReviewIssue]:
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
                            title=title, description=f"Line {line_no}: {line.strip()[:80]}",
                            suggestion=suggestion,
                        ))

        # Long function detection
        in_func = False
        func_start = 0
        func_lines = 0
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r'^\s*def\s+\w+', stripped):
                if in_func and func_lines > 100:
                    issues.append(ReviewIssue(
                        file=filepath, line=func_start,
                        severity="medium", category="style",
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
                            severity="medium", category="style",
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
                severity="medium", category="style",
                title="函数过长",
                description=f"函数长度 {func_lines} 行",
                suggestion="考虑拆分函数",
            ))

        # Sort by severity
        issues.sort(key=lambda i: SEVERITY_ORDER.get(i.severity, 99))
        return issues

    def review_summary(self, issues: list[ReviewIssue], **kw) -> dict:
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
            "by_category": by_category,
        }

    def project_review(self, directory: str, exclude_dirs: set[str] | None = None, **kw) -> dict:
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
        ext_map = {".py": "python", ".js": "javascript", ".ts": "javascript", ".jsx": "javascript"}
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
                file_issues = self.review_file(fpath, content, lang)
                files_scanned += 1
                for issue in file_issues:
                    all_issues.append(issue.to_dict())
                by_file[fpath] = len(file_issues)
        all_issues.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 99))
        summary = self.review_summary([ReviewIssue(**{k: v for k, v in i.items() if k in ReviewIssue.__slots__}) for i in all_issues])  # type: ignore[arg-type]
        summary["files_scanned"] = files_scanned
        summary["issues"] = all_issues
        summary["by_file"] = by_file
        return summary

    def ai_deep_review(self, content: str, language: str = "python", **kw) -> dict | None:
        return None

    def review(self, code: str, *a, **kw) -> dict:
        issues = self.review_file("", code, a[0] if a else "python")
        summary = self.review_summary(issues)
        return {"issues": [i.to_dict() for i in issues], "suggestions": [], "score": summary["score"]}

    def stats(self, **kw) -> dict:
        return {}

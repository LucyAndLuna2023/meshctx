"""
MeshCtx Code Review Plugin — AI-Powered PR Reviewer
====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Automated code review using AI models.
Detects bugs, security issues, style violations, and suggests improvements.

License: AGPLv3 for non-commercial use only.
"""
import re
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReviewIssue:
    """A single issue found during code review."""
    file: str
    line: int = 0
    severity: str = "info"  # critical, high, medium, low, info
    category: str = "style"  # bug, security, style, performance, docs
    title: str = ""
    description: str = ""
    suggestion: str = ""

    def to_dict(self) -> Dict:
        return {
            "file": self.file, "line": self.line,
            "severity": self.severity, "category": self.category,
            "title": self.title, "description": self.description,
            "suggestion": self.suggestion,
        }


class CodeReviewer:
    """AI-powered code review engine."""

    # Static analysis patterns
    PATTERNS = {
        "python": [
            (re.compile(r"except\s*:"), "high", "bug",
             "Bare except clause", "Catching all exceptions hides bugs. Specify exception type."),
            (re.compile(r"import\s+\*"), "medium", "style",
             "Wildcard import", "Avoid 'from x import *'. Import only what you need."),
            (re.compile(r"eval\("), "critical", "security",
             "eval() usage detected", "eval() is dangerous. Use ast.literal_eval() or avoid entirely."),
            (re.compile(r"exec\("), "critical", "security",
             "exec() usage detected", "exec() can execute arbitrary code. Avoid unless absolutely necessary."),
            (re.compile(r"password\s*=\s*['\"][^'\"]+['\"]"), "critical", "security",
             "Hardcoded password", "Never hardcode credentials. Use environment variables."),
            (re.compile(r"api_key\s*=\s*['\"][^'\"]+['\"]"), "critical", "security",
             "Hardcoded API key", "Use environment variables or config files for API keys."),
            (re.compile(r"os\.system\("), "high", "security",
             "os.system() usage", "os.system() is vulnerable to injection. Use subprocess.run() with list args."),
            (re.compile(r"subprocess\.(call|Popen)\([^)]*shell\s*=\s*True"), "high", "security",
             "Shell=True in subprocess", "Shell=True is vulnerable to injection. Use list arguments instead."),
            (re.compile(r"TODO|FIXME|HACK|XXX"), "info", "docs",
             "TODO/FIXME comment", "Address TODO/FIXME comments before merging."),
            (re.compile(r"print\(.*\)"), "low", "style",
             "print() statement", "Use logging instead of print() for production code."),
            (re.compile(r"\.sleep\(\d+\)"), "medium", "performance",
             "time.sleep() in code", "Sleep calls may indicate race conditions. Use proper synchronization."),
        ],
        "javascript": [
            (re.compile(r"eval\("), "critical", "security", "eval() detected", "eval() is dangerous."),
            (re.compile(r"innerHTML\s*="), "medium", "security", "innerHTML assignment", "Use textContent or safe DOM methods to prevent XSS."),
            (re.compile(r"console\.log\("), "low", "style", "console.log()", "Remove debug logging before production."),
            (re.compile(r"TODO|FIXME|HACK"), "info", "docs", "TODO comment", "Address before merging."),
        ],
    }

    def review_file(self, filepath: str, content: str,
                     language: str = "python") -> List[ReviewIssue]:
        """Run static analysis on a single file."""
        issues = []
        patterns = self.PATTERNS.get(language, self.PATTERNS["python"])
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            for pattern, severity, category, title, desc in patterns:
                if pattern.search(line):
                    issues.append(ReviewIssue(
                        file=filepath, line=line_num,
                        severity=severity, category=category,
                        title=title, description=desc,
                        suggestion=f"Line {line_num}: {line.strip()[:80]}"
                    ))

        # Check for large functions (Python only)
        if language == "python":
            issues.extend(self._check_function_length(filepath, content))
            issues.extend(self._check_file_length(filepath, len(lines)))

        return issues

    def _check_function_length(self, filepath: str, content: str) -> List[ReviewIssue]:
        issues = []
        lines = content.split("\n")
        in_func = False
        func_start = 0
        func_indent = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r"^(async\s+)?def\s+\w+", stripped):
                in_func = True
                func_start = i
                func_indent = len(line) - len(line.lstrip())
            elif in_func and stripped and len(line) - len(line.lstrip()) <= func_indent and not stripped.startswith("@"):
                func_len = i - func_start
                if func_len > 100:
                    issues.append(ReviewIssue(
                        file=filepath, line=func_start,
                        severity="medium", category="style",
                        title=f"Function too long ({func_len} lines)",
                        description="Long functions are hard to understand. Consider refactoring into smaller units.",
                        suggestion=f"Split function starting at line {func_start}"
                    ))
                in_func = False

        return issues

    def _check_file_length(self, filepath: str, line_count: int) -> List[ReviewIssue]:
        if line_count > 1000:
            return [ReviewIssue(
                file=filepath, severity="low", category="style",
                title=f"File too large ({line_count} lines)",
                description="Consider splitting large files into modules."
            )]
        return []

    def review_summary(self, issues: List[ReviewIssue]) -> Dict:
        """Generate a review summary."""
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        by_category = {"bug": 0, "security": 0, "style": 0, "performance": 0, "docs": 0}
        for i in issues:
            by_severity[i.severity] = by_severity.get(i.severity, 0) + 1
            by_category[i.category] = by_category.get(i.category, 0) + 1

        score = max(0, 100 - by_severity["critical"] * 15 - by_severity["high"] * 8
                     - by_severity["medium"] * 3 - by_severity["low"] * 1)

        return {
            "total_issues": len(issues),
            "score": min(100, score),
            "by_severity": by_severity,
            "by_category": by_category,
            "verdict": "✅ Ready" if score >= 80 else "⚠ Review" if score >= 60 else "❌ Needs Work",
        }

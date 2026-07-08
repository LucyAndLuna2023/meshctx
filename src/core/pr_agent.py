#!/usr/bin/env python3
"""pr_agent.py — Automated PR creation with diff summarization and reviewer recommendations.

Zero-dependency, pure-Python stdlib. Competes with Devin/Copilot PR automation.

Components:
    PRAgent              — Orchestrator: diff → summary → template → PR.
    DiffSummarizer       — Parses git diff into structured, human-readable summaries.
    PRTemplate           — Multi-template system (feature/bugfix/docs/hotfix).
    ReviewerRecommender  — git-blame analysis to suggest best reviewers.
    PRValidator          — Pre-flight checks: merge conflicts, TODOs, tests, file sizes.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import typing as t

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TEMPLATES: dict[str, str] = {
    "feature": (
        "## Summary\n\n{summary}\n\n"
        "## Motivation\n\n{changelog}\n\n"
        "## Changed Files\n\n{file_list}\n\n"
        "## Breaking Changes\n\n{breaking_changes}\n\n"
        "## Checklist\n\n"
        "- [ ] Tests added / updated\n"
        "- [ ] Documentation updated\n"
        "- [ ] Changelog entry added\n"
    ),
    "bugfix": (
        "## Bug Description\n\n{summary}\n\n"
        "## Root Cause\n\n{changelog}\n\n"
        "## Fix\n\n{file_list}\n\n"
        "## Breaking Changes\n\n{breaking_changes}\n\n"
        "## Checklist\n\n"
        "- [ ] Regression test added\n"
        "- [ ] Related issues linked\n"
    ),
    "docs": (
        "## Documentation Changes\n\n{summary}\n\n"
        "## Affected Pages\n\n{file_list}\n\n"
        "## Checklist\n\n"
        "- [ ] Spelling / grammar checked\n"
        "- [ ] Links verified\n"
    ),
    "hotfix": (
        "## ⚠️  HOTFIX — Urgent\n\n"
        "## Problem\n\n{summary}\n\n"
        "## Immediate Fix\n\n{changelog}\n\n"
        "## Changed Files\n\n{file_list}\n\n"
        "## Rollback Plan\n\n{breaking_changes}\n\n"
        "## Checklist\n\n"
        "- [ ] Deployed to staging first\n"
        "- [ ] On-call notified\n"
        "- [ ] Post-mortem ticket created\n"
    ),
}

_BREAKING_KEYWORDS: tuple[str, ...] = (
    "BREAKING CHANGE", "BREAKING-CHANGE", "breaking change", "breaking-change",
    "backward incompatible", "api change", "removed", "deprecated",
    "signature change", "interface change",
)

_TODO_PATTERN: re.Pattern[str] = re.compile(r"(?i)\b(TODO|FIXME|HACK|XXX|TBD)\b")
_FUNCTION_HUNK_RE: re.Pattern[str] = re.compile(
    r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@\s*(.*)$"
)
_DIFF_STAT_RE: re.Pattern[str] = re.compile(
    r"^\s*(\d+)\s+files?\s+changed(?:,\s*(\d+)\s+insertions?\(\+\))?"
    r"(?:,\s*(\d+)\s+deletions?\(-\))?"
)
_FILE_HEADER_RE: re.Pattern[str] = re.compile(r"^diff --git a/(.+) b/(.+)$")
_RENAME_RE: re.Pattern[str] = re.compile(r"^rename (?:from|to) (.+)$")
_NEW_FILE_RE: re.Pattern[str] = re.compile(r"^new file mode")
_DELETED_FILE_RE: re.Pattern[str] = re.compile(r"^deleted file mode")

_BLAME_SAMPLE_LIMIT: int = 200

_PURPOSE_MAP: dict[str, str] = {
    "src/": "core source", "lib/": "core source",
    "tests/": "tests", "test/": "tests",
    "docs/": "documentation", "doc/": "documentation",
    "scripts/": "tooling", "tools/": "tooling",
    "ci/": "CI / CD", ".github/": "CI / CD",
    "migrations/": "database migrations", "config/": "configuration",
    "assets/": "assets", "public/": "assets",
}


# ===========================================================================
# Enums
# ===========================================================================

class PRType(enum.Enum):
    """Category of the proposed pull request."""
    FEATURE = "feature"
    BUGFIX = "bugfix"
    DOCS = "docs"
    HOTFIX = "hotfix"
    UNKNOWN = "unknown"

    @classmethod
    def from_branch_name(cls, branch: str) -> PRType:
        lowered = branch.lower()
        if any(t in lowered for t in ("feat/", "feature/", "enhancement/", "feat-", "feature-")):
            return cls.FEATURE
        if any(t in lowered for t in ("fix/", "bugfix/", "bug/", "hotfix/", "patch/", "fix-", "bug-")):
            return cls.HOTFIX if "hotfix" in lowered else cls.BUGFIX
        if any(t in lowered for t in ("docs/", "documentation/", "doc/")):
            return cls.DOCS
        return cls.UNKNOWN


class ChangeType(enum.Enum):
    ADDED = "added"; MODIFIED = "modified"; DELETED = "deleted"
    RENAMED = "renamed"; COPIED = "copied"


class BreakingChangeSeverity(enum.Enum):
    CRITICAL = "critical"; MAJOR = "major"; MINOR = "minor"; INFORMATIONAL = "informational"


class ValidationStatus(enum.Enum):
    PASSED = "passed"; FAILED = "failed"; WARNING = "warning"; SKIPPED = "skipped"


# ===========================================================================
# Data Classes
# ===========================================================================

@dataclasses.dataclass
class FileChange:
    """A single file altered in the diff."""
    path: str
    change_type: ChangeType
    lines_added: int = 0
    lines_removed: int = 0
    function_scopes: list[str] = dataclasses.field(default_factory=list)
    is_breaking: bool = False
    breaking_details: str = ""

    @property
    def net_change(self) -> int: return self.lines_added - self.lines_removed

    @property
    def churn(self) -> int: return self.lines_added + self.lines_removed


@dataclasses.dataclass
class DiffSummary:
    """Structured summary of a full git diff."""
    files_changed: list[FileChange] = dataclasses.field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0
    breaking_changes: list[str] = dataclasses.field(default_factory=list)
    changelog_entry: str = ""
    grouped_by_purpose: dict[str, list[str]] = dataclasses.field(default_factory=dict)

    @property
    def total_files(self) -> int: return len(self.files_changed)


@dataclasses.dataclass
class ReviewRecommendation:
    """A suggested reviewer with confidence score."""
    author: str
    email: str
    score: float  # 0.0 .. 1.0
    files_touched: int = 0
    last_commit_date: str = ""


@dataclasses.dataclass
class ValidationResult:
    """Outcome of a single validation check."""
    check_name: str
    status: ValidationStatus
    message: str = ""
    suggestion: str = ""


@dataclasses.dataclass
class PREntry:
    """Fully assembled PR ready for submission."""
    title: str
    body: str
    pr_type: PRType
    base_branch: str
    head_branch: str
    summary: DiffSummary
    reviewers: list[ReviewRecommendation] = dataclasses.field(default_factory=list)
    validations: list[ValidationResult] = dataclasses.field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = [
            f"# {self.title}", "", self.body, "",
            "---",
            f"### 🤖 Auto-generated | Type: {self.pr_type.value}",
            f"`{self.base_branch}` ← `{self.head_branch}`",
        ]
        if self.reviewers:
            sections.append("### Recommended Reviewers")
            for rr in self.reviewers:
                sections.append(
                    f"- **{rr.author}** <{rr.email}>  "
                    f"({rr.score:.0%}, {rr.files_touched} files)"
                )
        return "\n".join(sections)


# ===========================================================================
# DiffSummarizer
# ===========================================================================

class DiffSummarizer:
    """Parses `git diff` output into structured, human-readable summaries.

    Detects file-level changes, function scopes from hunk headers, breaking-change
    keywords in diffs and commit messages, and groups files by purpose (src/, tests/, etc.).
    """

    def summarize(
        self, diff_text: str,
        commit_messages: t.Sequence[str] | None = None,
    ) -> DiffSummary:
        """Parse git diff text into a structured DiffSummary."""
        files: list[FileChange] = []
        current_file: FileChange | None = None
        total_added, total_removed = 0, 0
        breaking: list[str] = []

        for line in diff_text.splitlines():
            fm = _FILE_HEADER_RE.match(line)
            if fm:
                if current_file: files.append(current_file)
                current_file = FileChange(path=fm.group(2), change_type=ChangeType.MODIFIED)
                continue

            if current_file is None:
                sm = _DIFF_STAT_RE.match(line)
                if sm:
                    total_added = int(sm.group(2) or 0)
                    total_removed = int(sm.group(3) or 0)
                continue

            if _NEW_FILE_RE.match(line):
                current_file.change_type = ChangeType.ADDED; continue
            if _DELETED_FILE_RE.match(line):
                current_file.change_type = ChangeType.DELETED; continue
            if _RENAME_RE.match(line):
                current_file.change_type = ChangeType.RENAMED; continue

            if line.startswith("+") and not line.startswith("+++"):
                current_file.lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_file.lines_removed += 1

            hm = _FUNCTION_HUNK_RE.match(line)
            if hm and hm.group(1).strip():
                scope = hm.group(1).strip()
                if scope not in current_file.function_scopes:
                    current_file.function_scopes.append(scope)

            for kw in _BREAKING_KEYWORDS:
                if kw in line and kw not in ("added", "removed"):
                    current_file.is_breaking = True
                    detail = f"{kw} in {current_file.path}"
                    if detail not in breaking: breaking.append(detail)
                    current_file.breaking_details = detail
                    break

        if current_file: files.append(current_file)

        if total_added == 0 and total_removed == 0:
            total_added = sum(f.lines_added for f in files)
            total_removed = sum(f.lines_removed for f in files)

        if commit_messages:
            for msg in commit_messages:
                for kw in _BREAKING_KEYWORDS:
                    if kw.lower() in msg.lower():
                        entry = f"Commit message: {msg.strip()}"
                        if entry not in breaking: breaking.append(entry)

        grouped: dict[str, list[str]] = collections.defaultdict(list)
        for fc in files:
            purpose = "other"
            for prefix, label in _PURPOSE_MAP.items():
                if fc.path.startswith(prefix): purpose = label; break
            grouped[purpose].append(fc.path)

        changelog = self._synthesize_changelog(files, breaking)

        return DiffSummary(
            files_changed=files, total_added=total_added, total_removed=total_removed,
            breaking_changes=breaking, changelog_entry=changelog,
            grouped_by_purpose=dict(grouped),
        )

    @staticmethod
    def _synthesize_changelog(files: list[FileChange], breaking: list[str]) -> str:
        added = [f.path for f in files if f.change_type == ChangeType.ADDED]
        removed = [f.path for f in files if f.change_type == ChangeType.DELETED]
        modified = [f.path for f in files if f.change_type == ChangeType.MODIFIED]
        parts: list[str] = []
        if added: parts.append("### Added\n" + "\n".join(f"- {p}" for p in added))
        if removed: parts.append("### Removed\n" + "\n".join(f"- {p}" for p in removed))
        if modified: parts.append("### Changed\n" + "\n".join(f"- {p}" for p in modified))
        if breaking: parts.append("### ⚠️  Breaking Changes\n" + "\n".join(f"- {b}" for b in breaking))
        return "\n\n".join(parts) if parts else "No significant changes detected."


# ===========================================================================
# PRTemplate
# ===========================================================================

class PRTemplate:
    """Generates PR title and body from a DiffSummary using selectable templates.

    Template keys: {summary}, {changelog}, {file_list}, {breaking_changes}.
    """

    def __init__(self, custom_templates: dict[str, str] | None = None) -> None:
        self._templates = dict(_DEFAULT_TEMPLATES)
        if custom_templates: self._templates.update(custom_templates)

    def generate_title(
        self, summary: DiffSummary, pr_type: PRType | None = None, prefix: str = "",
    ) -> str:
        """Generate conventional-commit style title, e.g. 'feat(scope): description'."""
        detected = pr_type or self._detect_type(summary)
        type_map = {PRType.FEATURE: "feat", PRType.BUGFIX: "fix",
                    PRType.DOCS: "docs", PRType.HOTFIX: "hotfix", PRType.UNKNOWN: "chore"}
        scope = f"({prefix})" if prefix else ""
        return f"{type_map.get(detected, 'chore')}{scope}: {self._extract_headline(summary)}"

    def generate_body(self, summary: DiffSummary, pr_type: PRType | None = None) -> str:
        """Render PR body from the detected or specified template."""
        detected = pr_type or self._detect_type(summary)
        template = self._templates.get(detected.value, self._templates["feature"])
        return template.format(
            summary=self._generate_human_summary(summary),
            changelog=summary.changelog_entry,
            file_list=self._format_file_list(summary.files_changed),
            breaking_changes=self._format_breaking(summary.breaking_changes),
        )

    def list_templates(self) -> list[str]:
        return sorted(self._templates.keys())

    @staticmethod
    def _detect_type(summary: DiffSummary) -> PRType:
        if summary.files_changed and all(
            f.path.startswith(("docs/", "doc/", "README", "CHANGELOG"))
            for f in summary.files_changed
        ):
            return PRType.DOCS
        if summary.breaking_changes:
            for bc in summary.breaking_changes:
                if "hotfix" in bc.lower() or "urgent" in bc.lower():
                    return PRType.HOTFIX
        return PRType.FEATURE if summary.total_added > summary.total_removed * 2 else PRType.BUGFIX

    @staticmethod
    def _extract_headline(summary: DiffSummary) -> str:
        if not summary.files_changed: return "no changes detected"
        scopes: list[str] = []
        for fc in summary.files_changed: scopes.extend(fc.function_scopes)
        if scopes:
            unique = list(dict.fromkeys(scopes))
            return ", ".join(unique[:3])
        paths = [fc.path for fc in summary.files_changed[:3]]
        suffix = " and others" if summary.total_files > 3 else ""
        return f"changes to {', '.join(paths)}{suffix}"

    @staticmethod
    def _format_file_list(files: list[FileChange]) -> str:
        if not files: return "_No files changed._"
        icons = {ChangeType.ADDED: "➕", ChangeType.DELETED: "➖",
                 ChangeType.MODIFIED: "✏️", ChangeType.RENAMED: "🔄", ChangeType.COPIED: "📋"}
        lines: list[str] = []
        for fc in files:
            icon = icons.get(fc.change_type, "•")
            stat = f" (+{fc.lines_added}/-{fc.lines_removed})" if fc.churn > 0 else ""
            tag = " ⚠️ BREAKING" if fc.is_breaking else ""
            lines.append(f"- {icon} `{fc.path}`{stat}{tag}")
        return "\n".join(lines)

    @staticmethod
    def _format_breaking(breaking: list[str]) -> str:
        if not breaking: return "_No breaking changes detected._"
        return "\n".join(f"- ⚠️ {b}" for b in breaking)

    @staticmethod
    def _generate_human_summary(summary: DiffSummary) -> str:
        if not summary.files_changed: return "This PR contains no file changes."
        churn = summary.total_added + summary.total_removed
        parts: list[str] = [
            f"This PR modifies **{summary.total_files}** file(s) "
            f"(+{summary.total_added}/-{summary.total_removed} lines, {churn} churn)."
        ]
        if summary.grouped_by_purpose:
            plines = [f"  - **{p}**: {', '.join(paths)}"
                      for p, paths in summary.grouped_by_purpose.items()]
            parts.append("Changes grouped by area:\n" + "\n".join(plines))
        if summary.breaking_changes:
            parts.append(f"⚠️ **{len(summary.breaking_changes)} breaking change(s)** — review carefully.")
        return "\n\n".join(parts)


# ===========================================================================
# ReviewerRecommender
# ===========================================================================

class ReviewerRecommender:
    """Recommends reviewers via `git blame` ownership analysis of changed files.

    Samples up to _BLAME_SAMPLE_LIMIT lines per file, aggregates authorship scores,
    and ranks authors by total ownership across changed files.
    """

    def __init__(
        self, repo_path: str = ".", max_recommendations: int = 5,
        min_score: float = 0.1, exclude_authors: t.Sequence[str] | None = None,
    ) -> None:
        self._repo_path = os.path.abspath(repo_path)
        self._max = max_recommendations
        self._min_score = min_score
        self._exclude: set[str] = set(exclude_authors or [])

    def recommend(
        self, changed_files: t.Sequence[str], base_ref: str | None = None,
    ) -> list[ReviewRecommendation]:
        """Rank reviewers by blame ownership across changed_files."""
        if not changed_files: return []
        scores: dict[str, dict] = {}
        for fp in changed_files:
            for author, email in self._blame_file(fp, base_ref):
                if not author or not email or email in self._exclude: continue
                if email not in scores:
                    scores[email] = {"author": author, "email": email,
                                     "lines": 0, "files": set(), "last_date": ""}
                scores[email]["lines"] += 1
                scores[email]["files"].add(fp)

        total_lines = sum(v["lines"] for v in scores.values())
        if total_lines == 0: return []

        results: list[ReviewRecommendation] = []
        for data in scores.values():
            sc = data["lines"] / total_lines
            if sc >= self._min_score:
                results.append(ReviewRecommendation(
                    author=data["author"], email=data["email"], score=round(sc, 4),
                    files_touched=len(data["files"]), last_commit_date=data["last_date"],
                ))
        results.sort(key=lambda r: (-r.score, -r.files_touched, r.author))
        return results[:self._max]

    def get_file_owners(self, filepath: str, top_n: int = 3) -> list[tuple[str, str, float]]:
        """Top-N authors for a single file, with ownership fractions."""
        blame = self._blame_file(filepath)
        if not blame: return []
        counter: dict[str, tuple[str, str, int]] = {}
        for author, email in blame:
            if email not in counter: counter[email] = (author, email, 0)
            a, e, c = counter[email]; counter[email] = (a, e, c + 1)
        total = sum(c[2] for c in counter.values())
        ranked = sorted(counter.values(), key=lambda x: -x[2])
        return [(author, email, round(count / total, 3))
                for author, email, count in ranked[:top_n] if total > 0]

    def _blame_file(self, filepath: str, base_ref: str | None = None) -> list[tuple[str, str]]:
        full_path = os.path.join(self._repo_path, filepath)
        if not os.path.isfile(full_path): return []
        ref = base_ref or "HEAD"
        try:
            proc = subprocess.run(
                ["git", "-C", self._repo_path, "blame", "--line-porcelain", ref, "--", filepath],
                capture_output=True, text=True, timeout=15, env={**os.environ, "LANG": "C"},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        if proc.returncode != 0: return []

        results: list[tuple[str, str]] = []
        author, line_count = "", 0
        for line in proc.stdout.splitlines():
            if line_count >= _BLAME_SAMPLE_LIMIT: break
            if line.startswith("author "): author = line[7:].strip()
            elif line.startswith("author-mail ") and author:
                results.append((author, line[12:].strip().strip("<>")))
                line_count += 1; author = ""
        return results


# ===========================================================================
# PRValidator
# ===========================================================================

class PRValidator:
    """Pre-flight checks: merge conflicts, TODO leftovers, title format,
    file-size limits, and optional test execution."""

    def __init__(
        self, repo_path: str = ".", test_command: str | None = None,
        max_file_lines: int = 2000, skip_tests: bool = False,
    ) -> None:
        self._repo_path = os.path.abspath(repo_path)
        self._test_command = test_command
        self._max_file_lines = max_file_lines
        self._skip_tests = skip_tests

    def validate(self, diff_text: str, title: str = "", base_branch: str = "main") -> list[ValidationResult]:
        """Run all enabled validators."""
        results = [
            self._check_conflicts(base_branch),
            self._check_todos(diff_text),
            self._check_title(title),
            self._check_file_sizes(diff_text),
        ]
        if self._test_command and not self._skip_tests:
            results.append(self._check_tests())
        else:
            results.append(ValidationResult("tests-pass", ValidationStatus.SKIPPED,
                                            "No test command configured or tests skipped."))
        return results

    def is_ready(self, results: list[ValidationResult]) -> bool:
        return all(r.status != ValidationStatus.FAILED for r in results)

    def format_report(self, results: list[ValidationResult]) -> str:
        if not results: return "_No validations run._"
        icons = {ValidationStatus.PASSED: "✅", ValidationStatus.FAILED: "❌",
                 ValidationStatus.WARNING: "⚠️", ValidationStatus.SKIPPED: "⏭️"}
        lines = ["### Pre-flight Checks", ""]
        for r in results:
            lines.append(f"- {icons.get(r.status, '•')} **{r.check_name}**: {r.message}")
            if r.suggestion: lines.append(f"  > {r.suggestion}")
        return "\n".join(lines) + "\n"

    # --- individual checks ---

    def _check_conflicts(self, base_branch: str) -> ValidationResult:
        try:
            proc = subprocess.run(
                ["git", "-C", self._repo_path, "merge-base", "--is-ancestor",
                 base_branch, "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return ValidationResult("no-merge-conflicts", ValidationStatus.SKIPPED,
                                    f"git merge-base failed: {exc}")
        if proc.returncode == 0:
            return ValidationResult("no-merge-conflicts", ValidationStatus.PASSED,
                                    f"HEAD is descendant of {base_branch}.")
        return self._dry_merge_check(base_branch)

    def _dry_merge_check(self, base_branch: str) -> ValidationResult:
        try:
            proc = subprocess.run(
                ["git", "-C", self._repo_path, "merge-tree", "--write-tree",
                 base_branch, "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return ValidationResult(
                "no-merge-conflicts", ValidationStatus.WARNING,
                f"merge-tree unavailable: {exc}",
                "Verify manually: `git merge --no-commit --no-ff`.",
            )
        if proc.returncode != 0 or any(m in proc.stdout for m in ("<<<<<<<", ">>>>>>>", "=======")):
            return ValidationResult(
                "no-merge-conflicts", ValidationStatus.FAILED,
                f"Conflicts detected with {base_branch}.",
                f"Run: `git merge {base_branch}` and resolve conflicts.",
            )
        return ValidationResult("no-merge-conflicts", ValidationStatus.PASSED,
                                f"No conflicts merging into {base_branch}.")

    def _check_todos(self, diff_text: str) -> ValidationResult:
        added = [line[1:] for line in diff_text.splitlines()
                 if line.startswith("+") and not line.startswith("+++")]
        matches: list[str] = []
        for line in added: matches.extend(_TODO_PATTERN.findall(line))
        if matches:
            unique = sorted(set(matches))
            return ValidationResult(
                "no-todo-leftovers", ValidationStatus.WARNING,
                f"Found {len(unique)} marker type(s): {', '.join(unique)}.",
                "Resolve TODOs or promote to tracked issues.",
            )
        return ValidationResult("no-todo-leftovers", ValidationStatus.PASSED,
                                "No TODO/FIXME/HACK/XXX in added lines.")

    @staticmethod
    def _check_title(title: str) -> ValidationResult:
        if not title:
            return ValidationResult(
                "conventional-title", ValidationStatus.WARNING,
                "No title provided.",
                "Use: type(scope): description (e.g. feat(auth): add OAuth2).",
            )
        if re.match(
            r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert|hotfix)"
            r"(\([^)]+\))?:\s+.+$", title,
        ):
            return ValidationResult("conventional-title", ValidationStatus.PASSED,
                                    f"Title follows convention: `{title}`")
        return ValidationResult(
            "conventional-title", ValidationStatus.WARNING,
            f"Non-conventional title: `{title}`.",
            "Use: type(scope): description.",
        )

    def _check_file_sizes(self, diff_text: str) -> ValidationResult:
        oversized: list[str] = []
        cur, newf, count = "", False, 0
        for line in diff_text.splitlines():
            if line.startswith("diff --git"):
                if newf and count > self._max_file_lines:
                    oversized.append(f"{cur} ({count} lines)")
                cur, newf, count = "", False, 0
                m = re.match(r"^diff --git a/(.+) b/", line)
                if m: cur = m.group(1)
            elif line.startswith("new file mode"):
                newf = True
            elif newf and line.startswith("+") and not line.startswith("+++"):
                count += 1
        if newf and count > self._max_file_lines:
            oversized.append(f"{cur} ({count} lines)")
        if oversized:
            return ValidationResult(
                "file-size-limits", ValidationStatus.WARNING,
                f"{len(oversized)} new file(s) > {self._max_file_lines} lines: "
                f"{', '.join(oversized[:5])}",
                "Consider splitting large files.",
            )
        return ValidationResult("file-size-limits", ValidationStatus.PASSED,
                                f"All new files ≤ {self._max_file_lines} lines.")

    def _check_tests(self) -> ValidationResult:
        if not self._test_command:
            return ValidationResult("tests-pass", ValidationStatus.SKIPPED, "No test command.")
        try:
            proc = subprocess.run(
                shlex.split(self._test_command), capture_output=True, text=True,
                timeout=300, cwd=self._repo_path,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult("tests-pass", ValidationStatus.WARNING,
                                    "Tests timed out (300s).", "Run manually.")
        except (FileNotFoundError, OSError) as exc:
            return ValidationResult("tests-pass", ValidationStatus.SKIPPED,
                                    f"Cannot run tests: {exc}")
        if proc.returncode == 0:
            return ValidationResult("tests-pass", ValidationStatus.PASSED, "All tests passed.")
        tail = "\n".join(proc.stdout.strip().splitlines()[-5:])
        return ValidationResult("tests-pass", ValidationStatus.FAILED,
                                f"Tests failed (exit {proc.returncode}).",
                                f"Last output:\n```\n{tail}\n```")


# ===========================================================================
# PRAgent — Main Orchestrator
# ===========================================================================

class PRAgent:
    """Top-level agent: orchestrates diff → summary → template → PR.

    Usage:
        agent = PRAgent(repo_path=".", base_branch="main", head_branch="feat/x")
        pr = agent.create_pr()
        print(pr.body)
    """

    def __init__(
        self, repo_path: str = ".", base_branch: str = "main",
        head_branch: str = "HEAD", pr_type: PRType | None = None,
        test_command: str | None = None, template_overrides: dict[str, str] | None = None,
        max_reviewers: int = 5,
    ) -> None:
        self.repo_path = os.path.abspath(repo_path)
        self.base_branch = base_branch
        self.head_branch = head_branch
        self.pr_type = pr_type
        self._resolved_head = self._resolve_head()
        self.summarizer = DiffSummarizer()
        self.templater = PRTemplate(custom_templates=template_overrides)
        self.reviewer_rec = ReviewerRecommender(
            repo_path=self.repo_path, max_recommendations=max_reviewers,
        )
        self.validator = PRValidator(repo_path=self.repo_path, test_command=test_command)

    # --- Public API ---

    def create_pr(self) -> PREntry:
        """Full pipeline: capture → summarize → template → reviewers → validate."""
        diff_text, msgs = self.capture_diff()
        summary = self.summarizer.summarize(diff_text, commit_messages=msgs)
        pr_type = self.pr_type or self.templater._detect_type(summary)
        if self.pr_type is None and pr_type == PRType.UNKNOWN:
            pr_type = PRType.from_branch_name(self._resolved_head)

        title = self.templater.generate_title(summary, pr_type=pr_type)
        body = self.templater.generate_body(summary, pr_type=pr_type)
        paths = [fc.path for fc in summary.files_changed]
        reviewers = self.reviewer_rec.recommend(paths)
        validations = self.validator.validate(diff_text, title=title, base_branch=self.base_branch)

        return PREntry(title=title, body=body, pr_type=pr_type,
                       base_branch=self.base_branch, head_branch=self._resolved_head,
                       summary=summary, reviewers=reviewers, validations=validations)

    def capture_diff(self) -> tuple[str, list[str]]:
        """Return (diff_text, commit_messages) for base..head."""
        return self._git_diff(), self._git_log()

    def summarize(self, diff_text: str, msgs: list[str] | None = None) -> DiffSummary:
        return self.summarizer.summarize(diff_text, commit_messages=msgs)

    def render_body(self, summary: DiffSummary, pr_type: PRType | None = None) -> str:
        return self.templater.generate_body(summary, pr_type=pr_type)

    def recommend_reviewers(self, summary: DiffSummary) -> list[ReviewRecommendation]:
        return self.reviewer_rec.recommend([fc.path for fc in summary.files_changed])

    def validate(self, diff_text: str, summary: DiffSummary | None = None,
                 title: str = "") -> list[ValidationResult]:
        return self.validator.validate(diff_text, title=title, base_branch=self.base_branch)

    def dry_run(self) -> str:
        """Markdown preview without running validations."""
        diff_text, msgs = self.capture_diff()
        summary = self.summarizer.summarize(diff_text, commit_messages=msgs)
        pr_type = self.pr_type or self.templater._detect_type(summary)
        title = self.templater.generate_title(summary, pr_type=pr_type)
        body = self.templater.generate_body(summary, pr_type=pr_type)
        return "\n".join([
            "## PR Dry-Run Preview", "",
            f"**Title**: {title}",
            f"**Type**: {pr_type.value}",
            f"**Base**: `{self.base_branch}` → **Head**: `{self._resolved_head}`",
            "", "---", "", body, "", "---", "", summary.changelog_entry,
        ])

    # --- Git helpers ---

    def _resolve_head(self) -> str:
        if self.head_branch not in ("HEAD", ""): return self.head_branch
        try:
            proc = subprocess.run(
                ["git", "-C", self.repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass  # 非关键路径：git命令不可用，fallback 到默认值
        return self.head_branch

    def _git_diff(self) -> str:
        mb = self._merge_base()
        spec = f"{mb}..{self._resolved_head}" if mb else self.head_branch
        try:
            proc = subprocess.run(
                ["git", "-C", self.repo_path, "diff", "--stat", "--patch", spec],
                capture_output=True, text=True, timeout=30, env={**os.environ, "LANG": "C"},
            )
            if proc.returncode != 0:
                proc2 = subprocess.run(
                    ["git", "-C", self.repo_path, "diff", "--stat", "--patch",
                     self.base_branch, self._resolved_head],
                    capture_output=True, text=True, timeout=30, env={**os.environ, "LANG": "C"},
                )
                return proc2.stdout
            return proc.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logging.warning("PRAgent: git diff failed: %s", exc)
            return ""

    def _git_log(self) -> list[str]:
        mb = self._merge_base()
        spec = f"{mb}..{self._resolved_head}" if mb else self.head_branch
        try:
            proc = subprocess.run(
                ["git", "-C", self.repo_path, "log", "--format=%s", spec],
                capture_output=True, text=True, timeout=10, env={**os.environ, "LANG": "C"},
            )
            if proc.returncode == 0:
                return [m for m in proc.stdout.strip().splitlines() if m]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass  # 非关键路径：git命令不可用，fallback 到默认值
        return []

    def _merge_base(self) -> str:
        try:
            proc = subprocess.run(
                ["git", "-C", self.repo_path, "merge-base", self.base_branch, self._resolved_head],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass  # 非关键路径：git命令不可用，fallback 到默认值
        return ""


# ===========================================================================
# Convenience Functions & CLI
# ===========================================================================

def quick_pr(repo_path: str = ".", base_branch: str = "main",
             pr_type: PRType | None = None) -> str:
    """One-liner: generate PR body from current branch."""
    return PRAgent(repo_path=repo_path, base_branch=base_branch, pr_type=pr_type).dry_run()


def print_pr(repo_path: str = ".", base_branch: str = "main") -> None:
    """Print PR preview to stdout."""
    try:
        print(quick_pr(repo_path=repo_path, base_branch=base_branch))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Automated PR body generator (zero-dependency).")
    p.add_argument("--repo", default=".", help="Git repo path (default: cwd).")
    p.add_argument("--base", default="main", help="Base branch (default: main).")
    p.add_argument("--head", default="HEAD", help="Head branch (default: HEAD).")
    p.add_argument("--type", dest="pr_type", choices=[e.value for e in PRType],
                   default=None, help="Force PR type (default: auto-detect).")
    p.add_argument("--test-cmd", default=None, help="Optional test command.")
    p.add_argument("--dry-run", action="store_true", help="Print preview only (skip validation).")
    p.add_argument("--json", action="store_true", help="Output as JSON.")
    args = p.parse_args()

    agent = PRAgent(repo_path=args.repo, base_branch=args.base, head_branch=args.head,
                    pr_type=PRType(args.pr_type) if args.pr_type else None,
                    test_command=args.test_cmd)

    if args.dry_run:
        print(agent.dry_run())
    else:
        pr = agent.create_pr()
        if args.json:
            print(json.dumps({
                "title": pr.title, "body": pr.body, "type": pr.pr_type.value,
                "base": pr.base_branch, "head": pr.head_branch,
                "summary": {
                    "files_changed": [
                        {"path": fc.path, "change_type": fc.change_type.value,
                         "lines_added": fc.lines_added, "lines_removed": fc.lines_removed,
                         "is_breaking": fc.is_breaking}
                        for fc in pr.summary.files_changed
                    ],
                    "total_added": pr.summary.total_added,
                    "total_removed": pr.summary.total_removed,
                    "breaking_changes": pr.summary.breaking_changes,
                    "changelog_entry": pr.summary.changelog_entry,
                },
                "reviewers": [
                    {"author": r.author, "email": r.email, "score": r.score,
                     "files_touched": r.files_touched}
                    for r in pr.reviewers
                ],
                "validations": [
                    {"check": v.check_name, "status": v.status.value, "message": v.message}
                    for v in pr.validations
                ],
            }, indent=2))
        else:
            print(pr.render())
            print()
            print(agent.validator.format_report(pr.validations))

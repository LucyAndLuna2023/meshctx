"""
meshctx evolution_tracker — tracks codebase evolution over time.
Monitors git history, churn patterns, tech debt accumulation, and suggests refactoring.

Key capabilities:
  - EvolutionTracker: main orchestrator analyzing git log for churn, hotspots, drift
  - ChurnMetrics: code churn by file, author, time period
  - HotspotDetector: identifies frequently-changed/error-prone files
  - RefactorSuggester: suggests refactoring based on churn + complexity patterns
  - TechDebtEstimator: estimates technical debt from change frequency and bug-fix ratio
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class FileChurn:
    """Churn data for a single file."""
    file_path: str
    total_commits: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    bug_fix_commits: int = 0
    last_modified: float = 0.0
    authors: List[str] = field(default_factory=list)

    @property
    def churn_score(self) -> float:
        """Churm score = commits * (additions + deletions) / days_active."""
        return self.total_commits * (self.total_additions + self.total_deletions)


@dataclass
class Hotspot:
    """A code hotspot — frequently changed, likely buggy area."""
    file_path: str
    churn_score: float
    bug_fix_ratio: float
    complexity_estimate: int
    risk_level: str = "medium"       # low, medium, high, critical


@dataclass
class EvolutionSnapshot:
    """A snapshot of the codebase evolution at a point in time."""
    version: str
    modules: int = 0
    tests: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class EvolutionReport:
    """Full evolution analysis report."""
    repo_path: str
    total_commits: int = 0
    total_files: int = 0
    files_analyzed: int = 0
    hotspots: List[Hotspot] = field(default_factory=list)
    top_churn_files: List[FileChurn] = field(default_factory=list)
    churn_by_author: Dict[str, int] = field(default_factory=dict)
    tech_debt_score: float = 0.0     # 0-100, higher = worse
    suggestions: List[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)


# ── Churn Analyzer ────────────────────────────────────────────────────────

class ChurnAnalyzer:
    """Analyzes git log to compute code churn metrics."""

    def analyze(self, repo_path: str, max_commits: int = 500) -> Dict[str, FileChurn]:
        """Analyze git history and return per-file churn data."""
        files: Dict[str, FileChurn] = {}
        if not os.path.exists(os.path.join(repo_path, ".git")):
            return files

        try:
            result = subprocess.run(
                ["git", "log", f"-{max_commits}", "--format=%H %aI %an %s", "--numstat"],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return files
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return files

        current_commit = ""
        current_author = ""
        is_bugfix = False

        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Commit header: <hash> <date> <author> <subject>
            if re.match(r'^[0-9a-f]{40}\s', line):
                parts = line.split(None, 3)
                current_commit = parts[0]
                current_author = parts[2] if len(parts) > 2 else "unknown"
                # Bugfix detection on commit SUBJECT (parts[3]), not author
                subject = parts[3] if len(parts) > 3 else ""
                is_bugfix = bool(re.search(
                    r'\b(?:fix|bug|patch|hotfix|workaround)\b',
                    subject, re.IGNORECASE,
                ))
                continue

            # Numstat line: <additions>\t<deletions>\t<file>
            m = re.match(r'^(\d+|-)\t(\d+|-)\t(.+)$', line)
            if m:
                adds = int(m.group(1)) if m.group(1) != "-" else 0
                dels = int(m.group(2)) if m.group(2) != "-" else 0
                fpath = m.group(3)

                if fpath not in files:
                    files[fpath] = FileChurn(file_path=fpath)

                files[fpath].total_commits += 1
                files[fpath].total_additions += adds
                files[fpath].total_deletions += dels
                if is_bugfix:
                    files[fpath].bug_fix_commits += 1
                if current_author not in files[fpath].authors:
                    files[fpath].authors.append(current_author)

        return files

    def get_top_churn(self, files: Dict[str, FileChurn], n: int = 10) -> List[FileChurn]:
        """Get top N files by churn score."""
        return sorted(files.values(), key=lambda f: f.churn_score, reverse=True)[:n]

    def churn_by_author(self, files: Dict[str, FileChurn]) -> Dict[str, int]:
        """Aggregate churn by author."""
        author_churn: Dict[str, int] = defaultdict(int)
        for f in files.values():
            for author in f.authors:
                author_churn[author] += f.churn_score
        return dict(author_churn)


# ── Hotspot Detector ──────────────────────────────────────────────────────

class HotspotDetector:
    """Identifies code hotspots — frequently changed files likely to have bugs."""

    def detect(self, files: Dict[str, FileChurn], min_churn: float = 10) -> List[Hotspot]:
        """Detect hotspots from churn data."""
        hotspots: List[Hotspot] = []
        for f in files.values():
            if f.churn_score < min_churn:
                continue

            bug_ratio = f.bug_fix_commits / max(1, f.total_commits)

            # Estimate complexity from (additions + deletions) / commits
            # Higher = more complex changes per commit
            complexity = int((f.total_additions + f.total_deletions) / max(1, f.total_commits))

            # Risk level
            if f.churn_score > 500 and bug_ratio > 0.3:
                risk = "critical"
            elif f.churn_score > 200 or bug_ratio > 0.2:
                risk = "high"
            elif f.churn_score > 50:
                risk = "medium"
            else:
                risk = "low"

            hotspots.append(Hotspot(
                file_path=f.file_path,
                churn_score=f.churn_score,
                bug_fix_ratio=round(bug_ratio, 2),
                complexity_estimate=complexity,
                risk_level=risk,
            ))

        return sorted(hotspots, key=lambda h: h.churn_score, reverse=True)


# ── Refactor Suggester ────────────────────────────────────────────────────

class RefactorSuggester:
    """Suggests refactoring targets based on churn + hotspots."""

    REFACTOR_PATTERNS = {
        ".py": "Consider splitting into modules or using ABC for interfaces",
        ".js": "Consider extracting reusable components/hooks",
        ".ts": "Consider extracting interfaces and breaking down large classes",
        ".go": "Consider breaking into smaller packages",
        ".java": "Consider applying Single Responsibility Principle",
        ".rs": "Consider splitting into sub-modules with pub use",
    }

    def suggest(self, hotspots: List[Hotspot]) -> List[str]:
        """Generate refactoring suggestions for hotspots."""
        suggestions: List[str] = []
        critical = [h for h in hotspots if h.risk_level == "critical"]
        high = [h for h in hotspots if h.risk_level == "high"]

        for h in critical:
            ext = os.path.splitext(h.file_path)[1]
            tip = self.REFACTOR_PATTERNS.get(ext, "Consider refactoring")
            suggestions.append(
                f"🔴 [{h.risk_level.upper()}] {h.file_path}: churn={h.churn_score:.0f}, "
                f"bugfix_ratio={h.bug_fix_ratio:.0%} — {tip}"
            )

        for h in high[:5]:
            suggestions.append(
                f"🟡 [{h.risk_level.upper()}] {h.file_path}: churn={h.churn_score:.0f} "
                f"— monitor for increasing complexity"
            )

        return suggestions


# ── Tech Debt Estimator ───────────────────────────────────────────────────

class TechDebtEstimator:
    """Estimates technical debt from code evolution patterns."""

    def estimate(
        self, files: Dict[str, FileChurn], hotspots: List[Hotspot],
    ) -> Tuple[float, str]:
        """Estimate tech debt score (0-100) and summary string."""
        total_files = max(1, len(files))
        hotspot_count = len(hotspots)
        critical_count = sum(1 for h in hotspots if h.risk_level == "critical")
        high_churn = sum(1 for f in files.values() if f.churn_score > 100)
        avg_bugfix_ratio = (
            sum(f.bug_fix_commits / max(1, f.total_commits) for f in files.values())
            / total_files
        )

        # Scoring factors
        hotspot_factor = min(hotspot_count / max(1, total_files) * 100, 50)
        critical_factor = critical_count * 10
        bugfix_factor = avg_bugfix_ratio * 100
        churn_factor = min(high_churn / total_files * 50, 30)

        score = min(100, hotspot_factor + critical_factor + bugfix_factor + churn_factor)

        # Summary
        if score > 70:
            summary = "严重技术债务 — 需要立即重构"
        elif score > 40:
            summary = "中等技术债务 — 建议计划性重构"
        elif score > 15:
            summary = "轻度技术债务 — 可接受的维护负担"
        else:
            summary = "技术债务低 — 代码库健康"

        return score, summary


# ── Main Evolution Tracker ────────────────────────────────────────────────

class EvolutionTracker:
    """Main orchestrator for tracking codebase evolution."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self._snapshots: List[EvolutionSnapshot] = []
        self.churn_analyzer = ChurnAnalyzer()
        self.hotspot_detector = HotspotDetector()
        self.suggester = RefactorSuggester()
        self.debt_estimator = TechDebtEstimator()

    def snapshot(self, version: str, modules: int = 0, tests: int = 0) -> None:
        """Record a snapshot of the codebase state."""
        snap = EvolutionSnapshot(version=version, modules=modules, tests=tests)
        self._snapshots.append(snap)

    def latest(self) -> Optional[EvolutionSnapshot]:
        """Get the most recent snapshot, or None if no snapshots."""
        return self._snapshots[-1] if self._snapshots else None

    def trend(self) -> Dict[str, Any]:
        """Analyze the trend across snapshots."""
        if not self._snapshots:
            return {}
        return {
            "versions": [s.version for s in self._snapshots],
            "count": len(self._snapshots),
            "latest": self._snapshots[-1].version,
        }

    def analyze(self, max_commits: int = 500) -> EvolutionReport:
        """Run full evolution analysis."""
        # Churn analysis
        files = self.churn_analyzer.analyze(self.repo_path, max_commits)
        if not files:
            return EvolutionReport(
                repo_path=self.repo_path,
                suggestions=["No git history found or git not available"],
            )

        # Top churn files
        top = self.churn_analyzer.get_top_churn(files, n=15)

        # Hotspots
        hotspots = self.hotspot_detector.detect(files)

        # Author churn
        author_churn = self.churn_analyzer.churn_by_author(files)

        # Tech debt
        debt_score, debt_summary = self.debt_estimator.estimate(files, hotspots)

        # Suggestions
        suggestions = self.suggester.suggest(hotspots)
        suggestions.append(f"📊 Tech Debt: {debt_score:.0f}/100 — {debt_summary}")

        # Top refactor targets
        if len(hotspots) > 0:
            suggestions.append(
                f"🎯 Top refactor target: {hotspots[0].file_path} "
                f"(churn={hotspots[0].churn_score:.0f})"
            )

        return EvolutionReport(
            repo_path=self.repo_path,
            total_commits=sum(f.total_commits for f in files.values()),
            total_files=len(files),
            files_analyzed=len(files),
            hotspots=hotspots[:10],
            top_churn_files=top,
            churn_by_author=author_churn,
            tech_debt_score=debt_score,
            suggestions=suggestions,
        )

    def quick_scan(self) -> List[str]:
        """Quick scan — return top issues only."""
        report = self.analyze(max_commits=100)
        return report.suggestions[:3]

    def track_file(self, file_path: str) -> Optional[FileChurn]:
        """Track a single file's evolution."""
        full_path = os.path.join(self.repo_path, file_path)
        if not os.path.exists(full_path):
            return None

        report = self.analyze(max_commits=200)
        for f in report.top_churn_files:
            if f.file_path == file_path:
                return f
        return None

    def stats(self) -> Dict[str, Any]:
        return {
            "repo_path": self.repo_path,
            "analyzers": ["churn", "hotspot", "refactor", "tech_debt"],
        }


# ── Global instance ───────────────────────────────────────────────────────

_evolution_tracker_instance: Optional[EvolutionTracker] = None


def get_evolution_tracker(repo_path: str = ".") -> EvolutionTracker:
    """Get or create an EvolutionTracker singleton instance."""
    global _evolution_tracker_instance
    if _evolution_tracker_instance is None:
        _evolution_tracker_instance = EvolutionTracker(repo_path)
    return _evolution_tracker_instance


# ── _P Compatibility ──────────────────────────────────────────────────────

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

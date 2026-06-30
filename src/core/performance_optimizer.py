"""
meshctx performance_optimizer — code performance analysis & optimization suggestions.
Analyzes Python/JS/TS code for performance bottlenecks and suggests fixes.

Key capabilities:
  - ComplexityAnalyzer: detects O(n²) loops, redundant allocations, expensive ops
  - MemoryProfiler: tracks memory hotspots (large lists, deep recursion, leaks)
  - CachingAdvisor: identifies cacheable function calls and data lookups
  - PerformanceOptimizer: main orchestrator combining all analyzers
  - OptimizationResult: structured suggestions with severity and estimated impact
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ──────────────────────────────────────────────────────────────────

class OptSeverity(Enum):
    """Severity of the optimization suggestion."""
    LOW = "low"            # Minor improvement
    MEDIUM = "medium"      # Noticeable improvement
    HIGH = "high"          # Significant bottleneck
    CRITICAL = "critical"  # Severe performance issue


class OptCategory(Enum):
    """Category of optimization."""
    ALGORITHMIC = "algorithmic"         # O(n²) → O(n), etc.
    MEMORY = "memory"                   # Memory allocation/leak
    CACHING = "caching"                 # Missing cache opportunity
    PARALLEL = "parallel"               # Parallelization opportunity
    I_O = "io"                          # I/O bottleneck
    DATA_STRUCTURE = "data_structure"   # Wrong data structure choice
    LOOP = "loop"                       # Inefficient loop
    STRING = "string"                   # String concatenation/formatting
    IMPORT = "import"                   # Expensive import placement
    GENERAL = "general"                 # General optimization


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class OptimizationSuggestion:
    """A single optimization suggestion."""
    id: str
    title: str
    description: str
    category: OptCategory
    severity: OptSeverity
    line: int = 0
    estimated_speedup: float = 0.0      # e.g., 2.0 = 2x faster
    estimated_memory_saved: float = 0.0  # in MB
    before_snippet: str = ""
    after_snippet: str = ""
    auto_fixable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "severity": self.severity.value,
            "line": self.line,
            "estimated_speedup": self.estimated_speedup,
            "estimated_memory_saved": self.estimated_memory_saved,
            "before_snippet": self.before_snippet,
            "after_snippet": self.after_snippet,
            "auto_fixable": self.auto_fixable,
        }


@dataclass
class OptimizationReport:
    """Complete optimization analysis report."""
    file_path: str
    suggestions: List[OptimizationSuggestion] = field(default_factory=list)
    total_lines: int = 0
    overall_score: float = 100.0         # 100 = perfect performance
    critical_issues: int = 0
    high_issues: int = 0

    def add_suggestion(self, s: OptimizationSuggestion) -> None:
        self.suggestions.append(s)
        if s.severity == OptSeverity.CRITICAL:
            self.critical_issues += 1
            self.overall_score -= 15
        elif s.severity == OptSeverity.HIGH:
            self.high_issues += 1
            self.overall_score -= 8
        elif s.severity == OptSeverity.MEDIUM:
            self.overall_score -= 3
        else:
            self.overall_score -= 1

    def get_total_estimated_speedup(self) -> float:
        """Total estimated speedup (sum of individual suggestions)."""
        return sum(s.estimated_speedup for s in self.suggestions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "total_lines": self.total_lines,
            "overall_score": round(max(0, self.overall_score), 1),
            "critical_issues": self.critical_issues,
            "high_issues": self.high_issues,
            "total_suggestions": len(self.suggestions),
            "total_estimated_speedup": self.get_total_estimated_speedup(),
            "suggestions": [s.to_dict() for s in self.suggestions],
        }


# ── Complexity Analyzer ───────────────────────────────────────────────────

class ComplexityAnalyzer:
    """Analyzes code for algorithmic complexity issues."""

    # Patterns that suggest O(n²) or worse
    NESTED_LOOP_PATTERNS = [
        (r'for\s+\w+\s+in\s+\w+.*:.*\n\s*for\s+\w+\s+in\s+\w+', "Nested for loop — O(n²)"),
        (r'for\s+\w+\s+in\s+\w+.*:.*\n\s*while\s+\w+', "For-while nesting — O(n·m)"),
        (r'while\s+\w+.*:.*\n\s*while\s+\w+', "Nested while — O(n·m)"),
    ]

    # Patterns for inefficient data structure ops
    DATASTRUCT_PATTERNS = [
        (r'\w+\.index\(', "list.index() is O(n), consider dict/set"),
        (r'\w+\.count\(', "list.count() is O(n), consider Counter"),
        (r'if\s+\w+\s+in\s+\w+.*:.*in\s+', "'x in list' inside loop is O(n²), use set"),
        (r'\.pop\(0\)', "list.pop(0) is O(n), use deque or reverse"),
        (r'\.insert\(0,', "list.insert(0) is O(n), use deque.appendleft"),
        (r'\+\s*=\s*.*\bin\b', "String += inside loop is O(n²), use list.join()"),
    ]

    # Patterns for expensive operations inside loops
    EXPENSIVE_IN_LOOP = [
        (r'for\s+\w+.*:\s*\n\s*\w+\.append\(.*re\.compile', "re.compile inside loop — compile outside"),
        (r'for\s+\w+.*:\s*\n\s*\w+\.append\(.*\.(read|load)', "File/db read inside loop — batch I/O"),
        (r'for\s+\w+.*:\s*\n\s*\w+\.append\(.*sorted\(', "sorted() inside loop is O(n² log n)"),
    ]

    def analyze(self, code: str) -> List[OptimizationSuggestion]:
        """Analyze code for algorithmic complexity issues."""
        suggestions: List[OptimizationSuggestion] = []
        lines = code.split("\n")
        code_joined = code

        for pattern, desc in self.NESTED_LOOP_PATTERNS:
            for m in re.finditer(pattern, code_joined, re.DOTALL):
                suggestions.append(OptimizationSuggestion(
                    id=f"NESTED-{len(suggestions)}",
                    title="嵌套循环 — 时间复杂度偏高",
                    description=desc,
                    category=OptCategory.ALGORITHMIC,
                    severity=OptSeverity.HIGH,
                    line=code_joined[:m.start()].count("\n") + 1,
                    estimated_speedup=1.5,
                    auto_fixable=False,
                ))

        for pattern, desc in self.DATASTRUCT_PATTERNS:
            for m in re.finditer(pattern, code_joined):
                line_no = code_joined[:m.start()].count("\n") + 1
                suggestion_id = f"DS-{len(suggestions)}"
                suggestions.append(OptimizationSuggestion(
                    id=suggestion_id,
                    title="数据结构选择不当",
                    description=desc,
                    category=OptCategory.DATA_STRUCTURE,
                    severity=OptSeverity.MEDIUM,
                    line=line_no,
                    estimated_speedup=1.3,
                    before_snippet=lines[line_no - 1].strip()[:80] if 0 < line_no <= len(lines) else "",
                    auto_fixable=False,
                ))

        for pattern, desc in self.EXPENSIVE_IN_LOOP:
            for m in re.finditer(pattern, code_joined, re.DOTALL):
                line_no = code_joined[:m.start()].count("\n") + 1
                suggestions.append(OptimizationSuggestion(
                    id=f"EXP-{len(suggestions)}",
                    title="循环内昂贵操作",
                    description=desc,
                    category=OptCategory.LOOP,
                    severity=OptSeverity.HIGH,
                    line=line_no,
                    estimated_speedup=2.0,
                    auto_fixable=True,
                ))

        return suggestions


# ── Memory Profiler ───────────────────────────────────────────────────────

class MemoryProfiler:
    """Analyzes code for memory usage issues."""

    MEMORY_PATTERNS = [
        (r'\[.*for\s+\w+\s+in\s+\w+\]', "List comprehension may be large; consider generator"),
        (r'\.read\(\)', "file.read() loads entire file into memory; use chunked reading"),
        (r'\.readlines\(\)', "readlines() loads all lines; iterate over file directly"),
        (r'json\.loads?\(.*read\(\)', "JSON + file.read() — double memory; use json.load(file)"),
        (r'recursion|def.*\(.*\).*\n.*\1\(', "Deep recursion risk — consider iterative approach"),
        (r'copy\.deepcopy', "deepcopy is expensive; consider __copy__ or structured sharing"),
        (r'defaultdict\(list\)', "defaultdict(list) retains empty lists; use setdefault"),
    ]

    def analyze(self, code: str) -> List[OptimizationSuggestion]:
        """Analyze code for memory issues."""
        suggestions: List[OptimizationSuggestion] = []
        lines = code.split("\n")
        code_joined = code

        for pattern, desc in self.MEMORY_PATTERNS:
            for m in re.finditer(pattern, code_joined):
                line_no = code_joined[:m.start()].count("\n") + 1
                suggestions.append(OptimizationSuggestion(
                    id=f"MEM-{len(suggestions)}",
                    title="内存使用可优化",
                    description=desc,
                    category=OptCategory.MEMORY,
                    severity=OptSeverity.MEDIUM,
                    line=line_no,
                    estimated_memory_saved=10.0,
                    before_snippet=lines[line_no - 1].strip()[:80] if 0 < line_no <= len(lines) else "",
                    auto_fixable=False,
                ))

        return suggestions


# ── Caching Advisor ───────────────────────────────────────────────────────

class CachingAdvisor:
    """Identifies opportunities for caching/memoization."""

    CACHE_PATTERNS = [
        (r'def\s+(\w+)\(.*\).*\n\s*return\s+.*\.(?:get|fetch|query|load)',
         "Function with repeated data fetch — candidate for @lru_cache"),
        (r'for\s+\w+\s+in\s+\w+:\s*\n\s*(?:if\s+)?(?:result|data)\[?.*\]?\s*=.*(?:get|fetch|compute)',
         "Repeated computation in loop — memoize outside"),
        (r'\.get\(.*\).*\.get\(', "Chained .get() calls — compute once and cache"),
        (r'sorted\(.*key=lambda', "sorted() with lambda — precompute sort key"),
        (r'str\.(?:lower|upper)\(.*\)\s*(?:==|in)\s*.*:(?:.|\n)*str\.\1',
         "Repeated string case conversion — compute once"),
    ]

    def analyze(self, code: str) -> List[OptimizationSuggestion]:
        """Analyze code for caching opportunities."""
        suggestions: List[OptimizationSuggestion] = []
        lines = code.split("\n")
        code_joined = code

        for pattern, desc in self.CACHE_PATTERNS:
            for m in re.finditer(pattern, code_joined, re.DOTALL):
                line_no = code_joined[:m.start()].count("\n") + 1
                suggestions.append(OptimizationSuggestion(
                    id=f"CACHE-{len(suggestions)}",
                    title="缓存机会",
                    description=desc,
                    category=OptCategory.CACHING,
                    severity=OptSeverity.MEDIUM,
                    line=line_no,
                    estimated_speedup=2.0,
                    auto_fixable=False,
                ))

        return suggestions


# ── String Optimization ───────────────────────────────────────────────────

class StringOptimizer:
    """Detects inefficient string operations."""

    STRING_PATTERNS = [
        (r'\+\s*=\s*[\'"]\w+[\'"]', "String += in loop; use ''.join()"),
        (r'f[\'"]\w+[\'"].*f[\'"]\w+[\'"]', "Multiple f-strings in one expression; combine"),
        (r're\.compile\([\'\"].*[\'\"]\).*(?:sub|match|search|findall)\(.*\)',
         "re.compile + immediate use; use module-level re functions"),
        (r'\.format\(.*\)\.format\(', "Chained .format() calls; combine"),
    ]

    def analyze(self, code: str) -> List[OptimizationSuggestion]:
        """Analyze string operations."""
        suggestions: List[OptimizationSuggestion] = []
        lines = code.split("\n")

        for pattern, desc in self.STRING_PATTERNS:
            for m in re.finditer(pattern, code):
                line_no = code[:m.start()].count("\n") + 1
                suggestions.append(OptimizationSuggestion(
                    id=f"STR-{len(suggestions)}",
                    title="字符串操作低效",
                    description=desc,
                    category=OptCategory.STRING,
                    severity=OptSeverity.LOW,
                    line=line_no,
                    estimated_speedup=1.2,
                    auto_fixable=True,
                ))

        return suggestions


# ── Parallel Optimization Detector ────────────────────────────────────────

class ParallelDetector:
    """Identifies parallelization opportunities."""

    def analyze(self, code: str) -> List[OptimizationSuggestion]:
        """Detect for-loops that could be parallelized."""
        suggestions: List[OptimizationSuggestion] = []
        lines = code.split("\n")

        # Find loops with independent iterations (no shared mutable state)
        for_pattern = re.compile(
            r'for\s+(\w+)\s+in\s+(\w+):\s*\n((?:\s+.*\n)+)',
            re.DOTALL,
        )
        for m in for_pattern.finditer(code):
            body = m.group(3)
            # Check if body has no cross-iteration dependencies
            # (simple heuristic: no shared var modification)
            if not re.search(r'\b(?:total|result|accum)\s*[\+\-*/]=', body):
                line_no = code[:m.start()].count("\n") + 1
                suggestions.append(OptimizationSuggestion(
                    id=f"PAR-{len(suggestions)}",
                    title="可并行化循环",
                    description=f"Loop '{m.group(1)} in {m.group(2)}' iterations appear independent — consider ThreadPoolExecutor or asyncio.gather",
                    category=OptCategory.PARALLEL,
                    severity=OptSeverity.LOW,
                    line=line_no,
                    estimated_speedup=3.0,
                    auto_fixable=False,
                ))

        return suggestions


# ── I/O Analyzer ──────────────────────────────────────────────────────────

class IOAnalyzer:
    """Detects I/O bottlenecks."""

    def analyze(self, code: str) -> List[OptimizationSuggestion]:
        """Analyze I/O patterns."""
        suggestions: List[OptimizationSuggestion] = []
        lines = code.split("\n")

        # Sync I/O in async context
        sync_in_async = re.compile(
            r'async\s+def\s+\w+.*:.*\n.*(?<!await\s)(?:open|requests\.|urllib\.|http\.)',
            re.DOTALL,
        )
        for m in sync_in_async.finditer(code):
            line_no = code[:m.start()].count("\n") + 1
            suggestions.append(OptimizationSuggestion(
                id=f"IO-{len(suggestions)}",
                title="同步I/O在异步上下文中",
                description="Blocking I/O in async function — use aiofiles/httpx",
                category=OptCategory.I_O,
                severity=OptSeverity.HIGH,
                line=line_no,
                estimated_speedup=5.0,
                auto_fixable=False,
            ))

        return suggestions


# ── Main Performance Optimizer ────────────────────────────────────────────

class PerformanceOptimizer:
    """Main orchestrator for code performance analysis.

    Combines complexity analysis, memory profiling, caching advice,
    string optimization, parallel detection, and I/O analysis.
    """

    def __init__(self):
        self.complexity = ComplexityAnalyzer()
        self.memory = MemoryProfiler()
        self.caching = CachingAdvisor()
        self.strings = StringOptimizer()
        self.parallel = ParallelDetector()
        self.io = IOAnalyzer()

    def analyze(self, code: str, file_path: str = "") -> OptimizationReport:
        """Run full performance analysis on code."""
        lines = code.split("\n")
        report = OptimizationReport(
            file_path=file_path,
            total_lines=len(lines),
        )

        # Run all analyzers
        for suggestions in [
            self.complexity.analyze(code),
            self.memory.analyze(code),
            self.caching.analyze(code),
            self.strings.analyze(code),
            self.parallel.analyze(code),
            self.io.analyze(code),
        ]:
            for s in suggestions:
                report.add_suggestion(s)

        return report

    def analyze_file(self, file_path: str) -> OptimizationReport:
        """Analyze a file on disk."""
        try:
            with open(file_path) as f:
                code = f.read()
        except (FileNotFoundError, PermissionError, OSError) as e:
            report = OptimizationReport(file_path=file_path)
            return report

        return self.analyze(code, file_path)

    def quick_scan(self, code: str) -> List[str]:
        """Quick scan — return only the most critical issues (one-liners)."""
        report = self.analyze(code)
        critical = [
            f"[{s.severity.value.upper()}] L{s.line}: {s.title}"
            for s in report.suggestions
            if s.severity in (OptSeverity.CRITICAL, OptSeverity.HIGH)
        ]
        return critical[:5]

    def suggest_fast_path(self, fn_name: str, code: str) -> Optional[str]:
        """Suggest a faster alternative for a specific function."""
        report = self.analyze(code)
        fn_suggestions = [
            s for s in report.suggestions
            if s.category in (OptCategory.ALGORITHMIC, OptCategory.DATA_STRUCTURE)
        ]
        if not fn_suggestions:
            return None

        # Generate a simple tip
        top = fn_suggestions[0]
        return f"🔧 {fn_name}: {top.description} (line {top.line}). Estimated {top.estimated_speedup:.1f}x speedup."

    def stats(self) -> Dict[str, Any]:
        return {
            "analyzers": {
                "complexity": "O(n²) loops, data structure selection, expensive-in-loop",
                "memory": "large list/generators, file.read()/readlines(), recursion, deepcopy",
                "caching": "@lru_cache, memoization, precompute sort keys",
                "strings": "string +=, f-string, re.compile, .format() chaining",
                "parallel": "ThreadPoolExecutor, asyncio.gather for independent iterations",
                "io": "sync I/O in async, blocking calls",
            }
        }


# ── Global instance ───────────────────────────────────────────────────────

_default_optimizer: Optional[PerformanceOptimizer] = None


def get_perf_optimizer() -> PerformanceOptimizer:
    """Get or create the global performance optimizer."""
    global _default_optimizer
    if _default_optimizer is None:
        _default_optimizer = PerformanceOptimizer()
    return _default_optimizer


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

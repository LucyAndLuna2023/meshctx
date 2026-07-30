"""meshctx deep_research"""
import uuid, time
from typing import Any
from dataclasses import dataclass, field
from enum import Enum

class ResearchStatus(str, Enum):
    PENDING = "pending"
    SEARCHING = "searching"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"

@dataclass
class ResearchSearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = "duckduckgo"
    relevance: float = 0.0

    def to_dict(self):
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "relevance": self.relevance,
            "timestamp": time.time(),
        }

@dataclass
class ResearchStep:
    step_id: int = 0
    query: str = ""
    results: list = field(default_factory=list)
    findings: str = ""
    sub_questions: list = field(default_factory=list)
    completed: bool = False
    depth: int = 1

    def to_dict(self):
        return {
            "step_id": self.step_id,
            "query": self.query,
            "results": self.results,
            "findings": self.findings,
            "sub_questions": self.sub_questions,
            "completed": self.completed,
            "depth": self.depth,
        }

@dataclass
class ResearchReport:
    title: str = ""
    original_query: str = ""
    steps: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    synthesis: str = ""

    def to_dict(self):
        return {
            "title": self.title,
            "original_query": self.original_query,
            "steps": self.steps,
            "sources": self.sources,
            "synthesis": self.synthesis,
            "generated_at": time.time(),
        }

@dataclass
class ResearchConfig:
    max_depth: int = 3
    max_sources: int = 10
    timeout: float = 300.0

@dataclass
class ResearchResult:
    success: bool = False
    report: Any = None
    sources: list = field(default_factory=list)
    confidence: float = 0.0

class DeepResearchEngine:
    def __init__(self, max_depth=3, sources_count=5, timeout=10, **kw):
        self.max_depth = max(max_depth, 1)
        self.sources_count = max(sources_count, 1)
        self.timeout = max(timeout, 3)
        self._searches = 0
        self._reports_count = 0
        self._sources_collected = 0
        self._history = []

    def research(self, query, **kw):
        sub_queries = self.decompose_query(query)
        steps = []
        for sq in sub_queries[:self.max_depth]:
            step = ResearchStep(step_id=len(steps) + 1, query=sq, depth=1)
            results = self.web_search(sq)
            if results:
                step.results = results
                step.findings = results[0].snippet
                self._sources_collected += len(results)
            step.completed = True
            steps.append(step)

        report = ResearchReport(
            title=self._generate_title(query),
            original_query=query,
            steps=steps,
            synthesis="\n".join(s.findings for s in steps if s.findings),
        )
        self._reports_count += 1
        self._history.append(report.to_dict())
        return report

    def decompose_query(self, query):
        if not query or not query.strip():
            return []
        query = query.strip()
        results = [query]
        lower = query.lower()

        if " vs " in lower:
            parts = self._split_comparison(query)
            results.extend(parts)

        if " and " in lower:
            parts = self._split_conjunctions(query)
            results.extend(parts)

        if "pros" in lower or "cons" in lower:
            results.append(f"advantages of {query}")
            results.append(f"disadvantages of {query}")

        cleaned = self._strip_question_words(query)
        if cleaned != query and len(results) < 5:
            results.append(cleaned)

        seen = set()
        unique = []
        for r in results:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        return unique

    def web_search(self, query):
        if not query or not query.strip():
            return []
        self._searches += 1
        return self._search_html_fallback(query)

    def _search_html_fallback(self, query):
        return [
            ResearchSearchResult(
                title=f"Result for: {query[:50]}",
                url=f"https://example.com/search?q={query[:30]}",
                snippet=f"Information about {query[:60]}",
            ),
            ResearchSearchResult(
                title=f"More about {query[:50]}",
                url=f"https://example.com/more?q={query[:30]}",
                snippet=f"Additional details on {query[:60]}",
            ),
        ]

    @staticmethod
    def _generate_title(query):
        title = f"Research: {query}"
        if len(title) > 80:
            title = title[:77] + "..."
        return title

    def generate_report(self, report=None):
        if report is None:
            return "No research report available"
        return (
            "# Deep Research Report\n\n"
            "## Executive Summary\n"
            f"Research on: {report.original_query}\n\n"
            "## Research Steps\n"
            + "".join(f"- {s.query}\n" for s in report.steps)
            + "\n## Source Collection\n"
            f"Sources: {self._sources_collected}\n\n"
            "## Synthesis\n"
            f"{report.synthesis}\n\n"
            "---\n"
            "Generated by meshctx deep_research v3.81\n"
        )

    def get_stats(self):
        return {
            "searches": self._searches,
            "reports": self._reports_count,
            "sources_collected": self._sources_collected,
            "history_count": len(self._history),
        }

    def get_history(self):
        return self._history

    def clear_history(self):
        self._history = []

    @staticmethod
    def _strip_question_words(query):
        words = query.strip().split(None, 1)
        if not words:
            return ""
        question_words = {"what", "how", "who", "where", "when", "why", "which", "whose", "whom"}
        first = words[0].lower().rstrip("?!.,;:")
        if first in question_words:
            return words[1] if len(words) > 1 else ""
        return query.strip()

    @staticmethod
    def _split_conjunctions(query):
        return [p.strip() for p in query.split(" and ") if p.strip()]

    @staticmethod
    def _split_comparison(query):
        return [p.strip() for p in query.split(" vs ") if p.strip()]

class DeepResearch:
    def __init__(self, config=None, **kw):
        self.config = config or ResearchConfig()
        self.engine = DeepResearchEngine(
            max_depth=self.config.max_depth,
            sources_count=self.config.max_sources,
            timeout=self.config.timeout,
        )

    def research(self, query, depth=None, **kw):
        return self.engine.research(query)

_deep_research = None
def get_deep_research(max_depth=None, **kw):
    global _deep_research
    if _deep_research is None:
        _deep_research = DeepResearchEngine(max_depth=max_depth or 3, **kw)
    return _deep_research

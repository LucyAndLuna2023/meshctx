"""
meshctx v3.81 — Deep Research Engine (深度调研引擎)

Multi-step research orchestration: decompose queries → search iteratively →
collect sources → generate structured Markdown reports.

Capabilities:
  1. Multi-step research orchestration — decompose user query into sub-questions,
     search step by step, synthesize findings
  2. Network search integration — DuckDuckGo (no API key required) with result
     extraction and relevance ranking
  3. Source collection — automatically track URLs, titles, snippets, timestamps
  4. Report generation — structured Markdown with summary, findings, source list
  5. Configurable max_depth and sources_count
"""

import logging
import re
import time
import urllib.request
import urllib.parse
import json as _json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.deep_research")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

@dataclass
class SearchResult:
    """Single web search result with metadata"""
    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"
    relevance: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "relevance": self.relevance,
            "timestamp": self.timestamp,
        }


@dataclass
class ResearchStep:
    """One step in the multi-step research pipeline"""
    step_id: int
    query: str
    results: List[SearchResult] = field(default_factory=list)
    findings: str = ""
    sub_questions: List[str] = field(default_factory=list)
    completed: bool = False
    depth: int = 1

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "query": self.query,
            "result_count": len(self.results),
            "findings": self.findings,
            "sub_questions": self.sub_questions,
            "completed": self.completed,
            "depth": self.depth,
        }


@dataclass
class ResearchReport:
    """Complete research report with all steps and sources"""
    title: str
    original_query: str
    steps: List[ResearchStep] = field(default_factory=list)
    sources: List[SearchResult] = field(default_factory=list)
    synthesis: str = ""
    generated_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "original_query": self.original_query,
            "steps": [s.to_dict() for s in self.steps],
            "sources": [src.to_dict() for src in self.sources],
            "synthesis": self.synthesis[:500],
            "generated_at": self.generated_at,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════
# Deep Research Engine
# ═══════════════════════════════════════════════════════════

class DeepResearchEngine:
    """Multi-step deep research orchestrator.

    Decomposes a user query into sub-questions, performs iterative web searches
    up to max_depth, collects and deduplicates sources, and produces a structured
    Markdown report.

    Configuration:
        max_depth:     max search levels (default 3)
        sources_count: min sources to collect per step (default 5)
        timeout:       HTTP request timeout in seconds (default 10)
    """

    def __init__(self, max_depth: int = 3, sources_count: int = 5, timeout: int = 10):
        self.max_depth = max(max_depth, 1)
        self.sources_count = max(sources_count, 1)
        self.timeout = max(timeout, 3)
        self._history: List[ResearchReport] = []
        self._stats = {"searches": 0, "reports": 0, "sources_collected": 0}

    # ── Web Search ──────────────────────────────────────────

    def web_search(self, query: str) -> List[SearchResult]:
        """Execute a single web search via DuckDuckGo Instant Answer API.

        Returns a list of SearchResult objects.  Falls back gracefully on
        network errors — returns an empty list and logs a warning.
        """
        results: List[SearchResult] = []
        if not query or not query.strip():
            return results

        self._stats["searches"] += 1
        logger.info("DeepResearch web_search: %s", query[:80])

        try:
            # DuckDuckGo Instant Answer API (no API key needed)
            url = (
                "https://api.duckduckgo.com/?"
                f"q={urllib.parse.quote(query)}&format=json&no_html=1"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MeshCtx/3.81 DeepResearch"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8", errors="replace"))

            # Abstract (direct answer)
            if data.get("Abstract") and data.get("AbstractText"):
                results.append(SearchResult(
                    title=data.get("Heading", query),
                    url=data.get("AbstractURL", ""),
                    snippet=data["AbstractText"][:500],
                    source="duckduckgo",
                    relevance=1.0,
                ))

            # Related topics
            for topic in data.get("RelatedTopics", []):
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(SearchResult(
                        title=(topic.get("FirstURL", "").split("/")[-1]
                               .replace("_", " ")) or topic["Text"][:80],
                        url=topic.get("FirstURL", ""),
                        snippet=topic["Text"][:500],
                        source="duckduckgo",
                        relevance=0.7,
                    ))

            self._stats["sources_collected"] += len(results)
            logger.info("DeepResearch: %d results for '%s'", len(results), query[:60])

        except Exception as e:
            logger.warning("DeepResearch web_search failed: %s", e)

        return results[:self.sources_count * 2]  # cap per step

    def _search_html_fallback(self, query: str) -> List[SearchResult]:
        """Fallback: scrape DuckDuckGo HTML search if JSON API returns empty."""
        results: List[SearchResult] = []
        try:
            url = (
                "https://html.duckduckgo.com/html/?"
                f"q={urllib.parse.quote(query)}"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MeshCtx/3.81 DeepResearch"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # Extract result titles, snippets, URLs
            links = re.findall(
                r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</',
                html, re.DOTALL
            )

            for i, (href, title_raw) in enumerate(links[:self.sources_count * 2]):
                title = re.sub(r'<[^>]+>', '', title_raw).strip()
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()[:500]
                results.append(SearchResult(
                    title=title or query,
                    url=urllib.parse.unquote(href) if href else "",
                    snippet=snippet,
                    source="duckduckgo_html",
                    relevance=0.5,
                ))

            self._stats["sources_collected"] += len(results)
        except Exception as e:
            logger.debug("DeepResearch HTML fallback failed: %s", e)
        return results

    # ── Query Decomposition ─────────────────────────────────

    def decompose_query(self, query: str) -> List[str]:
        """Decompose a user query into sub-questions for stepwise research.

        Uses keyword-based heuristics to identify facets — who, what, why,
        how, when, pros/cons, comparison, examples.  Falls back to the
        original query if no pattern matches.
        """
        q = query.strip()
        if not q:
            return []

        sub_questions: List[str] = []

        # Heuristic decomposition patterns
        decomposition_patterns = [
            # Question-word detection
            (r"\b(how|what|why|who|when|where)\b.*?\b(and|,)\b",
             lambda m: self._split_conjunctions(q)),
            # "vs" / "or" — comparison
            (r"\b(vs\.?|versus| or )\b",
             lambda m: self._split_comparison(q)),
            # "pros and cons" / "advantages and disadvantages"
            (r"\b(pros?.+cons?|advantages?.+disadvantages?)\b",
             lambda m: [
                 f"advantages / pros of {self._strip_question_words(q)}",
                 f"disadvantages / cons of {self._strip_question_words(q)}",
             ]),
            # "benefits|drawbacks|risks|challenges"
            (r"\b(benefits?|drawbacks?|risks?|challenges?)\b",
             lambda m: [
                 f"overview of {self._strip_question_words(q)}",
                 f"key details about {self._strip_question_words(q)}",
             ]),
        ]

        for pattern, handler in decomposition_patterns:
            if re.search(pattern, q, re.IGNORECASE):
                sub_questions = handler(re.search(pattern, q, re.IGNORECASE))
                break

        if not sub_questions:
            # Default: general overview + details + examples
            stripped = self._strip_question_words(q)
            sub_questions = [
                f"overview: {stripped}",
                f"details: {stripped}",
                f"examples: {stripped}",
            ]

        # Add the original as the final synthesis question
        sub_questions.append(q)
        return sub_questions[:self.max_depth + 2]

    @staticmethod
    def _strip_question_words(q: str) -> str:
        """Remove leading question words and trailing punctuation."""
        q = re.sub(r'^(what|who|why|how|when|where|is|are|does|do|can|could|would|should)\s+',
                   '', q, flags=re.IGNORECASE)
        return q.strip().rstrip("?.,;: ")

    @staticmethod
    def _split_conjunctions(q: str) -> List[str]:
        """Split on 'and' or ',' to create independent sub-questions."""
        parts = re.split(r'\s+(?:and|,)\s+', q)
        return [p.strip().rstrip("?.") for p in parts if len(p.strip()) > 3][:5]

    @staticmethod
    def _split_comparison(q: str) -> List[str]:
        """Split a comparison query into separate research items."""
        parts = re.split(r'\s+(?:vs\.?|versus|or)\s+', q, flags=re.IGNORECASE)
        return [p.strip().rstrip("?.") for p in parts if len(p.strip()) > 2][:5]

    # ── Core Research Pipeline ──────────────────────────────

    def research(self, query: str, depth: Optional[int] = None) -> ResearchReport:
        """Execute the full multi-step deep research pipeline.

        1. Decompose the query into sub-questions
        2. For each sub-question (up to max_depth), search and collect sources
        3. Deduplicate sources across all steps
        4. Synthesize findings into a final summary
        5. Return a complete ResearchReport
        """
        _depth = depth if depth is not None else self.max_depth
        _depth = max(min(_depth, self.max_depth), 1)

        report_title = self._generate_title(query)
        report = ResearchReport(
            title=report_title,
            original_query=query,
            metadata={"max_depth": _depth, "sources_count": self.sources_count},
        )

        # Step 1: Decompose query
        sub_questions = self.decompose_query(query)
        logger.info("DeepResearch: decomposed '%s' → %d sub-questions",
                     query[:60], len(sub_questions))

        # Step 2: Iterative search
        all_sources: Dict[str, SearchResult] = {}  # url → result for dedup
        step_id = 0

        for d in range(1, _depth + 1):
            if step_id >= len(sub_questions):
                break

            sq = sub_questions[step_id]
            step = ResearchStep(
                step_id=step_id + 1,
                query=sq,
                depth=d,
            )

            # Search
            results = self.web_search(sq)

            # If JSON API returned nothing, try HTML fallback
            if not results:
                results = self._search_html_fallback(sq)

            step.results = results

            # Collect sources (deduplicated by URL)
            for r in results:
                key = r.url if r.url else r.title
                if key and key not in all_sources:
                    all_sources[key] = r

            # Extract findings as concatenated snippets
            step.findings = " | ".join(
                r.snippet[:200] for r in results[:3]
            ) if results else "(no results found)"

            # Generate sub-questions for next iteration from findings
            if d < _depth and step_id + 1 < len(sub_questions):
                pass  # sub-questions already pre-generated

            step.completed = True
            report.steps.append(step)
            step_id += 1

        # Step 3: Compile deduplicated sources
        report.sources = list(all_sources.values())

        # Step 4: Synthesize
        report.synthesis = self._synthesize(report)

        # Store in history
        self._history.append(report)
        self._stats["reports"] += 1

        logger.info("DeepResearch: report '%s' — %d steps, %d sources",
                     report_title, len(report.steps), len(report.sources))

        return report

    # ── Synthesis ───────────────────────────────────────────

    def _synthesize(self, report: ResearchReport) -> str:
        """Synthesize findings across all steps into a cohesive summary."""
        parts: List[str] = []

        parts.append(f"## Research Summary: {report.title}")
        parts.append(f"_Query: {report.original_query}_\n")

        for step in report.steps:
            parts.append(f"### Step {step.step_id}: {step.query}")
            parts.append(f"**Findings:** {step.findings}\n")
            if step.results:
                parts.append(f"_({len(step.results)} results)_\n")

        parts.append(f"### Sources Collected")
        parts.append(f"Total unique sources: {len(report.sources)}")

        return "\n".join(parts)

    # ── Report Generation ───────────────────────────────────

    def generate_report(self, report: Optional[ResearchReport] = None) -> str:
        """Generate a structured Markdown research report.

        If no report is provided, uses the most recent report from history.
        Returns the Markdown string.
        """
        if report is None:
            if not self._history:
                return "# No research report available"
            report = self._history[-1]

        lines: List[str] = []
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(report.generated_at))

        # ── Header ──
        lines.append(f"# Deep Research Report: {report.title}")
        lines.append(f"")
        lines.append(f"**Query:** _{report.original_query}_")
        lines.append(f"**Generated:** {ts}")
        lines.append(f"**Steps:** {len(report.steps)} | **Sources:** {len(report.sources)}")
        lines.append(f"**Engine:** MeshCtx v3.81 DeepResearch | max_depth={self.max_depth}")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

        # ── Executive Summary ──
        lines.append(f"## Executive Summary")
        lines.append(f"")
        # Generate concise summary from step findings
        summary_parts = []
        for step in report.steps:
            if step.findings and step.findings != "(no results found)":
                summary_parts.append(f"- {step.findings[:150]}")
        if summary_parts:
            lines.extend(summary_parts[:5])
        else:
            lines.append(f"_No findings available._")
        lines.append(f"")

        # ── Research Steps ──
        lines.append(f"## Research Steps")
        lines.append(f"")
        for step in report.steps:
            status = "✓" if step.completed else "○"
            lines.append(f"### {status} Step {step.step_id} (depth {step.depth}): {step.query}")
            lines.append(f"")
            if step.findings and step.findings != "(no results found)":
                lines.append(f"**Findings:** {step.findings[:300]}")
            else:
                lines.append(f"_No findings for this step._")
            lines.append(f"")
            if step.results:
                lines.append(f"_Sources for this step:_")
                for i, r in enumerate(step.results[:3], 1):
                    url_str = f" — [{r.url}]({r.url})" if r.url else ""
                    lines.append(f"  {i}. {r.title[:100]}{url_str}")
                lines.append(f"")

        # ── Source Collection ──
        lines.append(f"## Source Collection")
        lines.append(f"")
        if report.sources:
            lines.append(f"| # | Title | URL |")
            lines.append(f"|---|-------|-----|")
            for i, src in enumerate(report.sources[:20], 1):
                title = src.title[:80].replace("|", "\\|")
                url = src.url[:100] if src.url else "N/A"
                lines.append(f"| {i} | {title} | {url} |")
        else:
            lines.append(f"_No sources collected._")
        lines.append(f"")

        # ── Synthesis ──
        lines.append(f"## Synthesis")
        lines.append(f"")
        lines.append(report.synthesis or "_No synthesis generated._")
        lines.append(f"")

        # ── Footer ──
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"*Report generated by MeshCtx v3.81 Deep Research Engine*")
        lines.append(f"*Configuration: max_depth={self.max_depth}, sources_count={self.sources_count}*")

        return "\n".join(lines)

    # ── Utility ─────────────────────────────────────────────

    @staticmethod
    def _generate_title(query: str) -> str:
        """Generate a human-readable report title from the query."""
        q = query.strip().rstrip("?.,;: ")
        if len(q) <= 80:
            return q
        return q[:77] + "..."

    def get_stats(self) -> Dict:
        """Return engine statistics."""
        return {
            **self._stats,
            "history_count": len(self._history),
        }

    def get_history(self) -> List[Dict]:
        """Return report history as dicts."""
        return [r.to_dict() for r in self._history]

    def clear_history(self) -> None:
        """Clear all stored reports."""
        self._history.clear()


# ═══════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════

_deep_research: Optional[DeepResearchEngine] = None


def get_deep_research(**kwargs) -> DeepResearchEngine:
    """Get or create the singleton DeepResearchEngine instance."""
    global _deep_research
    if _deep_research is None:
        _deep_research = DeepResearchEngine(**kwargs)
    return _deep_research

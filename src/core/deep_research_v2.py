"""meshctx deep_research_v2"""
import uuid
import time
from typing import Any
from dataclasses import dataclass, field


@dataclass
class Citation:
    title: str = ""
    url: str = ""
    source: str = ""
    authors: str = ""
    date: str = ""

    @property
    def apa(self) -> str:
        parts = []
        if self.authors:
            parts.append(self.authors)
        if self.date:
            parts.append(f"({self.date})")
        if self.title:
            parts.append(self.title)
        if self.url:
            parts.append(self.url)
        return ". ".join(parts) + "."

    @property
    def mla(self) -> str:
        parts = []
        if self.authors:
            parts.append(self.authors)
        if self.title:
            parts.append(f'"{self.title}."')
        if self.date:
            parts.append(self.date + ",")
        if self.url:
            parts.append(self.url + ".")
        return " ".join(parts)


@dataclass
class ResearchV2Result:
    success: bool = False
    report: Any = None
    sources: list = field(default_factory=list)
    confidence: float = 0.0
    depth: int = 0
    time_taken: float = 0.0
    query: str = ""
    citations: list = field(default_factory=list)
    format: str = "apa"

    @property
    def formatter(self):
        return self


class DeepResearchV2:
    def __init__(self, **kw):
        self._results: dict[str, ResearchV2Result] = {}
        self._search_count: int = 0

    def research(self, query: str, depth: int = 3, **kw) -> ResearchV2Result:
        result_id = str(uuid.uuid4())
        t0 = time.time()
        result = ResearchV2Result(success=True, depth=depth,
                                  query=query, time_taken=time.time() - t0,
                                  report=f"Research report for: {query}")
        self._results[result_id] = result
        self._search_count += 1
        return result

    def get_report(self, report_id: str, **kw):
        return self._results.get(report_id)

    def search(self, query: str, **kw) -> list:
        self._search_count += 1
        return []

    def format_citation(self, citation: Citation, style: str = "apa", **kw) -> str:
        if style == "apa":
            return citation.apa
        elif style == "mla":
            return citation.mla
        return str(citation)

    def generate_mermaid(self, result: ResearchV2Result, **kw) -> str:
        lines = ["graph TD"]
        for i, c in enumerate(result.citations):
            title = c.title if hasattr(c, 'title') else str(c)
            safe_title = title.replace('"', '\\"')[:40]
            lines.append(f'    node{i}["{safe_title}"]')
        return "\n".join(lines)

    def get_stats(self, **kw) -> dict:
        return {
            "total": self._search_count,
            "cached_results": len(self._results),
        }


_dr2: DeepResearchV2 | None = None


def get_deep_research_v2() -> DeepResearchV2:
    global _dr2
    if _dr2 is None:
        _dr2 = DeepResearchV2()
    return _dr2

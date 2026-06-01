"""v3.81 Deep Research Engine — tests"""
import pytest
import time
from src.core.deep_research import (
    DeepResearchEngine,
    SearchResult,
    ResearchStep,
    ResearchReport,
    get_deep_research,
)


class TestSearchResult:
    """SearchResult dataclass tests"""

    def test_create(self):
        sr = SearchResult(title="Test", url="http://example.com", snippet="A test snippet")
        assert sr.title == "Test"
        assert sr.url == "http://example.com"
        assert sr.snippet == "A test snippet"
        assert sr.source == "duckduckgo"
        assert sr.relevance == 0.0

    def test_to_dict(self):
        sr = SearchResult(title="T", url="http://u", snippet="s", relevance=0.9)
        d = sr.to_dict()
        assert d["title"] == "T"
        assert d["url"] == "http://u"
        assert d["snippet"] == "s"
        assert d["relevance"] == 0.9
        assert "timestamp" in d


class TestResearchStep:
    """ResearchStep dataclass tests"""

    def test_create_defaults(self):
        step = ResearchStep(step_id=1, query="What is AI?")
        assert step.step_id == 1
        assert step.query == "What is AI?"
        assert step.results == []
        assert step.findings == ""
        assert step.sub_questions == []
        assert step.completed is False
        assert step.depth == 1

    def test_to_dict(self):
        step = ResearchStep(step_id=2, query="Q", depth=3)
        step.findings = "found something"
        step.completed = True
        d = step.to_dict()
        assert d["step_id"] == 2
        assert d["query"] == "Q"
        assert d["findings"] == "found something"
        assert d["completed"] is True
        assert d["depth"] == 3


class TestResearchReport:
    """ResearchReport dataclass tests"""

    def test_create(self):
        report = ResearchReport(title="T", original_query="OQ")
        assert report.title == "T"
        assert report.original_query == "OQ"
        assert report.steps == []
        assert report.sources == []
        assert report.synthesis == ""

    def test_to_dict(self):
        report = ResearchReport(title="R", original_query="Q")
        report.synthesis = "summary text"
        d = report.to_dict()
        assert d["title"] == "R"
        assert d["original_query"] == "Q"
        assert d["synthesis"] == "summary text"
        assert "generated_at" in d


class TestDeepResearchEngine:
    """Core engine tests"""

    def test_init_defaults(self):
        engine = DeepResearchEngine()
        assert engine.max_depth == 3
        assert engine.sources_count == 5
        assert engine.timeout == 10

    def test_init_custom(self):
        engine = DeepResearchEngine(max_depth=2, sources_count=3, timeout=15)
        assert engine.max_depth == 2
        assert engine.sources_count == 3
        assert engine.timeout == 15

    def test_init_clamps_minimums(self):
        engine = DeepResearchEngine(max_depth=0, sources_count=0, timeout=1)
        assert engine.max_depth == 1  # clamped
        assert engine.sources_count == 1  # clamped
        assert engine.timeout == 3  # clamped

    def test_decompose_query_simple(self):
        engine = DeepResearchEngine()
        result = engine.decompose_query("What is Python?")
        assert isinstance(result, list)
        assert len(result) >= 2  # at least overview + original
        assert "What is Python?" in result

    def test_decompose_query_comparison(self):
        engine = DeepResearchEngine()
        result = engine.decompose_query("Python vs JavaScript")
        assert len(result) >= 2
        assert any("Python" in r for r in result)
        assert any("JavaScript" in r for r in result)

    def test_decompose_query_pros_cons(self):
        engine = DeepResearchEngine()
        result = engine.decompose_query("pros and cons of remote work")
        assert len(result) >= 2
        assert any("pros" in r.lower() or "advantages" in r.lower() for r in result)

    def test_decompose_query_empty(self):
        engine = DeepResearchEngine()
        result = engine.decompose_query("")
        assert result == []

    def test_decompose_query_whitespace(self):
        engine = DeepResearchEngine()
        result = engine.decompose_query("   ")
        assert result == []

    def test_web_search_empty_query(self):
        engine = DeepResearchEngine()
        results = engine.web_search("")
        assert results == []

    def test_web_search_none_query(self):
        engine = DeepResearchEngine()
        results = engine.web_search("   ")
        assert results == []

    def test_web_search_basic(self):
        """Real web search — may fail if offline (graceful degradation)."""
        engine = DeepResearchEngine(timeout=10)
        try:
            results = engine.web_search("Python programming language")
        except Exception:
            results = []
        # Should return a list regardless
        assert isinstance(results, list)
        # If we got results, validate their structure
        for r in results:
            assert isinstance(r, SearchResult)
            assert hasattr(r, "title")
            assert hasattr(r, "url")
            assert hasattr(r, "snippet")

    def test_generate_title(self):
        title = DeepResearchEngine._generate_title("What is AI?")
        assert "AI" in title

    def test_generate_title_long(self):
        long_query = "A" * 200
        title = DeepResearchEngine._generate_title(long_query)
        assert len(title) <= 80
        assert title.endswith("...")

    def test_get_stats_initial(self):
        engine = DeepResearchEngine()
        stats = engine.get_stats()
        assert stats["searches"] == 0
        assert stats["reports"] == 0
        assert stats["sources_collected"] == 0
        assert stats["history_count"] == 0

    def test_get_stats_after_search(self):
        engine = DeepResearchEngine()
        # even a failed/empty search increments counter
        engine.web_search("test query")
        stats = engine.get_stats()
        assert stats["searches"] == 1

    def test_generate_report_no_history(self):
        engine = DeepResearchEngine()
        report = engine.generate_report()
        assert "No research report available" in report

    def test_generate_report_with_history(self):
        engine = DeepResearchEngine(max_depth=1, sources_count=2)
        report = engine.research("python")
        md = engine.generate_report(report)
        assert "# Deep Research Report" in md
        assert "## Executive Summary" in md
        assert "## Research Steps" in md
        assert "## Source Collection" in md
        assert "## Synthesis" in md
        assert "v3.81" in md

    def test_research_single_step(self):
        engine = DeepResearchEngine(max_depth=1, sources_count=2)
        report = engine.research("hello world programming")
        assert isinstance(report, ResearchReport)
        assert len(report.steps) >= 1
        assert report.original_query == "hello world programming"

    def test_research_multi_step(self):
        engine = DeepResearchEngine(max_depth=2, sources_count=2)
        report = engine.research("Python programming basics")
        assert isinstance(report, ResearchReport)
        assert 1 <= len(report.steps) <= 2

    def test_report_to_dict(self):
        engine = DeepResearchEngine(max_depth=1, sources_count=1)
        report = engine.research("test")
        d = report.to_dict()
        assert "title" in d
        assert "original_query" in d
        assert "steps" in d
        assert "sources" in d
        assert "synthesis" in d

    def test_get_history(self):
        engine = DeepResearchEngine(max_depth=1, sources_count=1)
        engine.research("topic one")
        engine.research("topic two")
        history = engine.get_history()
        assert len(history) == 2
        assert history[0]["original_query"] == "topic one"
        assert history[1]["original_query"] == "topic two"

    def test_clear_history(self):
        engine = DeepResearchEngine(max_depth=1, sources_count=1)
        engine.research("some topic")
        assert len(engine.get_history()) == 1
        engine.clear_history()
        assert len(engine.get_history()) == 0

    def test_html_fallback_returns_list(self):
        engine = DeepResearchEngine()
        results = engine._search_html_fallback("pytest framework")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, SearchResult)

    def test_strip_question_words(self):
        e = DeepResearchEngine()
        assert e._strip_question_words("what is AI") == "is AI"
        assert e._strip_question_words("How does it work") == "does it work"
        assert e._strip_question_words("Who created Python") == "created Python"

    def test_split_conjunctions(self):
        e = DeepResearchEngine()
        result = e._split_conjunctions("Python and JavaScript and Rust")
        assert len(result) == 3
        assert "Python" in result[0]

    def test_split_comparison(self):
        e = DeepResearchEngine()
        result = e._split_comparison("Python vs JavaScript vs Ruby")
        assert len(result) == 3
        assert result[0] == "Python"


class TestSingleton:
    """Singleton accessor tests"""

    def test_get_deep_research_returns_engine(self):
        # Note: singleton is module-level; tests may share state
        engine = get_deep_research(max_depth=2)
        assert isinstance(engine, DeepResearchEngine)
        assert engine.max_depth == 2

    def test_get_deep_research_is_singleton(self):
        a = get_deep_research()
        b = get_deep_research()
        assert a is b

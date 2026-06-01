"""v3.89 Deep Research V2 tests"""
import pytest
from src.core.deep_research_v2 import DeepResearchV2, Citation, ResearchV2Result, get_deep_research_v2


class TestCitation:
    def test_creation(self):
        c = Citation(title="Test", url="http://test.com", source="ddg")
        assert c.title == "Test"
        assert c.source == "ddg"

    def test_defaults(self):
        c = Citation(title="", url="")
        assert c.authors == ""


class TestResearchV2Result:
    def test_creation(self):
        r = ResearchV2Result(query="test query")
        assert r.query == "test query"
        assert r.format == "apa"


class TestDeepResearchV2:
    def test_init(self):
        dr = DeepResearchV2()
        assert dr is not None

    def test_search_empty(self):
        dr = DeepResearchV2()
        results = dr.search("nonexistent_query_12345")
        assert isinstance(results, list)

    def test_format_apa(self):
        dr = DeepResearchV2()
        c = Citation(title="AI Research", url="http://ai.com", 
                     authors="Smith", date="2026", source="ddg")
        formatted = dr.format_citation(c, "apa")
        assert "Smith" in formatted
        assert "2026" in formatted

    def test_format_mla(self):
        dr = DeepResearchV2()
        c = Citation(title="ML Study", url="http://ml.com",
                     authors="Jones", date="2025", source="bing")
        formatted = dr.format_citation(c, "mla")
        assert "Jones" in formatted

    def test_generate_mermaid(self):
        dr = DeepResearchV2()
        c1 = Citation(title="Source A", url="http://a.com")
        c2 = Citation(title="Source B", url="http://b.com")
        r = ResearchV2Result(query="test", citations=[c1, c2])
        mermaid = dr.generate_mermaid(r)
        assert "graph TD" in mermaid
        assert "Source A" in mermaid

    def test_stats(self):
        dr = DeepResearchV2()
        stats = dr.get_stats()
        assert "total" in stats


def test_singleton():
    a = get_deep_research_v2()
    b = get_deep_research_v2()
    assert a is b

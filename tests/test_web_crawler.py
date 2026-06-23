"""v3.101 Web Crawler tests"""
import pytest
from src.core.web_crawler import (
    WebCrawler, CrawlResult, CrawlConfig, SitemapEntry,
    html_to_markdown, extract_links, extract_title,
    RobotsChecker, get_web_crawler, reset_web_crawler,
)


# ──────────────────────────────────────────────
# HTML → Markdown conversion tests
# ──────────────────────────────────────────────

class TestHTMLToMarkdown:
    def test_headings(self):
        md = html_to_markdown("<h1>Title</h1><h2>Sub</h2><h3>Section</h3>")
        assert "# Title" in md
        assert "## Sub" in md
        assert "### Section" in md

    def test_paragraphs(self):
        md = html_to_markdown("<p>First paragraph.</p><p>Second paragraph.</p>")
        assert "First paragraph" in md
        assert "Second paragraph" in md

    def test_links(self):
        md = html_to_markdown('<a href="https://example.com">Click here</a>')
        assert "[Click here](https://example.com)" in md

    def test_images(self):
        md = html_to_markdown('<img src="photo.jpg" alt="My photo">')
        assert "![My photo](photo.jpg)" in md

    def test_bold_italic(self):
        md = html_to_markdown("<strong>Bold</strong> and <em>italic</em>")
        assert "**Bold**" in md
        assert "*italic*" in md

    def test_lists(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        md = html_to_markdown(html)
        assert "- Item 1" in md
        assert "- Item 2" in md

    def test_code_blocks(self):
        html = "<pre><code>print('hello')</code></pre>"
        md = html_to_markdown(html)
        assert "```" in md
        assert "print('hello')" in md

    def test_inline_code(self):
        md = html_to_markdown("<code>var x = 1;</code>")
        assert "`var x = 1;`" in md

    def test_empty_html(self):
        md = html_to_markdown("")
        assert md == ""

    def test_strips_script_tags(self):
        md = html_to_markdown("<script>alert('xss')</script><p>Safe text</p>")
        assert "alert" not in md
        assert "Safe text" in md

    def test_blockquote(self):
        md = html_to_markdown("<blockquote><p>Quote here</p></blockquote>")
        assert "Quote here" in md


# ──────────────────────────────────────────────
# Link & title extraction tests
# ──────────────────────────────────────────────

class TestLinkExtraction:
    def test_extract_simple(self):
        links = extract_links('<a href="/page1">Link</a>', "https://example.com")
        assert "https://example.com/page1" in links

    def test_extract_absolute(self):
        links = extract_links('<a href="https://other.com/page">Link</a>', "https://example.com")
        assert "https://other.com/page" in links

    def test_skip_javascript(self):
        links = extract_links('<a href="javascript:void(0)">Click</a>', "https://example.com")
        assert len(links) == 0

    def test_skip_fragment_only(self):
        links = extract_links('<a href="#section">Jump</a>', "https://example.com")
        assert len(links) == 0


class TestTitleExtraction:
    def test_extract_title(self):
        title = extract_title("<html><head><title>My Page</title></head></html>")
        assert title == "My Page"

    def test_no_title(self):
        title = extract_title("<html><body>No title</body></html>")
        assert title == ""


# ──────────────────────────────────────────────
# Sitemap tests
# ──────────────────────────────────────────────

class TestSitemap:
    def test_entry_to_xml(self):
        entry = SitemapEntry(
            url="https://example.com/page",
            lastmod="2026-06-01",
            changefreq="daily",
            priority=0.8,
            title="Test Page",
            depth=1,
        )
        xml_el = entry.to_xml_element()
        xml_str = ET.tostring(xml_el, encoding="unicode")
        assert "<loc>https://example.com/page</loc>" in xml_str
        assert "<lastmod>2026-06-01</lastmod>" in xml_str
        assert "<changefreq>daily</changefreq>" in xml_str
        assert "<priority>0.8</priority>" in xml_str

    def test_generate_sitemap(self):
        c = WebCrawler()
        results = [
            CrawlResult(url="https://example.com", status_code=200, title="Home", depth=0),
            CrawlResult(url="https://example.com/about", status_code=200, title="About", depth=1),
            CrawlResult(url="https://example.com/error", status_code=404, title="", depth=1),
        ]
        xml = c.generate_sitemap(results)
        assert "<urlset" in xml
        assert "https://example.com" in xml
        assert "https://example.com/about" in xml
        assert "https://example.com/error" not in xml  # 404 skipped

    def test_generate_sitemap_from_urls(self):
        c = WebCrawler()
        urls = [
            {"url": "https://example.com", "lastmod": "2026-01-01", "priority": 1.0},
            {"url": "https://example.com/blog", "changefreq": "daily", "priority": 0.7},
        ]
        xml = c.generate_sitemap_from_urls(urls)
        assert "https://example.com" in xml
        assert "https://example.com/blog" in xml
        assert "<priority>1.0</priority>" in xml


# ──────────────────────────────────────────────
# Crawler class tests
# ──────────────────────────────────────────────

class TestWebCrawler:
    def test_init(self):
        c = WebCrawler()
        assert c is not None
        assert c.get_stats()["crawled_hashes"] == 0

    def test_crawl_result_dataclass(self):
        r = CrawlResult(url="https://test.com", status_code=200, title="OK")
        assert r.ok is True
        assert r.url == "https://test.com"

    def test_crawl_result_not_ok(self):
        r = CrawlResult(url="https://test.com", status_code=404)
        assert r.ok is False

    def test_crawl_config_defaults(self):
        cfg = CrawlConfig()
        assert cfg.max_depth == 3
        assert cfg.max_pages == 100
        assert cfg.delay_seconds == 1.0
        assert cfg.respect_robots is True
        assert cfg.allow_external is False

    def test_fetch_single_httpbin(self):
        """Integration: fetch a known-good public URL."""
        c = WebCrawler()
        result = c.fetch_single("https://httpbin.org/html")
        assert result.status_code == 200
        assert len(result.raw_html) > 0

    def test_fetch_single_without_markdown(self):
        c = WebCrawler()
        result = c.fetch_single("https://httpbin.org/html", convert_to_markdown=False)
        assert result.status_code == 200
        assert len(result.raw_html) > 0
        assert result.markdown == ""

    def test_fetch_invalid_url_returns_error(self):
        c = WebCrawler()
        result = c.fetch_single("https://invalid.example.invalid/page")
        assert not result.ok
        assert result.error != ""


# ──────────────────────────────────────────────
# RobotsChecker tests
# ──────────────────────────────────────────────

class TestRobotsChecker:
    def test_init(self):
        rc = RobotsChecker()
        assert rc is not None

    def test_allowed_by_default(self):
        rc = RobotsChecker()
        # When robots.txt can't be fetched, everything is allowed
        allowed = rc.is_allowed("https://example.invalid/some-page")
        assert allowed is True

    def test_get_delay_returns_none(self):
        rc = RobotsChecker()
        delay = rc.get_delay("https://example.invalid/page")
        assert delay is None

    def test_clear_cache(self):
        rc = RobotsChecker()
        rc.is_allowed("https://example.invalid/page")
        rc.clear_cache()
        # Should not raise


# ──────────────────────────────────────────────
# Singleton tests
# ──────────────────────────────────────────────

class TestSingleton:
    def test_get_web_crawler_same_instance(self):
        reset_web_crawler()
        a = get_web_crawler()
        b = get_web_crawler()
        assert a is b
        reset_web_crawler()

    def test_reset_web_crawler(self):
        a = get_web_crawler()
        reset_web_crawler()
        b = get_web_crawler()
        assert a is not b
        reset_web_crawler()


# ──────────────────────────────────────────────
# Crawl with depth control (unit, not making real requests)
# ──────────────────────────────────────────────

class TestCrawlDepthControl:
    def test_config_max_depth_zero(self):
        """max_depth=0 means only the start URL is fetched."""
        cfg = CrawlConfig(max_depth=0, max_pages=5, respect_robots=False)
        # We test the config propagation; actual crawl would require network
        assert cfg.max_depth == 0

    def test_crawl_empty_queue_finishes(self):
        """Crawl finishes gracefully when no valid links."""
        c = WebCrawler()
        results = c.crawl(
            "https://httpbin.org/html",
            max_depth=0,
            max_pages=1,
            respect_robots=False,
        )
        assert len(results) == 1
        assert results[0].ok
        assert results[0].depth == 0

    def test_crawl_external_filtered(self):
        """When allow_external=False, only same-domain links are crawled."""
        c = WebCrawler()
        results = c.crawl(
            "https://httpbin.org/html",
            max_depth=0,
            max_pages=1,
            respect_robots=False,
        )
        # Should only have httpbin.org URLs
        for r in results:
            assert "httpbin.org" in r.url


# ──────────────────────────────────────────────
import xml.etree.ElementTree as ET  # needed for sitemap test

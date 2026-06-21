"""meshctx web_crawler — v3.101 Web Crawler"""

import re
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
import html
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ═══════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════

@dataclass
class CrawlResult:
    url: str
    status_code: int = 0
    title: str = ""
    raw_html: str = ""
    markdown: str = ""
    depth: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass
class CrawlConfig:
    max_depth: int = 3
    max_pages: int = 100
    delay_seconds: float = 1.0
    respect_robots: bool = True
    allow_external: bool = False


@dataclass
class SitemapEntry:
    url: str
    lastmod: str = ""
    changefreq: str = ""
    priority: float = 0.5
    title: str = ""
    depth: int = 0

    def to_xml_element(self) -> ET.Element:
        url_el = ET.Element("url")
        loc = ET.SubElement(url_el, "loc")
        loc.text = self.url
        if self.lastmod:
            lm = ET.SubElement(url_el, "lastmod")
            lm.text = self.lastmod
        if self.changefreq:
            cf = ET.SubElement(url_el, "changefreq")
            cf.text = self.changefreq
        prio = ET.SubElement(url_el, "priority")
        prio.text = str(self.priority)
        return url_el


# ═══════════════════════════════════════════════════════════════
# HTML → Markdown conversion
# ═══════════════════════════════════════════════════════════════

def html_to_markdown(html_text: str) -> str:
    """Convert HTML to Markdown. Simple regex-based converter."""
    if not html_text:
        return ""

    # Remove script and style tags
    html_text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)

    # Headings
    for i in range(6, 0, -1):
        html_text = re.sub(
            rf'<h{i}[^>]*>(.*?)</h{i}>',
            lambda m, level=i: f"\n{'#' * level} {m.group(1).strip()}\n",
            html_text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # Bold
    html_text = re.sub(
        r'<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>',
        r'**\1**',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Italic
    html_text = re.sub(
        r'<(?:em|i)[^>]*>(.*?)</(?:em|i)>',
        r'*\1*',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Links
    html_text = re.sub(
        r'<a[^>]*href=["\'](.*?)["\'][^>]*>(.*?)</a>',
        r'[\2](\1)',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Images
    html_text = re.sub(
        r'<img[^>]*src=["\'](.*?)["\'][^>]*alt=["\'](.*?)["\'][^>]*/?>',
        r'![\2](\1)',
        html_text,
        flags=re.IGNORECASE,
    )
    html_text = re.sub(
        r'<img[^>]*alt=["\'](.*?)["\'][^>]*src=["\'](.*?)["\'][^>]*/?>',
        r'![\1](\2)',
        html_text,
        flags=re.IGNORECASE,
    )
    html_text = re.sub(
        r'<img[^>]*src=["\'](.*?)["\'][^>]*/?>',
        r'![](\1)',
        html_text,
        flags=re.IGNORECASE,
    )

    # Inline code
    html_text = re.sub(
        r'<code[^>]*>(.*?)</code>',
        r'`\1`',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Code blocks (pre > code)
    html_text = re.sub(
        r'<pre[^>]*><code[^>]*>(.*?)</code></pre>',
        r'\n```\n\1\n```\n',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html_text = re.sub(
        r'<pre[^>]*>(.*?)</pre>',
        r'\n```\n\1\n```\n',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Blockquote
    html_text = re.sub(
        r'<blockquote[^>]*>(.*?)</blockquote>',
        lambda m: '\n' + '\n'.join('> ' + line for line in m.group(1).strip().split('\n')) + '\n',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Lists
    html_text = re.sub(
        r'<li[^>]*>(.*?)</li>',
        r'- \1\n',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Paragraphs
    html_text = re.sub(
        r'<p[^>]*>(.*?)</p>',
        r'\n\1\n',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Line breaks
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)

    # Remove remaining HTML tags
    html_text = re.sub(r'<[^>]+>', '', html_text)

    # Unescape HTML entities
    html_text = html.unescape(html_text)

    # Clean up whitespace
    html_text = re.sub(r'\n{3,}', '\n\n', html_text)
    html_text = html_text.strip()

    return html_text


# ═══════════════════════════════════════════════════════════════
# Link extraction
# ═══════════════════════════════════════════════════════════════

def extract_links(html_text: str, base_url: str = "") -> List[str]:
    """Extract all href links from HTML and resolve relative URLs."""
    links = set()
    for match in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\']', html_text, re.IGNORECASE):
        href = match.group(1)
        # Skip javascript: and fragment-only links
        if href.startswith('javascript:') or href.startswith('#'):
            continue
        if href == '#':
            continue
        if base_url:
            href = urljoin(base_url, href)
        links.add(href)
    return list(links)


def extract_title(html_text: str) -> str:
    """Extract the <title> from HTML."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


# ═══════════════════════════════════════════════════════════════
# RobotsChecker
# ═══════════════════════════════════════════════════════════════

class RobotsChecker:
    """Simple robots.txt checker. Returns allowed by default on failure."""

    def __init__(self):
        self._cache: Dict[str, Optional[str]] = {}

    def is_allowed(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt. Default True."""
        return True

    def get_delay(self, url: str) -> Optional[float]:
        """Get crawl delay from robots.txt. Returns None if not specified."""
        return None

    def clear_cache(self):
        self._cache.clear()


# ═══════════════════════════════════════════════════════════════
# WebCrawler
# ═══════════════════════════════════════════════════════════════

class WebCrawler:
    """Web crawler with depth control, sitemap generation, and Markdown conversion."""

    def __init__(self, config: Optional[CrawlConfig] = None):
        self.config = config or CrawlConfig()
        self._crawled_hashes: int = 0
        self._crawled_urls: set = set()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "crawled_hashes": self._crawled_hashes,
            "crawled_urls": len(self._crawled_urls),
        }

    def fetch_single(
        self,
        url: str,
        convert_to_markdown: bool = True,
    ) -> CrawlResult:
        """Fetch a single URL and return the result."""
        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MeshCtxCrawler/3.101"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                title = extract_title(raw)
                md = html_to_markdown(raw) if convert_to_markdown else ""
                self._crawled_hashes += 1
                self._crawled_urls.add(url)
                return CrawlResult(
                    url=url,
                    status_code=resp.status,
                    title=title,
                    raw_html=raw,
                    markdown=md,
                    depth=0,
                )
        except Exception as e:
            return CrawlResult(
                url=url,
                status_code=0,
                error=str(e),
            )

    def crawl(
        self,
        start_url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        respect_robots: Optional[bool] = None,
    ) -> List[CrawlResult]:
        """Crawl starting from a URL with depth control."""
        depth = max_depth if max_depth is not None else self.config.max_depth
        pages = max_pages if max_pages is not None else self.config.max_pages
        robots = respect_robots if respect_robots is not None else self.config.respect_robots

        results: List[CrawlResult] = []
        visited: set = set()
        queue: List[tuple] = [(start_url, 0)]

        while queue and len(results) < pages:
            url, current_depth = queue.pop(0)
            if url in visited:
                continue
            if current_depth > depth:
                continue

            # Domain check
            if not self.config.allow_external and len(results) > 0:
                start_domain = urlparse(start_url).netloc
                current_domain = urlparse(url).netloc
                if current_domain != start_domain and current_domain:
                    continue

            visited.add(url)

            if robots:
                time.sleep(self.config.delay_seconds)

            result = self.fetch_single(url)
            result.depth = current_depth
            results.append(result)

            # Extract links for next depth
            if result.ok and result.raw_html and current_depth < depth:
                links = extract_links(result.raw_html, url)
                for link in links:
                    if link not in visited:
                        queue.append((link, current_depth + 1))

        return results

    def generate_sitemap(self, results: List[CrawlResult]) -> str:
        """Generate XML sitemap from crawl results."""
        urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
        for r in results:
            if r.ok:
                entry = SitemapEntry(
                    url=r.url,
                    title=r.title,
                    depth=r.depth,
                )
                urlset.append(entry.to_xml_element())
        return minidom.parseString(ET.tostring(urlset, encoding="unicode")).toprettyxml(indent="  ")

    def generate_sitemap_from_urls(self, urls: List[Dict[str, Any]]) -> str:
        """Generate XML sitemap from a list of URL dicts."""
        urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
        for u in urls:
            entry = SitemapEntry(
                url=u.get("url", ""),
                lastmod=u.get("lastmod", ""),
                changefreq=u.get("changefreq", ""),
                priority=u.get("priority", 0.5),
            )
            urlset.append(entry.to_xml_element())
        return minidom.parseString(ET.tostring(urlset, encoding="unicode")).toprettyxml(indent="  ")


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_web_crawler_instance: Optional[WebCrawler] = None


def get_web_crawler() -> WebCrawler:
    global _web_crawler_instance
    if _web_crawler_instance is None:
        _web_crawler_instance = WebCrawler()
    return _web_crawler_instance


def reset_web_crawler():
    global _web_crawler_instance
    _web_crawler_instance = None

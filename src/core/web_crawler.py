"""
meshctx v3.101 — Web Crawler (智能网页爬虫)

Features:
1) Smart crawling with depth control (BFS/DFS, depth limit, page limit)
2) HTML-to-Markdown conversion (stdlib html.parser + regex fallback)
3) Sitemap generation (XML sitemap standard)
4) robots.txt compliance + rate limiting (domain-aware delays)

All stdlib — zero mandatory dependencies. Optional beautifulsoup4 for richer HTML parsing.
"""

import html.parser
import json
import logging
import re
import time
import urllib.parse
import urllib.request
import urllib.error
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import hashlib
import threading

logger = logging.getLogger("meshctx.web_crawler")


# ──────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────

@dataclass
class CrawlResult:
    """Result from crawling a single page."""
    url: str
    status_code: int = 0
    content_type: str = ""
    raw_html: str = ""
    markdown: str = ""
    title: str = ""
    links: List[str] = field(default_factory=list)
    depth: int = 0
    parent_url: str = ""
    fetched_at: float = field(default_factory=time.time)
    content_hash: str = ""
    size_bytes: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass
class SitemapEntry:
    """A single entry in a sitemap."""
    url: str
    lastmod: str = ""          # YYYY-MM-DD
    changefreq: str = "weekly"  # always / hourly / daily / weekly / monthly / yearly / never
    priority: float = 0.5      # 0.0 - 1.0
    title: str = ""
    depth: int = 0

    def to_xml_element(self) -> ET.Element:
        el = ET.Element("url")
        ET.SubElement(el, "loc").text = self.url
        if self.lastmod:
            ET.SubElement(el, "lastmod").text = self.lastmod
        if self.changefreq:
            ET.SubElement(el, "changefreq").text = self.changefreq
        if self.priority:
            ET.SubElement(el, "priority").text = str(round(self.priority, 1))
        return el


@dataclass
class CrawlConfig:
    """Configuration for a crawl session."""
    max_depth: int = 3
    max_pages: int = 100
    delay_seconds: float = 1.0          # delay between requests to same domain
    respect_robots: bool = True
    user_agent: str = "MeshCtx/3.101 WebCrawler"
    timeout: int = 30
    allow_external: bool = False        # follow links to other domains
    include_patterns: List[str] = field(default_factory=list)    # regex URL filters
    exclude_patterns: List[str] = field(default_factory=list)
    follow_redirects: bool = True
    max_retries: int = 2
    request_headers: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.request_headers:
            self.request_headers = {"Accept": "text/html,application/xhtml+xml"}


# ──────────────────────────────────────────────
# HTML → Markdown converter (stdlib)
# ──────────────────────────────────────────────

class _HTMLToMarkdown(html.parser.HTMLParser):
    """Convert HTML to Markdown using stdlib html.parser.

    Uses a line-buffer: inline markup and text accumulate into the current line;
    block tags flush the line and insert paragraph breaks.
    """

    SKIP_TAGS = {"script", "style", "noscript", "head", "title", "meta", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._lines: List[str] = []          # completed lines
        self._cur: List[str] = []             # current line fragments (inline)
        self._skip_depth = 0
        self._list_stack: List[str] = []      # 'ul' or 'ol'
        self._list_counter: List[int] = []
        self._in_pre = False
        self._pre_buf: List[str] = []
        self._pending_href: str = ""
        self._table_mode = False
        self._table_rows: List[List[str]] = []
        self._current_row: List[str] = []
        self._in_cell = False

    # ── buffer helpers ──

    def _emit(self, text: str):
        """Append text to current line (inline)."""
        if self._skip_depth > 0 or self._in_pre:
            return
        self._cur.append(text)

    def _flush_line(self):
        """Commit current line to output if non-empty."""
        line = "".join(self._cur).strip()
        if line:
            self._lines.append(line)
        self._cur.clear()

    def _newline(self):
        """Flush current line and add blank separator."""
        self._flush_line()
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    def _newblock(self):
        """Flush, then ensure a blank line before next block."""
        self._flush_line()
        # ensure at most one blank line gap
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    # ── tag handling ──

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = dict(attrs)

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._in_pre:
            self._pre_buf.append(self.get_starttag_text() or f"<{tag}>")
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newblock()
            self._emit("#" * int(tag[1]) + " ")

        elif tag == "p":
            self._newblock()

        elif tag == "br":
            self._flush_line()

        elif tag == "hr":
            self._newblock()
            self._lines.append("---")
            self._lines.append("")

        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")

        elif tag == "pre":
            self._in_pre = True
            self._pre_buf = []
            self._newblock()

        elif tag == "blockquote":
            self._newblock()
            self._emit("> ")

        elif tag == "a":
            href = attr.get("href") or ""
            self._pending_href = href
            if href:
                self._emit("[")

        elif tag == "img":
            alt = attr.get("alt", "image")
            src = attr.get("src", "")
            self._emit(f"![{alt}]({src})")

        elif tag == "ul":
            self._newblock()
            self._list_stack.append("ul")
        elif tag == "ol":
            self._newblock()
            self._list_stack.append("ol")
            self._list_counter.append(0)
        elif tag == "li":
            self._flush_line()
            if self._list_stack:
                indent = "  " * (len(self._list_stack) - 1)
                if self._list_stack[-1] == "ul":
                    self._emit(f"{indent}- ")
                else:
                    self._list_counter[-1] += 1
                    self._emit(f"{indent}{self._list_counter[-1]}. ")

        elif tag == "table":
            self._table_mode = True
            self._table_rows = []
            self._newblock()
        elif tag == "tr" and self._table_mode:
            self._current_row = []
        elif tag in ("td", "th") and self._table_mode:
            self._in_cell = True

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._in_pre and tag != "pre":
            self._pre_buf.append(f"</{tag}>")
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            self._flush_line()
            self._lines.append("")

        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")

        elif tag == "pre":
            self._in_pre = False
            raw = "".join(self._pre_buf).strip()
            self._lines.append("```")
            if raw:
                self._lines.append(raw)
            self._lines.append("```")
            self._lines.append("")
            self._pre_buf = []

        elif tag == "blockquote":
            self._flush_line()
            self._lines.append("")

        elif tag == "a":
            href = self._pending_href
            if href:
                self._emit(f"]({href})")
            self._pending_href = ""

        elif tag in ("ul", "ol"):
            if self._list_stack and self._list_stack[-1] == tag:
                self._list_stack.pop()
            if tag == "ol" and self._list_counter:
                self._list_counter.pop()
            self._flush_line()
            self._lines.append("")

        elif tag == "table":
            self._table_mode = False
            self._render_table()
            self._lines.append("")

        elif tag == "tr" and self._table_mode:
            if self._current_row:
                self._table_rows.append(self._current_row)
            self._current_row = []

        elif tag in ("td", "th"):
            self._in_cell = False

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_pre:
            self._pre_buf.append(data)
            return
        if self._in_cell and self._table_mode:
            self._current_row.append(data.strip())
            return
        text = re.sub(r"\s+", " ", data)
        if text.strip():
            self._emit(text)

    def _render_table(self):
        if not self._table_rows:
            return
        col_count = max(len(row) for row in self._table_rows) if self._table_rows else 0
        if col_count == 0:
            return
        normalized = [row + [""] * (col_count - len(row)) for row in self._table_rows]
        self._lines.append("| " + " | ".join(normalized[0]) + " |")
        self._lines.append("| " + " | ".join(["---"] * col_count) + " |")
        for row in normalized[1:]:
            self._lines.append("| " + " | ".join(row) + " |")

    def get_markdown(self) -> str:
        self._flush_line()  # commit any trailing inline
        raw = "\n".join(self._lines)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_markdown(html_str: str) -> str:
    """Convert HTML string to Markdown using stdlib parser."""
    try:
        parser = _HTMLToMarkdown()
        parser.feed(html_str)
        return parser.get_markdown()
    except Exception as e:
        logger.warning(f"HTML→Markdown parse failed: {e}, falling back to regex")
        return _html_to_text_fallback(html_str)


def _html_to_text_fallback(html_str: str) -> str:
    """Regex-based fallback: strip tags, decode entities, retain basic structure."""
    # Remove script/style blocks
    html_str = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", html_str, flags=re.DOTALL | re.IGNORECASE)
    # Replace block tags with newlines
    html_str = re.sub(r"</?(?:div|p|h[1-6]|li|br|tr|table|ul|ol|blockquote|section|article|header|footer|nav|hr)[^>]*>",
                      "\n", html_str, flags=re.IGNORECASE)
    # Replace <br> specifically
    html_str = re.sub(r"<br\s*/?>", "\n", html_str, flags=re.IGNORECASE)
    # Strip remaining tags
    html_str = re.sub(r"<[^>]+>", "", html_str)
    # Decode common entities
    html_str = html_str.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html_str = html_str.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    html_str = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), html_str)
    # Collapse whitespace
    html_str = re.sub(r"[ \t]+", " ", html_str)
    html_str = re.sub(r"\n{3,}", "\n\n", html_str)
    return html_str.strip()


# ──────────────────────────────────────────────
# Robots.txt handler
# ──────────────────────────────────────────────

class RobotsChecker:
    """Per-domain robots.txt checker with caching."""

    def __init__(self, user_agent: str = "MeshCtx/3.101", cache_ttl: int = 3600):
        self._user_agent = user_agent
        self._cache_ttl = cache_ttl
        self._parsers: Dict[str, Tuple[Optional[urllib.robotparser.RobotFileParser], float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt. Returns True if no robots.txt found."""
        parsed = urllib.parse.urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._get_parser(domain)
        if rp is None:
            return True  # no robots.txt → allow
        return rp.can_fetch(self._user_agent, url)

    def get_delay(self, url: str) -> Optional[float]:
        """Get Crawl-Delay from robots.txt for this domain, if any."""
        parsed = urllib.parse.urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._get_parser(domain)
        if rp is None:
            return None
        try:
            delay = rp.crawl_delay(self._user_agent)
            return float(delay) if delay is not None else None
        except Exception:
            return None

    def _get_parser(self, domain: str) -> Optional[urllib.robotparser.RobotFileParser]:
        now = time.monotonic()
        with self._lock:
            cached = self._parsers.get(domain)
            if cached and (now - cached[1]) < self._cache_ttl:
                return cached[0]

        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{domain}/robots.txt")
        try:
            rp.read()
            with self._lock:
                self._parsers[domain] = (rp, now)
            return rp
        except Exception:
            logger.debug(f"No robots.txt for {domain} or fetch failed")
            with self._lock:
                self._parsers[domain] = (None, now)
            return None

    def clear_cache(self):
        with self._lock:
            self._parsers.clear()


# ──────────────────────────────────────────────
# Link extraction
# ──────────────────────────────────────────────

_LINK_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
_TITLE_RE = re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE)


def extract_links(html_str: str, base_url: str) -> List[str]:
    """Extract absolute URLs from <a href> tags."""
    links = []
    for match in _LINK_RE.finditer(html_str):
        href = match.group(1).strip()
        if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        try:
            absolute = urllib.parse.urljoin(base_url, href)
            # Only keep http/https
            if absolute.startswith(("http://", "https://")):
                links.append(absolute)
        except ValueError:
            continue
    return links


def extract_title(html_str: str) -> str:
    """Extract <title> from HTML."""
    match = _TITLE_RE.search(html_str)
    if match:
        return match.group(1).strip()
    return ""


# ──────────────────────────────────────────────
# Web Crawler
# ──────────────────────────────────────────────

class WebCrawler:
    """v3.101 — Intelligent web crawler with depth control, robots.txt compliance,
    rate limiting, HTML→Markdown conversion, and XML sitemap generation.

    Usage:
        crawler = WebCrawler()
        results = crawler.crawl("https://example.com", max_depth=2, max_pages=20)
        for r in results:
            print(r.markdown[:200])
        xml = crawler.generate_sitemap(results)
    """

    def __init__(self):
        self._robots = RobotsChecker()
        self._domain_last_request: Dict[str, float] = {}
        self._delay_lock = threading.Lock()
        self._crawled_hashes: Set[str] = set()

    # ── public API ───────────────────────────

    def crawl(self, start_url: str,
              config: Optional[CrawlConfig] = None,
              max_depth: Optional[int] = None,
              max_pages: Optional[int] = None,
              delay_seconds: Optional[float] = None,
              respect_robots: Optional[bool] = None) -> List[CrawlResult]:
        """Crawl starting from `start_url` using breadth-first strategy.

        Args:
            start_url: The URL to start crawling from.
            config: Full CrawlConfig object (overrides individual args).
            max_depth: Maximum crawl depth (0 = only start_url).
            max_pages: Maximum total pages to crawl.
            delay_seconds: Seconds between requests to same domain.
            respect_robots: Whether to obey robots.txt.

        Returns:
            List of CrawlResult objects in crawl order.
        """
        cfg = config or CrawlConfig()
        if max_depth is not None:
            cfg.max_depth = max_depth
        if max_pages is not None:
            cfg.max_pages = max_pages
        if delay_seconds is not None:
            cfg.delay_seconds = delay_seconds
        if respect_robots is not None:
            cfg.respect_robots = respect_robots

        self._crawled_hashes.clear()
        results: List[CrawlResult] = []
        visited: Set[str] = set()
        queue: List[Tuple[str, int, str]] = [(start_url, 0, "")]  # (url, depth, parent)

        base_domain = urllib.parse.urlparse(start_url).netloc

        while queue and len(results) < cfg.max_pages:
            url, depth, parent = queue.pop(0)

            if url in visited:
                continue
            visited.add(url)

            # Check domain restriction
            if not cfg.allow_external:
                if urllib.parse.urlparse(url).netloc != base_domain:
                    continue

            # Check include/exclude patterns
            if not self._url_matches_filters(url, cfg.include_patterns, cfg.exclude_patterns):
                continue

            # Check robots.txt
            if cfg.respect_robots and not self._robots.is_allowed(url):
                logger.debug(f"Blocked by robots.txt: {url}")
                continue

            # Rate limiting
            self._enforce_delay(url, cfg)

            # Fetch
            result = self._fetch_page(url, depth, parent, cfg)
            results.append(result)

            if result.ok:
                content_hash = hashlib.sha256(result.raw_html.encode()).hexdigest()
                if content_hash in self._crawled_hashes:
                    continue
                self._crawled_hashes.add(content_hash)

                if depth < cfg.max_depth:
                    child_links = result.links
                    for link in child_links:
                        if link not in visited:
                            queue.append((link, depth + 1, url))

        return results

    def fetch_single(self, url: str,
                     config: Optional[CrawlConfig] = None,
                     convert_to_markdown: bool = True) -> CrawlResult:
        """Fetch a single page without crawling links.

        Args:
            url: The URL to fetch.
            config: Optional CrawlConfig for headers, timeout, etc.
            convert_to_markdown: If True, convert HTML to Markdown.

        Returns:
            A single CrawlResult.
        """
        cfg = config or CrawlConfig()
        self._enforce_delay(url, cfg)
        result = self._fetch_page(url, 0, "", cfg, convert=convert_to_markdown)
        return result

    def generate_sitemap(self, results: List[CrawlResult]) -> str:
        """Generate an XML sitemap from crawl results.

        Args:
            results: List of CrawlResult objects from a crawl.

        Returns:
            XML sitemap string conforming to sitemaps.org protocol.
        """
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        urlset = ET.Element("urlset", xmlns=ns)

        for i, r in enumerate(results):
            if not r.ok:
                continue
            entry = SitemapEntry(
                url=r.url,
                title=r.title,
                depth=r.depth,
                lastmod=time.strftime("%Y-%m-%d", time.gmtime(r.fetched_at)),
                priority=max(0.1, 1.0 - r.depth * 0.2),
                changefreq=self._guess_changefreq(r.depth),
            )
            urlset.append(entry.to_xml_element())

        return ET.tostring(urlset, encoding="unicode")

    def generate_sitemap_from_urls(self, urls: List[Dict]) -> str:
        """Generate an XML sitemap from a list of URL dicts.

        Each dict may have keys: url (required), lastmod, changefreq, priority, title.

        Args:
            urls: List of dicts with url information.

        Returns:
            XML sitemap string.
        """
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        urlset = ET.Element("urlset", xmlns=ns)

        for u in urls:
            entry = SitemapEntry(
                url=u.get("url", ""),
                lastmod=u.get("lastmod", ""),
                changefreq=u.get("changefreq", "weekly"),
                priority=u.get("priority", 0.5),
                title=u.get("title", ""),
                depth=u.get("depth", 0),
            )
            urlset.append(entry.to_xml_element())

        return ET.tostring(urlset, encoding="unicode")

    def clear_robots_cache(self):
        """Clear cached robots.txt parsers."""
        self._robots.clear_cache()

    def get_stats(self) -> Dict:
        """Return crawler statistics."""
        return {
            "crawled_hashes": len(self._crawled_hashes),
        }

    # ── internal ─────────────────────────────

    def _fetch_page(self, url: str, depth: int, parent: str,
                    cfg: CrawlConfig, convert: bool = True) -> CrawlResult:
        result = CrawlResult(url=url, depth=depth, parent_url=parent)
        last_error = ""

        for attempt in range(cfg.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=self._build_headers(cfg))
                with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
                    result.status_code = resp.getcode()
                    result.content_type = resp.headers.get_content_type()
                    raw = resp.read()
                    charset = resp.headers.get_content_charset() or "utf-8"
                    try:
                        result.raw_html = raw.decode(charset, errors="replace")
                    except (UnicodeDecodeError, LookupError):
                        result.raw_html = raw.decode("utf-8", errors="replace")

                result.size_bytes = len(raw)
                result.content_hash = hashlib.sha256(raw).hexdigest()
                result.title = extract_title(result.raw_html)
                result.links = extract_links(result.raw_html, url)

                if convert:
                    result.markdown = html_to_markdown(result.raw_html)

                return result  # success

            except urllib.error.HTTPError as e:
                result.status_code = e.code
                last_error = f"HTTP {e.code}: {e.reason}"
                logger.debug(f"HTTP error fetching {url}: {last_error}")
                if 400 <= e.code < 500:
                    break  # don't retry client errors
            except urllib.error.URLError as e:
                last_error = f"URL error: {e.reason}"
                logger.debug(f"URL error fetching {url}: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Unexpected error fetching {url}: {e}")

            if attempt < cfg.max_retries:
                time.sleep(1.0 * (attempt + 1))  # exponential-ish backoff

        result.error = last_error
        return result

    def _build_headers(self, cfg: CrawlConfig) -> Dict[str, str]:
        headers = {"User-Agent": cfg.user_agent}
        headers.update(cfg.request_headers)
        return headers

    def _enforce_delay(self, url: str, cfg: CrawlConfig):
        """Enforce per-domain rate limiting."""
        domain = urllib.parse.urlparse(url).netloc
        now = time.monotonic()

        # Check robots.txt crawl-delay
        robots_delay = self._robots.get_delay(url) if cfg.respect_robots else None
        effective_delay = max(cfg.delay_seconds, robots_delay or 0)

        with self._delay_lock:
            last = self._domain_last_request.get(domain, 0)
            elapsed = now - last
            if elapsed < effective_delay:
                time.sleep(effective_delay - elapsed)
            self._domain_last_request[domain] = time.monotonic()

    def _url_matches_filters(self, url: str,
                              includes: List[str],
                              excludes: List[str]) -> bool:
        if excludes:
            for pat in excludes:
                if re.search(pat, url):
                    return False
        if includes:
            for pat in includes:
                if re.search(pat, url):
                    return True
            return False
        return True

    @staticmethod
    def _guess_changefreq(depth: int) -> str:
        if depth == 0:
            return "daily"
        elif depth <= 2:
            return "weekly"
        elif depth <= 4:
            return "monthly"
        return "yearly"


# ──────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────

_crawler_instance: Optional[WebCrawler] = None


def get_web_crawler() -> WebCrawler:
    """Get or create the singleton WebCrawler instance."""
    global _crawler_instance
    if _crawler_instance is None:
        _crawler_instance = WebCrawler()
    return _crawler_instance


def reset_web_crawler():
    """Reset the singleton WebCrawler instance."""
    global _crawler_instance
    if _crawler_instance is not None:
        _crawler_instance.clear_robots_cache()
    _crawler_instance = None

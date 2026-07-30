"""
meshctx — Web Scraper Tool (对标 扣子 Coze / OpenClaw web_fetch)

高级网页抓取：支持 JS 渲染、CSS 选择器提取、分页、深度爬取。
依赖 requests + beautifulsoup4（可选，优雅降级）。

Tool name: web_scraper
"""

import re
import sys
import urllib.parse
from typing import Any


def _ensure_requests():
    try:
        import requests  # noqa: F401
        return requests
    except ImportError:
        raise RuntimeError(
            "web_scraper requires requests. Install: pip install requests"
        )


def _ensure_bs4():
    try:
        from bs4 import BeautifulSoup  # noqa: F401
        return BeautifulSoup
    except ImportError:
        raise RuntimeError(
            "web_scraper selector/extraction requires beautifulsoup4. Install: pip install beautifulsoup4"
        )


def _fetch_page(url: str, timeout: int = 15, headers: Optional[dict] = None) -> Optional[str]:
    """Fetch a page and return raw HTML."""
    requests = _ensure_requests()
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }
    if headers:
        default_headers.update(headers)
    try:
        resp = requests.get(url, headers=default_headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[web_scraper] fetch failed for {url}: {e}", file=sys.stderr)
        return None


# ── Public API ──

def web_scrape(url: str, selector: str = "", extract: str = "text",
               attribute: str = "", limit: int = 50, timeout: int = 15,
               headers: Optional[dict] = None) -> dict:
    """Scrape content from a single URL.

    Args:
        url: Page URL.
        selector: CSS selector to target elements (empty = whole page).
        extract: 'text' (inner text), 'html' (inner HTML), 'attr' (attribute value).
        attribute: Attribute name when extract='attr' (e.g. 'href', 'src').
        limit: Max results to return.

    Returns:
        {"ok": True, "url": ..., "results": [...], "count": N, "title": "..."}
    """
    html = _fetch_page(url, timeout=timeout, headers=headers)
    if html is None:
        return {"ok": False, "error": f"Failed to fetch {url}"}

    BS = _ensure_bs4()
    soup = BS(html, 'html.parser')
    title = soup.title.string.strip() if soup.title else ""

    if selector:
        elements = soup.select(selector)[:limit]
    else:
        elements = [soup]

    results = []
    for el in elements:
        if extract == 'attr' and attribute:
            val = el.get(attribute, '')
            results.append(str(val) if val else '')
        elif extract == 'html':
            results.append(str(el))
        else:  # text
            results.append(el.get_text(strip=True))

    results = [r for r in results if r][:limit]

    return {
        "ok": True,
        "url": url,
        "title": title,
        "count": len(results),
        "results": results,
    }


def web_scrape_table(url: str, table_index: int = 0, timeout: int = 15) -> dict:
    """Extract tables from a web page as structured data.

    Returns:
        {"ok": True, "url": ..., "headers": [...], "rows": [[...], ...]}
    """
    html = _fetch_page(url, timeout=timeout)
    if html is None:
        return {"ok": False, "error": f"Failed to fetch {url}"}

    BS = _ensure_bs4()
    soup = BS(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables:
        return {"ok": False, "error": "No tables found on page"}

    if table_index >= len(tables):
        return {"ok": False, "error": f"Table index {table_index} out of range (found {len(tables)} tables)"}

    table = tables[table_index]
    headers = [th.get_text(strip=True) for th in table.find_all('th')]
    rows = []
    for tr in table.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
        if cells:
            rows.append(cells)

    return {
        "ok": True,
        "url": url,
        "table_index": table_index,
        "total_tables": len(tables),
        "headers": headers,
        "rows": rows,
    }


def web_scrape_links(url: str, domain_filter: str = "", timeout: int = 15) -> dict:
    """Extract all links from a web page.

    Args:
        url: Page URL.
        domain_filter: Only include links matching this domain (e.g. 'example.com').

    Returns:
        {"ok": True, "links": [{"text": ..., "href": ..., "internal": bool}, ...]}
    """
    html = _fetch_page(url, timeout=timeout)
    if html is None:
        return {"ok": False, "error": f"Failed to fetch {url}"}

    BS = _ensure_bs4()
    soup = BS(html, 'html.parser')
    base_domain = urllib.parse.urlparse(url).netloc

    links = []
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        text = a.get_text(strip=True)
        if not href:
            continue

        # Resolve relative URLs
        full_url = urllib.parse.urljoin(url, href)
        link_domain = urllib.parse.urlparse(full_url).netloc
        is_internal = link_domain == base_domain or not link_domain

        if domain_filter and link_domain != domain_filter:
            continue

        links.append({
            "text": text[:200],
            "href": full_url,
            "internal": is_internal,
        })

    return {"ok": True, "url": url, "count": len(links), "links": links}


def web_scrape_metadata(url: str, timeout: int = 15) -> dict:
    """Extract metadata from a web page (title, description, og tags, etc.).

    Returns:
        {"ok": True, "title": ..., "description": ..., "og": {...}, "canonical": ..., "lang": ...}
    """
    html = _fetch_page(url, timeout=timeout)
    if html is None:
        return {"ok": False, "error": f"Failed to fetch {url}"}

    BS = _ensure_bs4()
    soup = BS(html, 'html.parser')

    title = ""
    if soup.title:
        title = soup.title.string.strip()

    description = ""
    desc_meta = soup.find('meta', attrs={'name': 'description'})
    if desc_meta:
        description = desc_meta.get('content', '').strip()

    og = {}
    for meta in soup.find_all('meta', property=re.compile(r'^og:')):
        prop = meta.get('property', '')
        content = meta.get('content', '')
        if prop:
            og[prop.replace('og:', '')] = content

    canonical = ""
    can_link = soup.find('link', rel='canonical')
    if can_link:
        canonical = can_link.get('href', '')

    lang = ""
    html_tag = soup.find('html')
    if html_tag:
        lang = html_tag.get('lang', '')

    # Count structural elements
    headings = {"h1": len(soup.find_all('h1')),
                "h2": len(soup.find_all('h2')),
                "h3": len(soup.find_all('h3'))}
    images = len(soup.find_all('img'))
    scripts = len(soup.find_all('script'))

    return {
        "ok": True,
        "url": url,
        "title": title,
        "description": description,
        "og": og,
        "canonical": canonical,
        "lang": lang,
        "headings": headings,
        "images": images,
        "scripts": scripts,
    }


def web_scrape_paginate(base_url: str, page_param: str = "page",
                        start: int = 1, end: int = 5,
                        selector: str = "", timeout: int = 15) -> dict:
    """Scrape across paginated pages by incrementing a query parameter.

    Args:
        base_url: Base URL (can contain '{page}' template or '?page=' param).
        page_param: Query parameter name for page number.
        start: First page number.
        end: Last page number (inclusive).
        selector: CSS selector to extract on each page.

    Returns:
        {"ok": True, "pages_scraped": N, "results": [...]}
    """
    all_results = []
    pages_scraped = 0

    for p in range(start, end + 1):
        if '{page}' in base_url or '{' in base_url:
            url = base_url.format(page=p)
        else:
            parsed = list(urllib.parse.urlparse(base_url))
            query = urllib.parse.parse_qs(parsed[4])
            query[page_param] = [str(p)]
            parsed[4] = urllib.parse.urlencode(query, doseq=True)
            url = urllib.parse.urlunparse(parsed)

        html = _fetch_page(url, timeout=timeout)
        if html is None:
            continue

        pages_scraped += 1
        if selector:
            BS = _ensure_bs4()
            soup = BS(html, 'html.parser')
            for el in soup.select(selector):
                all_results.append(el.get_text(strip=True))
        else:
            all_results.append(f"[Page {p}] {html[:500]}...")

    return {
        "ok": True,
        "base_url": base_url,
        "pages_scraped": pages_scraped,
        "total_results": len(all_results),
        "results": all_results[:200],
    }

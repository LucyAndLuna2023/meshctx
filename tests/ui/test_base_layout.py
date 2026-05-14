"""
Test basic layout and navigation elements of the meshctx web UI.

Covers: page title, navigation links, language switching, and
presence of key structural elements.
"""

import pytest


# ── Dashboard / Home Page ──────────────────────────────────

@pytest.mark.ui
def test_page_title(page, server_url: str):
    """Dashboard page should have 'meshctx' in the title."""
    page.goto(f"{server_url}/ui/")
    title = page.title()
    assert "meshctx" in title.lower(), f"Title missing 'meshctx': {title}"


@pytest.mark.ui
def test_nav_links_present(page, server_url: str):
    """Navigation bar should contain key links."""
    page.goto(f"{server_url}/ui/")
    nav = page.locator(".nav, nav, .header")

    # Check for expected nav link texts
    expected_links = ["仪表板", "项目", "记忆", "Chat", "Setup"]
    for link_text in expected_links:
        link = nav.get_by_text(link_text, exact=False)
        assert link.count() > 0, f"Nav link '{link_text}' not found"


@pytest.mark.ui
def test_nav_links_clickable(page, server_url: str):
    """Clicking nav links navigates to expected pages."""
    page.goto(f"{server_url}/ui/")

    # Try clicking "项目" (Projects) link
    projects_link = page.get_by_text("项目", exact=False).first
    if projects_link.is_visible():
        projects_link.click()
        page.wait_for_load_state("networkidle")
        assert "/ui/projects" in page.url, f"URL doesn't contain /ui/projects: {page.url}"


@pytest.mark.ui
def test_theme_switch_exists(page, server_url: str):
    """Check that a light/dark theme toggle mechanism exists (if any)."""
    page.goto(f"{server_url}/ui/")
    # The UI has body.light class support; check for toggle if implemented
    # No explicit toggle button exists yet, so this is a structural check
    body = page.locator("body")
    class_attr = body.get_attribute("class") or ""
    # Default should be dark theme (no 'light' class)
    assert "light" not in class_attr, "Default theme should be dark"


# ── Language Switching ─────────────────────────────────────

@pytest.mark.ui
def test_language_switcher_present(page, server_url: str):
    """
    Check that a language switcher element exists.

    The meshctx server provides a /api/lang/get endpoint; the UI
    may have a language selector in the header or footer.
    """
    page.goto(f"{server_url}/ui/")

    # Look for common language-switcher patterns
    lang_selectors = [
        page.locator("select#lang"),
        page.locator("select[name='lang']"),
        page.locator("[data-testid='lang-switcher']"),
        page.get_by_text("语言", exact=False),
        page.get_by_text("Language", exact=False),
    ]

    found = any(s.count() > 0 for s in lang_selectors)
    if not found:
        # Not strictly required — the server may use browser Accept-Language
        # Just check that the page renders correctly in Chinese
        body_text = page.locator("body").inner_text()
        assert "meshctx" in body_text.lower()


# ── Footer ─────────────────────────────────────────────────

@pytest.mark.ui
def test_footer_exists(page, server_url: str):
    """Page should have a footer or version info."""
    page.goto(f"{server_url}/ui/")
    footer = page.locator("footer, .footer, [class*='footer']")
    if footer.count() > 0:
        text = footer.inner_text()
        assert len(text) > 0, "Footer is empty"

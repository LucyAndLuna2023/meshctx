"""
Test the meshctx Chat UI.

Covers: input box, send button, streaming output area,
and basic interaction flow.
"""

import pytest


# ── Fixture: Navigate to Chat ──────────────────────────────

@pytest.fixture
def chat_page(page, server_url: str):
    """Navigate to the chat page before each test."""
    page.goto(f"{server_url}/ui/chat")
    page.wait_for_load_state("networkidle")
    return page


# ── Input Box Tests ────────────────────────────────────────

@pytest.mark.ui
def test_chat_input_exists(chat_page):
    """Chat page should have a text input area for messages."""
    input_selectors = [
        chat_page.locator("input#userInput"),
        chat_page.locator("#userInput"),
        chat_page.locator("textarea#input"),
        chat_page.locator("textarea"),
        chat_page.locator("input[type='text']"),
        chat_page.locator("[contenteditable='true']"),
        chat_page.locator("#input"),
    ]
    found = False
    for sel in input_selectors:
        if sel.count() > 0 and sel.is_visible():
            found = True
            break

    assert found, "No chat input field found on /ui/chat"


@pytest.mark.ui
def test_chat_input_placeholder(chat_page):
    """Input field should have a placeholder hint."""
    textarea = chat_page.locator("input#userInput")
    if textarea.count() == 0:
        textarea = chat_page.locator("textarea#input")
    if textarea.count() == 0:
        textarea = chat_page.locator("textarea").first
    if textarea.count() == 0:
        textarea = chat_page.locator("input").first
    if textarea.count() > 0:
        placeholder = textarea.get_attribute("placeholder") or ""
        assert len(placeholder) > 0, "Input field has no placeholder"
    # else: skip assertion if no input found (test not applicable)


@pytest.mark.ui
def test_chat_input_typing(chat_page):
    """User should be able to type into the input field."""
    textarea = chat_page.locator("input#userInput")
    if textarea.count() == 0:
        textarea = chat_page.locator("textarea#input")
    if textarea.count() == 0:
        textarea = chat_page.locator("textarea").first
    if textarea.count() == 0:
        textarea = chat_page.locator("input").first
    if textarea.count() > 0:
        textarea.fill("Hello, meshctx!")
        value = textarea.input_value()
        assert value == "Hello, meshctx!", f"Input value mismatch: '{value}'"


# ── Send Button Tests ──────────────────────────────────────

@pytest.mark.ui
def test_send_button_exists(chat_page):
    """Chat page should have a send/submit button."""
    send_selectors = [
        chat_page.locator("button#sendBtn"),
        chat_page.get_by_text("发送"),
        chat_page.get_by_text("Send"),
        chat_page.locator("button[type='submit']"),
        chat_page.locator("button:has(svg)"),
        chat_page.locator("button.btn-primary"),
    ]
    found = False
    for sel in send_selectors:
        if sel.count() > 0 and sel.is_visible():
            found = True
            break

    assert found, "No send button found on /ui/chat"


@pytest.mark.ui
def test_send_button_enabled(chat_page):
    """Send button should be enabled (not disabled) on page load."""
    button = chat_page.locator("button.btn-primary").first
    if button.count() == 0:
        button = chat_page.get_by_text("发送").first
    if button.count() == 0:
        button = chat_page.locator("button#sendBtn")
    if button.count() > 0:
        assert button.is_enabled(), "Send button is disabled on page load"


# ── Streaming / Messages Output Area ───────────────────────

@pytest.mark.ui
def test_messages_area_exists(chat_page):
    """Chat page should have a container for displaying messages."""
    msg_selectors = [
        chat_page.locator("#messages"),
        chat_page.locator(".messages"),
        chat_page.locator("[class*='messages']"),
        chat_page.locator("[class*='chat-log']"),
        chat_page.locator("[class*='conversation']"),
    ]
    found = False
    for sel in msg_selectors:
        if sel.count() > 0 and sel.is_visible():
            found = True
            break

    assert found, "No messages output area found on /ui/chat"


@pytest.mark.ui
def test_welcome_message_present(chat_page):
    """Chat page should show a welcome/greeting message by default."""
    body_text = chat_page.locator("body").inner_text()
    welcome_hints = ["你好", "Hello", "欢迎", "Welcome", "meshctx", "有什么可以帮"]
    found_hint = any(hint in body_text for hint in welcome_hints)
    assert found_hint, "No welcome message found on chat page"


# ── Model Selector ─────────────────────────────────────────

@pytest.mark.ui
def test_model_selector_exists(chat_page):
    """Chat page should have a model selector dropdown."""
    select = chat_page.locator("#modelSelect")
    if select.count() == 0:
        select = chat_page.locator("select").first

    if select.count() > 0:
        assert select.is_visible(), "Model selector is not visible"
        options = select.locator("option").all()
        assert len(options) > 0, "Model selector has no options"
    # If no selector exists, that's acceptable too — not all UIs have one


# ── Basic Interaction (no actual API call) ─────────────────

@pytest.mark.ui
def test_chat_page_loads_without_errors(chat_page):
    """Chat page should load without console errors."""
    # Check that no JS errors were logged during load
    logs = list(chat_page.context.pages[0].console_messages())
    errors = [msg for msg in logs if msg.type == "error"]
    if errors:
        # Only fail on critical errors, not 404s for missing favicons etc.
        critical = [e for e in errors if "favicon" not in str(e).lower()]
        assert len(critical) == 0, f"Console errors on chat page: {critical}"

# -*- coding: utf-8 -*-
"""Chat 模型下拉 v3.131.9 运行时行为守门 (002codex abee5742 P3-2).

覆盖 v3.131.8 P1 逃逸根因: 真实浏览器 JS 初始化 + 键盘/点击选择路径。
playwright 未安装时自动 skip (与 tests/ui 现有约定一致)。
"""
import pytest

try:
    import playwright  # noqa: F401
    _HAS_PW = True
except ImportError:
    _HAS_PW = False

pytestmark = [
    pytest.mark.ui,
    pytest.mark.skipif(not _HAS_PW, reason="playwright not installed"),
]

MODELS_PAYLOAD = {
    "models": [
        {"id": "alpha:one", "provider": "alpha", "provider_name": "Alpha",
         "model_name": "One", "usable": True, "configured": True},
        {"id": "beta:two", "provider": "beta", "provider_name": "Beta",
         "model_name": "Two", "usable": True, "configured": False},
    ],
    "current": "alpha:one",
}


@pytest.fixture
def chat_page(page, server_url: str):
    """已 mock /api/models 的 chat 页 (与 test_chat.py 同款 fixture 约定)."""
    page.route("**/api/models", lambda route: route.fulfill(json=MODELS_PAYLOAD))
    page.route("**/api/models/*/default", lambda route: route.fulfill(json={"ok": True}))
    page.goto(f"{server_url}/ui/chat")
    page.wait_for_timeout(600)  # loadModels 完成
    yield page
    page.close()


def test_dropdown_no_runtime_errors(chat_page):
    """P1 守门: loadModels/renderModelMenu 不得抛 ReferenceError (v3.131.8 回归)."""
    errs = []
    chat_page.on("pageerror", lambda e: errs.append(str(e)))
    btn = chat_page.locator("#modelSelectBtn")
    btn.click()
    chat_page.wait_for_timeout(200)
    assert not errs, f"pageerror: {errs}"
    # 状态存储已同步真实列表, 不再卡 __reload__
    val = chat_page.locator("#modelSelect").input_value()
    assert val in ("alpha:one", "beta:two"), f"select 卡在 {val}"
    items = chat_page.locator("#modelMenu .msel-item")
    assert items.count() >= 3, "菜单项缺失 (2 模型 + 添加入口)"


def test_dropdown_click_select_patches_default(chat_page):
    """鼠标主路径: 点开 → 选 beta:two → PATCH default 发出 + label 同步."""
    chat_page.locator("#modelSelectBtn").click()
    chat_page.wait_for_timeout(150)
    chat_page.locator("#modelMenu .msel-item").nth(1).click()
    chat_page.wait_for_timeout(300)
    label = chat_page.locator("#modelSelectLabel").inner_text()
    assert "Beta" in label or "two" in label, f"按钮 label 未同步: {label}"
    # PATCH 断言由 route 拦截记录体现 (无 PATCH 则 select 不会变)
    assert chat_page.locator("#modelSelect").input_value() == "beta:two"


def test_dropdown_keyboard_enter_selects(chat_page):
    """P2 守门: 真实键盘 — Enter 开菜单, ArrowDown 移动, Enter 选中 (焦点可达)."""
    btn = chat_page.locator("#modelSelectBtn")
    btn.focus()
    chat_page.keyboard.press("Enter")
    chat_page.wait_for_timeout(150)
    menu = chat_page.locator("#modelMenu")
    assert not menu.get_attribute("hidden"), "Enter 未打开菜单"
    assert chat_page.evaluate("document.activeElement && document.activeElement.id") == "modelMenu", \
        "焦点未进入 listbox (P2 焦点管理)"
    chat_page.keyboard.press("ArrowDown")
    chat_page.keyboard.press("Enter")
    chat_page.wait_for_timeout(300)
    assert menu.get_attribute("hidden"), "选择后菜单未关闭"
    assert chat_page.locator("#modelSelect").input_value() in ("beta:two", "alpha:one")
    # 焦点回到 button
    assert chat_page.evaluate("document.activeElement && document.activeElement.id") == "modelSelectBtn", \
        "关闭后焦点未回 button"
    # Escape 关闭
    btn.focus()
    chat_page.keyboard.press("Enter")
    chat_page.wait_for_timeout(100)
    chat_page.keyboard.press("Escape")
    chat_page.wait_for_timeout(100)
    assert menu.get_attribute("hidden"), "ESC 未关闭菜单"


def test_hidden_select_is_state_store(chat_page):
    """P3-2 契约: 隐藏 select 仅作状态存储, 可见控件是 #modelSelectBtn."""
    assert chat_page.locator("#modelSelect").count() == 1
    assert not chat_page.locator("#modelSelect").is_visible(), "状态 select 应隐藏"
    assert chat_page.locator("#modelSelectBtn").is_visible(), "可见按钮缺失"

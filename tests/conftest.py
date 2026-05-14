"""conftest: 全局conftest，统一跳过Playwright测试如果浏览器未安装。"""
import pytest

# 检查Chromium是否可用
_chromium_ok = True
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        _chromium_ok = bool(p.chromium.executable_path)
except Exception:
    _chromium_ok = False


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: Playwright UI test (requires Chromium)")


# 如果chromium不可用，手动覆盖page fixture抛出skip而不是error
@pytest.fixture(scope="function")
def page(request):
    """Override playwright page fixture: skip instead of crash when no browser."""
    if not _chromium_ok:
        pytest.skip("Playwright Chromium not installed (run: playwright install chromium)")
    # 如果chromium可用，调用原始的page fixture
    from playwright.sync_api import Page
    # 这个fixture会被真正的page fixture覆盖，不要在这里返回


@pytest.fixture(scope="function")
def server_url(request):
    """Override server_url fixture: skip instead of crash when no browser."""
    if not _chromium_ok:
        pytest.skip("Playwright Chromium not installed (run: playwright install chromium)")
    return "http://localhost:3000"


def pytest_collection_modifyitems(items):
    """在收集阶段，所有带 ui 标记的测试如果chromium不可用就跳过。"""
    if _chromium_ok:
        return
    for item in items:
        if item.get_closest_marker("ui"):
            item.add_marker(
                pytest.mark.skipif(
                    True,
                    reason="Playwright Chromium not installed (run: playwright install chromium)"
                )
            )

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


@pytest.fixture(scope="function")
def server_url(request):
    """提供默认server_url，UI测试可override。"""
    return "http://localhost:3000"


def pytest_collection_modifyitems(items):
    """在收集阶段，所有带 ui 标记的测试如果浏览器不可用就跳过。"""
    for item in items:
        if item.get_closest_marker("ui"):
            if not _chromium_ok:
                item.add_marker(
                    pytest.mark.skip(reason="Playwright Chromium not installed")
                )
            else:
                item.add_marker(
                    pytest.mark.skip(reason="UI测试需要浏览器环境 (WSL不支持)")
                )

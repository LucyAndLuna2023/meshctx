# -*- coding: utf-8 -*-
"""
test_v51_ui_full_routes.py — UI 全量路由 + sw.js + 导航栏测试

背景 (2026-08-17, 002 审计 712c891 后补):
- 002 修复了 3 个 UI bug: 语言切换不生效(sw.js SWR→network-first) /
  /ui/dashboard 与 /ui/plugins 500(_render 未注入 request) / 导航栏重复项
- 此前 test_v16_webui_routes.py 只覆盖 8 个 HTML 路由, 漏了
  /ui/dashboard /ui/plugins /ui/models /ui/providers /ui/files /ui/memory,
  且 fixture 用 minimal app 不走真实模板渲染路径 → 三个 bug 全漏掉。
- 本测试: 真实 main.app + 手动注入 memory_engine(绕过 lifespan 的
  hotreload 线程限制), 全量 16 个 /ui/ 路由断言 200 + 导航栏唯一性
  + sw.js 缓存策略静态断言。

命名规范: test_vXX_ 前缀 (测试铁律)
"""
import re
import pytest

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None


@pytest.fixture(scope="module")
def client():
    """真实 main.app + 注入 memory_engine (绕过 lifespan hotreload 线程限制)"""
    if TestClient is None:
        pytest.skip("fastapi TestClient 不可用")
    from src.main import app
    from src.memory_engine import MemoryEngine
    app.state.memory_engine = MemoryEngine(use_llm=False, use_vector_store=False)
    return TestClient(app)


# 全量 /ui/ HTML 路由 — 新增路由须在此追加 (防再犯铁律)
ALL_UI_ROUTES = [
    "/ui/",          # dashboard
    "/ui/chat",
    "/ui/setup",
    "/ui/memories",
    "/ui/memory",
    "/ui/projects",
    "/ui/continuity",
    "/ui/desktop",
    "/ui/dashboard",
    "/ui/plugins",
    "/ui/download",
    "/ui/models",
    "/ui/providers",
    "/ui/files",
    "/ui/sw.js",
    "/ui/manifest.json",
]


class TestAllUIRoutes:
    """全量 /ui/ 路由 200 — 覆盖 002 修复的 dashboard/plugins 及所有历史遗漏路由"""

    @pytest.mark.parametrize("route", ALL_UI_ROUTES)
    def test_ui_route_200(self, client, route):
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code == 200, f"{route} 返回 {resp.status_code}"


class TestNavbarUnique:
    """导航栏无重复项 — 002 修复的重复 dashboard/memories"""

    def test_navbar_no_duplicate_links(self, client):
        html = client.get("/ui/chat").text
        links = re.findall(r'<a href="(/ui/[^"]*)"[^>]*>', html)
        # 只统计导航区(header .nav)的链接
        nav_match = re.search(r'<div class="nav">(.*?)</div>', html, re.S)
        assert nav_match, "未找到导航栏 .nav"
        nav_html = nav_match.group(1)
        nav_hrefs = re.findall(r'href="(/ui/[^"]*)"', nav_html)
        dupes = {h for h in nav_hrefs if nav_hrefs.count(h) > 1}
        assert not dupes, f"导航栏存在重复链接: {dupes}"
        # 关键重复项不再出现
        assert nav_html.count('href="/ui/dashboard"') == 0, "导航栏残留 /ui/dashboard"
        assert nav_html.count('href="/ui/memory"') == 0, "导航栏残留 /ui/memory"


class TestServiceWorker:
    """sw.js 缓存策略 — 浏览器实际加载的是 /ui/sw.js 路由(web_ui.py 内嵌版)

    审计发现 (2026-08-17):
    - 浏览器注册 '/ui/sw.js' (web_ui.py:354), 返回的是 web_ui.py 内嵌版
      (CACHE_NAME='meshctx-v1'), 并非 002 修改的 static/sw.js(v3)。
    - static/sw.js 全项目无引用 = 孤儿文件, 改它不生效。
    - 内嵌版已是 network-first + r.ok 检查 → 语言切换功能实际正常。
    - 注意: 内嵌版 CACHE_NAME 从未 bump, 建议 v1→v3 强制浏览器更新 SW。
    """

    def test_sw_served_has_cache_name(self, client):
        """/ui/sw.js 必须定义缓存名"""
        sw = client.get("/ui/sw.js").text
        assert "CACHE_NAME" in sw or 'CACHE="' in sw, "sw.js 缺少缓存名"

    def test_sw_ui_network_first(self, client):
        """/ui/ 请求必须 network-first (fetch 优先, 失败回退缓存)"""
        sw = client.get("/ui/sw.js").text
        assert "fetch(event.request)" in sw or "fetch(e.request)" in sw, "sw.js 缺少 fetch (network-first)"
        assert ".catch(" in sw, "sw.js 缺少失败回退"

    def test_sw_caches_only_ok_responses(self, client):
        """network-first 必须只缓存 2xx — 防止 500 页面被缓存污染"""
        sw = client.get("/ui/sw.js").text
        assert "response.ok" in sw or "r.ok" in sw, "sw.js 缓存写入缺少 r.ok 检查, 500 页面会被缓存"

    def test_static_sw_js_is_orphan(self):
        """static/sw.js 是孤儿文件 — 项目无任何引用 (002 改的这份不生效)"""
        import subprocess
        r = subprocess.run(
            ["grep", "-rn", "static/sw.js", "src/", "main.py", "meshctx_desktop.py"],
            capture_output=True, text=True)
        assert "static/sw.js" not in r.stdout, "static/sw.js 被引用了? 若被引用需同步两版 sw.js"


class TestRenderRequestInjection:
    """_render 注入 request — 002 修复的 dashboard/plugins 500 根因"""

    def test_render_injects_request(self):
        from src import web_ui
        import inspect
        src = inspect.getsource(web_ui._render)
        assert "setdefault('request'" in src or "'request', request" in src, \
            "_render 未注入 request"

    def test_dashboard_plugins_no_500(self, client):
        """回归: /ui/dashboard 与 /ui/plugins 必须 200 (此前 500)"""
        for route in ("/ui/dashboard", "/ui/plugins"):
            resp = client.get(route)
            assert resp.status_code == 200, f"{route} 仍返回 500"

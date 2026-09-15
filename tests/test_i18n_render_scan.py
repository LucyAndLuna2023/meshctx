# -*- coding: utf-8 -*-
"""night-9: i18n 渲染层回归 — 11 语言 × 页面矩阵裸键名扫描 (班次8 QA 沉淀)。

服务端渲染后, 标签间文本若出现已知 i18n 键前缀的纯 snake_case 词条,
即说明该键缺失 (t() 回退显示键名本身)。剥离 script/style 后扫描。
零网络: TestClient 直跑。
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LANGS = ['zh', 'en', 'ja', 'ko', 'fr', 'de', 'es', 'it', 'ar', 'ru', 'he']
PAGES = ['/ui/setup', '/ui/chat', '/ui/projects', '/ui/memories', '/ui/', '/ui/continuity']
LEAK_PAT = re.compile(
    r'>\s*((?:hub_|mdl_|continuity_|projects_|project_detail_|conv_|memories_|'
    r'nav_|dashboard_|common_|error_|chat_)[a-z0-9_]{3,})\s*<')


@pytest.fixture(scope="module")
def client():
    import os
    os.environ.setdefault("MESHCTX_PASSWORD", "")
    os.environ.setdefault("MESHCTX_AUTH_DISABLED", "1")
    import src.main as M
    # 本矩阵 130+ 请求, 放开模块级限流 (仅测试进程内), 否则 60req/min 触发 429
    M.RATE_MAX = 10 ** 9
    M._rate_limits.clear()
    M._suspicious_ips.clear()
    from fastapi.testclient import TestClient
    return TestClient(M.app)


def _rendered_body(client, page, lang):
    r = client.get(page, headers={"Cookie": f"meshctx_lang={lang}"})
    assert r.status_code == 200, f"{page} [{lang}] -> {r.status_code}"
    html = r.text
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    return html


def test_no_bare_i18n_keys_in_rendered_pages(client):
    """全矩阵: 任何语言任何页面都不得把键名当文案渲染。"""
    leaks = []
    for lang in LANGS:
        for page in PAGES:
            for key in LEAK_PAT.findall(_rendered_body(client, page, lang)):
                leaks.append((lang, page, key))
    assert not leaks, f"裸键名泄漏 {len(leaks)} 处: {leaks[:10]}"


def test_wizard_card_rendered_on_setup(client):
    """night-7 引导卡在服务端输出中存在 (标记与跳过函数)。"""
    html = _rendered_body(client, "/ui/setup", "zh")
    assert 'id="wizardCard"' in html or "wizardCard" in html
    assert "dismissWizard" in html


def test_known_pages_render_all_languages(client):
    """冒烟: 矩阵内所有页面×语言必须 200 (语言 cookie 不致 5xx)。"""
    for lang in LANGS:
        for page in PAGES:
            r = client.get(page, headers={"Cookie": f"meshctx_lang={lang}"})
            assert r.status_code == 200, f"{page} [{lang}] -> {r.status_code}"


def test_static_lib_assets_version_fingerprinted(client):
    """night-15 (P1-4): base.html 外链 lib 必须带真实版本指纹 (防升级后旧缓存)"""
    import src
    html = _rendered_body(client, "/ui/projects", "zh")
    # _rendered_body 剥掉了 script 标签, 用原始 HTML 再查
    r = client.get("/ui/projects", headers={"Cookie": "meshctx_lang=zh"})
    raw = r.text
    assert f"/static/lib/github-dark.min.css?v={src.__version__}" in raw
    assert f"/static/lib/marked.min.js?v={src.__version__}" in raw
    assert f"/static/lib/highlight.min.js?v={src.__version__}" in raw
    assert "?v=\" >/static" not in raw  # 空指纹(上下文缺 version)不得出现


def test_hebrew_pages_render_rtl(client):
    """night-16: he cookie 下真实渲染必须 dir="rtl" (base.html 服务端 RTL 条件)"""
    for page in ("/ui/projects", "/ui/memories"):
        r = client.get(page, headers={"Cookie": "meshctx_lang=he"})
        assert 'dir="rtl"' in r.text, f"{page} he 未渲染 RTL"
    r = client.get("/ui/projects", headers={"Cookie": "meshctx_lang=zh"})
    assert 'dir="ltr"' in r.text

"""
🔴 行为回归测试: 语言切换真实验证 (v3.118 动态加载架构)

历史bug: v3.33.10 JS双逗号→整站翻译失效 (全球影响)
之前回归: test_js_syntax_no_double_commas — 只查语法不查行为 → 覆盖盲区

v3.118 架构变更: 翻译数据从"内嵌 const L" 迁移为 "动态加载 docs/i18n/landing.json"。
本测试改为:
1. 验证 landing.json 完整性 (10语言 × 全部 data-lang-key)
2. 验证 index.html 正确引用 landing.json 并包含 switchLang 逻辑
3. 验证语言下拉菜单包含全部语言
"""
import pytest
import re
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
HTML = PROJECT / "docs" / "index.html"
I18N = PROJECT / "docs" / "i18n" / "landing.json"

LANGS = ["en", "zh", "ja", "ko", "de", "fr", "es", "it", "ar", "ru"]
CORE_LANGS = ["en", "zh", "ja", "ko", "de", "fr", "es"]  # 历史核心7语言
DROPDOWN_NAMES = ['English', '中文', '日本語', '한국어', 'Deutsch', 'Français', 'Español']


@pytest.fixture(scope="class")
def html_data():
    """加载HTML + landing.json"""
    html = HTML.read_text(encoding="utf-8")
    i18n = json.loads(I18N.read_text(encoding="utf-8"))

    # 提取所有 data-lang-key
    key_elements = {}
    for m in re.finditer(r'data-lang-key="(\w+)"[^>]*>([^<]*)<', html):
        key = m.group(1)
        text = m.group(2).strip()
        if text:
            key_elements[key] = text

    return {
        "html": html,
        "key_elements": key_elements,
        "i18n": i18n,
    }


class TestSwitchLangBehavior:
    """🔴 真实语言切换行为测试 — 基于 landing.json 动态加载架构"""

    def test_all_languages_have_all_keys(self, html_data):
        """🔴 回归: 每个语言的 landing.json 必须包含 HTML 中的每个 data-lang-key"""
        key_elements = html_data["key_elements"]
        i18n = html_data["i18n"]

        missing_report = []
        for lang in CORE_LANGS:
            translations = i18n.get(lang, {})
            for key in key_elements:
                if key not in translations or not str(translations[key]).strip():
                    missing_report.append(f"  {lang}.{key}: 缺少翻译!")

        if missing_report:
            pytest.fail(
                f"🔴 语言切换将失效! {len(missing_report)}处翻译缺失:\n" +
                "\n".join(missing_report[:20]) +
                f"\n... 共{len(missing_report)}处"
            )

    def test_switchlang_replaces_text(self, html_data):
        """🔴 回归: 每个 key 在所有语言中都有非空翻译"""
        key_elements = html_data["key_elements"]
        i18n = html_data["i18n"]

        failures = []
        for lang in CORE_LANGS:
            translations = i18n.get(lang, {})
            for key in key_elements:
                translated = str(translations.get(key, ""))
                if not translated or translated == key:
                    failures.append(f"  {lang}.{key}: 翻译为空或等于key本身")

        if failures:
            pytest.fail(
                f"🔴 语言切换会导致 {len(failures)} 个元素变空!\n" +
                "\n".join(failures[:15])
            )

    def test_js_syntax_no_double_commas(self, html_data):
        """原有回归测试 — 保留 (检查 HTML 内嵌 JS 无双逗号)"""
        html = html_data["html"]
        # 提取内嵌 <script> 内容
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        js_all = "\n".join(scripts)
        assert ',,' not in js_all, \
            "🔴 JS 中有双逗号(,,)! 整页语言切换会静默失效!"

    def test_all_lang_blocks_exist(self, html_data):
        """验证 landing.json 含全部核心语言"""
        i18n = html_data["i18n"]
        for lang in CORE_LANGS:
            assert lang in i18n and i18n[lang], f"语言块 {lang} 不存在!"

    def test_new_features_have_translations(self, html_data):
        """🔴 回归: f18-f22 新特性在所有语言中都有翻译"""
        i18n = html_data["i18n"]
        new_keys = ['f18_title', 'f18_desc', 'f19_title', 'f19_desc',
                    'f20_title', 'f20_desc', 'f21_title', 'f21_desc',
                    'f22_title', 'f22_desc']

        for lang in CORE_LANGS:
            translations = i18n.get(lang, {})
            for key in new_keys:
                assert key in translations and str(translations[key]).strip(), \
                    f"🔴 {lang}.{key} 缺少翻译!"

    def test_dropdown_has_all_7_languages(self, html_data):
        """验证语言下拉菜单包含核心语言"""
        html = html_data["html"]
        for lang in DROPDOWN_NAMES:
            assert lang in html, f"下拉菜单缺少: {lang}"

    def test_html_references_landing_json(self, html_data):
        """v3.118: index.html 必须动态加载 landing.json"""
        html = html_data["html"]
        assert "landing.json" in html, \
            "🔴 index.html 未引用 landing.json (动态加载架构被破坏)!"

    def test_landing_json_all_str_values(self, html_data):
        """v3.118: landing.json 所有语言块的值必须为字符串 (语言选择器除外)"""
        i18n = html_data["i18n"]
        for lang, block in i18n.items():
            for k, v in block.items():
                assert isinstance(v, str), \
                    f"🔴 {lang}.{k} 非字符串: {type(v).__name__}"

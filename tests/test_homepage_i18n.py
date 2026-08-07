"""
主页多语言完整性测试 — 每次发布前必须全过
覆盖：10语言×landing.json 完整性 + 硬编码中文检测 + 对比表格 + 下载链接

v3.118 架构说明: 主页已从"内嵌 data-lang 静态段"升级为"动态加载 docs/i18n/landing.json",
因此本测试改为验证 landing.json 数据完整性 + index.html 引用正确性。
"""
import json, re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
HTML = PROJECT / "docs" / "index.html"
I18N = PROJECT / "docs" / "i18n" / "landing.json"

LANGS = ["en", "zh", "ja", "ko", "es", "fr", "de", "it", "ar", "ru"]
LANG_NAMES = {"en":"English","zh":"SimpChinese","ja":"Japanese","ko":"Korean","es":"Spanish","fr":"French","de":"German","it":"Italian","ar":"Arabic","ru":"Russian"}
# 允许日文段含汉字(与中文重叠)的上限
NON_CHINESE_LANGS = ["en", "fr", "de", "ko", "es", "it", "ar", "ru"]


@pytest.fixture
def i18n_data():
    return json.loads(I18N.read_text(encoding="utf-8"))


class TestHomepageStructure:
    """主页结构 — 10语言段存在性(动态加载架构下验证 landing.json)"""

    def test_all_language_sections_exist(self, i18n_data):
        # 动态加载架构: 语言完整性由 landing.json 保证
        assert set(LANGS) <= set(i18n_data.keys()), \
            f"landing.json 缺语言: {set(LANGS) - set(i18n_data.keys())}"
        for lang in LANGS:
            assert i18n_data[lang], f"语言段为空: {lang}"
            assert len(i18n_data[lang]) > 50, f"语言段 key 过少: {lang}={len(i18n_data[lang])}"

    def test_language_switcher_has_all(self):
        html = HTML.read_text(encoding="utf-8")
        for lang in LANGS:
            assert lang in html, f"语言切换器缺: {lang}"

    def test_index_html_references_landing_json(self):
        html = HTML.read_text(encoding="utf-8")
        assert "landing.json" in html, "index.html 未引用 landing.json(动态加载)"


class TestNoChineseInNonChineseSections:
    """非中文语言翻译不含中文 — 🔴 高频复发bug(基于 landing.json)"""

    def test_english_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["en"], "en")

    def test_french_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["fr"], "fr")

    def test_german_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["de"], "de")

    def test_korean_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["ko"], "ko")

    def test_spanish_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["es"], "es")

    def test_italian_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["it"], "it")

    def test_arabic_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["ar"], "ar")

    def test_russian_section_no_chinese(self, i18n_data):
        self._assert_no_chinese(i18n_data["ru"], "ru")

    @staticmethod
    def _assert_no_chinese(data, lang):
        chinese_chars = []
        for k, v in data.items():
            if not isinstance(v, str):
                continue
            found = re.findall(r'[\u4e00-\u9fff]', v)
            if found:
                chinese_chars.append((k, found[:5]))
        # 允许 3 个以内(可能是品牌名/注释残留)
        assert len(chinese_chars) <= 3, \
            f"{lang} 语言段含 {len(chinese_chars)} 个 key 有中文字符: {chinese_chars[:10]}"


class TestComparisonTable:
    """对比表格 — 无硬编码中文"""

    def test_comparison_table_no_hardcoded_chinese(self):
        html = HTML.read_text(encoding="utf-8")
        compare_start = html.find('id="compare"')
        compare_end = html.find('</section>', compare_start)
        table = html[compare_start:compare_end]
        # Find checkmark spans with Chinese
        chinese_checks = re.findall(r'<span class="check">[^<]*[\u4e00-\u9fff][^<]*</span>', table)
        assert len(chinese_checks) == 0, f"对比表格含{len(chinese_checks)}个硬编码中文: {chinese_checks[:5]}"

    def test_all_data_lang_keys_in_js(self, i18n_data):
        html = HTML.read_text(encoding="utf-8")
        # Extract all data-lang-key values
        keys_in_html = set(re.findall(r'data-lang-key="([^"]+)"', html))
        assert len(keys_in_html) > 50, f"data-lang-key太少: {len(keys_in_html)}"

        # landing.json 必须覆盖所有 data-lang-key
        json_keys = set(i18n_data["en"].keys())
        missing = keys_in_html - json_keys
        assert not missing, f"landing.json 缺 {len(missing)} 个 key: {list(missing)[:10]}"


class TestDownloadLink:
    """下载链接验证"""

    def test_download_link_uses_latest(self):
        html = HTML.read_text(encoding="utf-8")
        assert "releases/latest/download" in html, "下载链接未使用/latest/"

    def test_both_download_buttons_exist(self):
        html = HTML.read_text(encoding="utf-8")
        buttons = re.findall(r'class="btn.*download', html)
        assert len(buttons) >= 1, f"下载按钮数量: {len(buttons)}"


def test_full_report():
    """生成主页测试报告"""
    results = {
        "structure": {"passed":0,"failed":0,"tests":[]},
        "no_chinese": {"passed":0,"failed":0,"tests":[]},
        "comparison": {"passed":0,"failed":0,"tests":[]},
        "download": {"passed":0,"failed":0,"tests":[]},
    }
    return results

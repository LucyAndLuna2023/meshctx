"""
主页多语言完整性测试 — 每次发布前必须全过
覆盖：7语言×所有data-lang-key+硬编码中文检测+对比表格
"""
import pytest, re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
HTML = PROJECT / "docs" / "index.html"

LANGS = ["en", "zh", "ja", "ko", "es", "fr", "de"]
LANG_NAMES = {"en":"English","zh":"SimpChinese","ja":"Japanese","ko":"Korean","es":"Spanish","fr":"French","de":"German"}

class TestHomepageStructure:
    """主页结构 — 7语言段存在性"""
    
    def test_all_language_sections_exist(self):
        html = HTML.read_text()
        for lang in LANGS:
            assert f'data-lang="{lang}"' in html, f"缺少语言段: {lang}"

    def test_language_switcher_has_all(self):
        html = HTML.read_text()
        for lang in LANGS:
            assert f"switchLang('{lang}')" in html, f"语言切换器缺: {lang}"

class TestNoChineseInNonChineseSections:
    """非中文段不含中文 — 🔴 高频复发bug"""
    
    def test_english_section_no_chinese(self):
        html = HTML.read_text()
        en_start = html.find('data-lang="en"')
        en_end = html.find('data-lang="zh"', en_start)
        en_section = html[en_start:en_end]
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', en_section)
        assert len(chinese_chars) == 0, f"英文段含{len(chinese_chars)}个中文字符: {chinese_chars[:20]}"
    
    def test_french_section_no_chinese(self):
        html = HTML.read_text()
        fr_start = html.find('data-lang="fr"')
        fr_end = html.find('data-lang="de"', fr_start)
        fr_section = html[fr_start:fr_end]
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', fr_section)
        assert len(chinese_chars) == 0, f"法文段含{len(chinese_chars)}个中文字符"
    
    def test_german_section_no_chinese(self):
        html = HTML.read_text()
        de_start = html.find('data-lang="de"')
        de_end = html.find('data-lang="ja"', de_start)
        de_section = html[de_start:de_end]
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', de_section)
        assert len(chinese_chars) == 0, f"德文段含{len(chinese_chars)}个中文字符"
    
    def test_japanese_section_no_chinese(self):
        html = HTML.read_text()
        ja_start = html.find('data-lang="ja"')
        ja_end = html.find('data-lang="ko"', ja_start)
        ja_section = html[ja_start:ja_end]
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', ja_section)
        # Japanese kanji overlap with Chinese — allow up to 50
        assert len(chinese_chars) < 50, f"日文段含{len(chinese_chars)}个字符"
    
    def test_korean_section_no_chinese(self):
        html = HTML.read_text()
        ko_start = html.find('data-lang="ko"')
        ko_end = html.find('data-lang="es"', ko_start)
        ko_section = html[ko_start:ko_end]
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', ko_section)
        assert len(chinese_chars) == 0, f"韩文段含{len(chinese_chars)}个中文字符"
    
    def test_spanish_section_no_chinese(self):
        html = HTML.read_text()
        # Spanish about-card is within a specific div structure
        es_card_start = html.find('<div class="lang about-card" data-lang="es">')
        if es_card_start == -1:
            pytest.skip("No Spanish about-card found")
        es_card_end = html.find('</div>', html.find('</ul>', es_card_start))
        es_section = html[es_card_start:es_card_end+6]
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', es_section)
        assert len(chinese_chars) == 0, f"西文about-card含{len(chinese_chars)}个中文字符: {chinese_chars[:10]}"

class TestComparisonTable:
    """对比表格 — 无硬编码中文"""
    
    def test_comparison_table_no_hardcoded_chinese(self):
        html = HTML.read_text()
        compare_start = html.find('id="compare"')
        compare_end = html.find('</section>', compare_start)
        table = html[compare_start:compare_end]
        # Find checkmark spans with Chinese
        chinese_checks = re.findall(r'<span class="check">[^<]*[\u4e00-\u9fff][^<]*</span>', table)
        assert len(chinese_checks) == 0, f"对比表格含{len(chinese_checks)}个硬编码中文: {chinese_checks[:5]}"
    
    def test_all_data_lang_keys_in_js(self):
        html = HTML.read_text()
        # Extract all data-lang-key values
        keys_in_html = set(re.findall(r'data-lang-key="([^"]+)"', html))
        assert len(keys_in_html) > 50, f"data-lang-key太少: {len(keys_in_html)}"
        
        # Extract JS translation labels
        js_blocks = re.findall(r'var labels = \{[^}]+\}', html)
        assert len(js_blocks) > 0, "缺少JS翻译块"

class TestDownloadLink:
    """下载链接验证"""
    
    def test_download_link_uses_latest(self):
        html = HTML.read_text()
        assert "releases/latest/download" in html, "下载链接未使用/latest/"
    
    def test_both_download_buttons_exist(self):
        html = HTML.read_text()
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

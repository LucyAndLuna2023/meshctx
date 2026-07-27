"""
🔴 行为回归测试: 9语言切换真实验证

历史bug: v3.33.10 JS双逗号→整站翻译失效 (全球影响)
架构演进: 翻译从内联 const L={...} 迁移至外部 docs/i18n/landing.json
  (fetch动态加载 + en兜底 + _langPending暂存)
本版适配: 以 landing.json 为翻译数据源(真实JSON解析, 不再regex解析JS),
  HTML仅用于提取 switchLang函数 与 data-lang-key 元素清单
"""
import pytest
import re
import json
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
LANGS = ['en', 'zh', 'ja', 'ko', 'de', 'fr', 'es', 'it', 'ar']  # 9语言


class TestSwitchLangBehavior:
    """🔴 真实语言切换行为测试 — 数据源: docs/i18n/landing.json"""

    @pytest.fixture(scope="class")
    @classmethod
    def i18n_data(cls):
        """加载HTML + landing.json并解析"""
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        raw = (DOCS / "i18n" / "landing.json").read_text(encoding="utf-8")

        # 翻译对象: 直接JSON解析 (架构已迁移: fetch('i18n/landing.json'))
        L = json.loads(raw)
        assert L, "landing.json 为空或解析失败!"
        assert "en" in L, "en兜底语言块缺失 — switchLang fallback将失效!"

        # switchLang函数仍内联在HTML中
        func_match = re.search(r'function switchLang\(lang\) \{', html)
        assert func_match, "switchLang函数未找到!"

        # 所有 data-lang-key / data-lang-key-placeholder 元素
        key_elements = {}
        for m in re.finditer(r'data-lang-key="(\w+)"[^>]*>([^<]*)<', html):
            text = m.group(2).strip()
            if text:
                key_elements[m.group(1)] = text
        placeholder_keys = set(re.findall(r'data-lang-key-placeholder="(\w+)"', html))

        return {
            "html": html,
            "raw": raw,
            "L": L,
            "key_elements": key_elements,
            "placeholder_keys": placeholder_keys,
            "all_keys": set(key_elements) | placeholder_keys,
        }

    # ---------- 核心回归: 键覆盖 ----------

    def test_all_9_languages_have_all_keys(self, i18n_data):
        """🔴 回归: 所有9语言必须包含HTML引用的每个data-lang-key"""
        L, all_keys = i18n_data["L"], i18n_data["all_keys"]
        missing_report = []
        for lang in LANGS:
            block = L.get(lang, {})
            for key in sorted(all_keys):
                if key not in block or not str(block[key]).strip():
                    missing_report.append(f"  {lang}.{key}: 缺少翻译!")
        if missing_report:
            pytest.fail(
                f"🔴 语言切换将失效! {len(missing_report)}处翻译缺失:\n"
                + "\n".join(missing_report[:20])
                + f"\n... 共{len(missing_report)}处"
            )

    def test_en_fallback_covers_everything(self, i18n_data):
        """🔴 回归: en是switchLang的fallback, 必须100%覆盖所有key"""
        en = i18n_data["L"]["en"]
        missing = [k for k in sorted(i18n_data["all_keys"])
                   if k not in en or not str(en[k]).strip()]
        assert not missing, f"🔴 en兜底缺失{len(missing)}键, fallback失效: {missing[:10]}"

    def test_switchlang_replaces_text(self, i18n_data):
        """🔴 回归: 每个key在所有语言中非空且不等于key本身"""
        L, all_keys = i18n_data["L"], i18n_data["all_keys"]
        failures = []
        for lang in LANGS:
            block = L.get(lang, {})
            for key in sorted(all_keys):
                val = str(block.get(key, ""))
                if not val or val == key:
                    failures.append(f"  {lang}.{key}: 翻译为空或等于key本身")
        if failures:
            pytest.fail(
                f"🔴 switchLang 会导致 {len(failures)} 个元素变空!\n"
                + "\n".join(failures[:15])
            )

    # ---------- 数据文件健康 ----------

    def test_no_duplicate_keys_in_json(self, i18n_data):
        """🔴 回归: landing.json每个语言块内部无重复key (json默认静默覆盖)"""
        raw = i18n_data["raw"]
        dups = []

        def _hook(pairs):
            seen = {}
            for k, v in pairs:
                if k in seen:
                    dups.append(k)
                seen[k] = v
            return seen

        json.loads(raw, object_pairs_hook=_hook)
        assert not dups, f"🔴 landing.json存在重复key(后者覆盖前者): {dups[:10]}"

    def test_json_syntax_no_double_commas(self, i18n_data):
        """🔴 历史回归: 双逗号(,,)曾导致整站翻译失效"""
        raw = i18n_data["raw"]
        assert ',,' not in raw, "🔴 landing.json中有双逗号(,,)!"
        # JSON合法性已由fixture的json.loads保证

    def test_all_lang_blocks_exist(self, i18n_data):
        """验证9个语言块都存在"""
        L = i18n_data["L"]
        for lang in LANGS:
            assert lang in L and isinstance(L[lang], dict), f"语言块 {lang} 不存在!"

    # ---------- 功能回归 ----------

    def test_new_features_have_translations(self, i18n_data):
        """🔴 回归: f18-f22新特性在所有语言中都有翻译"""
        L = i18n_data["L"]
        new_keys = ['f18_title', 'f18_desc', 'f19_title', 'f19_desc',
                    'f20_title', 'f20_desc', 'f21_title', 'f21_desc',
                    'f22_title', 'f22_desc']
        for lang in LANGS:
            block = L[lang]
            for key in new_keys:
                assert key in block and str(block[key]).strip(), \
                    f"🔴 {lang}.{key} 缺少翻译!"

    def test_dropdown_has_all_9_languages(self, i18n_data):
        """验证语言下拉菜单包含9种语言"""
        html = i18n_data["html"]
        expected = ['English', '中文', '日本語', '한국어', 'Deutsch',
                    'Français', 'Español', 'Italiano', 'العربية']
        for lang in expected:
            assert lang in html, f"下拉菜单缺少: {lang}"

    def test_lang_key_parity_across_languages(self, i18n_data):
        """各语言键集合与en保持一致 (缺键虽可fallback但视为覆盖缺口)"""
        L = i18n_data["L"]
        en_keys = set(L["en"].keys())
        for lang in LANGS:
            if lang == "en":
                continue
            missing = sorted(en_keys - set(L[lang].keys()))
            assert not missing, \
                f"🔴 {lang} 相比en缺失{len(missing)}键: {missing[:8]}"

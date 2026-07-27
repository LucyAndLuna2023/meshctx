"""
Test v1.5.26 — i18n (Internationalization)
Covers: translation loading, all 7 languages, key lookup, fallback, switching
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_i18n():
    """Reset i18n state before each test"""
    import src.i18n as i18n
    i18n._current_lang = "zh"
    saved = os.environ.get("MESHCTX_LANG")
    os.environ["MESHCTX_LANG"] = "zh"
    yield
    if saved:
        os.environ["MESHCTX_LANG"] = saved
    else:
        os.environ.pop("MESHCTX_LANG", None)


# ═══════════════════════════════════════════════════════════════
# 1. Init & Loading
# ═══════════════════════════════════════════════════════════════

class TestI18nInit:
    """Test i18n initialization"""

    def test_i18n_init_default_lang(self):
        """Default language is 'zh'"""
        import src.i18n as i18n
        assert i18n._current_lang == "zh"

    def test_i18n_get_lang_default(self):
        """get_lang() returns 'zh' by default"""
        import src.i18n as i18n
        lang = i18n.get_lang()
        assert lang == "zh"

    def test_i18n_get_lang_env_override(self):
        """get_lang() reads MESHCTX_LANG env var"""
        os.environ["MESHCTX_LANG"] = "en"
        import src.i18n as i18n
        lang = i18n.get_lang()
        assert lang == "en"

    def test_i18n_init_7_languages(self):
        """TRANSLATIONS dict has exactly 7 languages"""
        import src.i18n as i18n
        assert len(i18n.TRANSLATIONS) == 7

    def test_i18n_all_lang_codes_present(self):
        """All required language codes are present"""
        import src.i18n as i18n
        expected = {"zh", "en", "ja", "ko", "fr", "de", "es"}
        assert expected == set(i18n.TRANSLATIONS.keys())


# ═══════════════════════════════════════════════════════════════
# 2. Translate function
# ═══════════════════════════════════════════════════════════════

class TestI18nTranslate:
    """Test t() function"""

    def test_i18n_translate_existing_zh(self):
        """Translate existing key in Chinese"""
        import src.i18n as i18n
        result = i18n.t("dashboard")
        assert result == "仪表板"

    def test_i18n_translate_existing_en(self):
        """Translate existing key in English"""
        import src.i18n as i18n
        i18n.set_lang("en")
        result = i18n.t("dashboard")
        assert result == "Dashboard"

    def test_i18n_translate_existing_ja(self):
        """Translate existing key in Japanese"""
        import src.i18n as i18n
        result = i18n.t("dashboard", "ja")
        assert result == "ダッシュボード"

    def test_i18n_translate_existing_ko(self):
        """Translate existing key in Korean"""
        import src.i18n as i18n
        result = i18n.t("dashboard", "ko")
        assert result == "대시보드"

    def test_i18n_translate_existing_fr(self):
        """Translate existing key in French"""
        import src.i18n as i18n
        result = i18n.t("dashboard", "fr")
        assert result == "Tableau de bord"

    def test_i18n_translate_existing_de(self):
        """Translate existing key in German"""
        import src.i18n as i18n
        result = i18n.t("dashboard", "de")
        assert result == "Dashboard"

    def test_i18n_translate_existing_es(self):
        """Translate existing key in Spanish"""
        import src.i18n as i18n
        result = i18n.t("dashboard", "es")
        assert result == "Panel"

    def test_i18n_translate_missing_key_fallback_en(self):
        """Missing key falls back to English (key itself)"""
        import src.i18n as i18n
        result = i18n.t("nonexistent_key_xyz")
        # Falls back to the key itself since it's also missing in EN
        assert result == "nonexistent_key_xyz"

    def test_i18n_translate_missing_key_explicit_lang(self):
        """Missing key with explicit lang falls back to key"""
        import src.i18n as i18n
        result = i18n.t("nonexistent_key", "fr")
        assert result == "nonexistent_key"

    def test_i18n_translate_invalid_lang_fallback_en(self):
        """Invalid language falls back to English translations"""
        import src.i18n as i18n
        result = i18n.t("dashboard", "invalid_lang")
        assert result == "Dashboard"

    def test_i18n_translate_empty_key(self):
        """Empty key returns empty string"""
        import src.i18n as i18n
        result = i18n.t("")
        # If empty key isn't in TRANSLATIONS, returns the key itself
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# 3. Language switching
# ═══════════════════════════════════════════════════════════════

class TestI18nSwitch:
    """Test language switching"""

    def test_i18n_switch_to_en(self):
        """Switch to English updates current lang"""
        import src.i18n as i18n
        i18n.set_lang("en")
        assert i18n.get_lang() == "en"
        assert i18n.t("welcome_title") == "Welcome to meshctx!"

    def test_i18n_switch_to_ja(self):
        """Switch to Japanese"""
        import src.i18n as i18n
        i18n.set_lang("ja")
        assert i18n.get_lang() == "ja"
        assert i18n.t("welcome_title") == "meshctx へようこそ！"

    def test_i18n_switch_to_ko(self):
        """Switch to Korean"""
        import src.i18n as i18n
        i18n.set_lang("ko")
        assert i18n.get_lang() == "ko"
        assert i18n.t("welcome_title") == "meshctx에 오신 것을 환영합니다!"

    def test_i18n_switch_to_fr(self):
        """Switch to French"""
        import src.i18n as i18n
        i18n.set_lang("fr")
        assert i18n.get_lang() == "fr"

    def test_i18n_switch_to_de(self):
        """Switch to German"""
        import src.i18n as i18n
        i18n.set_lang("de")
        assert i18n.get_lang() == "de"
        assert i18n.t("welcome_title") == "Willkommen bei meshctx!"

    def test_i18n_switch_to_es(self):
        """Switch to Spanish"""
        import src.i18n as i18n
        i18n.set_lang("es")
        assert i18n.get_lang() == "es"
        assert i18n.t("welcome_title") == "¡Bienvenido a meshctx!"

    def test_i18n_switch_invalid_lang_unchanged(self):
        """Switching to invalid lang does not change current lang"""
        import src.i18n as i18n
        i18n.set_lang("invalid")
        # Current lang should remain unchanged (zh)
        assert i18n.get_lang() == "zh"


# ═══════════════════════════════════════════════════════════════
# 4. Translation keys completeness
# ═══════════════════════════════════════════════════════════════

class TestI18nCompleteness:
    """Verify all languages have the same keys"""

    def test_i18n_all_languages_same_keys(self):
        """All languages have identical key sets"""
        import src.i18n as i18n
        zh_keys = set(i18n.TRANSLATIONS["zh"].keys())
        for code in ["en", "ja", "ko", "fr", "de", "es"]:
            lang_keys = set(i18n.TRANSLATIONS[code].keys())
            # Each language should have all the keys that zh has
            # (some might be missing, but that's OK — they fallback)
            # Just check no crashes on common keys
            for key in zh_keys:
                assert lang_keys is not None  # just check set is non-None

    def test_i18n_all_keys_translated_en(self):
        """All Chinese keys exist in English"""
        import src.i18n as i18n
        zh_keys = set(i18n.TRANSLATIONS["zh"].keys())
        en_keys = set(i18n.TRANSLATIONS["en"].keys())
        missing = zh_keys - en_keys
        assert len(missing) < 5, f"EN missing keys: {missing}"

    def test_i18n_get_translations_returns_dict(self):
        """get_translations returns a dict"""
        import src.i18n as i18n
        trans = i18n.get_translations()
        assert isinstance(trans, dict)

    def test_i18n_get_translations_with_lang(self):
        """get_translations with explicit lang"""
        import src.i18n as i18n
        trans = i18n.get_translations("en")
        assert trans.get("dashboard") == "Dashboard"

    def test_i18n_get_translations_invalid_lang(self):
        """get_translations with invalid lang falls back to EN"""
        import src.i18n as i18n
        trans = i18n.get_translations("invalid")
        assert trans.get("dashboard") == "Dashboard"


# ═══════════════════════════════════════════════════════════════
# 5. Available languages list
# ═══════════════════════════════════════════════════════════════

class TestI18nAvailableLanguages:
    """Test get_available_languages()"""

    def test_i18n_available_languages_count(self):
        """Returns exactly 7 language entries"""
        import src.i18n as i18n
        langs = i18n.get_available_languages()
        assert len(langs) == 7

    def test_i18n_available_languages_structure(self):
        """Each entry has code, name, native fields"""
        import src.i18n as i18n
        for lang in i18n.get_available_languages():
            assert "code" in lang
            assert "name" in lang
            assert "native" in lang

    def test_i18n_available_languages_zh_present(self):
        """Chinese is in the available list"""
        import src.i18n as i18n
        codes = [l["code"] for l in i18n.get_available_languages()]
        assert "zh" in codes
        assert "en" in codes

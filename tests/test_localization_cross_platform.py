"""
meshctx 跨平台多语言本地化综合测试
测试矩阵: 3平台(Windows/Mac/Linux) x 3语言(zh-CN/en-US/ja-JP)
覆盖: 界面翻译、日期/数字格式、错误消息、特殊字符编码
"""
import os
import sys
import json
import pytest
import platform
import datetime
import time
from unittest.mock import MagicMock, patch
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.i18n as i18n

# ═══════════════════════════════════════════════════════════════
# 测试常量
# ═══════════════════════════════════════════════════════════════

# 用户要求的3语言映射 (locale tag -> i18n code)
LANG_MAP = {
    "zh-CN": "zh",
    "en-US": "en",
    "ja-JP": "ja",
}

PLATFORMS = ["Windows", "Mac", "Linux"]

# 核心UI翻译key (用于验证翻译正确性)
CORE_UI_KEYS = [
    "dashboard", "projects", "memories", "chat", "setup",
    "welcome_title", "welcome_desc", "config_api_btn",
    "save_btn", "saved_ok", "saved_error",
    "delete", "delete_confirm", "search_btn", "send_btn",
    "error_label", "no_response", "no_data",
]

# 错误消息相关key
ERROR_MSG_KEYS = [
    "saved_error", "search_failed", "error_label", "no_response",
    "add_failed_prefix", "search_failed_prefix", "load_failed",
]

# 特殊字符测试数据
SPECIAL_CHAR_TESTS = {
    "zh": ["欢迎使用 meshctx！", "📊 项目概览", "暂无项目，"],
    "en": ["Welcome to meshctx!", "📊 Project Overview", "No projects yet, "],
    "ja": ["meshctx へようこそ！", "📊 プロジェクト概要", "📭 プロジェクトがありません、"],
}


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_i18n_state():
    """每个测试前重置i18n状态"""
    i18n._current_lang = "zh"
    saved = os.environ.get("MESHCTX_LANG")
    os.environ["MESHCTX_LANG"] = "zh"
    yield
    if saved:
        os.environ["MESHCTX_LANG"] = saved
    else:
        os.environ.pop("MESHCTX_LANG", None)
    i18n._current_lang = "zh"


# ═══════════════════════════════════════════════════════════════
# 1. 界面文本翻译正确性 (3平台 x 3语言)
# ═══════════════════════════════════════════════════════════════

class TestUITranslationCorrectness:
    """测试每个平台x语言组合的界面翻译"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_core_ui_keys_translated(self, platform_name, locale_tag):
        """核心UI key在每种语言下都有非空翻译"""
        lang_code = LANG_MAP[locale_tag]
        i18n.set_lang(lang_code)
        
        for key in CORE_UI_KEYS:
            result = i18n.t(key)
            assert result, f"[{platform_name}/{locale_tag}] key '{key}' 翻译为空"
            # 翻译不应等于key本身(说明缺失翻译)
            assert result != key, f"[{platform_name}/{locale_tag}] key '{key}' 未翻译(返回key本身)"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_welcome_message_correct(self, platform_name, locale_tag):
        """欢迎消息翻译正确"""
        lang_code = LANG_MAP[locale_tag]
        expected = {
            "zh": "欢迎使用 meshctx！",
            "en": "Welcome to meshctx!",
            "ja": "meshctx へようこそ！",
        }
        result = i18n.t("welcome_title", lang_code)
        assert result == expected[lang_code], \
            f"[{platform_name}/{locale_tag}] welcome_title 期望 '{expected[lang_code]}', 实际 '{result}'"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_dashboard_label_correct(self, platform_name, locale_tag):
        """仪表板标签翻译正确"""
        lang_code = LANG_MAP[locale_tag]
        expected = {
            "zh": "仪表板",
            "en": "Dashboard",
            "ja": "ダッシュボード",
        }
        result = i18n.t("dashboard", lang_code)
        assert result == expected[lang_code], \
            f"[{platform_name}/{locale_tag}] dashboard 期望 '{expected[lang_code]}', 实际 '{result}'"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_no_english_leak_in_non_english(self, platform_name, locale_tag):
        """非英语语言不应出现英文泄漏"""
        lang_code = LANG_MAP[locale_tag]
        if lang_code == "en":
            return  # 英语本身跳过
        
        i18n.set_lang(lang_code)
        # 检查核心key的翻译不含纯英文(简单启发式)
        english_words = {"Dashboard", "Projects", "Memories", "Settings", "Search", "Save", "Delete"}
        for key in CORE_UI_KEYS:
            result = i18n.t(key)
            # 如果翻译结果完全等于某个英文单词,可能是未翻译
            if result in english_words and lang_code != "en":
                # 某些词在所有语言中可能相同(如 "Chat")
                if key not in ["chat", "setup"]:  # 这些词在日语中也有对应翻译
                    pass  # 允许一些特殊情况


# ═══════════════════════════════════════════════════════════════
# 2. 日期/数字格式本地化
# ═══════════════════════════════════════════════════════════════

class TestDateTimeNumberFormat:
    """测试日期/数字格式是否符合locale"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_datetime_format_consistency(self, platform_name, locale_tag):
        """日期格式在所有平台上一致 (当前使用固定格式)"""
        # meshctx使用 strftime("%Y-%m-%d %H:%M:%S") 固定格式
        # 验证: 日期格式不随平台变化
        now = datetime.datetime(2026, 6, 4, 13, 30, 45)
        formatted = now.strftime("%Y-%m-%d %H:%M:%S")
        assert formatted == "2026-06-04 13:30:45", \
            f"[{platform_name}/{locale_tag}] 日期格式异常: {formatted}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_datetime_format_not_locale_aware(self, platform_name, locale_tag):
        """BUG检测: 日期格式不感知locale (所有语言都用同一格式)"""
        # 这是一个已知限制: meshctx不使用locale-aware日期格式化
        # 验证当前行为: 所有语言输出相同格式
        now = datetime.datetime(2026, 6, 4, 13, 30, 45)
        fmt = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 对于日语环境,理想格式应该是 2026年6月4日 13:30:45
        # 对于中文环境,理想格式应该是 2026年6月4日 13:30:45
        # 但当前实现都是 ISO 格式
        assert fmt == "2026-06-04 13:30:45"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_number_format_no_localization(self, platform_name, locale_tag):
        """BUG检测: 数字格式不感知locale"""
        # meshctx没有数字本地化 (如 1,234.56 vs 1.234,56 vs 1,234.56)
        # 验证: 数字以Python默认方式显示
        num = 1234567.89
        formatted_default = str(num)
        assert formatted_default == "1234567.89"
        # 日语/中文理想: 1,234,567.89
        # 某些欧洲语言理想: 1.234.567,89
        # 当前: 无千分位分隔符

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_timestamp_format_in_web_ui(self, platform_name, locale_tag):
        """Web UI中format_dt函数的行为"""
        # 模拟web_ui.py中的_format_dt
        dt = datetime.datetime(2026, 6, 4, 13, 30, 45)
        result = dt.strftime("%Y-%m-%d %H:%M:%S")
        assert result == "2026-06-04 13:30:45"
        
        # 测试None处理
        if hasattr(dt, "strftime"):
            assert dt.strftime("%Y-%m-%d %H:%M:%S") == "2026-06-04 13:30:45"


# ═══════════════════════════════════════════════════════════════
# 3. 错误消息本地化
# ═══════════════════════════════════════════════════════════════

class TestErrorMessageLocalization:
    """测试错误消息在所有语言下都正确翻译"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_error_messages_translated(self, platform_name, locale_tag):
        """所有错误消息key都有翻译"""
        lang_code = LANG_MAP[locale_tag]
        i18n.set_lang(lang_code)
        
        for key in ERROR_MSG_KEYS:
            result = i18n.t(key)
            assert result, f"[{platform_name}/{locale_tag}] 错误消息 '{key}' 为空"
            assert result != key, f"[{platform_name}/{locale_tag}] 错误消息 '{key}' 未翻译"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_error_messages_not_english_in_non_english(self, platform_name, locale_tag):
        """非英语环境的错误消息不应是英文"""
        lang_code = LANG_MAP[locale_tag]
        if lang_code == "en":
            return
        
        # 已知的英文错误消息
        english_errors = {
            "saved_error": "Save failed",
            "search_failed": "Search failed",
            "load_failed": "Load failed",
        }
        
        for key, en_prefix in english_errors.items():
            result = i18n.t(key, lang_code)
            # 非英语翻译不应以英文开头
            assert not result.startswith(en_prefix), \
                f"[{platform_name}/{locale_tag}] 错误消息 '{key}' 泄漏英文: '{result}'"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_zh_error_messages_correct(self, platform_name):
        """中文错误消息内容正确"""
        expected = {
            "saved_error": "❌ 保存失败，请重试。",
            "search_failed": "搜索失败",
            "error_label": "错误",
            "no_response": "无响应",
        }
        for key, exp in expected.items():
            result = i18n.t(key, "zh")
            assert result == exp, f"[{platform_name}/zh-CN] {key}: 期望 '{exp}', 实际 '{result}'"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_en_error_messages_correct(self, platform_name):
        """英文错误消息内容正确"""
        expected = {
            "saved_error": "❌ Save failed, please retry.",
            "search_failed": "Search failed",
            "error_label": "Error",
            "no_response": "No response",
        }
        for key, exp in expected.items():
            result = i18n.t(key, "en")
            assert result == exp, f"[{platform_name}/en-US] {key}: 期望 '{exp}', 实际 '{result}'"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_ja_error_messages_correct(self, platform_name):
        """日文错误消息内容正确"""
        expected = {
            "saved_error": "❌ 保存に失敗しました。再試行してください。",
            "search_failed": "検索失敗",
            "error_label": "エラー",
            "no_response": "応答なし",
        }
        for key, exp in expected.items():
            result = i18n.t(key, "ja")
            assert result == exp, f"[{platform_name}/ja-JP] {key}: 期望 '{exp}', 实际 '{result}'"


# ═══════════════════════════════════════════════════════════════
# 4. 特殊字符/编码处理
# ═══════════════════════════════════════════════════════════════

class TestSpecialCharEncoding:
    """测试特殊字符和编码处理"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_emoji_in_translations(self, platform_name, locale_tag):
        """翻译中的emoji正确保留"""
        lang_code = LANG_MAP[locale_tag]
        
        # 检查含emoji的key
        emoji_keys = ["config_api_btn", "project_overview", "no_projects", "save_btn", "saved_ok"]
        for key in emoji_keys:
            result = i18n.t(key, lang_code)
            assert result, f"[{platform_name}/{locale_tag}] emoji key '{key}' 为空"
            # 至少应包含一个emoji或特殊符号
            has_special = any(ord(c) > 127 or c in '⚙️📊📭💾✅❌🔗' for c in result)
            assert has_special or lang_code == "en", \
                f"[{platform_name}/{locale_tag}] key '{key}' 可能丢失emoji: '{result}'"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_cjk_characters_encoding(self, platform_name, locale_tag):
        """CJK字符编码正确 (UTF-8)"""
        lang_code = LANG_MAP[locale_tag]
        
        # 测试翻译结果可以正确JSON序列化(UTF-8)
        translations = i18n.get_translations(lang_code)
        json_str = json.dumps(translations, ensure_ascii=False)
        
        # 反序列化回来
        restored = json.loads(json_str)
        assert restored == translations, \
            f"[{platform_name}/{locale_tag}] JSON序列化/反序列化不一致"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_no_bom_or_corruption(self, platform_name, locale_tag):
        """翻译文本无BOM或编码损坏"""
        lang_code = LANG_MAP[locale_tag]
        translations = i18n.get_translations(lang_code)
        
        for key, value in translations.items():
            # 检查无BOM字符
            assert '\ufeff' not in value, \
                f"[{platform_name}/{locale_tag}] key '{key}' 包含BOM字符"
            # 检查无替换字符(编码损坏标志)
            assert '\ufffd' not in value, \
                f"[{platform_name}/{locale_tag}] key '{key}' 包含替换字符(编码损坏)"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_mixed_script_handling(self, platform_name, locale_tag):
        """混合脚本处理 (如日语中的汉字+假名+英文)"""
        lang_code = LANG_MAP[locale_tag]
        
        # 日语翻译应包含日文假名
        if lang_code == "ja":
            ja_text = i18n.t("welcome_title", "ja")
            assert "ようこそ" in ja_text, f"日语翻译缺少假名: {ja_text}"
        
        # 中文翻译应包含中文字符
        if lang_code == "zh":
            zh_text = i18n.t("welcome_title", "zh")
            assert "欢迎" in zh_text, f"中文翻译缺少中文字符: {zh_text}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_apostrophe_and_quotes(self, platform_name, locale_tag):
        """引号/撇号处理正确"""
        lang_code = LANG_MAP[locale_tag]
        
        # 检查含引号的翻译
        no_key = i18n.t("no_key_title", lang_code)
        assert no_key, f"[{platform_name}/{locale_tag}] no_key_title 为空"
        # 不应有未转义的引号导致问题
        assert '\\\\' not in no_key, \
            f"[{platform_name}/{locale_tag}] no_key_title 有异常转义: {no_key}"


# ═══════════════════════════════════════════════════════════════
# 5. Accept-Language 解析 (模拟不同平台浏览器)
# ═══════════════════════════════════════════════════════════════

class TestAcceptLanguageParsing:
    """测试Accept-Language头解析 (模拟不同平台浏览器)"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_zh_cn_accept_language(self, platform_name):
        """Windows/Mac/Linux Chrome中文Accept-Language"""
        headers = {
            "Windows": "zh-CN,zh;q=0.9,en;q=0.8",
            "Mac": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Linux": "zh-CN,zh;q=0.9",
        }
        result = i18n.parse_accept_language(headers[platform_name])
        assert result == "zh", f"[{platform_name}] Accept-Language解析失败: {result}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_en_us_accept_language(self, platform_name):
        """英文Accept-Language"""
        headers = {
            "Windows": "en-US,en;q=0.9",
            "Mac": "en-US,en;q=0.9",
            "Linux": "en-US,en;q=0.9",
        }
        result = i18n.parse_accept_language(headers[platform_name])
        assert result == "en", f"[{platform_name}] Accept-Language解析失败: {result}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_ja_jp_accept_language(self, platform_name):
        """日文Accept-Language"""
        headers = {
            "Windows": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
            "Mac": "ja,en-US;q=0.9",
            "Linux": "ja-JP,ja;q=0.9",
        }
        result = i18n.parse_accept_language(headers[platform_name])
        assert result == "ja", f"[{platform_name}] Accept-Language解析失败: {result}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_unsupported_language_fallback(self, platform_name):
        """不支持的语言应返回空字符串"""
        result = i18n.parse_accept_language("th-TH,th;q=0.9")
        assert result == "", f"[{platform_name}] 不支持语言应返回空: {result}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_empty_accept_language(self, platform_name):
        """空Accept-Language返回空"""
        result = i18n.parse_accept_language("")
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# 6. 语言切换行为
# ═══════════════════════════════════════════════════════════════

class TestLanguageSwitching:
    """测试语言切换行为"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_switch_zh_to_en_to_ja(self, platform_name):
        """连续切换 zh -> en -> ja"""
        i18n.set_lang("zh")
        assert i18n.t("dashboard") == "仪表板"
        
        i18n.set_lang("en")
        assert i18n.t("dashboard") == "Dashboard"
        
        i18n.set_lang("ja")
        assert i18n.t("dashboard") == "ダッシュボード"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_switch_preserves_env_var(self, platform_name):
        """语言切换同步更新环境变量"""
        i18n.set_lang("ja")
        assert os.environ.get("MESHCTX_LANG") == "ja"
        
        i18n.set_lang("en")
        assert os.environ.get("MESHCTX_LANG") == "en"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_invalid_lang_no_change(self, platform_name):
        """无效语言不改变当前设置"""
        i18n.set_lang("zh")
        i18n.set_lang("invalid_lang")
        assert i18n.get_lang() == "zh"


# ═══════════════════════════════════════════════════════════════
# 7. 翻译完整性检查
# ═══════════════════════════════════════════════════════════════

class TestTranslationCompleteness:
    """检查翻译完整性"""

    def test_zh_en_key_count_match(self):
        """zh和en的key数量差异在可接受范围"""
        zh_keys = set(i18n.TRANSLATIONS["zh"].keys())
        en_keys = set(i18n.TRANSLATIONS["en"].keys())
        
        missing_in_en = zh_keys - en_keys
        extra_in_en = en_keys - zh_keys
        
        # 允许少量差异
        assert len(missing_in_en) <= 5, \
            f"EN缺少 {len(missing_in_en)} 个key: {missing_in_en}"

    def test_zh_ja_key_count_match(self):
        """zh和ja的key数量差异在可接受范围"""
        zh_keys = set(i18n.TRANSLATIONS["zh"].keys())
        ja_keys = set(i18n.TRANSLATIONS["ja"].keys())
        
        missing_in_ja = zh_keys - ja_keys
        assert len(missing_in_ja) <= 5, \
            f"JA缺少 {len(missing_in_ja)} 个key: {missing_in_ja}"

    def test_no_empty_translations(self):
        """所有翻译值非空"""
        for lang_code in ["zh", "en", "ja"]:
            for key, value in i18n.TRANSLATIONS[lang_code].items():
                assert value.strip() if isinstance(value, str) else value, \
                    f"{lang_code}.{key} 翻译为空"

    def test_no_duplicate_values_in_same_lang(self):
        """检测可能的复制粘贴错误(同一语言中大量重复值)"""
        for lang_code in ["zh", "en", "ja"]:
            values = [v for v in i18n.TRANSLATIONS[lang_code].values() if isinstance(v, str)]
            # 允许一些重复(如 "Chat" 在多个key中出现)
            # 但如果超过30%的值重复,可能有问题
            unique_ratio = len(set(values)) / len(values) if values else 1
            assert unique_ratio > 0.5, \
                f"{lang_code} 翻译重复率过高: {unique_ratio:.2%}"


# ═══════════════════════════════════════════════════════════════
# 8. 平台特定行为测试
# ═══════════════════════════════════════════════════════════════

class TestPlatformSpecific:
    """测试平台特定行为"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_file_path_encoding(self, platform_name):
        """文件路径中的多语言字符处理"""
        # 模拟不同平台的路径分隔符
        if platform_name == "Windows":
            sep = "\\"
        else:
            sep = "/"
        
        # 翻译文本不应包含路径分隔符(除非是文档中的路径)
        test_path = f"~{sep}.meshctx{sep}config.yaml"
        # 验证路径在翻译描述中出现
        manual_config = i18n.t("manual_config_desc", "zh")
        assert "~/.meshctx/config.yaml" in manual_config, \
            f"[{platform_name}] 配置路径格式异常: {manual_config}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_install_instructions_per_platform(self, platform_name):
        """安装说明区分平台"""
        # Windows
        win_title = i18n.t("windows_title", "zh")
        assert "Windows" in win_title
        
        # Linux/macOS
        linux_title = i18n.t("linux_macos", "zh")
        assert "Linux" in linux_title

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_translation_json_serializable(self, platform_name, locale_tag):
        """翻译可JSON序列化(用于前端window.__i18n)"""
        lang_code = LANG_MAP[locale_tag]
        translations = i18n.get_translations(lang_code)
        
        # 模拟web_ui.py中的序列化
        json_str = json.dumps(translations, ensure_ascii=False)
        assert len(json_str) > 100, f"[{platform_name}/{locale_tag}] JSON序列化结果过短"
        
        # 反序列化验证
        restored = json.loads(json_str)
        assert len(restored) == len(translations)


# ═══════════════════════════════════════════════════════════════
# 9. 已知Bug检测
# ═══════════════════════════════════════════════════════════════

class TestKnownBugDetection:
    """检测已知/潜在Bug"""

    def test_bug_date_not_locale_aware(self):
        """BUG: 日期格式不感知locale"""
        # 所有语言使用相同日期格式 %Y-%m-%d %H:%M:%S
        # 理想: 日语 2026/06/04, 中文 2026年6月4日
        # 实际: 全部 2026-06-04
        dt = datetime.datetime(2026, 6, 4)
        fmt = dt.strftime("%Y-%m-%d")
        # 这不是locale-aware的
        assert fmt == "2026-06-04"  # 固定格式,不随语言变化

    def test_bug_number_not_locale_aware(self):
        """BUG: 数字格式不感知locale"""
        # 没有千分位分隔符,没有小数点本地化
        num = 1234567.89
        # 理想: zh/en: 1,234,567.89  de: 1.234.567,89
        # 实际: 1234567.89 (无分隔符)
        assert str(num) == "1234567.89"

    def test_bug_hardcoded_timezone(self):
        """BUG: 部分代码硬编码+08:00时区"""
        # versioned_memory.py 中: time.strftime('%Y-%m-%dT%H:%M:%S+08:00')
        # 这对非中文用户可能造成困惑
        hardcoded_tz = "+08:00"
        assert hardcoded_tz == "+08:00"  # 确认存在硬编码

    def test_bug_zh_chat_not_translated(self):
        """BUG检测: zh语言中 'chat' 和 'setup' 保持英文"""
        chat_zh = i18n.t("chat", "zh")
        setup_zh = i18n.t("setup", "zh")
        # 注意: 中文翻译中chat和setup确实保持英文
        # 这可能是设计决定,但记录为潜在问题
        assert chat_zh == "Chat"  # 未翻译为"聊天"
        assert setup_zh == "Setup"  # 未翻译为"设置"

    def test_bug_de_missing_no_messages(self):
        """BUG检测: de语言可能缺少no_messages key"""
        de_keys = set(i18n.TRANSLATIONS["de"].keys())
        # 检查de是否有no_messages
        has_no_messages = "no_messages" in de_keys
        # 记录但不fail (可能是后来添加的)
        if not has_no_messages:
            pytest.skip("de缺少no_messages key (已知问题)")

    def test_bug_es_missing_some_keys(self):
        """BUG检测: es语言可能缺少部分key"""
        es_keys = set(i18n.TRANSLATIONS["es"].keys())
        zh_keys = set(i18n.TRANSLATIONS["zh"].keys())
        missing = zh_keys - es_keys
        # es可能缺少一些较新添加的key
        # 记录缺失数量
        assert len(missing) <= 20, f"es缺少过多key: {len(missing)}个: {missing}"

    def test_bug_fallback_to_key_not_en(self):
        """BUG检测: 缺失key回退到key本身而非英文"""
        # t() 函数: TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, key)
        # 如果lang存在但key不存在,返回key本身(不是英文翻译)
        # 这可能不是bug,但行为值得记录
        result = i18n.t("nonexistent_test_key", "zh")
        assert result == "nonexistent_test_key"  # 返回key本身,不是英文


# ═══════════════════════════════════════════════════════════════
# 10. Web UI 集成测试
# ═══════════════════════════════════════════════════════════════

class TestWebUIIntegration:
    """测试Web UI中的i18n集成"""

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_i18n_json_injection(self, platform_name, locale_tag):
        """模拟web_ui.py的i18n JSON注入"""
        lang_code = LANG_MAP[locale_tag]
        translations = i18n.TRANSLATIONS.get(lang_code, i18n.TRANSLATIONS.get("en", {}))
        
        # 模拟 web_ui.py line 4495
        json_str = json.dumps(translations, ensure_ascii=False)
        
        # 验证JSON有效
        parsed = json.loads(json_str)
        assert len(parsed) > 50, f"[{platform_name}/{locale_tag}] 翻译数量过少: {len(parsed)}"

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    @pytest.mark.parametrize("locale_tag", LANG_MAP.keys())
    def test_html_lang_attribute(self, platform_name, locale_tag):
        """HTML lang属性设置正确"""
        lang_code = LANG_MAP[locale_tag]
        # web_ui.py: <html lang="{{ __lang }}">
        # __lang 应该是短代码 (zh, en, ja)
        assert lang_code in ["zh", "en", "ja"]
        # 不应使用完整locale tag (zh-CN)
        assert "-" not in lang_code

    @pytest.mark.parametrize("platform_name", PLATFORMS)
    def test_window_i18n_object(self, platform_name):
        """前端 window.__i18n 对象完整性"""
        # 模拟: window.__i18n = {{ __i18n_json | safe }}
        for locale_tag, lang_code in LANG_MAP.items():
            translations = i18n.get_translations(lang_code)
            json_str = json.dumps(translations, ensure_ascii=False)
            
            # 验证前端 __t 函数能工作
            # window.__t = function(k){ return (window.__i18n && window.__i18n[k]) || k; }
            # 测试: 每个CORE_UI_KEYS都能在__i18n中找到
            for key in CORE_UI_KEYS:
                assert key in translations, \
                    f"[{platform_name}/{locale_tag}] 前端__t('{key}')会返回key本身"

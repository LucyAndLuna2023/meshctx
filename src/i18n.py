"""
meshctx i18n 多语言支持
支持: 中文(zh) / English(en) / Русский(ru) / 日本語(ja) / 한국어(ko) / Français(fr) / Deutsch(de) / Español(es) / Italiano(it) / العربية(ar)

── Key 命名规范 (v3.115.16 Phase 1) ──
所有 key 使用 snake_case，按功能域分组，用 _ 分隔层级:

  [domain]_[component]_[property]

Domain    | 前缀         | 说明
──────────┼──────────────┼──────────────────
navigation| nav_         | 导航栏、标签页
dashboard | dashboard_   | 仪表板/首页
project   | project_     | 项目管理 CRUD
chat      | chat_        | 聊天界面
setup     | setup_       | 配置/API密钥
memory    | memory_      | 记忆管理
agent     | agent_       | Agent/会话
files     | files_       | 文件管理器
provider  | provider_    | 模型供应商
common    | common_      | 通用UI(保存/取消/删除等)
error     | error_       | 错误消息
search    | search_      | 搜索功能
continuity| continuity_  | 连续性检测

Component  | 后缀       | 说明
──────────┼────────────┼──────────────────
title     | _title     | 标题/标题栏
desc      | _desc      | 描述文本
label     | _label     | 表单/字段标签
btn       | _btn       | 按钮文本
placeholder| _placeholder| 输入框占位符
hint      | _hint      | 提示信息
empty     | _empty     | 空状态文本

示例: project_create_btn, chat_input_placeholder, common_delete_confirm
"""

# ── 权威语言定义（唯一真相源）──────────────────────────────────
# 所有引用此列表的地方（web_ui.py, base.html, chat.html 等）
# 必须从此处导入，不得硬编码！

LANGUAGES = [
    {"code": "zh", "name": "Chinese", "native": "中文", "rtl": False},
    {"code": "en", "name": "English", "native": "English", "rtl": False},
    {"code": "ja", "name": "Japanese", "native": "日本語", "rtl": False},
    {"code": "ko", "name": "Korean", "native": "한국어", "rtl": False},
    {"code": "fr", "name": "French", "native": "Français", "rtl": False},
    {"code": "de", "name": "German", "native": "Deutsch", "rtl": False},
    {"code": "es", "name": "Spanish", "native": "Español", "rtl": False},
    {"code": "it", "name": "Italian", "native": "Italiano", "rtl": False},
    {"code": "ru", "name": "Russian", "native": "Русский", "rtl": False},
    {"code": "ar", "name": "Arabic", "native": "العربية", "rtl": True},
]

LANGUAGE_CODES = [lang["code"] for lang in LANGUAGES]
RTL_LANGUAGES = {lang["code"] for lang in LANGUAGES if lang["rtl"]}
import json
import os
from pathlib import Path
from typing import Dict

if getattr(__import__("sys"), 'frozen', False):
    BASE_DIR = Path(__import__("sys")._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

_loaded: Dict[str, Dict[str, str]] = {}
_current_lang = os.environ.get("MESHCTX_LANG", "zh")


# ── v3.115.16: Lazy-load translations from JSON (196KB → on-demand) ──
_TRANSLATIONS_FILE = Path(__file__).parent / 'i18n_translations.json'
_TRANSLATIONS_CACHE: Dict[str, Dict[str, str]] = {}

class _LazyTranslations:
    """Lazy-loading proxy — loads TRANSLATIONS from JSON on first access.
    
    Usage unchanged: TRANSLATIONS['zh']['key'], TRANSLATIONS.get('en', {})
    """
    def __getitem__(self, lang: str) -> Dict[str, str]:
        if not _TRANSLATIONS_CACHE and _TRANSLATIONS_FILE.exists():
            with open(_TRANSLATIONS_FILE, 'r', encoding='utf-8') as f:
                _TRANSLATIONS_CACHE.update(json.load(f))
        return _TRANSLATIONS_CACHE.get(lang, _TRANSLATIONS_CACHE.get('en', {}))
    
    def get(self, lang, default=None):
        try: return self[lang]
        except Exception: return default or {}
    
    def __contains__(self, lang):
        self[lang]; return lang in _TRANSLATIONS_CACHE
    
    def keys(self):
        if not _TRANSLATIONS_CACHE: self['zh']
        return _TRANSLATIONS_CACHE.keys()
    
    def items(self):
        if not _TRANSLATIONS_CACHE: self['zh']
        return _TRANSLATIONS_CACHE.items()
    
    def __iter__(self):
        if not _TRANSLATIONS_CACHE: self['zh']
        return iter(_TRANSLATIONS_CACHE)
    
    def __len__(self):
        if not _TRANSLATIONS_CACHE: self['zh']
        return len(_TRANSLATIONS_CACHE)

TRANSLATIONS = _LazyTranslations()

def parse_accept_language(header: str) -> str:
    """解析 Accept-Language 头，返回最佳匹配语言代码 (zh/en/ja/ko/fr/de/es)"""
    if not header:
        return ""
    # e.g. "ja,zh-CN;q=0.9,en;q=0.8" → try each in order
    for part in header.split(","):
        lang_tag = part.split(";")[0].strip()
        # Normalize: zh-CN→zh, en-US→en, ja-JP→ja, etc.
        code = lang_tag.split("-")[0].lower()
        if code in TRANSLATIONS:
            return code
    return ""


def get_lang(request=None) -> str:
    """获取当前语言（优先级：cookie > Accept-Language > 环境变量 > 默认 zh）"""
    # 1. Cookie（手动选择）
    if request is not None:
        try:
            cookie_lang = request.cookies.get("meshctx_lang")
            if cookie_lang and cookie_lang in TRANSLATIONS:
                return cookie_lang
        except Exception:
            pass
        # 2. Accept-Language 请求头（浏览器语言）
        try:
            accept = request.headers.get("Accept-Language", "")
            detected = parse_accept_language(accept)
            if detected:
                return detected
        except Exception:
            pass
    # 3. 环境变量 / 默认
    global _current_lang
    env_lang = os.environ.get("MESHCTX_LANG", "")
    if env_lang and env_lang in TRANSLATIONS:
        return env_lang
    return _current_lang or "zh"


def validate_keys() -> dict:
    """校验所有语言 key 一致性 (Phase 1 质量门禁)

    Returns: {"ok": True} 或 {"missing": {lang: [missing_keys]}}
    """
    ref_keys = set(TRANSLATIONS.get("en", {}).keys())
    if not ref_keys:
        return {"ok": True, "total_keys": 0}
    missing = {}
    for lang in TRANSLATIONS:
        lang_keys = set(TRANSLATIONS[lang].keys())
        diff = ref_keys - lang_keys
        if diff:
            missing[lang] = sorted(diff)
    return {"ok": len(missing) == 0, "total_keys": len(ref_keys), "missing": missing}


def set_lang(lang: str):
    """设置语言（同时更新全局状态和环境变量）"""
    global _current_lang
    if lang in TRANSLATIONS:
        _current_lang = lang
        os.environ["MESHCTX_LANG"] = lang


def t(key: str, lang: str = None) -> str:
    """翻译: t('welcome_title') → 当前语言的翻译"""
    lang = lang or _current_lang
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))


def get_translations(lang: str = None) -> Dict[str, str]:
    """获取指定语言的全部翻译"""
    lang = lang or _current_lang
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"])


def get_available_languages() -> list:
    """可用的语言列表（从 LANGUAGES 常量生成）"""
    return [{"code": lang["code"], "name": lang["name"], "native": lang["native"]} for lang in LANGUAGES]

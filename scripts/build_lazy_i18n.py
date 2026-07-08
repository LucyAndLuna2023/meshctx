#!/usr/bin/env python3
"""Rebuild i18n.py: head + lazy loader + tail"""
head = head_text
lazy = '''
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

TRANSLATIONS = _LazyTranslations()
'''
tail = start_of_tail

new_content = head + lazy + tail
with open('src/i18n.py', 'w') as f:
    f.write(new_content)
print(f"Written: {len(new_content)} chars (was {len(head)+158258+len(tail)})")
print(f"Reduction: {158258 - len(lazy)} chars")

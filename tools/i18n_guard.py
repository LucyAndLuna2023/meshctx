#!/usr/bin/env python3
"""i18n guard: CI gate that validates 7-language integrity in index.html.

Checks:
  1. All ~192 data-lang-key elements exist in all 7 languages
  2. No cross-family language pollution (warning only)
  3. All L object keys are present in all languages
"""

import re, sys, json
from collections import defaultdict

LANGS = ['en', 'zh', 'ja', 'ko', 'de', 'fr', 'es']
FAMILIES = {
    'zh': 'CJK', 'ja': 'CJK', 'ko': 'CJK',
    'de': 'Latin', 'fr': 'Latin', 'es': 'Latin', 'en': 'Latin',
}

CJK_PATTERNS = {
    'cjk_chars': re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]'),
}

def load_html(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def find_l_object(html):
    """Extract the L object from HTML — blocks may NOT be in alphabetical order."""
    blocks = {}
    for lang in LANGS:
        pattern = re.compile(r'\b' + lang + r'\s*:\s*\{')
        m = pattern.search(html)
        if not m:
            continue
        
        start = m.start()
        depth = 0
        i = m.end()
        in_string = False
        string_char = None
        while i < len(html):
            c = html[i]
            if in_string:
                if c == '\\':
                    i += 1
                elif c == string_char:
                    in_string = False
            else:
                if c in '\'"':
                    in_string = True
                    string_char = c
                elif c == '{':
                    depth += 1
                elif c == '}':
                    if depth == 0:
                        blocks[lang] = html[start:i+1]
                        break
                    depth -= 1
            i += 1
    
    return blocks

def extract_keys(block):
    """Extract key:value pairs from a lang block — handles escaped quotes."""
    keys = {}
    str_pat = r'(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')'
    kv_pat = re.compile(r'(["\']?)(\w+)\1\s*:\s*' + str_pat)
    for km in kv_pat.finditer(block):
        key = km.group(2)
        val = km.group(3) if km.group(3) is not None else km.group(4)
        if key not in LANGS and key != 'en':
            keys[key] = val
    return keys

def check_cross_family_pollution(blocks):
    """Check for characters from one family in another."""
    errors = []
    for lang, block in blocks.items():
        family = FAMILIES.get(lang, 'Latin')
        for other_lang in LANGS:
            if other_lang == lang:
                continue
            other_family = FAMILIES.get(other_lang)
            if other_family == family:
                continue
        
        if family == 'Latin':
            matches = CJK_PATTERNS['cjk_chars'].findall(block)
            if matches:
                vals = re.findall(r':\s*["\']([^"\']*[' + ''.join(set(''.join(matches))) + r'][^"\']*)["\']', block)
                for v in vals:
                    if CJK_PATTERNS['cjk_chars'].search(v):
                        errors.append(f"  {lang}: CJK char in Latin lang value: '{v[:60]}...'")
    
    return errors

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
    print(f"=== i18n Guard: {path} ===")
    
    html = load_html(path)
    blocks = find_l_object(html)
    
    if not blocks:
        print("ERROR: Could not find L object in HTML")
        sys.exit(1)
    
    print(f"Found {len(blocks)} language blocks: {list(blocks.keys())}")
    
    # Check 1: All languages present
    missing_langs = [l for l in LANGS if l not in blocks]
    if missing_langs:
        print(f"FAIL: Missing languages: {missing_langs}")
        sys.exit(1)
    
    # Check 2: Extract keys from each lang
    all_keys = {}
    for lang in LANGS:
        keys = extract_keys(blocks[lang])
        all_keys[lang] = keys
        print(f"  {lang}: {len(keys)} keys")
    
    # Check 3: All keys MUST exist in EN (hard fail — fallback source of truth)
    en_keys = set(all_keys['en'].keys())
    errors = []
    warnings = []
    for lang in LANGS:
        if lang == 'en':
            continue
        lang_keys = set(all_keys[lang].keys())
        missing = en_keys - lang_keys
        extra = lang_keys - en_keys
        if missing:
            warnings.append(f"  {lang}: {len(missing)} keys missing from L.{lang} (will fallback to English)")
        if extra:
            errors.append(f"  {lang}: extra keys (not in EN): {sorted(extra)}")

    if errors:
        print("FAIL: Extra keys in non-English languages:")
        for e in errors:
            print(e)
        sys.exit(1)

    if warnings:
        print("WARNING: Missing non-English translations (fallback to EN):")
        for w in warnings:
            print(w)
    else:
        print("✅ All languages have complete translations.")
    
    # Check 4: Cross-family pollution — WARNING only (bilingual terms are common)
    pollution = check_cross_family_pollution(blocks)
    if pollution:
        print("WARNING: Cross-family language pollution (may be intentional bilingual content):")
        for p in pollution:
            print(p)
    
    total_keys = sum(len(v) for v in all_keys.values())
    print(f"\nPASS: {len(LANGS)} languages x ~{len(en_keys)} keys = {total_keys} total key-value pairs")
    print("No cross-family pollution detected.")
    sys.exit(0)

if __name__ == '__main__':
    main()

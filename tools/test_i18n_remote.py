"""7-language UI test — runs inside WSL on target machine"""
import urllib.request
import json, sys

BASE = "http://localhost:3001"
LANGS = {
    'en': 'English', 'zh': '中文', 'ja': '日本語',
    'ko': '한국어', 'de': 'Deutsch', 'fr': 'Français', 'es': 'Español'
}

results = {}

# 1. Check server
try:
    resp = urllib.request.urlopen(f"{BASE}/api/version", timeout=5)
    ver = json.loads(resp.read())
    print(f"SERVER: {ver.get('version', 'unknown')}")
except Exception as e:
    print(f"SERVER: DOWN ({e})")
    sys.exit(1)

# 2. Test each language
for code, name in LANGS.items():
    try:
        resp = urllib.request.urlopen(f"{BASE}/ui/chat?lang={code}", timeout=10)
        html = resp.read().decode('utf-8')
        
        has_switchLang = 'switchLang' in html
        has_i18n_js = 'const L = {' in html
        key_count = html.count('data-lang-key')
        
        # Check specific translations
        checks = {
            'cv_a': 'cv_a:' in html,
            'cv_n': 'cv_n:' in html,
            'pl1_title': 'pl1_title:' in html,
        }
        
        status = '✓' if (has_switchLang and has_i18n_js and key_count > 20) else '✗'
        results[code] = {
            'status': status,
            'name': name,
            'switchLang': has_switchLang,
            'i18n_js': has_i18n_js,
            'key_count': key_count,
            'checks': checks,
        }
        print(f"{status} {code}({name}): keys={key_count} JS={has_i18n_js}")
        
    except Exception as e:
        results[code] = {'status': '✗', 'name': name, 'error': str(e)}
        print(f"✗ {code}({name}): ERROR {e}")

# Summary
passed = sum(1 for r in results.values() if r['status'] == '✓')
print(f"\n=== SUMMARY: {passed}/{len(LANGS)} languages pass ===")
print(json.dumps(results, indent=2, ensure_ascii=False))

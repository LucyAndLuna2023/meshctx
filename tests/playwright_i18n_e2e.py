#!/usr/bin/env python3
"""Playwright E2E: test all 7 languages on meshctx.com with SSL ignore"""
from playwright.sync_api import sync_playwright

url_tries = ["http://meshctx.com", "http://lucyandluna2023.github.io/meshctx/"]
langs = [
    ("en","English"), ("zh","Chinese"), ("ja","Japanese"), ("ko","Korean"),
    ("de","German"), ("fr","French"), ("es","Spanish"),
]
# Map display names to expected button text
btn_map = {
    "en": "English", "zh": "中文", "ja": "日本語", "ko": "한국어",
    "de": "Deutsch", "fr": "Français", "es": "Español",
}
results = []
js_errors = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    page.on("pageerror", lambda e: js_errors.append(str(e)))
    
    connected = False
    for url_try in url_tries:
        try:
            page.goto(url_try, wait_until="networkidle", timeout=15000)
            results.append(f"Connected: {url_try}")
            connected = True
            break
        except Exception as e:
            results.append(f"Failed: {url_try} - {str(e)[:80]}")
    
    if not connected:
        # Try raw GitHub 
        try:
            page.goto("https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/docs/index.html", 
                      wait_until="networkidle", timeout=10000)
            results.append("Connected to raw GitHub (static HTML, no JS)")
        except:
            results.append("ALL URLs failed")
            browser.close()
            print("\n".join(results))
            exit()
    
    page.wait_for_timeout(1000)
    
    for code in ["en","zh","ja","ko","de","fr","es"]:
        btn = btn_map[code]
        try:
            # Try dropdown toggle
            toggle = page.query_selector("#langToggle")
            if toggle:
                toggle.click()
                page.wait_for_timeout(200)
            
            # Try to find and click the button
            found = False
            for selector in [
                f'.lang-dropdown-menu button:has-text("{btn}")',
                f'button:has-text("{btn}")',
                f'[data-lang="{code}"]',
                f'.lang-btn[data-lang="{code}"]',
            ]:
                el = page.query_selector(selector)
                if el:
                    el.click()
                    found = True
                    break
            
            if not found:
                results.append("  FAIL {}: button '{}' not found".format(code, btn))
                continue
            
            page.wait_for_timeout(500)
            
            # Verify
            active_blocks = page.evaluate(
                "Array.from(document.querySelectorAll('.lang[data-lang].active')).map(e=>e.dataset.lang)"
            )
            nav_key = page.evaluate(
                "document.querySelector('[data-lang-key=\"nav_features\"]')?.textContent || ''"
            )
            hero_h1 = page.evaluate(
                "document.querySelector('.lang.active h1')?.textContent?.substring(0,60) || 'NONE'"
            )
            ls = page.evaluate("localStorage.getItem('meshctx-lang')")
            trans_count = page.evaluate(
                "Array.from(document.querySelectorAll('[data-lang-key]')).filter(el=>el.offsetParent!==null).length"
            )
            blank_elems = page.evaluate(
                "Array.from(document.querySelectorAll('[data-lang-key]')).filter(el=>el.offsetParent!==null&&el.textContent.trim()==='').map(el=>el.getAttribute('data-lang-key'))"
            )
            
            ok = active_blocks and code in active_blocks and ls == code and not blank_elems
            status = "PASS" if ok else "FAIL"
            
            results.append("  {} {:3s} | active={} | nav='{}' | hero='{}' | LS={} | elems={}".format(
                status, code, active_blocks, nav_key[:15], hero_h1[:30], ls, trans_count
            ))
            if blank_elems:
                results.append("         BLANK elements: {}".format(blank_elems[:5]))
                
        except Exception as e:
            results.append("  FAIL {}: {}".format(code, str(e)[:80]))
    
    results.append("\nJS console errors: {}".format(len(js_errors)))
    for e in js_errors[:3]:
        results.append("  JS: {}".format(e[:150]))
    
    browser.close()

print("\n".join(results))
passed = sum(1 for r in results if r.strip().startswith("PASS") or r.strip().startswith("  PASS"))
failed = sum(1 for r in results if r.strip().startswith("FAIL") or r.strip().startswith("  FAIL"))
print("\n{} passed, {} failed out of 7 languages".format(passed, failed))

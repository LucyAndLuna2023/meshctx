#!/usr/bin/env python3
"""
🔴 7语言浏览器自动化测试 — Playwright真浏览器实测
测试meshctx.com主页 + templates/Web UI 所有语言切换
"""
import asyncio, json, os, sys
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

REPORT_DIR = Path("/tmp/meshctx_ui_tests")
REPORT_DIR.mkdir(exist_ok=True)

LANGS = {
    'en': 'English', 'zh': '中文', 'ja': '日本語',
    'ko': '한국어', 'de': 'Deutsch', 'fr': 'Français', 'es': 'Español'
}

EXPECTED_TEXTS = {
    'en': ['Features', 'Compare', 'Why MeshCtx', 'Hierarchical Memory', 'Self-Evolving'],
    'zh': ['特性', '对比', '为什么选择', '层次记忆', '自我进化'],
    'ja': ['機能', '比較', 'なぜ', '階層記憶', '自己進化'],
    'ko': ['기능', '비교', '왜', '계층적 메모리', '자가 진화'],
    'de': ['Features', 'Vergleich', 'Warum', 'Hierarchischer', 'Selbstlernend'],
    'fr': ['Fonctionnalités', 'Comparer', 'Pourquoi', 'Mémoire', 'Auto-Évolutif'],
    'es': ['Funciones', 'Comparar', 'Por qué', 'Memoria', 'Auto-Evolutivo'],
}

async def test_homepage():
    """测试meshctx.com主页7语言切换"""
    results = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 800})
        
        # Load local homepage
        html_path = Path(os.getcwd()) / "docs" / "index.html"
        await page.goto(f"file://{html_path}")
        await page.wait_for_timeout(1000)
        
        for lang, name in LANGS.items():
            try:
                # Click language button
                lang_toggle = await page.query_selector('#langToggle')
                if lang_toggle:
                    await lang_toggle.click()
                    await page.wait_for_timeout(300)
                
                # Find and click the language option
                buttons = await page.query_selector_all('.lang-dropdown-menu button')
                clicked = False
                for btn in buttons:
                    text = await btn.text_content()
                    if text and name in text:
                        await btn.click()
                        clicked = True
                        break
                
                if not clicked:
                    # Fallback: execute JS directly
                    await page.evaluate(f'switchLang("{lang}")')
                
                await page.wait_for_timeout(500)
                
                # Verify translations
                checks = {}
                for expected in EXPECTED_TEXTS.get(lang, []):
                    content = await page.content()
                    checks[expected] = expected in content
                
                # Screenshot
                await page.screenshot(path=str(REPORT_DIR / f"homepage_{lang}.png"))
                
                # Count visible translated elements
                visible_count = await page.evaluate('''() => {
                    return document.querySelectorAll('[data-lang-key]').length;
                }''')
                
                all_pass = all(checks.values())
                results[lang] = {
                    'status': 'PASS' if all_pass else 'FAIL',
                    'checks': checks,
                    'visible_keys': visible_count,
                    'screenshot': f"homepage_{lang}.png",
                }
                
                icon = '✅' if all_pass else '❌'
                failed = [k for k, v in checks.items() if not v]
                print(f"  {icon} {lang}({name}): {sum(checks.values())}/{len(checks)} checks, {visible_count} keys" + 
                      (f" | missing: {failed}" if failed else ""))
                
            except Exception as e:
                results[lang] = {'status': 'ERROR', 'error': str(e)}
                print(f"  ❌ {lang}: {e}")
        
        await browser.close()
    
    return results

async def test_web_ui(server_url="http://127.0.0.1:3001"):
    """测试Web UI模板7语言切换"""
    results = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for lang, name in LANGS.items():
            try:
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})
                await page.goto(f"{server_url}/ui/?lang={lang}")
                await page.wait_for_timeout(1000)
                
                # Check if language selector exists
                has_selector = await page.query_selector('.lang-switch select') is not None
                
                # Check translated content
                content = await page.content()
                has_lang_obj = 'const LANG' in content or 'switchLang' in content
                has_nav = 'nav_dashboard' in content
                
                await page.screenshot(path=str(REPORT_DIR / f"webui_{lang}.png"))
                
                results[lang] = {
                    'status': 'PASS' if (has_selector or has_lang_obj) else 'FAIL',
                    'has_selector': has_selector,
                    'has_i18n': has_lang_obj,
                    'http_ok': len(content) > 500,
                    'screenshot': f"webui_{lang}.png",
                }
                
                icon = '✅' if results[lang]['status'] == 'PASS' else '❌'
                print(f"  {icon} {lang}({name}): selector={has_selector} i18n={has_lang_obj}")
                
                await page.close()
                
            except Exception as e:
                results[lang] = {'status': 'ERROR', 'error': str(e)}
                print(f"  ❌ {lang}: {e}")
                try: await page.close()
                except: pass
        
        await browser.close()
    
    return results

async def main():
    print("╔══════════════════════════════════════════╗")
    print("║  meshctx 7语言浏览器自动化测试         ║")
    print("╚══════════════════════════════════════════╝")
    print()
    
    # Test 1: Homepage
    print("=== 1. Homepage (docs/index.html) ===")
    hp_results = await test_homepage()
    
    # Test 2: Web UI (if server running)
    print("\n=== 2. Web UI (templates) ===")
    ui_results = {}
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:3001/api/version", timeout=2)
        ui_results = await test_web_ui()
    except:
        print("  ⚠ Server not running, skipping Web UI test")
    
    # Summary
    hp_pass = sum(1 for r in hp_results.values() if r['status'] in ('PASS',))
    ui_pass = sum(1 for r in ui_results.values() if r['status'] in ('PASS',))
    
    print(f"\n{'='*50}")
    print(f"Homepage: {hp_pass}/{len(LANGS)} languages pass")
    if ui_results:
        print(f"Web UI:   {ui_pass}/{len(LANGS)} languages pass")
    
    # Save detailed report
    report = {
        'timestamp': datetime.now().isoformat(),
        'homepage': hp_results,
        'web_ui': ui_results,
        'summary': {
            'homepage_pass': hp_pass,
            'web_ui_pass': ui_pass,
            'total_langs': len(LANGS),
        }
    }
    
    report_path = REPORT_DIR / 'report.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\nReport: {report_path}")
    print(f"Screenshots: {REPORT_DIR}/")
    
    return 0 if hp_pass == len(LANGS) else 1

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))

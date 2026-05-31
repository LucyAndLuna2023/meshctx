"""
meshctx 全量API + UI + 集成自动化测试
本地启动服务后自动运行所有测试
"""
import urllib.request, json, time, sys, os, subprocess

BASE = "http://127.0.0.1:3001"
passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        result = fn()
        if result:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            print(f"  ❌ {name}: FAILED")
    except Exception as e:
        failed += 1
        print(f"  ❌ {name}: ERROR - {e}")

def get(path):
    resp = urllib.request.urlopen(f"{BASE}{path}", timeout=5)
    return json.loads(resp.read())

# ═══ API测试 ═══
print("=== API Tests ===")
test("GET /api/health", lambda: get("/api/health")["status"] == "ok")
test("GET /api/version", lambda: "version" in get("/api/version"))
test("POST /api/jepa/health", lambda: get("/api/jepa/health")["status"] == "ok")
test("GET /api/session/resume/status", lambda: "resumed" in get("/api/session/resume/status"))
test("GET /api/archive/summary", lambda: "session_id" in get("/api/archive/summary"))
test("GET /api/archive/list", lambda: "archives" in get("/api/archive/list"))

print("\n=== I18N UI Tests ===")
def check_lang(lang):
    resp = urllib.request.urlopen(f"{BASE}/ui/?lang={lang}", timeout=10)
    html = resp.read().decode()
    return len(html) > 500
for lang in ['en','zh','ja','ko','de','fr','es']:
    test(f"UI /?lang={lang}", lambda l=lang: check_lang(l))

print(f"\n=== RESULT: {passed}/{passed+failed} passed ===")
sys.exit(0 if failed == 0 else 1)

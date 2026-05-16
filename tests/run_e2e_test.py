#!/usr/bin/env python3
"""meshctx v2.15.6 全链路E2E功能测试"""
import subprocess, json, sys

BASE = "http://47.120.0.239:3001"
PASS, FAIL = 0, 0

def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  ✅ {name}")
        PASS += 1
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        FAIL += 1

def curl(path, method="GET", data=None, timeout=10):
    cmd = ["curl","-s","-m",str(timeout),"-X",method]
    if data:
        cmd += ["-H","Content-Type: application/json","-d",json.dumps(data)]
    cmd.append(f"{BASE}{path}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+2)
    try:
        return json.loads(r.stdout) if r.stdout else {}
    except:
        return {"_raw": r.stdout[:200], "_code": r.returncode}

def ok(d):
    assert isinstance(d, dict) and "_raw" not in d, f"非JSON: {d.get('_raw','?')[:80]}"
    return d

def has(d, key):
    assert key in d, f"缺'{key}'"
    return d[key]

# ═══ Phase 1: 核心 ═══
print("\n═══ Phase 1: 核心健康 ═══")

def t1():
    d = ok(curl("/api/version"))
    v = has(d, "version")
    assert v.startswith("2.15"), v
check("GET /api/version", t1)

def t2():
    d = ok(curl("/health"))
    assert d.get("status") == "healthy"
check("GET /health", t2)

def t3():
    d = ok(curl("/api/system/summary"))
    has(d, "version")
check("GET /api/system/summary", t3)

def t4():
    ok(curl("/api/cache/stats"))
check("GET /api/cache/stats", t4)

def t5():
    ok(curl("/api/agent/monitor"))
check("GET /api/agent/monitor", t5)

# ═══ Phase 2: 模型 ═══
print("\n═══ Phase 2: 模型管理 ═══")

def t6():
    d = ok(curl("/api/models"))
    has(d, "models")
check("GET /api/models", t6)

def t7():
    ok(curl("/api/providers"))
check("GET /api/providers", t7)

def t8():
    ok(curl("/api/providers/health"))
check("GET /api/providers/health", t8)

TM = "test:e2e-model"
def t9():
    d = ok(curl("/api/models","POST",{
        "id":TM,"key":"sk-fake","base_url":"https://api.openai.com/v1",
        "model":"gpt-3.5","provider":"openai"
    }))
    assert d.get("status") == "ok" or "id" in d, str(d)
check("POST /api/models 添加", t9)

def t10():
    ok(curl(f"/api/models/{TM}","PUT",{"model":"gpt-4"}))
check("PUT /api/models 更新", t10)

def t11():
    d = ok(curl(f"/api/models/{TM}/test","POST"))
    assert d.get("status") == "error", f"假Key居然通过: {d.get('message','?')}"
check("POST test连接(应失败)", t11)

def t12():
    ok(curl(f"/api/models/{TM}","DELETE"))
check("DELETE /api/models 删除", t12)

# ═══ Phase 3: 新特性 ═══
print("\n═══ Phase 3: 新特性API (v2.15.4-v2.15.6) ═══")

def t13():
    has(ok(curl("/api/prompts")), "templates")
check("GET /api/prompts", t13)

PN = "e2e-prompt"
def t14():
    d = ok(curl("/api/prompts","POST",{"name":PN,"content":"test","tags":["e2e"]}))
    assert d.get("ok"), str(d)
check("POST /api/prompts", t14)

def t15():
    ok(curl(f"/api/prompts/{PN}","DELETE"))
check("DELETE /api/prompts", t15)

def t16():
    d = ok(curl("/api/utils/tokens","POST",{"text":"Hello 你好世界"}))
    assert has(d,"tokens") > 0
check("POST /api/utils/tokens", t16)

def t17():
    d = ok(curl("/api/chat","POST",{"message":"say PASS","system":"Reply: PASS"}))
    has(d,"content")
    print(f"     ↳ {d.get('content','?')[:60]}")
check("POST /api/chat+system", t17)

def t18():
    # SSE streaming returns data: {...}\n\n format, not JSON
    r = subprocess.run(["curl","-s","-m","15","-X","POST",
        f"{BASE}/api/chat/stream",
        "-H","Content-Type: application/json",
        "-d",'{"message":"hi","max_tokens":5}'],
        capture_output=True, text=True, timeout=20)
    output = r.stdout.strip()
    assert "data:" in output, f"不是SSE格式: {output[:80]}"
    assert "[DONE]" in output or "token" in output, f"缺完成信号: {output[:80]}"
    print(f"     ↳ SSE流式: {len(output)}字节")
check("POST /api/chat/stream", t18)

# ═══ Phase 4: Web UI ═══
print("\n═══ Phase 4: Web UI 页面 ═══")

def t19():
    r = subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}","-m","5",f"{BASE}/ui/chat"],
                      capture_output=True, text=True)
    assert r.stdout.strip() == "200", f"/ui/chat: {r.stdout.strip()}"
check("GET /ui/chat", t19)

def t20():
    r = subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}","-m","5",f"{BASE}/ui/desktop"],
                      capture_output=True, text=True)
    assert r.stdout.strip() == "200", f"/ui/desktop: {r.stdout.strip()}"
check("GET /ui/desktop", t20)

def t21():
    r = subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}","-m","5",f"{BASE}/docs"],
                      capture_output=True, text=True)
    assert r.stdout.strip() == "200", f"/docs: {r.stdout.strip()}"
check("GET /docs", t21)

# ═══ Phase 5: 竞品功能 ═══
print("\n═══ Phase 5: 竞品对标功能 ═══")

def t22():
    d = ok(curl("/api/chat/compare","POST",{"message":"1+1","models":[]}))
    assert isinstance(d, dict)
check("POST /api/chat/compare", t22)

def t23():
    d = ok(curl("/api/sandbox/execute","POST",{"code":"print(1+1)","language":"python"}))
check("POST /api/sandbox/execute", t23)

def t24():
    ok(curl("/api/project/index"))
check("GET /api/project/index", t24)

def t25():
    ok(curl("/api/search?q=test&engine=duckduckgo"))
check("GET /api/search", t25)

def t26():
    ok(curl("/api/update/check"))
check("GET /api/update/check", t26)

def t27():
    ok(curl("/api/memory"))
check("GET /api/memory", t27)

def t28():
    ok(curl("/api/workspaces"))
check("GET /api/workspaces", t28)

def t29():
    ok(curl("/api/brain/status"))
check("GET /api/brain/status", t29)

def t30():
    ok(curl("/api/lab/benchmark?scenario=quick"))
check("GET /api/lab/benchmark", t30)

# ═══ Phase 6: 文件/配置 ═══
print("\n═══ Phase 6: 文件与配置 ═══")

def t31():
    ok(curl("/api/file/list?path=."))
check("GET /api/file/list", t31)

def t32():
    ok(curl("/api/context/projects"))
check("GET /api/context/projects", t32)

def t33():
    ok(curl("/api/config/export"))
check("GET /api/config/export", t33)

def t34():
    ok(curl("/api/config/backup"))
check("GET /api/config/backup", t34)

def t35():
    ok(curl("/api/plugins"))
check("GET /api/plugins", t35)

def t36():
    ok(curl("/api/conversations"))
check("GET /api/conversations", t36)

# ═══ 结果 ═══
print("\n" + "="*60)
total = PASS + FAIL
pct = PASS/total*100 if total else 0
print(f"📊 {PASS}/{total} passed ({pct:.0f}%)")
print(f"🎯 {BASE}")
if FAIL:
    print(f"🔴 {FAIL} FAILED — 需修复!")
    sys.exit(1)
else:
    print("🟢 ALL PASSED!")
    sys.exit(0)

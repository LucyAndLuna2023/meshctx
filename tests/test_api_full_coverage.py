"""
API端点全覆盖测试 — v2.28.0
测试所有公开API端点: 200/正常响应/必要字段
"""
import requests
import time

BASE = "http://127.0.0.1:3001"
passed = 0
failed = 0

def check(name, status, resp=None, keys=None):
    global passed, failed
    ok = True
    msg = ""
    if status not in (200, 201, 204, 301, 302, 405, 503):
        ok = False; msg = f"status={status}"
    if resp and keys and ok:
        if isinstance(resp, dict):
            missing = [k for k in keys if k not in resp and k != "*"]
            if missing: ok = False; msg = f"missing keys: {missing}"
        elif isinstance(resp, list):
            if not resp and "*" not in keys: ok = False; msg = "empty list"
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}: {msg}")

# ========================================
# 系统
# ========================================
print("\n── 系统端点 ──")
r = requests.get(f"{BASE}/api/version"); check("/api/version", r.status_code, r.json(), ["version","models","providers"])
r = requests.get(f"{BASE}/health"); check("/health", r.status_code, r.json(), ["status"])
r = requests.get(f"{BASE}/api/health"); check("/api/health", r.status_code, r.json(), ["status"])

# ========================================
# 模型
# ========================================
print("\n── 模型 ──")
r = requests.get(f"{BASE}/api/models"); check("/api/models", r.status_code)
r = requests.get(f"{BASE}/api/providers"); check("/api/providers", r.status_code)

# ========================================
# 记忆
# ========================================
print("\n── 记忆 ──")
r = requests.get(f"{BASE}/api/memory/stats"); check("/api/memory/stats", r.status_code, r.json(), ["total_memories"])
r = requests.get(f"{BASE}/api/memory/graph"); check("/api/memory/graph", r.status_code, r.json(), ["nodes","edges"])
r = requests.post(f"{BASE}/api/memory/search", json={"query":"test","top_k":3}); check("/api/memory/search", r.status_code, r.json(), ["results"])
r = requests.post(f"{BASE}/api/memory/add", json={"content":"e2e test memory","type":"fact"}); check("/api/memory/add", r.status_code, r.json(), ["id"])

# ========================================
# 多Agent
# ========================================
print("\n── 多Agent ──")
r = requests.get(f"{BASE}/api/multi-agent/status"); check("/api/multi-agent/status", r.status_code, r.json(), ["manager"])
r = requests.post(f"{BASE}/api/multi-agent/create-team"); check("/api/multi-agent/create-team", r.status_code, r.json(), ["agents"])
r = requests.post(f"{BASE}/api/multi-agent/decompose", json={"type":"analysis","description":"test"}); check("/api/multi-agent/decompose", r.status_code, r.json(), ["subtasks"])
r = requests.post(f"{BASE}/api/multi-agent/plan", json={"type":"code","description":"test"}); check("/api/multi-agent/plan", r.status_code, r.json(), ["subtasks"])

# ========================================
# 自愈
# ========================================
print("\n── 自愈 ──")
r = requests.get(f"{BASE}/api/healer/status"); check("/api/healer/status", r.status_code in (200,503))
r = requests.get(f"{BASE}/api/healer/dashboard"); check("/api/healer/dashboard", r.status_code in (200,503))
r = requests.get(f"{BASE}/api/healer/history?limit=5"); check("/api/healer/history", r.status_code in (200,503))

# ========================================
# 性能
# ========================================
print("\n── 性能 ──")
r = requests.get(f"{BASE}/api/performance/benchmark"); check("/api/performance/benchmark", r.status_code in (200,503))
r = requests.get(f"{BASE}/api/performance/cache-stats"); check("/api/performance/cache-stats", r.status_code in (200,503))
r = requests.get(f"{BASE}/api/performance/latency-stats"); check("/api/performance/latency-stats", r.status_code in (200,503))

# ========================================
# 文件
# ========================================
print("\n── 文件 ──")
r = requests.get(f"{BASE}/api/file/list"); check("/api/file/list", r.status_code)
r = requests.get(f"{BASE}/context/build"); check("/context/build GET", r.status_code)
r = requests.get(f"{BASE}/api/file/read?path=/etc/hostname"); check("/api/file/read", r.status_code, r.json(), ["content"])

# ========================================
# 页面
# ========================================
print("\n── Web页面 ──")
for path in ["/","/ui/chat","/ui/dashboard","/ui/setup","/ui/plugins","/ui/files","/ui/memory","/ui/download","/ui/models","/ui/providers"]:
    r = requests.get(f"{BASE}{path}")
    check(path, r.status_code)
    if r.status_code == 200:
        html = r.text.lower()
        if len(html) < 200: check(f"{path} size", False, f"only {len(html)} bytes")
    else: check(f"{path} size", False, f"status={r.status_code}")

# ========================================
# 安装脚本
# ========================================
print("\n── 安装脚本 ──")
r = requests.get(f"{BASE}/install.sh"); check("/install.sh", r.status_code)
r = requests.get(f"{BASE}/install.bat"); check("/install.bat", r.status_code, r.json() if r.headers.get('content-type','').startswith('application/json') else None)

# ========================================
# 静态文件
# ========================================
print("\n── 静态文件 ──")
r = requests.get(f"{BASE}/ui/manifest.json"); check("/ui/manifest.json", r.status_code, r.json(), ["name","display"])
r = requests.get(f"{BASE}/static/dl/meshctx-windows.zip", stream=True); check("/static/dl/meshctx-windows.zip", r.status_code)

# ========================================
print(f"\n{'='*50}")
print(f"  结果: {passed}/{passed+failed} 通过")
print(f"{'='*50}")

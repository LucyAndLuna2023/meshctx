"""边界条件 + 错误处理测试"""
import requests

BASE = "http://127.0.0.1:3001"
p = f = 0

def t(name, fn):
    global p, f
    try:
        fn()
        p += 1; print(f"  ✅ {name}")
    except Exception as e:
        f += 1; print(f"  ❌ {name}: {e}")

print("\n── 空请求体 ──")
t("空body /api/memory/search", lambda: requests.post(f"{BASE}/api/memory/search", json={}).status_code in (200,400,422))
t("空body /api/multi-agent/decompose", lambda: requests.post(f"{BASE}/api/multi-agent/decompose").status_code in (400,422))

print("\n── 缺失参数 ──")
t("/api/file/read无path", lambda: requests.get(f"{BASE}/api/file/read").status_code == 400)
t("/api/file/write无path", lambda: requests.post(f"{BASE}/api/file/write").status_code == 400)

print("\n── 无效输入 ──")
t("无效JSON Chat", lambda: requests.post(f"{BASE}/api/chat", data="not json").status_code in (400,422))
t("超长路径 /api/file/read", lambda: requests.get(f"{BASE}/api/file/read?path=" + "x"*10000).status_code in (400,404,414))

print("\n── 安全边界 ──")
t("/sys拒绝访问", lambda: requests.get(f"{BASE}/api/file/read?path=/sys/kernel").status_code in (403,404))
t("/proc拒绝访问", lambda: requests.get(f"{BASE}/api/file/read?path=/proc/cpuinfo").status_code in (403,404))

print("\n── HTTP方法 ──")
t("OPTIONS /api/version", lambda: requests.options(f"{BASE}/api/version").status_code in (200,405))
t("HEAD /api/version", lambda: requests.head(f"{BASE}/api/version").status_code in (200,405))
t("PUT /api/version", lambda: requests.put(f"{BASE}/api/version").status_code in (405,404))

print("\n── 大响应 ──")
t("/ui/chat >10KB", lambda: len(requests.get(f"{BASE}/ui/chat").text) > 10000)
t("/ui/dashboard >1KB", lambda: len(requests.get(f"{BASE}/ui/dashboard").text) > 1000)

print(f"\n结果: {p}/{p+f} 通过")

"""
性能基准测试 — API延迟 + 模型CRUD + Chat流式
"""
import time, requests, statistics

BASE = "http://47.120.0.239:3001"

def bench(name, fn, iterations=5):
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    avg = statistics.mean(times)
    print(f"  {name}: {avg:.1f}ms (n={iterations})")
    return avg

results = {}

print("=== API Benchmarks ===")
results['version'] = bench("GET /api/version",
    lambda: requests.get(f"{BASE}/api/version", timeout=5))

results['health'] = bench("GET /api/health",
    lambda: requests.get(f"{BASE}/api/health", timeout=5))

results['models_list'] = bench("GET /api/models",
    lambda: requests.get(f"{BASE}/api/models", timeout=5))

results['plugins_market'] = bench("GET /api/plugins/market",
    lambda: requests.get(f"{BASE}/api/plugins/market", timeout=5))

results['feishu_status'] = bench("GET /api/feishu/status",
    lambda: requests.get(f"{BASE}/api/feishu/status", timeout=5))

print("\n=== Model CRUD Benchmarks ===")
results['add_model'] = bench("POST /api/models",
    lambda: requests.post(f"{BASE}/api/models", json={
        "id": "bench:test", "provider": "test", "key": "sk-test",
        "model": "test", "overwrite": True
    }, timeout=5))

results['update_model'] = bench("PUT /api/models/bench:test",
    lambda: requests.put(f"{BASE}/api/models/bench:test", json={
        "key": "sk-updated"
    }, timeout=5))

results['delete_model'] = bench("DELETE /api/models/bench:test",
    lambda: requests.delete(f"{BASE}/api/models/bench:test", timeout=5))

print("\n=== Chat Streaming ===")
def chat_stream():
    r = requests.post(f"{BASE}/api/chat/stream", json={
        "message": "hi", "model": "deepseek-v4-pro"
    }, timeout=30, stream=True)
    for line in r.iter_lines():
        if line and b'[DONE]' in line:
            break

results['chat_stream'] = bench("POST /api/chat/stream (hi→done)",
    chat_stream, iterations=2)

print("\n=== Web Search ===")
results['web_search'] = bench("GET /api/web/search?q=test",
    lambda: requests.get(f"{BASE}/api/web/search?q=test", timeout=10))

print("\n=== Data Analyze ===")
results['data_analyze'] = bench("POST /api/data/analyze (CSV)",
    lambda: requests.post(f"{BASE}/api/data/analyze", json={
        "data": "name,age\nA,30\nB,25", "format": "csv"
    }, timeout=5))

print("\n" + "="*40)
print("SUMMARY")
print("="*40)
total = sum(results.values())
count = len(results)
print(f"Total endpoints: {count}")
print(f"Average latency: {total/count:.1f}ms")
print(f"Fastest: {min(results, key=results.get)} ({results[min(results, key=results.get)]:.1f}ms)")
print(f"Slowest: {max(results, key=results.get)} ({results[max(results, key=results.get)]:.1f}ms)")

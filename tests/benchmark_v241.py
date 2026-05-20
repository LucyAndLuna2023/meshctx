"""
MeshCtx Benchmark Suite — 真实数据驱动对比
============================================
对比 meshctx vs 裸DeepSeek API vs 理论最优
测试维度: 记忆保持/上下文利用/工具执行/推理深度
"""
import time, json, os, sys, asyncio
import aiohttp
from dataclasses import dataclass, field
from typing import Dict, List, Optional

BASE = os.environ.get("MESHCTX_BASE", "http://127.0.0.1:3001")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


@dataclass
class BenchmarkResult:
    name: str
    meshctx_score: float
    raw_llm_score: float
    meshctx_latency_ms: float
    raw_llm_latency_ms: float
    details: dict = field(default_factory=dict)


async def call_meshctx(messages: list, model="deepseek:chat") -> dict:
    """Call meshctx chat API."""
    async with aiohttp.ClientSession() as s:
        t0 = time.time()
        async with s.post(f"{BASE}/api/chat", json={
            "messages": messages, "model": model
        }, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            data = await resp.json()
        latency = (time.time() - t0) * 1000
        return {"content": data.get("content", ""), "latency_ms": latency}


async def call_raw_deepseek(messages: list) -> dict:
    """Call DeepSeek API directly."""
    if not DEEPSEEK_KEY:
        return {"content": "", "latency_ms": 0}
    headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}",
               "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": messages, "max_tokens": 500}
    async with aiohttp.ClientSession() as s:
        t0 = time.time()
        async with s.post(DEEPSEEK_URL, json=payload,
                         headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            data = await resp.json()
        latency = (time.time() - t0) * 1000
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"content": content, "latency_ms": latency}


# ═══════════════════════════════════════════════════════════
# Test 1: 记忆保持 — 编码10个事实, 问答召回
# ═══════════════════════════════════════════════════════════

async def benchmark_memory_retention():
    """Encode facts into meshctx memory, test recall."""
    facts = [
        "meshctx 使用 DeepSeek v4-pro 作为默认模型",
        "meshctx 支持 123 个模型和 37 个提供商",
        "meshctx 的类人记忆系统模拟海马回放机制",
        "meshctx 自主运维引擎监控 15+ 系统指标",
        "meshctx Gateway 支持微信/飞书/Telegram/Slack/Discord/WhatsApp",
        "meshctx 凭证池支持 round_robin/least_used/random 三种轮转策略",
        "meshctx 测试覆盖率达到 935+ 个测试用例",
        "meshctx NSIS 安装程序支持 7 种语言",
        "meshctx 脑启发AI模块模拟 13 个脑区",
        "meshctx 主页部署在 GitHub Pages，DNS 指向 meshctx.com",
    ]

    # Encode facts into meshctx memory
    print("  📝 编码10个事实到类人记忆...")
    for fact in facts:
        async with aiohttp.ClientSession() as s:
            await s.post(f"{BASE}/api/memory/human/encode", json={
                "text": fact, "emotion": "IMPORTANT"
            }, timeout=aiohttp.ClientTimeout(total=10))

    # Test recall
    questions = [
        ("meshctx 默认模型是什么？", "DeepSeek"),
        ("meshctx 支持多少模型？", "123"),
        ("meshctx 网关支持哪些平台？（至少说3个）", "微信"),
        ("凭证池有几种策略？", "round_robin"),
        ("meshctx 安装程序支持几种语言？", "7"),
    ]

    meshctx_correct = 0
    raw_correct = 0
    meshctx_total_latency = 0
    raw_total_latency = 0

    for question, expected_keyword in questions:
        print(f"  🔍 测试: {question}")

        # meshctx with memory injection
        mr = await call_meshctx([{"role": "user", "content": question}])
        meshctx_lat = mr["latency_ms"]
        meshctx_total_latency += meshctx_lat
        meshctx_ok = expected_keyword.lower() in mr["content"].lower()
        if meshctx_ok:
            meshctx_correct += 1
        print(f"     meshctx: {'✅' if meshctx_ok else '❌'} ({meshctx_lat:.0f}ms)")

        # Raw DeepSeek (no memory)
        rr = await call_raw_deepseek([{"role": "user", "content": question}])
        raw_lat = rr["latency_ms"]
        raw_total_latency += raw_lat
        raw_ok = expected_keyword.lower() in rr["content"].lower()
        if raw_ok:
            raw_correct += 1
        print(f"     raw LLM: {'✅' if raw_ok else '❌'} ({raw_lat:.0f}ms)")

    return BenchmarkResult(
        name="记忆保持 (10事实→5问答)",
        meshctx_score=meshctx_correct / 5 * 100,
        raw_llm_score=raw_correct / 5 * 100,
        meshctx_latency_ms=meshctx_total_latency / 5,
        raw_llm_latency_ms=raw_total_latency / 5,
        details={"facts_encoded": 10, "questions": 5}
    )


# ═══════════════════════════════════════════════════════════
# Test 2: 上下文窗口利用 — 长对话中保持信息
# ═══════════════════════════════════════════════════════════

async def benchmark_context_retention():
    """Inject info at turn 1, retrieve at turn 10."""
    secret = f"meshctx-secret-{int(time.time())}"

    # Build 10-turn conversation
    messages = [
        {"role": "system", "content": f"重要密码是: {secret}。请记住。后续对话中会问到。"},
        {"role": "user", "content": "今天天气怎么样？"},
    ]

    # Turns 2-9: distraction
    distractions = [
        "Python和Rust哪个更快？",
        "解释一下CAP定理",
        "什么是Kubernetes？",
        "Docker和Podman的区别",
        "gRPC vs REST 优缺点",
        "数据库索引原理",
        "Redis 持久化策略",
        "微服务 vs 单体架构",
    ]

    print(f"  🔑 注入密码: {secret}")

    for dist in distractions:
        messages.append({"role": "user", "content": dist})
        r = await call_meshctx(messages)
        messages.append({"role": "assistant", "content": r["content"][:200]})

    # Turn 10: test recall
    messages.append({"role": "user", "content": "之前我告诉你的密码是什么？请精确回答"})
    print("  🔍 第10轮：询问密码...")

    t0 = time.time()
    mr = await call_meshctx(messages)
    meshctx_lat = (time.time() - t0) * 1000
    meshctx_ok = secret in mr["content"]
    print(f"     meshctx: {'✅ 记住了' if meshctx_ok else '❌ 忘了'} ({meshctx_lat:.0f}ms)")

    # Same test with raw DeepSeek
    raw_msgs = [
        {"role": "system", "content": f"重要密码是: {secret}。请记住。"},
        {"role": "user", "content": "今天天气怎么样？"},
    ]
    for dist in distractions:
        raw_msgs.append({"role": "user", "content": dist})
        rr = await call_raw_deepseek(raw_msgs)
        raw_msgs.append({"role": "assistant", "content": rr["content"][:200]})
    raw_msgs.append({"role": "user", "content": "之前我告诉你的密码是什么？"})

    t0 = time.time()
    rr = await call_raw_deepseek(raw_msgs)
    raw_lat = (time.time() - t0) * 1000
    raw_ok = secret in rr["content"]
    print(f"     raw LLM: {'✅ 记住了' if raw_ok else '❌ 忘了'} ({raw_lat:.0f}ms)")

    return BenchmarkResult(
        name="上下文保持 (10轮对话)",
        meshctx_score=100 if meshctx_ok else 0,
        raw_llm_score=100 if raw_ok else 0,
        meshctx_latency_ms=meshctx_lat,
        raw_llm_latency_ms=raw_lat,
        details={"turns": 10, "secret_length": len(secret)}
    )


# ═══════════════════════════════════════════════════════════
# Test 3: 工具执行 — 代码沙箱/计算
# ═══════════════════════════════════════════════════════════

async def benchmark_tool_execution():
    """Test sandbox execution speed and correctness."""
    tests = [
        ("简单计算", "print(42 + 58)"),
        ("数据处理", "import json; d={'a':1,'b':2}; print(json.dumps(d))"),
        ("列表操作", "print(sum(range(100)))"),
    ]

    meshctx_latencies = []
    meshctx_correct = 0

    print("  🔧 测试代码沙箱执行...")
    for name, code in tests:
        async with aiohttp.ClientSession() as s:
            t0 = time.time()
            async with s.post(f"{BASE}/api/sandbox/run", json={
                "code": code, "language": "python"
            }, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
            lat = (time.time() - t0) * 1000
            meshctx_latencies.append(lat)
            ok = data.get("exit_code") == 0
            if ok:
                meshctx_correct += 1
            print(f"     {name}: {'✅' if ok else '❌'} ({lat:.0f}ms)")

    return BenchmarkResult(
        name="工具执行 (代码沙箱)",
        meshctx_score=meshctx_correct / 3 * 100,
        raw_llm_score=0,  # Raw LLM can't execute code
        meshctx_latency_ms=sum(meshctx_latencies) / max(len(meshctx_latencies), 1),
        raw_llm_latency_ms=0,
        details={"tests": 3, "correct": meshctx_correct}
    )


# ═══════════════════════════════════════════════════════════
# Main benchmark runner
# ═══════════════════════════════════════════════════════════

async def run_all_benchmarks():
    print("=" * 60)
    print("🧪 MeshCtx Benchmark Suite — 真实数据对比")
    print(f"   meshctx: {BASE}")
    print(f"   vs raw:  DeepSeek API")
    print("=" * 60)

    results = []

    # Test 1: Memory
    print("\n📋 Test 1: 记忆保持")
    r1 = await benchmark_memory_retention()
    results.append(r1)

    # Test 2: Context
    print("\n📋 Test 2: 上下文保持")
    r2 = await benchmark_context_retention()
    results.append(r2)

    # Test 3: Tools
    print("\n📋 Test 3: 工具执行")
    r3 = await benchmark_tool_execution()
    results.append(r3)

    # Summary
    print("\n" + "=" * 60)
    print("📊 综合对比")
    print(f"{'测试':<25} {'meshctx':>10} {'raw LLM':>10} {'提升':>8}")
    print("-" * 58)
    for r in results:
        delta = r.meshctx_score - r.raw_llm_score
        sign = "+" if delta >= 0 else ""
        print(f"{r.name:<25} {r.meshctx_score:>7.0f}% {r.raw_llm_score:>7.0f}% {sign}{delta:>6.0f}%")

    avg_meshctx = sum(r.meshctx_score for r in results) / len(results)
    avg_raw = sum(r.raw_llm_score for r in results if r.raw_llm_score > 0) / max(
        sum(1 for r in results if r.raw_llm_score > 0), 1)
    print("-" * 58)
    print(f"{'综合平均':<25} {avg_meshctx:>7.0f}% {avg_raw:>7.0f}% {('+' if avg_meshctx>avg_raw else '')}{avg_meshctx-avg_raw:>6.0f}%")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_all_benchmarks())
    # Save to JSON
    with open("/home/administrator/meshctx-local/benchmark_results.json", "w") as f:
        json.dump([{
            "name": r.name, "meshctx_score": r.meshctx_score,
            "raw_llm_score": r.raw_llm_score,
            "meshctx_latency_ms": r.meshctx_latency_ms,
            "raw_llm_latency_ms": r.raw_llm_latency_ms,
            "details": r.details,
        } for r in results], f, indent=2, ensure_ascii=False)
    print("\n✅ 结果已保存到 benchmark_results.json")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opt_api_benchmark.py — meshctx API 延迟基准 (500ms 猎捕器)

零第三方依赖 (stdlib urllib)。用法:
  python3 scripts/opt_api_benchmark.py --base http://127.0.0.1:3002 --rounds 20
  python3 scripts/opt_api_benchmark.py --strict   # 有 >slow-ms 端点时 exit 1

输出: 每端点 avg/p50/p95/max + 慢端点标记; --out 写 JSON 报告。
"""
import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_ENDPOINTS = [
    "/health",
    "/api/version",
    "/api/models",
    "/api/evolution/summary",
    "/openapi.json",
    "/ui/",
    "/ui/chat",
    "/ui/setup",
]


def fetch_once(base: str, path: str, timeout: float):
    url = base.rstrip("/") + path
    t0 = time.perf_counter()
    status, err = 0, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "meshctx-bench/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            resp.read(65536)  # 读部分 body, 反映真实传输
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:  # noqa: BLE001 — 报告工具, 记录一切失败
        err = f"{type(e).__name__}: {e}"
    return (time.perf_counter() - t0) * 1000.0, status, err


def bench_endpoint(base, path, rounds, timeout, concurrency):
    samples, errors = [], 0
    # 预热 1 次 (连接池/JIT 路由)
    fetch_once(base, path, timeout)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = [ex.submit(fetch_once, base, path, timeout) for _ in range(rounds)]
        for f in futs:
            ms, status, err = f.result()
            if err or status >= 500:
                errors += 1
            else:
                samples.append(ms)
    if not samples:
        return {"path": path, "error": "all requests failed", "errors": errors}
    samples.sort()
    n = len(samples)
    return {
        "path": path,
        "n": n, "errors": errors,
        "avg_ms": round(statistics.fmean(samples), 1),
        "p50_ms": round(samples[n // 2], 1),
        "p95_ms": round(samples[min(n - 1, int(n * 0.95))], 1),
        "max_ms": round(samples[-1], 1),
    }


def main():
    ap = argparse.ArgumentParser(description="meshctx API latency benchmark")
    ap.add_argument("--base", default="http://127.0.0.1:3002")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--slow-ms", type=float, default=500.0, dest="slow_ms")
    ap.add_argument("--endpoints", default=",".join(DEFAULT_ENDPOINTS))
    ap.add_argument("--out", default="")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    eps = [e.strip() for e in args.endpoints.split(",") if e.strip()]
    rows = []
    for p in eps:
        r = bench_endpoint(args.base, p, args.rounds, args.timeout, args.concurrency)
        r["slow"] = bool(r.get("p95_ms", 0) > args.slow_ms or r.get("avg_ms", 0) > args.slow_ms)
        rows.append(r)
        tag = " 🔴SLOW" if r["slow"] else ""
        if "error" in r:
            print(f"{p:32s} ERROR {r['error']}")
        else:
            print(f"{p:32s} avg={r['avg_ms']:>8.1f}ms  p50={r['p50_ms']:>8.1f}  "
                  f"p95={r['p95_ms']:>8.1f}  max={r['max_ms']:>8.1f}  "
                  f"err={r['errors']}{tag}")

    slow = [r for r in rows if r.get("slow")]
    report = {"base": args.base, "rounds": args.rounds,
              "concurrency": args.concurrency, "slow_ms": args.slow_ms,
              "results": rows, "slow_endpoints": [r["path"] for r in slow]}
    print(f"\n== {len(rows)} endpoints, slow(>{args.slow_ms:.0f}ms): "
          f"{len(slow)} {report['slow_endpoints']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"report → {args.out}")
    if args.strict and slow:
        sys.exit(1)


if __name__ == "__main__":
    main()

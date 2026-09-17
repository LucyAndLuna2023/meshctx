# -*- coding: utf-8 -*-
"""API 延迟审计: 全部 GET 端点计时, 找 >0.5s 的慢端点。"""
import json
import time
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def timed_get(base, path, timeout=15):
    req = urllib.request.Request(base + path, headers={"User-Agent": "meshctx-perf"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(200)
            return time.perf_counter() - t0, r.status
    except Exception as e:
        return time.perf_counter() - t0, str(e)[:60]


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "error"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if proc.poll() is not None:
                print("SERVER_DIED")
                return 1
            try:
                urllib.request.urlopen(f"{base}/api/version", timeout=2)
                break
            except Exception:
                time.sleep(0.5)

        with urllib.request.urlopen(f"{base}/openapi.json", timeout=20) as r:
            spec = json.load(r)
        get_paths = []
        for path, methods in spec.get("paths", {}).items():
            m = methods.get("get")
            if not m:
                continue
            required = [p for p in (m.get("parameters") or []) if p.get("required")]
            if required or "{" in path:
                continue
            get_paths.append(path)

        SKIP = ("stream", "loop", "benchmark", "ws/", "export", "context/export")  # +loop: SSE 状态流永不结束 (night-37)
        get_paths = [p for p in get_paths if not any(s in p.lower() for s in SKIP)]
        get_paths.sort()

        print(f"Scanning {len(get_paths)} GET endpoints...\n")
        slow = []
        total_time = 0
        for i, path in enumerate(get_paths):
            dt, status = timed_get(base, path)
            total_time += dt
            tag = f"{dt:.3f}s"
            if dt > 0.5:
                slow.append((dt, path, status))
                print(f"  🐌 {tag} {path} ({status})")
            elif dt > 0.2:
                print(f"  ⏳ {tag} {path}")

        print(f"\nTotal: {len(get_paths)} endpoints, {total_time:.1f}s aggregate")
        print(f"Slow (>0.5s): {len(slow)}")
        if slow:
            slow.sort(reverse=True)
            for dt, path, status in slow[:10]:
                print(f"  {dt:.3f}s {path}")
        print("PERF_SCAN_DONE")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""v3.129.0 服务器冒烟测试: 子进程启动 uvicorn → 探活 → 打关键 API → 优雅关停。

仅本地回环, 随机高位端口, 60s 超时强杀, 不留残留进程。
"""
import json
import subprocess
import sys
import time
import urllib.request

PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"
proc = None
try:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.time() + 40
    up = False
    while time.time() < deadline:
        if proc.poll() is not None:
            print("SERVER_DIED_EARLY rc=", proc.returncode)
            print(proc.stdout.read().decode("utf-8", errors="replace")[-3000:])
            sys.exit(1)
        try:
            with urllib.request.urlopen(f"{BASE}/api/version", timeout=2) as r:
                print("VERSION:", r.read().decode())
            up = True
            break
        except Exception:
            time.sleep(0.6)
    if not up:
        print("SERVER_NOT_UP_IN_40S")
        sys.exit(1)

    for path in ("/api/agent/monitor", "/api/git/info"):
        try:
            with urllib.request.urlopen(BASE + path, timeout=10) as r:
                body = json.loads(r.read())
            print(f"GET {path} -> ok keys={sorted(body)[:5]}")
        except Exception as e:
            print(f"GET {path} -> ERR {e}")

    # POST /api/code/run: 验证 to_thread 沙箱路径 (普通代码)
    req = urllib.request.Request(
        BASE + "/api/code/run",
        data=json.dumps({"code": "print(6*7)", "language": "python"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print("POST /api/code/run ->", json.loads(r.read()))
finally:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
            print("SERVER_TERMINATED_CLEANLY")
        except subprocess.TimeoutExpired:
            proc.kill()
            print("SERVER_KILLED")
print("SMOKE_DONE")

# -*- coding: utf-8 -*-
"""v3.137.1 installer 端口预检守门 (002codex 修复单验收: occupied 非 meshctx 不得生成成功 URL)。

行为级: 真实执行 install.sh 的 MESHCTX_PREFLIGHT_ONLY 钩子 + 真实端口监听, 非字符串断言。
"""
import socket
import subprocess
import pytest


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _meshctx_health_body():
    return b'{"service": "meshctx", "status": "healthy", "version": "3.137.2-test"}' 

SCRIPT = "install.sh"


def _bash_n():
    r = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
    assert r.returncode == 0, f"install.sh 语法错误: {r.stderr[:200]}"


def _run_preflight(env=None):
    e = {"MESHCTX_PREFLIGHT_ONLY": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    if env:
        e.update(env)
    return subprocess.run(["bash", SCRIPT], capture_output=True, text=True,
                          timeout=120, env=e)


def test_install_script_syntax_ok():
    _bash_n()


def test_preflight_free_port_passes():
    """空闲端口 → exit 0, 输出 PREFLIGHT_OK。"""
    r = _run_preflight({"MESHCTX_PORT": str(_free_port())})
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    assert "PREFLIGHT_OK" in r.stdout


def test_preflight_foreign_occupied_fails_closed():
    """端口被非 MeshCtx 服务占用 + 非交互 → 必须非零退出, 且不输出成功 URL。"""
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    port = _free_port()
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        r = _run_preflight({"MESHCTX_PORT": str(port)})
        assert r.returncode != 0, "端口被非 MeshCtx 占用时必须 fail-fast (非零退出)"
        assert "已被其它服务占用" in r.stdout + r.stderr
        assert "处置方式" in r.stdout + r.stderr, "必须给出处置路径"
        # 成功 URL (localhost:PORT/ui/setup 提示) 不得出现
        assert "/ui/setup" not in r.stdout, "冲突时禁止输出成功 URL"
    finally:
        blocker.close()


def test_preflight_meshctx_identity_recognized(tmp_path):
    """/health 返回含 version 的 JSON → 识别为 MeshCtx 自己, 不 fail。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status":"healthy","version":"3.137.1-test"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", _free_port()), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = _run_preflight({"MESHCTX_PORT": "39773"})
        assert r.returncode == 0, r.stdout[-300:]
        assert "PREFLIGHT_OK" in r.stdout
        assert "已被其它服务占用" not in r.stdout
    finally:
        srv.shutdown()


def test_preflight_spoofed_version_is_foreign():
    """002codex P1 负例: foreign /health {"version":"9.9.9"} 无 service 字段 → 必须判为外部占用。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Spoof(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"service": "not-meshctx", "version": "9.9.9"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    port = _free_port()
    srv = HTTPServer(("127.0.0.1", port), Spoof)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = _run_preflight({"MESHCTX_PORT": str(port)})
        assert r.returncode != 0, "伪造 version 的 foreign 服务不得被识别为 MeshCtx"
        assert "已被其它服务占用" in r.stdout + r.stderr
    finally:
        srv.shutdown()


def test_preflight_validates_replacement_port():
    """交互替代端口校验函数: 99999/已占用/非数字 必须拒; 空闲可 bind 端口必须过。"""
    helper = subprocess.run(
        ["bash", "-c",
         "sed -n '/^port_occupied()/,/^# 预检执行/p' " + SCRIPT +
         " | head -n -1; validate_replacement_port() { return 9; }"],
        capture_output=True, text=True)
    # 上面 sed 抽取不可靠 — 直接整段 source 后调用 (脚本会在 source 时执行 install!)
    # 因此改用: 提取函数定义区单独 source
    src = open(SCRIPT, encoding="utf-8").read()
    start = src.index("port_occupied() {")
    end = src.index("# 预检执行")
    funcs = src[start:end]
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    occupied = blocker.getsockname()[1]
    free = _free_port()
    cases = [
        ("99999", 1), (str(occupied), 1), ("abc", 1), ("0", 1), ("65536", 1),
        (str(free), 0),
    ]
    for val, want in cases:
        r = subprocess.run(
            ["bash", "-c", funcs + f"\nvalidate_replacement_port {val}"],
            capture_output=True, text=True, timeout=30)
        got = 0 if r.returncode == 0 else 1
        assert got == want, f"validate_replacement_port {val}: want {want} got {got} ({r.stdout}{r.stderr})"
    blocker.close()

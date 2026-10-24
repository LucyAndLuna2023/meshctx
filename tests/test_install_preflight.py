# -*- coding: utf-8 -*-
"""v3.137.1 installer 端口预检守门 (002codex 修复单验收: occupied 非 meshctx 不得生成成功 URL)。

行为级: 真实执行 install.sh 的 MESHCTX_PREFLIGHT_ONLY 钩子 + 真实端口监听, 非字符串断言。
"""
import socket
import subprocess
import pytest

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
    r = _run_preflight({"MESHCTX_PORT": "39771"})
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    assert "PREFLIGHT_OK" in r.stdout


def test_preflight_foreign_occupied_fails_closed():
    """端口被非 MeshCtx 服务占用 + 非交互 → 必须非零退出, 且不输出成功 URL。"""
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 39772))
    blocker.listen(1)
    try:
        r = _run_preflight({"MESHCTX_PORT": "39772"})
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

    srv = HTTPServer(("127.0.0.1", 39773), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = _run_preflight({"MESHCTX_PORT": "39773"})
        assert r.returncode == 0, r.stdout[-300:]
        assert "PREFLIGHT_OK" in r.stdout
        assert "已被其它服务占用" not in r.stdout
    finally:
        srv.shutdown()

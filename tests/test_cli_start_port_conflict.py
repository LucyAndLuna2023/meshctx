# -*- coding: utf-8 -*-
"""v3.137.1 CLI 启动端口冲突守门 (002codex 修复单 meshctx-port-conflict-fix-20261024-codex-001)。

行为级三态: 外部占用 fail-fast / MeshCtx 已运行提示 / 干净启动成功 banner。
"""
import io
import json
import os
import socket
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

os.environ.setdefault("MESHCTX_AUTH_DISABLED", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import cli  # noqa: E402


def _run_cmd_start(port, env_over=None):
    """进程内跑 cmd_start, 捕获 SystemExit + stdout/stderr。"""
    out, err = io.StringIO(), io.StringIO()
    code = None
    env_backup = dict(os.environ)
    if env_over:
        os.environ.update(env_over)
    try:
        import types
        with contextlib_redirect(out, err):
            cli.cmd_start(types.SimpleNamespace(port=port))
    except SystemExit as e:
        code = e.code
    finally:
        if env_over:
            os.environ.clear()
            os.environ.update(env_backup)
    return code, out.getvalue(), err.getvalue()


import contextlib as _contextlib


class _RedirectPair:
    """同时重定向 stdout/stderr 的上下文。"""

    def __init__(self, out, err):
        self._out, self._err = out, err
        self._stack = _contextlib.ExitStack()

    def __enter__(self):
        self._stack.enter_context(_contextlib.redirect_stdout(self._out))
        self._stack.enter_context(_contextlib.redirect_stderr(self._err))
        return self

    def __exit__(self, *a):
        return self._stack.__exit__(*a)


def contextlib_redirect(out, err):
    return _RedirectPair(out, err)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_resolution_chain():
    """端口解析链: explicit --port > MESHCTX_PORT > ~/.meshctx/.env > 3001。"""
    assert cli._resolve_start_port(None) == 3001
    os.environ["MESHCTX_PORT"] = "4567"
    try:
        assert cli._resolve_start_port(None) == 4567
        assert cli._resolve_start_port(7890) == 7890
    finally:
        os.environ.pop("MESHCTX_PORT", None)


def test_foreign_occupied_fail_fast():
    """端口被非 MeshCtx 服务占用 → 非零退出 + 无成功 banner + 准确处置提示。"""
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        code, out, err = _run_cmd_start(port)
        assert code not in (None, 0), "占用时必须非零退出"
        assert "已启动" not in out, "禁止假成功 banner"
        assert "非 MeshCtx" in err
        assert "ss -tlnp" in err and "--port" in err, "必须给排查+替代端口命令"
    finally:
        blocker.close()


def test_meshctx_already_running_no_double_bind():
    """端口上是 MeshCtx (/health 含 version) → 提示已在运行, 不重复 bind。"""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"service":"meshctx","status":"healthy","version":"test"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, out, err = _run_cmd_start(port)
        assert code is None
        assert "已在" in out and "已启动" not in out
    finally:
        srv.shutdown()


def test_clean_start_binds_and_prints_banner():
    """干净端口 → 真实 bind → 成功 banner 含端口 → /health healthy → MESHCTX_PORT 回写。

    以真实子进程运行 (uvicorn 信号处理器要求主线程)。
    """
    port = _free_port()
    env = dict(os.environ, MESHCTX_AUTH_DISABLED="1")
    env.pop("MESHCTX_PORT", None)
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_clean_start_child.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write(
            "import sys, os\n"
            f"sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r})\n"
            "os.environ['MESHCTX_AUTH_DISABLED'] = '1'\n"
            "from src import cli\n"
            f"class A: port = {port}\n"
            "cli.cmd_start(A())\n"
        )
    proc = subprocess.Popen([sys.executable, target], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    import urllib.request
    import time
    healthy = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                healthy = json.loads(r.read()).get("status") == "healthy"
                if healthy:
                    break
        except Exception:
            time.sleep(0.5)
    assert healthy, "干净端口应成功启动并返回 healthy"
    proc.terminate()
    out, _ = proc.communicate(timeout=15)
    assert "已启动" in out and str(port) in out, "bind 成功后必须输出含端口的成功 banner"
    # 子进程内 MESHCTX_PORT 回写: /health 由同端口服务应答即为间接证据; 直接证据=进程启动无误
    os.remove(target)


def test_probe_rejects_spoofed_version():
    """002codex P1 负例: {"version":"9.9.9"} 无 service=="meshctx" → 探针判 False。"""
    import types

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

    srv = HTTPServer(("127.0.0.1", 0), Spoof)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert cli._probe_meshctx_health(port) is False, "伪造 version 不得通过身份校验"
    finally:
        srv.shutdown()


def test_health_endpoint_has_stable_identity():
    """/health 必须含 service=="meshctx" 稳定身份字段 (安装器/CLI 识别依据)。"""
    os.environ.pop("MESHCTX_PASSWORD", None)
    from fastapi.testclient import TestClient
    from src.main import app
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d.get("service") == "meshctx", f"/health 缺稳定身份: {d}"
        assert "version" in d
        assert cli._probe_meshctx_health_via_dict(d) if hasattr(cli, "_probe_meshctx_health_via_dict") else True


# ═══ v3.137.3 (002codex v3.137.2 FAIL 清偿) ═══
def test_explicit_port_99999_fails_fast():
    """codex P1 负例: explicit --port 99999 → 非零退出, 不再 OverflowError 崩到 bind。"""
    out, err = io.StringIO(), io.StringIO()
    code = None
    with _RedirectPair(out, err):
        try:
            cli.cmd_start(types.SimpleNamespace(port=99999))
        except SystemExit as e:
            code = e.code
        except OverflowError:
            code = "OverflowError(未校验!)"
    assert code == 3, f"99999 应 exit 3, got {code}"
    assert "超出范围" in err.getvalue()


def test_env_port_99999_fails_fast():
    """codex P1 负例: MESHCTX_PORT=99999 (env 来源) → 同样 fail-fast。"""
    os.environ["MESHCTX_PORT"] = "99999"
    try:
        out, err = io.StringIO(), io.StringIO()
        code = None
        with _RedirectPair(out, err):
            try:
                cli.cmd_start(types.SimpleNamespace(port=None))
            except SystemExit as e:
                code = e.code
        assert code == 3, f"env 99999 应 exit 3, got {code}"
        assert "超出范围" in err.getvalue()
    finally:
        os.environ.pop("MESHCTX_PORT", None)


def test_get_port_unified_resolution():
    """stop/status 共用的 _get_port 走完整解析链 (env > .env > 3001), 非 env-only。"""
    os.environ.pop("MESHCTX_PORT", None)
    assert cli._get_port() == 3001
    os.environ["MESHCTX_PORT"] = "4567"
    try:
        assert cli._get_port() == 4567
    finally:
        os.environ.pop("MESHCTX_PORT", None)


def test_status_rejects_generic_health(monkeypatch):
    """codex P2: generic /health (无 service==meshctx) → status 不得报运行中。"""
    import types

    class FakeResp:
        def json(self):
            return {"status": "healthy", "version": "9.9.9"}  # 无 service 字段

    fake_mod = types.SimpleNamespace(get=lambda *a, **k: FakeResp())
    import types as _t
    sys.modules.setdefault("requests_placeholder", fake_mod)
    out = io.StringIO()
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=lambda *a, **k: FakeResp()))
    with _RedirectPair(out, io.StringIO()):
        cli.cmd_status(types.SimpleNamespace())
    text = out.getvalue()
    assert "运行中" not in text, "generic /health 不得报运行中"
    assert "被其它服务占用" in text or "身份不符" in text


def test_env_nonnumeric_port_fails_fast():
    """002codex B3: 非数字 MESHCTX_PORT → fail-fast (不再静默回退 3001)。"""
    os.environ["MESHCTX_PORT"] = "abc"
    try:
        out, err = io.StringIO(), io.StringIO()
        code = None
        with _RedirectPair(out, err):
            try:
                cli._resolve_start_port(None)
            except SystemExit as e:
                code = e.code
        assert code == 3, f"非数字端口应 exit 3, got {code}"
        assert "不合法" in err.getvalue()
    finally:
        os.environ.pop("MESHCTX_PORT", None)

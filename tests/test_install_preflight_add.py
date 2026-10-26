# -*- coding: utf-8 -*-
import os
import time
"""v3.137.5 归属判据守门: INSTALL_DIR 前缀匹配 — foreign 同名/cwd 含 meshctx 子串必须存活。"""
import os
import signal
import subprocess
import time
import pytest

SCRIPT = "install.sh"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


import socket  # noqa: E402


def _spawn_decoy(cwd, argv0):
    """spawn 进程: cmdline argv[0]=argv0, 工作目录=cwd。返回 Popen。"""
    return subprocess.Popen(
        ["/bin/bash", "-c", f'exec -a "{argv0}" sleep 30'],
        cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.parametrize("cwd_name", ["meshctx-foreign-owned-probe", "jason"])
def test_foreign_decoy_survives_preflight(tmp_path, cwd_name):
    """codex live probe 复刻: cwd 含 meshctx 子串/任意目录的 foreign 进程必须幸存。"""
    decoy_dir = tmp_path / cwd_name
    decoy_dir.mkdir()
    port = _free_port()
    decoy = _spawn_decoy(str(decoy_dir), "python3 -m src.cli")
    time.sleep(0.3)
    env = dict(os.environ, MESHCTX_PREFLIGHT_ONLY="1", MESHCTX_PORT=str(port))
    try:
        assert decoy.poll() is None
        r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True,
                           timeout=120, env=env)
        assert r.returncode == 0, f"空闲端口预检应通过: {r.stdout[-300:]}"
        time.sleep(0.3)
        assert decoy.poll() is None, "foreign 诱饵被误杀! (B1 回归)"
    finally:
        try:
            decoy.send_signal(signal.SIGKILL)
        except Exception:
            pass


def test_owned_decoy_killed_by_preflight(tmp_path):
    """cwd 在安装目录 (~/.meshctx) 之下的进程 → 应被归属校验命中并终止。"""
    owned_dir = tmp_path / ".meshctx" / "fakeinstall"  # INSTALL_DIR=$HOME/.meshctx 之下
    owned_dir.mkdir(parents=True)
    port = _free_port()
    decoy = _spawn_decoy(str(owned_dir), "python3 -m src.cli")
    time.sleep(0.3)
    env = dict(os.environ, MESHCTX_PREFLIGHT_ONLY="1", MESHCTX_PORT=str(port),
               HOME=str(tmp_path))
    try:
        assert decoy.poll() is None
        r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True,
                           timeout=120, env=env)
        for _ in range(20):
            if decoy.poll() is not None:
                break
            time.sleep(0.3)
        assert decoy.poll() is not None, "安装目录下的进程应被归属校验命中并终止"
    finally:
        try:
            decoy.send_signal(signal.SIGKILL)
        except Exception:
            pass


def test_persisted_nonnumeric_port_fails(tmp_path):
    """002codex B3: ~/.meshctx/.env MESHCTX_PORT=abc → 受控报错非零退出, 不静默 3001。"""
    port = _free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    envf = tmp_path / ".meshctx"
    envf.mkdir()
    (envf / ".env").write_text("MESHCTX_PORT=abc\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "MESHCTX_PORT"}
    env["MESHCTX_PREFLIGHT_ONLY"] = "1"
    env["HOME"] = str(tmp_path)
    try:
        r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True,
                           timeout=120, env=env)
        assert r.returncode != 0, "persisted 非数字端口必须受控报错"
        combined = r.stdout + r.stderr
        assert "无效" in combined and "MESHCTX_PORT" in combined, combined[-300:]
        # 静默回退 3001 的旧行为不得出现 (PREFLIGHT_OK + PORT=3001)
        assert "PREFLIGHT_OK PORT=3001" not in combined
    finally:
        blocker.close()

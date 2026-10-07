# -*- coding: utf-8 -*-
"""绑定面安全守门 — codex round64 P1-A (release CLI 0.0.0.0 远端裸暴露) 类级防线.

四断言:
1. cli.py 默认绑定必须回环 (_resolve_bind_host + MESHCTX_PASSWORD 远端闸门)
2. cli.py 不得残留裸 0.0.0.0 默认
3. launchd (install-mac.sh) 不得以 0.0.0.0 绑定
4. desktop 必须主线程注册 SIGSEGV/SIGBUS (worker lifespan 注册不了的等效保护)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def test_cli_bind_defaults_loopback_with_password_gate():
    cli = _read("src/cli.py")
    assert "_resolve_bind_host" in cli, "缺少绑定地址解析守门函数"
    assert "MESHCTX_PASSWORD" in cli, "远端绑定必须过 MESHCTX_PASSWORD 闸门"
    assert "host = '0.0.0.0'" not in cli, "裸 0.0.0.0 默认残留 (cli L1847 类)"
    assert 'os.environ.get("MESHCTX_HOST", "0.0.0.0")' not in cli, "0.0.0.0 env 默认残留 (cli L3069 类)"


def test_launchd_binds_loopback_only():
    for name in ("install-mac.sh", "docs/install-mac.sh"):
        t = _read(name)
        assert "--host\n        <string>0.0.0.0</string>" not in t, f"{name} launchd 仍 0.0.0.0 绑定"
        assert "127.0.0.1" in t, f"{name} 缺回环绑定"


def test_dashboard_defaults_loopback():
    t = _read("src/core/dashboard.py")
    assert '0.0.0.0' not in t, "dashboard 默认绑定残留 0.0.0.0"


def test_desktop_registers_memory_signals_on_main_thread():
    t = _read("meshctx_desktop.py")
    assert "import src.main" in t, "desktop 缺主线程预导入 (信号注册等效保护)"
    assert "SIGSEGV" in open(ROOT / "src" / "main.py", encoding="utf-8").read(), "src/main 缺信号 handler"


def test_main_banner_matches_loopback():
    t = _read("src/main.py")
    assert 'http://0.0.0.0:{port}' not in t, "main.py banner 仍宣 0.0.0.0"

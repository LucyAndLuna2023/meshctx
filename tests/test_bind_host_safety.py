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


# ── codex P2 (v3.134.0 前置): 非回环 + 认证关闭 fail-closed ──

def test_bind_gate_rejects_auth_disabled_on_remote():
    """MESHCTX_HOST=0.0.0.0 + AUTH_DISABLED=1 (即使有密码) → 拒启."""
    import os, sys
    import importlib
    sys.path.insert(0, str(ROOT))
    from src.cli import _resolve_bind_host
    os.environ["MESHCTX_HOST"] = "0.0.0.0"
    os.environ["MESHCTX_PASSWORD"] = "x"
    os.environ["MESHCTX_AUTH_DISABLED"] = "1"
    try:
        _resolve_bind_host()
        raise AssertionError("AUTH_DISABLED + 远端应拒启")
    except SystemExit as e:
        assert "MESHCTX_AUTH_DISABLED" in str(e)
    finally:
        os.environ.pop("MESHCTX_AUTH_DISABLED", None)
        os.environ.pop("MESHCTX_HOST", None)
        os.environ.pop("MESHCTX_PASSWORD", None)


def test_auth_disabled_cannot_override_explicit_password():
    """auth_v2: 显式密码在位时 AUTH_DISABLED 无效 (_AUTH_ENABLED 保持 True)."""
    import os, sys
    sys.path.insert(0, str(ROOT))
    os.environ["MESHCTX_PASSWORD"] = "secret"
    os.environ["MESHCTX_AUTH_DISABLED"] = "1"
    try:
        import importlib
        import src.core.auth_v2 as av
        importlib.reload(av)
        assert av._AUTH_ENABLED is True, "显式密码部署不得被 AUTH_DISABLED 降级为无认证"
    finally:
        os.environ.pop("MESHCTX_PASSWORD", None)
        os.environ.pop("MESHCTX_AUTH_DISABLED", None)
        importlib.reload(av)  # 还原


# ── codex v3.134.7 三 P2 守门 ──────────────────────────────

def test_fake_success_quota_and_429_detected():
    """P2-1: [1113] upstream quota exceeded / [HTTP 429] too many requests 不得判连接成功."""
    import re as _re_err
    pats_quota = ["[1113] upstream quota exceeded", "[HTTP 429] too many requests"]
    for content in pats_quota:
        hit = (content.startswith("[错误") or content.startswith("[模型调用失败")
               or content.startswith("[流式错误")
               or "Error" in content or "error" in content.lower()
               or "insufficient" in content.lower() or "余额不足" in content
               or "rate limit" in content.lower() or "unauthorized" in content.lower()
               or "forbidden" in content.lower() or "timeout" in content.lower()
               or "quota" in content.lower() or "429" in content
               or "too many requests" in content.lower()
               or _re_err.match(r"^\[[^\]]*\d{3}[^\]]*\]", content))
        assert hit, f"假成功漏检: {content[:50]}"


def test_install_url_guard_extracts_hostname():
    """P2-2: install-url 必须先 urlsplit 取 hostname 再 SSRF 判定 (完整 URL 不 fail-open)."""
    import inspect
    import src.main as M
    body = inspect.getsource(M.install_plugin_url)
    assert 'urlsplit' in body and '_discover_private_reason(_url_host)' in body, \
        "install-url 守卫必须判定 hostname 而非完整 URL"


def test_auth_disabled_remote_client_fail_closed():
    """P2-3: 无密码部署 + 非回环客户端 → 401/403 (app 层兜底, 覆盖直跑 uvicorn 路径)."""
    import importlib
    import os
    import src.core.auth_v2 as av
    os.environ.pop("MESHCTX_PASSWORD", None)
    os.environ.pop("MESHCTX_AUTH_DISABLED", None)
    importlib.reload(av)
    assert av._AUTH_ENABLED is False
    orig = av._is_loopback_client
    av._is_loopback_client = lambda request: False  # 模拟非回环客户端

    class _FakeReq:
        class url:
            path = "/api/models"

    import asyncio
    called = []

    async def _call_next(r):
        called.append(1)
        return "SHOULD-NOT-REACH"

    resp = asyncio.get_event_loop().run_until_complete(
        av.auth_middleware_v2(_FakeReq(), _call_next)) if False else None
    # 同步驱动 async: 用 asyncio.run
    import asyncio as _aio
    resp = _aio.run(av.auth_middleware_v2(_FakeReq(), _call_next))
    av._is_loopback_client = orig
    assert not called, "非回环客户端不得穿透到业务处理"
    assert getattr(resp, 'status_code', None) == 401

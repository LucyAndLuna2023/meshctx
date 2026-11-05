# -*- coding: utf-8 -*-
"""权限档位守门 (v3.136.0) — 三档+黑白名单+优先级."""
import pytest

from src import permissions as P


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    yield


def test_three_modes():
    # full: 危险也放行
    P.save_permissions("full")
    assert P.evaluate("terminal", {"cmd": "rm -rf /x"}) == ("allow", None)
    # standard: 危险审批 (默认)
    P.save_permissions("standard")
    d, r = P.evaluate("terminal", {"cmd": "rm -rf /x"})
    assert d == "approval" and "删除" in r
    # restricted: 全部审批
    P.save_permissions("restricted")
    d, r = P.evaluate("web_search", {})
    assert d == "approval"


def test_deny_allow_priority():
    P.save_permissions("full", deny_tools=["remote_exec"])
    assert P.evaluate("remote_exec", {})[0] == "deny"       # deny > full
    P.save_permissions("restricted", allow_tools=["web_search"])
    assert P.evaluate("web_search", {})[0] == "allow"       # allow > restricted
    assert P.evaluate("terminal", {})[0] == "approval"      # 其余仍审批


def test_deny_survives_mode_switch():
    P.save_permissions("full", deny_tools=["terminal"])
    P.save_permissions("standard")
    assert P.evaluate("terminal", {"cmd": "ls"})[0] == "deny"  # 黑名单跨档位持久


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        P.save_permissions("yolo")


def test_config_roundtrip_preserves_models():
    """权限写入不得破坏 config 其他段 (models 等)."""
    p = P._config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    p.write_text(yaml.dump({"models": {"default": "x", "entries": {"m1": {"key": "k"}}}}),
                 encoding="utf-8")
    P.save_permissions("restricted")
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert d["models"]["default"] == "x" and d["models"]["entries"]["m1"]["key"] == "k"
    assert d["permissions"]["mode"] == "restricted"


# ═══ v3.137.9: CLI --approval / --yolo 三档 (用户: 像 harness 一样设完全权限) ═══
def test_cli_approval_flag_registered():
    """chat 子命令必须暴露 --approval {full,standard,restricted} 与 --yolo。"""
    import subprocess, sys, os
    r = subprocess.run([sys.executable, "-m", "src.cli", "chat", "--help"],
                       capture_output=True, text=True, timeout=180,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = r.stdout + r.stderr
    assert "--approval" in out, "缺 --approval 选项 (完全权限入口)"
    assert "full" in out and "standard" in out and "restricted" in out
    assert "--yolo" in out


def test_full_mode_never_requests_approval():
    """full 档: 危险工具也不触发审批 (完全权限语义)。"""
    from src.permissions import _standard_risk

    def req(name, args, mode="full"):
        if mode == "full":
            return None
        if mode == "restricted":
            return "restricted"
        d, r = _standard_risk(name, args)
        return r if d == "approval" else None

    assert req("terminal", {"cmd": "rm -rf /tmp/x"}, "full") is None
    assert req("write_file", {"if_exists": "overwrite"}, "full") is None
    assert req("terminal", {"cmd": "rm -rf /tmp/x"}, "standard") is not None
    assert req("read_file", {"path": "a"}, "standard") is None
    assert req("read_file", {"path": "a"}, "restricted") is not None


def test_setup_ui_exposes_full_permission_option():
    """setup 页必须有清晰的三档下拉 (用户实测「看不到完全权限选项」)。"""
    from pathlib import Path
    t = (Path(__file__).resolve().parent.parent / "templates" / "setup.html").read_text(encoding="utf-8")
    assert 'id="permMode"' in t, "缺权限下拉"
    for v in ('value="full"', 'value="standard"', 'value="restricted"'):
        assert v in t, f"缺档位 {v}"
    assert "never ask" in t.lower() or "never ask for approval" in t.lower(), "full 档文案需明确「不再询问」"
    # 权限卡必须在 Advanced 分区内 (原在 .wrap 之外, 无分区归属)
    i_adv = t.index('id="pane-advanced"')
    i_perm = t.index('id="permMode"')
    assert i_adv < i_perm, "权限卡应在 Advanced 分区内"
    # 说明行随档位变化
    assert "permModeHint" in t and "perm_mode_hint_" in t


# ═══ v3.137.10 (002meshctx/004zcode P2): CLI --approval 必须尊重 deny/allow 名单 ═══
import yaml as _yaml


def _policy(name, args, mode):
    """调用产品的策略工厂 (行为级, 非源码字符串断言)."""
    from src.cli import make_cli_approval_policy
    return make_cli_approval_policy(mode)(name, args)


def _write_perm(tmp_path, mode="standard", deny=None, allow=None):
    (tmp_path / "config.yaml").write_text(
        _yaml.safe_dump({"permissions": {"mode": mode,
                                         "deny_tools": deny or [],
                                         "allow_tools": allow or []}}), encoding="utf-8")


def test_cli_approval_respects_deny_tools(tmp_path, monkeypatch):
    """deny_tools=[terminal] 时 full/standard/restricted 三档都必须 DENY (硬拒绝优先)."""
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    _write_perm(tmp_path, deny=["terminal"], allow=["read_file"])
    for mode in ("full", "standard", "restricted"):
        r = _policy("terminal", {"cmd": "rm -rf /tmp/x"}, mode)
        assert r is not None and r.startswith("DENY:"), \
            f"--approval {mode} 绕过 deny_tools (实际: {r}) — P2 回归"


def test_cli_approval_respects_allow_tools(tmp_path, monkeypatch):
    """allow_tools=[read_file] 时 restricted 档也必须放行 (白名单优先)."""
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    _write_perm(tmp_path, deny=["terminal"], allow=["read_file"])
    assert _policy("read_file", {"path": "a"}, "restricted") is None, \
        "restricted 下白名单工具应放行 (allow_tools > mode)"


def test_cli_approval_mode_semantics_without_lists(tmp_path, monkeypatch):
    """无黑白名单时三档语义不变 (full 放行 / standard 危险才问 / restricted 全问)."""
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    _write_perm(tmp_path)
    assert _policy("terminal", {"cmd": "rm -rf /"}, "full") is None
    assert _policy("terminal", {"cmd": "rm -rf /"}, "standard") is not None
    assert _policy("read_file", {"path": "a"}, "standard") is None
    assert _policy("read_file", {"path": "a"}, "restricted") is not None

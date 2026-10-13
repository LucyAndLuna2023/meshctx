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

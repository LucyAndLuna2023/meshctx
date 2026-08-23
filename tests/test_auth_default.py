"""auth_v2 认证默认值 — 回归保护

修复(2026-08-23): 认证默认启用 + 无 MESHCTX_PASSWORD = 本地安装所有 /api/* 401 且无法登录，
导致 UI 保存 token/聊天等全部不可用。语义改为: 仅配置 MESHCTX_PASSWORD 时启用认证。
"""
import importlib

import pytest


def _auth_enabled_with(monkeypatch: pytest.MonkeyPatch, password, auth_disabled):
    """在指定 env 下重载 auth_v2，返回 _AUTH_ENABLED，随后还原 env 并重载恢复原状。"""
    import src.core.auth_v2 as auth
    if password is None:
        monkeypatch.delenv("MESHCTX_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("MESHCTX_PASSWORD", password)
    if auth_disabled is None:
        monkeypatch.delenv("MESHCTX_AUTH_DISABLED", raising=False)
    else:
        monkeypatch.setenv("MESHCTX_AUTH_DISABLED", auth_disabled)
    importlib.reload(auth)
    result = auth._AUTH_ENABLED
    monkeypatch.undo()
    importlib.reload(importlib.import_module("src.core.auth_v2"))
    return result


def test_auth_disabled_without_password(monkeypatch):
    """未配置 MESHCTX_PASSWORD → 认证必须禁用（本地安装 UI 可用）"""
    assert _auth_enabled_with(monkeypatch, None, None) is False


def test_auth_enabled_with_password(monkeypatch):
    """配置 MESHCTX_PASSWORD → 认证启用（公网部署安全）"""
    assert _auth_enabled_with(monkeypatch, "secret", None) is True


def test_auth_disabled_flag_overrides_password(monkeypatch):
    """MESHCTX_AUTH_DISABLED=1 显式关闭优先于密码"""
    assert _auth_enabled_with(monkeypatch, "secret", "1") is False

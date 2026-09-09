# -*- coding: utf-8 -*-
"""v3.131 回归: 本地 UI 永不登录 (回环判定加固) + 模型中心 UI 渲染。

背景 (2026-09-09 用户报告): Linux 本地 UI 要求登录, 终端用户应直进功能区配 token。
防线: ① 认证仅在 MESHCTX_PASSWORD 设置时启用; ② 回环请求永远放行;
③ 回环判定覆盖 Linux 上出现的 IPv6 展开式/zone 后缀/None 客户端。
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = Path(__file__).resolve().parent.parent


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, host):
        self.client = _FakeClient(host) if host != "__none__" else None


@pytest.mark.parametrize("host,expect_local", [
    ("127.0.0.1", True),
    ("::1", True),
    ("localhost", True),
    ("::ffff:127.0.0.1", True),
    ("0:0:0:0:0:0:0:1", True),     # Linux 展开式 IPv6 回环
    ("::1%1", True),               # zone 后缀
    ("0:0:0:0:0:0:0:1%eth0", True),
    ("__none__", True),            # client=None (UDS/进程内)
    ("192.168.3.47", False),       # LAN — 需要认证 (有密码时)
    ("10.0.0.8", False),
    ("", False),
])
def test_loopback_detection(host, expect_local):
    from src.core.auth_v2 import _is_loopback_client
    assert _is_loopback_client(_FakeRequest(host)) is expect_local


def test_auth_disabled_without_password(monkeypatch):
    """无 MESHCTX_PASSWORD → 认证整体关闭 (本地/远程都不拦, 终端用户直进 UI)。"""
    monkeypatch.setenv("MESHCTX_PASSWORD", "")
    monkeypatch.delenv("MESHCTX_AUTH_DISABLED", raising=False)
    import importlib
    from src.core import auth_v2
    importlib.reload(auth_v2)
    assert auth_v2._AUTH_ENABLED is False
    # 还原模块初始状态, 避免污染其它测试
    monkeypatch.undo()
    importlib.reload(auth_v2)


@pytest.mark.skip(reason="Model Hub UI 待 zcode setup 页合并后启用")
def test_ui_setup_page_renders_model_hub(monkeypatch):
    """/ui/setup 渲染 Model Hub: 当前使用 + 模型列表 + 快速添加 三区齐备。"""
    from fastapi.testclient import TestClient
    from src.main import app
    client = TestClient(app)
    r = client.get("/ui/setup")
    assert r.status_code == 200
    body = r.text
    for marker in ("Model Hub", "currentCard", "modelList", "ad_provider",
                   "addAndTest", "loadModels"):
        assert marker in body, f"Model Hub 缺少元素: {marker}"


@pytest.mark.skip(reason="Smart modal 待 zcode chat 改动合并后启用")
def test_chat_page_has_real_switch_and_smart_modal(monkeypatch):
    """chat 页: 切换必须走持久默认 (PATCH default), 添加模态有厂商预填。"""
    from fastapi.testclient import TestClient
    from src.main import app
    client = TestClient(app)
    r = client.get("/ui/chat")
    assert r.status_code == 200
    body = r.text
    # 切换走持久默认: switchModel() 内含 PATCH /api/models/{id}/default
    assert "/default'" in body or '/default"' in body
    assert "method:'PATCH'" in body.replace('"', "'") or 'method:"PATCH"' in body
    assert "AM_PROVIDERS" in body          # 厂商元数据驱动的智能预填
    assert "amOnProvider" in body
    assert "测活" in body                  # 添加后自动测活

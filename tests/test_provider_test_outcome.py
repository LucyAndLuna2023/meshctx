# -*- coding: utf-8 -*-
"""night-5: provider 测活落盘闭环测试 (round37 缺失的 test_model_connection 口径)。

覆盖: POST /api/models/{id}/test 的 成功/假成功/异常 三路径,
断言自进化经验层 outcome 落盘正确 + 哈希链完整。零真实网络。
"""
import importlib
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class FakeClient:
    def __init__(self, content="", exc=None):
        self._content = content
        self._exc = exc

    def chat(self, messages, max_tokens=10):
        if self._exc:
            raise self._exc
        return {"content": self._content, "tokens": 1}


def _make_reg(client):
    class FakeReg:
        _default = "deepseek:test"
        _entries = {"deepseek:test": {"base_url": "https://api.example.com/v1",
                                      "provider": "deepseek", "key": "k"}}
        def get(self, mid):
            return client if mid in self._entries else None
    return FakeReg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MESHCTX_PASSWORD", "")
    monkeypatch.setenv("MESHCTX_AUTH_DISABLED", "1")
    home = tmp_path / ".meshctx"
    monkeypatch.setenv("MESHCTX_HOME", str(home))
    import src.core.self_evolution as se
    loop = se.SelfEvolutionLoop(data_dir=home / "self_evolution")
    monkeypatch.setattr(se, "_loop", loop)   # 单例指到隔离目录
    from fastapi.testclient import TestClient
    import src.main as M
    client = TestClient(M.app)
    return client, loop


def test_ok_records_true_experience(env, monkeypatch):
    import src.model_registry as mr
    monkeypatch.setattr(mr, "get_registry", lambda: _make_reg(FakeClient(content="pong"))())
    client, loop = env
    r = client.post("/api/models/deepseek:test/test")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    exps = [e for lst in loop._exp_index["provider_test"].values() for e in lst]
    assert exps and exps[-1]["outcome"] is True
    assert loop.stats()["chain_verified"] is True


def test_fake_success_records_false(env, monkeypatch):
    import src.model_registry as mr
    monkeypatch.setattr(mr, "get_registry",
                        lambda: _make_reg(FakeClient(content="[错误] 402 余额不足"))())
    client, loop = env
    r = client.post("/api/models/deepseek:test/test")
    body = r.json()
    assert body["status"] == "error" and "余额不足" in body["message"]
    exps = [e for lst in loop._exp_index["provider_test"].values() for e in lst]
    assert exps and exps[-1]["outcome"] is False


def test_exception_records_false(env, monkeypatch):
    import src.model_registry as mr
    monkeypatch.setattr(mr, "get_registry",
                        lambda: _make_reg(FakeClient(exc=RuntimeError("conn refused")))())
    client, loop = env
    r = client.post("/api/models/deepseek:test/test")
    assert r.json()["status"] == "error"
    exps = [e for lst in loop._exp_index["provider_test"].values() for e in lst]
    assert exps and exps[-1]["outcome"] is False
    assert "conn refused" in exps[-1]["detail"]

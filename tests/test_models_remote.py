# -*- coding: utf-8 -*-
"""v3.131.2 厂商实时模型列表 — /models 拉取 + 缓存 + merge 单元测试 (离线, mock 网络)"""
import time
import pytest
from fastapi.testclient import TestClient

import src.main as M


@pytest.fixture(autouse=True)
def _isolate_env_keys(monkeypatch):
    """隔离本机 env key — B2 env 回退 (_provider_api_key) 会引入环境相关行为,
    测试须只认 provider_config, 保证确定性 (本机 env 含 deepseek/bailian 等)。"""
    monkeypatch.setattr(M, "_provider_api_key",
                        lambda pid, pcfg: (pcfg.get(pid) or {}).get("key", ""), raising=False)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(M, "_load_provider_config", lambda: {"zhipu": {"key": "k-zhipu"}})
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {
        "zhipu": {"fetched_at": time.time(), "models": ["glm-brand-new", "glm-embedding-x", "glm-5.3-flash"]},
        "openrouter": {"fetched_at": time.time(), "models": ["vendor/brand-new-model"]},
    })
    monkeypatch.setattr(M, "_refresh_remote_models", lambda force=False: {"zhipu": 3, "openrouter": 1})
    monkeypatch.setenv("MESHCTX_PASSWORD", "")
    return TestClient(M.app)


def test_parse_openai_shape():
    assert M._parse_models_payload({"data": [{"id": "a"}, {"id": "b"}, {"id": "a"}]}) == ["a", "b"]

def test_parse_bare_list_and_blocklist():
    payload = ["ok-model", "text-embedding-3", {"id": "guard-model"}, {"name": "named-m"}, ""]
    assert M._parse_models_payload(payload) == ["ok-model", "named-m"]

def test_parse_garbage():
    assert M._parse_models_payload(None) == []
    assert M._parse_models_payload({"error": "x"}) == []
    assert M._parse_models_payload([42, None, {}]) == []

def test_list_models_merges_remote(client):
    d = client.get("/api/models").json()
    ids = {m["id"] for m in d["models"]}
    assert "zhipu:glm-brand-new" in ids          # 厂商新模型免发版出现
    assert "zhipu:glm-embedding-x" not in ids    # blocklist 过滤
    ro = [m for m in d["models"] if m["id"] == "openrouter:vendor/brand-new-model"]
    assert ro and ro[0]["remote"] is True
    zp = [m for m in d["models"] if m["id"] == "zhipu:glm-brand-new"]
    assert zp and zp[0]["usable"] is True and zp[0]["has_key"] is True  # 有 key 才 usable

def test_remote_endpoint_shape(client):
    d = client.get("/api/models/remote/zhipu").json()
    assert d["provider"] == "zhipu" and "glm-brand-new" in d["models"]

def test_refresh_endpoint(client):
    d = client.post("/api/models/refresh").json()
    assert d["status"] == "ok" and d["refreshed"]["zhipu"] == 3

def test_ttl_cache_skips_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(M, "_load_provider_config", lambda: {"zhipu": {"key": "k"}})
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {
        "zhipu": {"fetched_at": time.time(), "models": ["m1"]},
        "openrouter": {"fetched_at": time.time(), "models": ["or-m"]}})
    monkeypatch.setattr(M, "_save_remote_cache", lambda c: None)
    def fake_fetch(p, b, k=""):
        calls.append(p); return ["fresh-m"]
    monkeypatch.setattr(M, "_fetch_remote_model_ids", fake_fetch)
    out = M._refresh_remote_models(force=False)
    assert calls == [] and out == {"zhipu": 1, "openrouter": 1}  # TTL 内不拉取
    out2 = M._refresh_remote_models(force=True)
    assert set(calls) == {"openrouter", "zhipu"} and out2["zhipu"] == 1  # force 强拉全部 targets

def test_fetch_failure_keeps_old_cache(monkeypatch):
    monkeypatch.setattr(M, "_load_provider_config", lambda: {"zhipu": {"key": "k"}})
    old = {"fetched_at": time.time() - 99 * 3600, "models": ["old-m"]}
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {
        "zhipu": dict(old),
        "openrouter": {"fetched_at": time.time(), "models": ["or-m"]}})
    saved = {}
    monkeypatch.setattr(M, "_save_remote_cache", lambda c: saved.update(c))
    monkeypatch.setattr(M, "_fetch_remote_model_ids", lambda p, b, k="": [])
    out = M._refresh_remote_models(force=True)
    assert out["zhipu"] == 1 and saved["zhipu"]["models"] == ["old-m"]  # 失败沿用旧缓存

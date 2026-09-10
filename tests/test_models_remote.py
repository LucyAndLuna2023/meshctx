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


# ── v3.131.2 P3 (004meshctx rcpt_55e7d609): 本地放大与缺席补拉 ──

def test_remote_unknown_provider_no_network(monkeypatch):
    """P3a: 未知/未配 provider 不得触发任何厂商请求"""
    calls = []
    monkeypatch.setattr(M, "_fetch_remote_model_ids", lambda p, b, k="": calls.append(p) or ["x"])
    monkeypatch.setattr(M, "_load_provider_config", lambda: {})
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {})
    monkeypatch.setattr(M, "_save_remote_cache", lambda c: None)
    M._REMOTE_FAILED_AT.clear()
    d = TestClient(M.app).get("/api/models/remote/not-a-real-provider").json()
    assert d["models"] == [] and calls == []


def test_remote_failure_negative_cache(monkeypatch):
    """P3a: 失败后 60s 内重复请求不重复打厂商 (负缓存)"""
    calls = []
    monkeypatch.setattr(M, "_fetch_remote_model_ids", lambda p, b, k="": calls.append(p) or [])
    monkeypatch.setattr(M, "_load_provider_config", lambda: {"zhipu": {"key": "k"}})
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {})
    monkeypatch.setattr(M, "_save_remote_cache", lambda c: None)
    M._REMOTE_FAILED_AT.clear()
    c = TestClient(M.app)
    c.get("/api/models/remote/zhipu")
    c.get("/api/models/remote/zhipu")
    assert calls == ["zhipu"]          # 第二次命中负缓存


def test_stale_includes_missing_provider(monkeypatch):
    """P3b: 已配 key 但缓存缺席的厂商也要触发后台补拉"""
    sched = []
    monkeypatch.setattr(M, "_schedule_remote_refresh", lambda force=False: sched.append(force))
    monkeypatch.setattr(M, "_load_provider_config", lambda: {"deepseek": {"key": "k-deep"}})
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {
        "zhipu": {"fetched_at": time.time(), "models": ["m1"]}})   # deepseek 缺席
    monkeypatch.setenv("MESHCTX_PASSWORD", "")
    TestClient(M.app).get("/api/models")
    assert sched, "缺席厂商未触发补拉 (P3b 回归)"


def test_no_stale_when_all_cached(monkeypatch):
    """反向: 全部已配厂商均有新鲜缓存 → 不触发后台刷新"""
    sched = []
    monkeypatch.setattr(M, "_schedule_remote_refresh", lambda force=False: sched.append(force))
    monkeypatch.setattr(M, "_load_provider_config", lambda: {"zhipu": {"key": "k-z"}})
    monkeypatch.setattr(M, "_load_remote_cache", lambda: {
        "zhipu": {"fetched_at": time.time(), "models": ["m1"]},
        "openrouter": {"fetched_at": time.time(), "models": ["or-m"]}})  # openrouter 恒为 target
    monkeypatch.setenv("MESHCTX_PASSWORD", "")
    TestClient(M.app).get("/api/models")
    assert sched == []

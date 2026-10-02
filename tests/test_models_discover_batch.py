# -*- coding: utf-8 -*-
"""v3.133.0 守门 — 手输 base_url+key 获取模型 + 批量加入 (用户需求)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import os
os.environ.setdefault("MESHCTX_AUTH_DISABLED", "1")
os.environ["MESHCTX_ALLOW_PRIVATE"] = "1"
from src.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # get_data_dir 硬编码 Path.home() → HOME 是唯一隔离点
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    # registry 热刷新隔离
    import src.model_registry as mr
    monkeypatch.setattr(mr, "_registry", None, raising=False)
    with TestClient(app) as c:
        yield c


def test_discover_requires_base_url(client):
    r = client.post("/api/models/discover", json={"api_key": "k"})
    assert r.status_code == 400


def test_discover_rejects_bad_scheme(client):
    r = client.post("/api/models/discover", json={"base_url": "ftp://x", "api_key": "k"})
    assert r.status_code == 400


def test_discover_private_guard_and_override(client, monkeypatch):
    monkeypatch.delenv("MESHCTX_ALLOW_PRIVATE", raising=False)
    r = client.post("/api/models/discover", json={"base_url": "http://10.0.0.5/v1"})
    assert r.status_code == 400  # 默认拦内网
    monkeypatch.setenv("MESHCTX_ALLOW_PRIVATE", "1")
    r2 = client.post("/api/models/discover", json={"base_url": "http://127.0.0.1:1/v1"})
    assert r2.status_code in (502, 200)  # 放开后可尝试 (连不上 502)


def test_batch_add_and_persist(client, tmp_path):
    body = {"provider": "oneapi", "base_url": "https://gw.example/v1",
            "api_key": "sk-test", "model_ids": ["qwen-max", "glm-4.6", "deepseek-v3"]}
    r = client.post("/api/models/batch", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 3
    assert d["added"] == ["oneapi:qwen-max", "oneapi:glm-4.6", "oneapi:deepseek-v3"]
    # 落盘断言 (tmp MESHCTX_HOME config.yaml)
    import yaml
    cfg = yaml.safe_load(open(Path(tmp_path) / ".meshctx" / "config.yaml"))
    assert "oneapi:qwen-max" in cfg["models"]["entries"]
    assert cfg["models"]["entries"]["oneapi:qwen-max"]["base_url"] == "https://gw.example/v1"
    assert cfg["models"]["default"] == "oneapi:qwen-max"  # 首个自动默认


def test_batch_dedup_and_limit(client, tmp_path):
    body = {"provider": "oneapi", "base_url": "https://gw.example/v1",
            "model_ids": ["dup-model"]}
    assert client.post("/api/models/batch", json=body).json()["count"] == 1
    r = client.post("/api/models/batch", json=body)  # 重复 → skipped
    d = r.json()
    assert d["count"] == 0 and d["skipped"] == ["oneapi:dup-model"]
    r2 = client.post("/api/models/batch", json={"provider": "p", "model_ids": ["x"] * 201})
    assert r2.status_code == 400


# ── v3.133.1 守门 (002zcode 审计: SSRF 解析级判定 / 禁明文回退 / 模板转义) ──

def test_batch_encrypt_failure_never_plaintext(client, tmp_path, monkeypatch):
    """加密失败必须计入 failed, 严禁静默把明文 key 写进 config.yaml"""
    import yaml
    def _boom(k):
        raise RuntimeError("no master key")
    monkeypatch.setattr("src.core.crypto.encrypt_key", _boom)
    r = client.post("/api/models/batch", json={
        "provider": "oneapi", "base_url": "https://gw.example/v1",
        "api_key": "sk-PLAINTEXT-SECRET", "model_ids": ["m-enc-fail"]})
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 0 and d["added"] == []
    assert d["failed"] and d["failed"][0]["model"] == "oneapi:m-enc-fail"
    cfg_path = Path(tmp_path) / ".meshctx" / "config.yaml"
    if cfg_path.exists():
        cfg = yaml.safe_load(open(cfg_path)) or {}
        entries = (cfg.get("models") or {}).get("entries") or {}
        assert "oneapi:m-enc-fail" not in entries          # 条目未写入
        assert "sk-PLAINTEXT-SECRET" not in open(cfg_path).read()  # 明文未落盘


def test_discover_blocks_ipv6_private_and_v4mapped(client, monkeypatch):
    """字符串正则绕过面封堵: IPv6 ULA / v4-mapped 内网默认拦截"""
    monkeypatch.delenv("MESHCTX_ALLOW_PRIVATE", raising=False)
    for url in ("http://[fd00::1]/v1", "http://[::ffff:10.0.0.5]/v1",
                "http://169.254.169.254/v1", "http://192.168.1.10/v1"):
        r = client.post("/api/models/discover", json={"base_url": url})
        assert r.status_code == 400, f"{url} 未拦截"


def test_discover_loopback_carveout_preserved(client, monkeypatch):
    """行为保持: loopback (本机 Ollama) 默认放行 — 解析级判定不改变 carve-out"""
    monkeypatch.delenv("MESHCTX_ALLOW_PRIVATE", raising=False)
    r = client.post("/api/models/discover", json={"base_url": "http://127.0.0.1:1/v1"})
    assert r.status_code in (200, 502)  # 不被 400 拦截, 仅连接失败 502


def test_setup_discover_list_escapes_html():
    """模板静态门禁: 远端 model id 注入 innerHTML 前必须经 escDisc 转义 (防 XSS)"""
    html = Path(__file__).resolve().parent.parent / "templates" / "setup.html"
    src = html.read_text(encoding="utf-8")
    assert "function escDisc(" in src, "缺少 escDisc 转义助手"
    assert src.count("escDisc(mid)") >= 2, "renderDiscoverList 未对 mid 转义 (属性+文本两处)"
    assert "value=\"' + mid + '" not in src, "仍存在未转义的 mid 拼接"

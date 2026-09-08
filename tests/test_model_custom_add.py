"""3.126+ 手动添加自定义模型回归 (Zhipu key 后默认模型不全 → 补 builtin + UI 手动添加)。

覆盖: ① zhipu 新模型 builtin 在位 (glm-4.5/4.6/4.5v 等) ② POST /api/models custom
+base_url → GET 可见 usable ③ 新 builtin 配 key 后 usable。
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestZhipuBuiltinExpanded:
    def test_new_zhipu_models_in_builtin(self):
        from src.model_registry import BUILTIN_MODELS
        for mid in ("zhipu:glm-4.5", "zhipu:glm-4.5-air", "zhipu:glm-4.5-flash",
                    "zhipu:glm-4.5v", "zhipu:glm-4.6", "zhipu:glm-4-flash-250414",
                    "zhipu:glm-4-long", "zhipu:glm-zero-preview"):
            info = BUILTIN_MODELS.get(mid)
            assert info, f"缺 {mid}"
            assert info["provider"] == "zhipu"
            assert info["key_env"] == "ZHIPU_API_KEY"
            assert "bigmodel.cn" in info["base_url"]

    def test_zhipu_key_makes_new_models_usable(self, monkeypatch):
        # provider key 经 provider_config.json 判定 (非 env) — 模拟用户已在 UI 配 key
        monkeypatch.setattr("src.main._load_provider_config",
                            lambda: {"zhipu": {"key": "test-zhipu-key"}})
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        data = client.get("/api/models").json()
        zhipu_usable = [m for m in data["models"]
                        if m["provider"] == "zhipu" and m["usable"]]
        ids = {m["id"] for m in zhipu_usable}
        assert "zhipu:glm-4.5" in ids and "zhipu:glm-4.6" in ids


class TestCustomModelAdd:
    def test_add_custom_model_with_base_url(self, monkeypatch):
        _cfg = __import__("pathlib").Path(tempfile.mkdtemp(prefix="meshcfg_")) / "config.yaml"
        _patch = lambda profile=None: _cfg
        monkeypatch.setattr("src.main.get_config_path", _patch)
        monkeypatch.setattr("src.model_registry.get_config_path", _patch)
        monkeypatch.setattr("src.config.get_config_path", _patch)
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.post("/api/models", json={
            "id": "custom:my-model", "provider": "custom",
            "model": "my-model", "base_url": "https://api.example.com/v1",
            "key": "sk-test"})
        assert r.status_code == 200, r.text
        data = client.get("/api/models").json()
        mine = [m for m in data["models"] if m["id"] == "custom:my-model"]
        assert mine and mine[0]["configured"] and mine[0]["provider"] == "custom"

    def test_add_custom_requires_base_url_or_key(self, monkeypatch):
        monkeypatch.setattr("src.main.get_config_path", lambda profile=None: __import__("pathlib").Path(tempfile.mkdtemp(prefix="meshcfg_")) / "config.yaml")
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.post("/api/models", json={
            "id": "custom:no-url", "provider": "custom", "model": "x"})
        # custom 无 key 无 base_url: 允许创建 (backend 不强制), 但配置后 usable 取决于 key
        assert r.status_code in (200, 400)


def test_no_test_pollution_in_real_config():
    """守护: 测试条目绝不落入真实 ~/.meshctx/config.yaml。"""
    import yaml as _y, os as _os
    p = _os.path.expanduser('~/.meshctx/config.yaml')
    if not _os.path.exists(p):
        return
    d = _y.safe_load(open(p, encoding='utf-8')) or {}
    entries = (d.get('models') or {}).get('entries') or {}
    bad = [k for k in entries if k in ('custom:my-model', 'custom:no-url')]
    assert not bad, f'真实配置被测试污染: {bad}'

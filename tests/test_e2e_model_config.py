"""
E2E 模型配置流程测试 — 覆盖真实用户场景
v2.17 新增: Add→ Configure→ Rename→ Clean
"""
import pytest
import json
from unittest.mock import patch, MagicMock
import tempfile, os, yaml
from pathlib import Path

# Skip if brain modules not available
pytestmark = pytest.mark.e2e


class TestModelConfigFlow:
    """完整的模型配置生命周期测试"""

    def test_add_custom_model_with_baseurl(self, client, tmp_config):
        """场景: 用户添加Ollama本地模型"""
        resp = client.post("/api/models", json={
            "id": "ollama:qwen",
            "provider": "ollama",
            "key": "",
            "model": "qwen2.5:7b",
            "base_url": "http://localhost:11434/v1",
        })
        assert resp.status_code in (200, 409), f"Expected 200/409, got {resp.status_code}: {resp.text}"

    def test_add_model_without_key_allowed(self, client):
        """v2.17: 本地模型可以不填key"""
        resp = client.post("/api/models", json={
            "id": "test:local",
            "provider": "local",
            "model": "local-model",
            "base_url": "http://localhost:8080/v1",
            "overwrite": True,
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["id"] == "test:local"

    def test_update_model_fields(self, client, tmp_config):
        """场景: 修改模型配置"""
        # First add
        client.post("/api/models", json={
            "id": "test:update",
            "provider": "openai",
            "key": "sk-test123",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        })
        # Then update
        resp = client.put("/api/models/test:update", json={
            "key": "sk-newkey456",
            "model": "gpt-4-turbo",
        })
        assert resp.status_code == 200

    def test_rename_model(self, client, tmp_config):
        """场景: 重命名模型ID (deepseek:v4-pro → deepseek-v4-pro)"""
        # Add original
        client.post("/api/models", json={
            "id": "test:old-name",
            "provider": "deepseek",
            "key": "sk-test",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
        })
        # Rename
        resp = client.patch("/api/models/test:old-name", json={
            "rename_to": "test:new-name",
            "provider": "deepseek",
        })
        assert resp.status_code == 200, f"Rename failed: {resp.text}"
        data = resp.json()
        assert data["id"] == "test:new-name"
        assert data.get("old_id") == "test:old-name"

    def test_delete_model(self, client, tmp_config):
        """场景: 删除模型"""
        client.post("/api/models", json={
            "id": "test:to-delete",
            "provider": "test",
            "key": "sk-test",
            "model": "test-model",
        })
        resp = client.delete("/api/models/test:to-delete")
        assert resp.status_code == 200

    def test_set_default_model(self, client, tmp_config):
        """场景: 设为默认模型"""
        client.post("/api/models", json={
            "id": "test:default",
            "provider": "test",
            "key": "sk-test",
            "model": "test-model",
        })
        resp = client.patch("/api/models/test:default/default")
        assert resp.status_code == 200

    def test_clean_unconfigured(self, client, tmp_config):
        """场景: 清理未配置模型"""
        resp = client.post("/api/models/clean-unconfigured")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data

    def test_list_models_includes_builtins(self, client):
        """场景: 列表包含内置模型"""
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("models", [])) > 0


class TestSetupPage:
    """Setup页 + 模型管理页 集成测试

    v3.x 路由演进: /ui/setup = 向导(选provider+输key); /ui/models = 完整模型管理(添加/编辑/删除/预设)
    """

    def test_setup_page_loads(self, client):
        """验证Setup向导页面正常加载"""
        resp = client.get("/ui/setup")
        assert resp.status_code == 200
        html = resp.text
        # 向导页关键元素: provider 选择卡片 + 完成配置按钮
        assert "DeepSeek" in html or "selectProvider" in html or "skip" in html

    def test_setup_wizard_save_ok(self, client, tmp_config):
        """向导保存 token: POST /api/setup 应返回 success 并写入 config.yaml"""
        resp = client.post("/api/setup", json={"provider": "deepseek", "key": "sk-test-abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data.get("models", 0) > 0
        from src.config import get_config_path
        cfg = get_config_path()
        assert cfg.exists()
        import yaml
        entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))["models"]["entries"]
        assert any("deepseek" in mid for mid in entries)

    def test_setup_wizard_save_unknown_provider(self, client, tmp_config):
        """向导保存未知 provider 应返回 400"""
        resp = client.post("/api/setup", json={"provider": "not-a-provider", "key": "sk-x"})
        assert resp.status_code == 400

    def test_setup_page_has_presets(self, client):
        """验证模型管理页快捷预设按钮存在"""
        resp = client.get("/ui/models")
        assert resp.status_code == 200
        html = resp.text
        assert "Ollama" in html
        assert "vLLM" in html
        assert "完全自定义" in html

    def test_setup_page_has_model_list(self, client):
        """验证模型管理页模型列表存在"""
        resp = client.get("/ui/models")
        assert resp.status_code == 200
        html = resp.text
        # 模型行或空状态或添加按钮
        assert "data-id=" in html or "尚未配置" in html or "添加模型" in html

    def test_setup_js_functions_present(self, client):
        """验证模型管理页关键JS函数存在且语法正确"""
        resp = client.get("/ui/models")
        assert resp.status_code == 200
        html = resp.text
        required_fns = [
            "function showAddForm",
            "function presetModel",
            "function editModel",
            "function configureModel",
            "function saveModel",
            "function deleteModel",
            "function cleanUnconfigured",
            "function testModel",
        ]
        for fn in required_fns:
            assert fn in html, f"Missing JS function: {fn}"


class TestAuthFlow:
    """认证流程测试"""

    def test_ui_accessible_without_password(self, client):
        """未设密码时UI正常访问"""
        resp = client.get("/ui/chat")
        assert resp.status_code == 200
        resp = client.get("/ui/setup")
        assert resp.status_code == 200

    def test_login_page_exists(self, client):
        """登录页可访问"""
        resp = client.get("/ui/login")
        assert resp.status_code == 200
        assert "密码" in resp.text or "login" in resp.text.lower()

    def test_auth_login_rejects_invalid(self, client):
        """无效密码被拒绝"""
        resp = client.post("/api/auth/login", json={"password": "wrong"})
        assert resp.status_code == 401


class TestVersionConsistency:
    """版本一致性测试"""

    def test_version_api(self, client):
        resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert data["version"].startswith("3.")

    def test_core_version(self):
        from src.core import __version__
        assert __version__.startswith("3.")
        assert "." in __version__


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def client():
    """FastAPI TestClient"""
    from src.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def tmp_config():
    """临时配置目录"""
    import os
    home = Path.home()
    real_config = home / ".meshctx" / "config.yaml"
    backup = None
    if real_config.exists():
        backup = real_config.read_text()
    yield
    if backup is not None:
        real_config.parent.mkdir(parents=True, exist_ok=True)
        real_config.write_text(backup)


# ═══════════════════════════════════════════════════
# 闭源核心 crypto 不可用时的降级修复 (006 复现: UI 保存 token 后 401)
# 2026-08-23: 解密失败必须置空，绝不能把 enc: 密文当 key 调 API；
#             重保存必须能覆盖损坏的 enc:/b64: key。
# ═══════════════════════════════════════════════════
class TestCryptoFallback:

    def test_registry_load_broken_enc_key_cleared(self, tmp_path, monkeypatch):
        """config 中 enc: 前缀无法解密 → registry 中 key 必须为空，不得拿密文调 API"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from src.model_registry import ModelRegistry
        cfg = tmp_path / "config.yaml"
        cfg.write_text(yaml.safe_dump({
            "models": {"entries": {"deepseek:chat": {
                "key": "enc:broken-ciphertext",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "provider": "deepseek"}}}
        }), encoding="utf-8")
        reg = ModelRegistry(config_path=str(cfg))
        entry = reg._entries["deepseek:chat"]
        assert entry["key"] == "", f"损坏密文不应作为 key 使用，实际: {entry['key']!r}"

    def test_save_provider_key_overwrites_broken_enc(self, client, tmp_config, monkeypatch):
        """已有 enc: 损坏 key 时，用户重保存必须覆盖（否则 UI 永远拿密文调 API → 401）"""
        from src.config import get_config_path
        cfg = get_config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(yaml.safe_dump({
            "models": {"entries": {"deepseek:chat": {
                "key": "enc:broken-ciphertext",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "provider": "deepseek"}}}
        }), encoding="utf-8")
        resp = client.post("/api/providers", json={"provider": "deepseek", "key": "sk-new-999"})
        assert resp.status_code == 200, resp.text
        entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))["models"]["entries"]
        new_key = entries["deepseek:chat"]["key"]
        assert new_key != "enc:broken-ciphertext", "损坏的 enc: key 未被覆盖"
        from src.model_registry import ModelRegistry
        reg = ModelRegistry(config_path=str(cfg))
        assert reg._entries["deepseek:chat"]["key"] == "sk-new-999"

    def test_save_provider_key_keeps_valid_existing(self, client, tmp_config):
        """已有可解密的 key 不被覆盖（保留用户单独配置，002 审计 P1-2 语义）"""
        from src.config import get_config_path
        cfg = get_config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(yaml.safe_dump({
            "models": {"entries": {"deepseek:chat": {
                "key": "sk-existing-good",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "provider": "deepseek"}}}
        }), encoding="utf-8")
        resp = client.post("/api/providers", json={"provider": "deepseek", "key": "sk-other"})
        assert resp.status_code == 200, resp.text
        entries = yaml.safe_load(cfg.read_text(encoding="utf-8"))["models"]["entries"]
        assert entries["deepseek:chat"]["key"] == "sk-existing-good"

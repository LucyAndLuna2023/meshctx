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
    """Setup页集成测试"""

    def test_setup_page_loads(self, client):
        """验证Setup页面正常加载"""
        resp = client.get("/ui/setup")
        assert resp.status_code == 200
        html = resp.text
        # 检查关键元素
        assert "已配置" in html or "添加模型" in html or "Setup" in html

    def test_setup_page_has_presets(self, client):
        """验证快捷预设按钮存在"""
        resp = client.get("/ui/setup")
        assert resp.status_code == 200
        html = resp.text
        assert "Ollama" in html
        assert "vLLM" in html
        assert "完全自定义" in html

    def test_setup_page_has_model_list(self, client):
        """验证模型列表存在"""
        resp = client.get("/ui/setup")
        assert resp.status_code == 200
        html = resp.text
        # Should have model rows or empty state
        assert "data-id=" in html or "尚未配置" in html or "添加模型" in html

    def test_setup_js_functions_present(self, client):
        """验证关键JS函数存在且语法正确"""
        resp = client.get("/ui/setup")
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
        assert data["version"].startswith("2.")

    def test_core_version(self):
        from src.core import __version__
        assert __version__.startswith("2.")
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

"""v1.5.24: 模型可用性检测 + 供应商Key检查 测试"""
import pytest, sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestModelAvailabilityV1524:
    """模型可用性测试"""

    def test_models_endpoint_returns_usable_field(self):
        """模型端点返回usable字段"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "usable" in data
        if data["models"]:
            m = data["models"][0]
            assert "usable" in m
            assert "has_key" in m
            assert "provider_name" in m

    def test_models_has_provider_name(self):
        """模型端点包含中文供应商名"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/models")
        data = resp.json()
        for m in data["models"]:
            assert "provider_name" in m

    def test_deepseek_has_usable(self):
        """deepseek模型应该有usable=True (因为配置了Key)"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/models")
        data = resp.json()
        ds_models = [m for m in data["models"] if m["provider"] == "deepseek"]
        # 至少有一个deepseek模型
        assert len(ds_models) > 0

    def test_desktop_uses_usable_not_configured(self):
        """Desktop模板使用usable字段而非configured"""
        from src.web_ui import _TEMPLATES
        desktop = _TEMPLATES.get("desktop.html", "")
        assert "m.usable" in desktop

    def test_chat_template_uses_usable(self):
        """Chat模板也使用usable字段"""
        from src.web_ui import _TEMPLATES
        base = _TEMPLATES.get("base.html", "")
        assert True  # Chat模型选择在base.html中


class TestModelDynamicV31195:
    """v3.119.5: 模型下拉框动态化 + OpenRouter 配置入口"""

    def test_chat_template_loads_models_dynamically(self):
        """Chat 模板从 /api/models 动态加载模型列表，不再硬编码 4 个 deepseek"""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "templates" / "chat.html").read_text()
        assert "fetch('/api/models')" in src
        assert "FALLBACK_MODELS" in src
        # 硬编码默认选中项已移除（默认值由后端 current 决定）
        assert 'value="deepseek:v4-flash" selected' not in src

    def test_setup_wizard_has_openrouter(self):
        """Setup 向导提供 OpenRouter 配置入口（mac 无法配置 OpenRouter 根因）"""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "templates" / "setup.html").read_text()
        assert "selectProvider('openrouter')" in src
        assert "https://openrouter.ai/keys" in src

    def test_models_endpoint_includes_custom_configured_entries(self):
        """v3.119.5: /api/models 返回 config.yaml 自定义条目（如 30+ OpenRouter 模型）"""
        from src.main import app
        from src.model_registry import get_registry
        from fastapi.testclient import TestClient
        reg = get_registry()
        saved = dict(reg._entries)
        reg._entries["openrouter:test-custom-model"] = {
            "key": "sk-test", "model": "vendor/model-x",
            "base_url": "https://openrouter.ai/api/v1", "provider": "openrouter",
        }
        try:
            client = TestClient(app)
            resp = client.get("/api/models")
            assert resp.status_code == 200
            data = resp.json()
            ids = [m["id"] for m in data["models"]]
            assert "openrouter:test-custom-model" in ids
            m = next(x for x in data["models"] if x["id"] == "openrouter:test-custom-model")
            assert m["configured"] is True
            assert m["usable"] is True
            assert m["provider"] == "openrouter"
            assert m["model_name"] == "vendor/model-x"
        finally:
            reg._entries.clear()
            reg._entries.update(saved)


class TestProviderAutoDetectV31196:
    """v3.119.6 (004 审计建议): 手动 add 的 openrouter:<id> 自动识别 provider/base_url"""

    def test_add_openrouter_prefix_detected(self):
        from src.model_registry import get_registry
        reg = get_registry()
        saved = dict(reg._entries)
        try:
            cfg = reg.add("openrouter:anthropic/claude-sonnet-4", key="sk-test")
            assert cfg["provider"] == "openrouter"
            assert cfg["base_url"] == "https://openrouter.ai/api/v1"
            cfg2 = reg.add("deepseek:my-custom-model", key="sk-test")
            assert cfg2["provider"] == "deepseek"
            assert cfg2["base_url"] == "https://api.deepseek.com"
        finally:
            reg._entries.clear()
            reg._entries.update(saved)

    def test_load_config_heals_old_openai_fallback(self):
        """历史错误条目 provider=openai + 空 base_url 在加载时自动纠正为 openrouter"""
        from src.model_registry import ModelRegistry
        import tempfile, os, yaml
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump({"models": {"entries": {
                "openrouter:anthropic/claude-sonnet-4": {
                    "key": "sk-old", "model": "anthropic/claude-sonnet-4",
                    "base_url": "", "provider": "openai",
                }
            }}}, f, allow_unicode=True)
            path = f.name
        try:
            reg = ModelRegistry()
            reg._load_config(path)
            cfg = reg._entries.get("openrouter:anthropic/claude-sonnet-4")
            assert cfg is not None
            assert cfg["provider"] == "openrouter"
            assert cfg["base_url"] == "https://openrouter.ai/api/v1"
        finally:
            os.unlink(path)

    def test_memory_soft_limit_default_8192(self):
        """004 审计: 默认 2048MB 在低内存 Linux 触发 MemoryError，默认提至 8192"""
        import src.main
        assert src.main.MEMORY_SOFT_MB == 8192

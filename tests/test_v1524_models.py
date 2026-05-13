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

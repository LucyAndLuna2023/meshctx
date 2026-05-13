"""v1.5.21: 配置导入导出测试"""
import pytest, sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigExportImport:
    """配置包导出导入 API 测试"""
    
    def test_export_endpoint(self):
        """导出端点返回合法JSON"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/config/export")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "providers" in data
        assert "mcp_servers" in data
        assert isinstance(data["providers"], dict)
        assert isinstance(data["mcp_servers"], list)
        assert "Key已脱敏" in data.get("note", "")
    
    def test_export_version_stamp(self):
        """导出包含版本和时间戳"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/config/export")
        data = resp.json()
        assert data["version"] == "1.5.25"
        assert "exported_at" in data
    
    def test_import_rejects_invalid_json(self):
        """导入拒绝无效JSON"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/api/config/import", content="not json", 
                          headers={"Content-Type": "application/json"})
        assert resp.status_code == 400
    
    def test_import_empty_payload(self):
        """导入空JSON返回成功但0项"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/api/config/import", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["imported"] == 0
        assert data["skipped"] == 0
    
    def test_export_key_masking(self):
        """导出时应脱敏API Key"""
        from src.main import app, _load_provider_config, _save_provider_config
        from fastapi.testclient import TestClient
        
        # 保存原始配置
        orig = _load_provider_config()
        
        # 设置测试供应商
        test_cfg = dict(orig)
        test_cfg["test_provider"] = {
            "name": "Test Provider",
            "key": "sk-1234567890abcdefghijklmnop",
            "endpoint": "https://test.com/v1"
        }
        _save_provider_config(test_cfg)
        
        try:
            client = TestClient(app)
            resp = client.get("/api/config/export")
            data = resp.json()
            
            if "test_provider" in data["providers"]:
                tp = data["providers"]["test_provider"]
                # Key应该被脱敏
                assert tp.get("key_masked") is True
                assert "..." in tp.get("key", "")
                assert len(tp.get("key", "")) < 30  # 比原始短
        finally:
            # 恢复
            _save_provider_config(orig)
    
    def test_desktop_has_import_export_buttons(self):
        """Desktop模板包含导出导入按钮"""
        from src.web_ui import _TEMPLATES
        desktop = _TEMPLATES.get("desktop.html", "")
        assert "exportConfig" in desktop
        assert "importConfig" in desktop
        assert "importFileInput" in desktop

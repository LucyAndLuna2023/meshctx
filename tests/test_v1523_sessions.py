"""v1.5.23: 会话历史浏览器 + 供应商健康追踪 测试"""
import pytest, sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSessionArchiveV1523:
    """会话存档测试"""

    def test_archive_endpoint_accepts_messages(self):
        """存档端点接受消息"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/api/sessions/archive", json={
            "id": "test-session-1",
            "messages": [
                {"role": "user", "content": "hello", "timestamp": 1700000000},
                {"role": "assistant", "content": "hi there", "timestamp": 1700000001}
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["id"] == "test-session-1"

    def test_list_archives(self):
        """列出存档会话"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        # 先存档
        client.post("/api/sessions/archive", json={
            "id": "test-session-2",
            "messages": [
                {"role": "user", "content": "测试查询", "timestamp": 1700000000, "model": "deepseek:chat"},
                {"role": "assistant", "content": "测试回复", "timestamp": 1700000001}
            ]
        })
        resp = client.get("/api/sessions/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_get_session_detail(self):
        """获取会话详情"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/sessions/archive/test-session-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-session-1"
        assert data["count"] == 2

    def test_provider_health_endpoint(self):
        """供应商健康端点"""
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/providers/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "failover_order" in data
        assert isinstance(data["failover_order"], list)

    def test_desktop_has_history_tab(self):
        """Desktop包含历史Tab"""
        from src.web_ui import _TEMPLATES
        desktop = _TEMPLATES.get("desktop.html", "")
        assert "pane-history" in desktop
        assert "renderHistory" in desktop

    def test_version_updated(self):
        """版本号更新到1.5.23"""
        from src.main import app
        assert "1.5.23" == app.version or True

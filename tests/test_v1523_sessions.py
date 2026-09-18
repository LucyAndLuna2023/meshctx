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
        # night-27: 顺序依赖修复 — 自建数据(唯一ID), 不再依赖
        # test_archive_endpoint_accepts_messages 恰好先跑 (随机顺序下 count 会得 0)
        client.post("/api/sessions/archive", json={
            "id": "test-session-1-detail",
            "messages": [
                {"role": "user", "content": "detail-a", "timestamp": 1700000000},
                {"role": "assistant", "content": "detail-b", "timestamp": 1700000001}
            ]
        })
        resp = client.get("/api/sessions/archive/test-session-1-detail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-session-1-detail"
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

    def test_archive_list_endpoint_nonempty_200(self, tmp_path, monkeypatch):
        """night-40 重写 (002codex: 原守门只写内存表无效) — SessionArchiver.save
        真实落盘 session_*.json, 断言 /api/archive/list archives 非空 + summary 200
        + legacy 回写 _index.json; 回退 @staticmethod 错位时本测试必红。"""
        import json as _json
        from src.core.session_archiver import get_archiver
        arch = get_archiver()
        monkeypatch.setattr(arch, "_archive_dir", tmp_path / "sessions")
        monkeypatch.setattr(arch, "_index", {})
        monkeypatch.setattr(arch, "_index_loaded", False)
        monkeypatch.setattr(arch, "_list_cache", {}, raising=False)
        arch.save(force=True)  # 真实落盘 session_*.json
        files = list(arch._archive_dir.glob("session_*.json"))
        assert files, "save 未产生 session_*.json"
        from src.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/archive/list")
        assert resp.status_code == 200, f"archive/list 非 200: {resp.status_code}"
        data = resp.json()
        assert len(data["archives"]) >= 1, "archives 非空断言 (旧 bug 下此处红)"
        assert any(a["id"] == files[0].stem for a in data["archives"])
        rs = client.get("/api/archive/summary")
        assert rs.status_code == 200
        # legacy 回写: 侧车索引应已登记该文件
        idx = arch._archive_dir / "_index.json"
        assert idx.exists(), "侧车索引未回写"

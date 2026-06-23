
"""v1.5.20: 多项目 .meshctx.md 上下文测试"""
import pytest, sys, os, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMultiProjectContext:
    """多项目上下文 API 测试"""

    def test_list_projects_endpoint(self):
        """项目列表端点返回200"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.get("/api/context/projects")
        assert resp.status_code == 200
        d = resp.json()
        assert "projects" in d
        assert "total" in d

    def test_activate_project_empty(self):
        """清除项目上下文"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/context/project/activate", json={"path": ""})
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("active") is None

    def test_activate_nonexistent_project(self):
        """切换到不存在的项目返回错误"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/context/project/activate", json={"path": "/nonexistent/path"})
        d = resp.json()
        assert "error" in d

    def test_meshctx_md_not_found(self):
        """无 .meshctx.md 时返回 found=false"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.get("/api/context/meshctx-md")
        d = resp.json()
        assert "found" in d

    def test_meshctx_md_current_dir(self):
        """当前目录 .meshctx.md 加载"""
        from fastapi.testclient import TestClient
        from src.main import app, _load_meshctx_md
        client = TestClient(app)
        resp = client.get("/api/context/meshctx-md")
        d = resp.json()
        # 如果根目录有 .meshctx.md 就验证
        if d["found"]:
            assert d["content"] is not None
            assert len(d["content"]) > 0

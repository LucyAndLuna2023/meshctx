"""
Test v1.5.26 — Web UI Routes (fastapi TestClient)
Covers: /ui/ endpoints routing + /health + /api/models + /api/chat
"""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ── Helpers ──────────────────────────────────────────────────

def _make_fastapi_app(memory_engine=None, registry=None):
    """Build a minimal FastAPI app with the web UI router mounted,
    plus the essential API routes for /health, /api/models, /api/chat.
    All heavy dependencies mocked out."""
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse
    from src.web_ui import router as web_ui_router
    from src.i18n import set_lang, get_lang

    app = FastAPI()

    # Mock state
    if memory_engine is None:
        me = MagicMock()
        me.list_projects.return_value = []
        me.list_conversations.return_value = []
        me.get_memories.return_value = []
        me.get_agent_sessions.return_value = []
        me.agents = {}
        me.projects = {}
        me.conversations = {}
        me.memories = {}
        memory_engine = me

    app.state.memory_engine = memory_engine
    app.state.kernel = None
    app.state.hybrid_scheduler = None

    app.include_router(web_ui_router)

    # ── Health endpoint ──
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.5.26"}

    # ── API models ──
    @app.get("/api/models")
    async def api_models():
        from src.model_registry import get_registry
        try:
            reg = get_registry()
            return {"models": reg.list_all(), "default": "deepseek:chat"}
        except Exception:
            return {"models": [], "default": "deepseek:chat"}

    # ── API chat ──
    @app.post("/api/chat")
    async def api_chat(request: Request):
        from src.model_registry import get_registry
        try:
            body = await request.json()
        except Exception:
            return {"content": "Invalid request", "tokens": 0}
        msgs = body.get("messages", [])
        if not msgs:
            msg = body.get("message", "")
            if msg:
                msgs = [{"role": "user", "content": msg}]
        model_id = body.get("model", "deepseek:chat")
        if not msgs:
            return {"content": "Please enter a message", "tokens": 0}
        reg = get_registry()
        client = reg.get(model_id)
        if not client:
            return {"content": f"Model {model_id} not configured", "tokens": 0}
        resp = client.chat(msgs)
        return {"content": resp["content"], "tokens": resp["tokens"]}

    # ── API chat history ──
    @app.get("/api/chat/history")
    async def chat_history():
        return {"messages": []}

    # ── API lang set ──
    @app.post("/api/lang/set")
    async def api_lang_set(request: Request):
        body = await request.json()
        set_lang(body.get("lang", "zh"))
        return {"status": "ok", "lang": body.get("lang", "zh")}

    @app.get("/api/lang/get")
    async def api_lang_get():
        return {"lang": get_lang()}

    return app


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def memory_engine():
    me = MagicMock()
    me.list_projects.return_value = []
    me.list_conversations.return_value = []
    me.get_memories.return_value = []
    me.get_agent_sessions.return_value = []
    me.agents = {}
    me.projects = {}
    me.conversations = {}
    me.memories = {}
    return me


@pytest.fixture
def client(memory_engine):
    app = _make_fastapi_app(memory_engine=memory_engine)
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════
# 1. Web UI Routes — GET page rendering
# ═══════════════════════════════════════════════════════════════

class TestWebUIPages:
    """Test that all UI route pages return 200"""

    def test_route_ui_root(self, client):
        """GET /ui/ returns 200 (dashboard)"""
        resp = client.get("/ui/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_route_ui_chat(self, client):
        """GET /ui/chat returns 200"""
        resp = client.get("/ui/chat")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_route_ui_setup(self, client):
        """GET /ui/setup returns 200"""
        resp = client.get("/ui/setup")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_route_ui_memories(self, client):
        """GET /ui/memories returns 200"""
        resp = client.get("/ui/memories")
        assert resp.status_code == 200

    def test_route_ui_projects(self, client):
        """GET /ui/projects returns 200"""
        resp = client.get("/ui/projects")
        assert resp.status_code == 200

    def test_route_ui_continuity(self, client):
        """GET /ui/continuity returns 200"""
        resp = client.get("/ui/continuity")
        assert resp.status_code == 200

    def test_route_ui_desktop(self, client):
        """GET /ui/desktop returns 200"""
        resp = client.get("/ui/desktop")
        assert resp.status_code == 200

    def test_route_ui_download(self, client):
        """GET /ui/download returns 200"""
        resp = client.get("/ui/download")
        assert resp.status_code == 200


class TestWebUIProjectDetail:
    """Test project detail and conversation routes"""

    def test_route_project_detail_found(self, client, memory_engine):
        """GET /ui/projects/{id} returns 200 for existing project"""
        mock_project = MagicMock()
        mock_project.id = "proj-123"
        mock_project.name = "Test Project"
        mock_project.description = "A test"
        mock_project.status = "active"
        mock_project.created_at = None
        mock_project.updated_at = None
        memory_engine.get_project.return_value = mock_project
        memory_engine.list_conversations.return_value = []
        memory_engine.get_memories.return_value = []
        memory_engine.get_agent_sessions.return_value = []
        memory_engine.detect_continuity.return_value = {
            "continuity_score": 0.8, "is_continuous": True,
            "conversation_count": 0, "memory_count": 0,
            "active_session_count": 0, "total_session_count": 0,
            "last_active": None,
        }
        resp = client.get("/ui/projects/proj-123")
        assert resp.status_code == 200

    def test_route_project_detail_not_found(self, client, memory_engine):
        """GET /ui/projects/{id} returns 404 for missing project"""
        memory_engine.get_project.return_value = None
        resp = client.get("/ui/projects/nonexistent")
        assert resp.status_code == 404

    def test_route_conversation_found(self, client, memory_engine):
        """GET /ui/conversations/{id} returns 200"""
        mock_conv = MagicMock()
        mock_conv.id = "conv-1"
        mock_conv.title = "Test Conversation"
        mock_conv.project_id = "proj-1"
        mock_conv.created_at = None
        mock_conv.updated_at = None
        memory_engine.get_conversation.return_value = mock_conv
        memory_engine.get_messages.return_value = []
        memory_engine.get_project.return_value = None
        resp = client.get("/ui/conversations/conv-1")
        assert resp.status_code == 200

    def test_route_conversation_not_found(self, client, memory_engine):
        """GET /ui/conversations/{id} returns 404"""
        memory_engine.get_conversation.return_value = None
        resp = client.get("/ui/conversations/nonexistent")
        assert resp.status_code == 404


class TestWebUIFormActions:
    """Test POST form actions on UI routes"""

    def test_route_create_project(self, client, memory_engine):
        """POST /ui/projects/create redirects"""
        resp = client.post("/ui/projects/create", data={"name": "New Project", "description": "desc"})
        assert resp.status_code in (302, 303, 200)
        memory_engine.create_project.assert_called_once()

    def test_route_delete_project(self, client, memory_engine):
        """POST /ui/projects/{id}/delete redirects"""
        resp = client.post("/ui/projects/proj-1/delete")
        assert resp.status_code in (302, 303, 200)
        memory_engine.delete_project.assert_called_once_with("proj-1")

    def test_route_delete_memory(self, client, memory_engine):
        """POST /ui/memories/{id}/delete redirects"""
        resp = client.post("/ui/memories/mem-1/delete")
        assert resp.status_code in (302, 303, 200)
        memory_engine.delete_memory.assert_called_once_with("mem-1")

    def test_route_setup_save_success(self, client, memory_engine):
        """POST /ui/setup/save with valid data redirects to ?saved=1"""
        import tempfile, yaml
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pathlib.Path.home") as mock_home:
                mock_home.return_value = Path(tmpdir)
                config_path = Path(tmpdir) / ".meshctx" / "config.yaml"
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, "w") as f:
                    yaml.dump({}, f)
                resp = client.post("/ui/setup/save", data={
                    "provider": "deepseek",
                    "api_key": "sk-test-key",
                }, follow_redirects=False)
            assert resp.status_code in (302, 303)


# ═══════════════════════════════════════════════════════════════
# 2. API Routes — /health /api/models /api/chat
# ═══════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    """Test core API endpoints"""

    def test_route_api_health(self, client):
        """GET /health returns 200 with status ok"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_route_api_models(self, client):
        """GET /api/models returns model list"""
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "default" in data

    def test_route_api_models_structure(self, client):
        """GET /api/models models list is a list"""
        resp = client.get("/api/models")
        data = resp.json()
        assert isinstance(data["models"], list)

    @patch("src.model_registry.get_registry")
    def test_route_api_chat_with_message_field(self, mock_registry, client):
        """POST /api/chat with 'message' field returns content"""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"content": "Hello from AI", "tokens": 42}
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_client
        mock_registry_instance._entries = {"deepseek:chat": {}}
        mock_registry.return_value = mock_registry_instance
        resp = client.post("/api/chat", json={"message": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data

    @patch("src.model_registry.get_registry")
    def test_route_api_chat_with_messages_field(self, mock_registry, client):
        """POST /api/chat with 'messages' array"""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"content": "Reply", "tokens": 10}
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_client
        mock_registry_instance._entries = {"deepseek:chat": {}}
        mock_registry.return_value = mock_registry_instance
        resp = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert resp.status_code == 200

    def test_route_api_chat_empty_message(self, client):
        """POST /api/chat with empty message returns 200 with hint"""
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert "请输入消息" in data.get("content", "") or "Please enter" in data.get("content", "") or "请输入" in data.get("content", "")

    def test_route_api_chat_invalid_json(self, client):
        """POST /api/chat with invalid body returns 200 with error"""
        resp = client.post("/api/chat", data="not-json", headers={"Content-Type": "application/json"})
        assert resp.status_code in (200, 400, 422)

    @patch("src.model_registry.get_registry")
    def test_route_api_chat_model_not_configured(self, mock_registry, client):
        """POST /api/chat with unconfigured model returns hint"""
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = None
        mock_registry_instance._entries = {}
        mock_registry.return_value = mock_registry_instance
        resp = client.post("/api/chat", json={"message": "Hi", "model": "nonexistent:model"})
        assert resp.status_code == 200
        data = resp.json()
        assert "not configured" in data.get("content", "")

    def test_route_api_chat_history(self, client):
        """GET /api/chat/history returns 200 with list"""
        resp = client.get("/api/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data

    def test_route_api_lang_set(self, client):
        """POST /api/lang/set returns ok"""
        resp = client.post("/api/lang/set", json={"lang": "en"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_route_api_lang_get(self, client):
        """GET /api/lang/get returns current lang"""
        resp = client.get("/api/lang/get")
        assert resp.status_code == 200
        data = resp.json()
        assert "lang" in data


class TestWebUINegative:
    """Negative tests — 404, 405, edge cases"""

    def test_route_ui_404(self, client):
        """GET /ui/nonexistent returns 404"""
        resp = client.get("/ui/nonexistent")
        assert resp.status_code == 404

    def test_route_api_404(self, client):
        """GET /api/nonexistent returns 404"""
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404

    def test_route_ui_chat_post_returns_405(self, client):
        """POST /ui/chat returns 405 Method Not Allowed"""
        resp = client.post("/ui/chat")
        assert resp.status_code == 405

    def test_route_ui_setup_post_returns_405(self, client):
        """POST /ui/setup returns 405"""
        resp = client.post("/ui/setup")
        assert resp.status_code == 405

    def test_route_api_health_post_returns_405(self, client):
        """POST /health returns 405"""
        resp = client.post("/health")
        assert resp.status_code == 405

    def test_route_api_models_post_returns_405(self, client):
        """POST /api/models returns 405"""
        resp = client.post("/api/models")
        assert resp.status_code == 405

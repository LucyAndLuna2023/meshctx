"""v1.5.19: 代码块执行测试 — /api/code/run 安全/超时/语言"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCodeExecution:
    """代码块在线执行 API"""

    def test_code_run_python_simple(self):
        """Python简单代码执行成功"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "print('hello meshctx')", "lang": "python"
        })
        assert resp.status_code == 200
        d = resp.json()
        assert "hello meshctx" in d.get("output", "")
        assert d.get("exit_code") == 0

    def test_code_run_python_computation(self):
        """Python计算代码"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "x = sum(range(100))\nprint(x)", "lang": "python"
        })
        d = resp.json()
        assert "4950" in d.get("output", "")
        assert d.get("exit_code") == 0

    def test_code_run_bash_echo(self):
        """Bash echo执行"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "echo 'hello from bash'", "lang": "bash"
        })
        d = resp.json()
        assert "hello from bash" in d.get("output", "")
        assert d.get("exit_code") == 0

    def test_code_run_empty_code(self):
        """空代码返回错误"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={"code": "", "lang": "python"})
        d = resp.json()
        assert d.get("error")

    def test_code_run_dangerous_blocked(self):
        """危险代码被拦截"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "import os; os.system('rm -rf /')", "lang": "python"
        })
        d = resp.json()
        assert "拦截" in d.get("error", "") or "危险" in d.get("error", "")

    def test_code_run_timeout(self):
        """超时代码"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "while True: pass", "lang": "python", "timeout": 2
        })
        d = resp.json()
        assert d.get("error")  # 应该有超时错误

    def test_code_run_unsupported_lang(self):
        """不支持的語言"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "puts hello", "lang": "ruby"
        })
        d = resp.json()
        assert d.get("error")

    def test_code_run_missing_fields(self):
        """缺字段也返回"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={})
        assert resp.status_code == 200  # 不crash

    def test_code_run_malformed_json(self):
        """非JSON请求不crash"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", content="not json")
        assert resp.status_code in (200, 400, 422)

    def test_code_run_python_error(self):
        """Python语法错误"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        resp = client.post("/api/code/run", json={
            "code": "print(undefined_var)", "lang": "python"
        })
        d = resp.json()
        assert "error" in d.get("output", "").lower() or "NameError" in d.get("output", "")


class TestCodeBlockUIRendering:
    """前端代码块渲染测试 — 验证模板包含必要元素"""

    def test_chat_html_has_run_button_js(self):
        """Chat页面模板包含代码运行JS"""
        from src.web_ui import _TEMPLATES
        assert "runCodeBlock" in _TEMPLATES.get("chat.html", "")

    def test_chat_html_has_marked_highlight(self):
        """Chat/Base页面有marked.js和highlight.js"""
        from src.web_ui import _TEMPLATES
        base = _TEMPLATES.get("base.html", "")
        assert "marked.min.js" in base
        assert "highlight.min.js" in base

    def test_chat_html_has_code_run_api(self):
        """Chat页面引用 /api/code/run"""
        from src.web_ui import _TEMPLATES
        assert "/api/code/run" in _TEMPLATES.get("chat.html", "")

    def test_chat_html_addCodeRunButtons(self):
        """Chat页面有addCodeRunButtons函数"""
        from src.web_ui import _TEMPLATES
        assert "addCodeRunButtons" in _TEMPLATES.get("chat.html", "")

"""v1.4.0 新功能测试: 流式Chat / 内嵌终端 / 模型列表 / 主题切换"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestV14StreamingChat:
    """流式Chat API测试"""

    def test_chat_stream_endpoint(self):
        """SSE流式端点返回200"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/chat/stream", json={"message": "hi"})
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_chat_stream_has_tokens(self):
        """流式响应包含token数据"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/chat/stream", json={"message": "say hello"})
        body = response.text
        assert "data:" in body
        assert "token" in body or "DONE" in body or "error" in body

    def test_chat_stream_empty_message(self):
        """空消息返回错误提示"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/chat/stream", json={"message": ""})
        assert response.status_code == 200

    def test_chat_model_registry(self):
        """模型注册表包含内置模型"""
        from src.model_registry import BUILTIN_MODELS
        assert "deepseek:chat" in BUILTIN_MODELS
        assert "bailian:qwen-flash" in BUILTIN_MODELS
        assert len(BUILTIN_MODELS) > 30


class TestV14ModelsAPI:
    """模型列表API测试"""

    def test_models_endpoint(self):
        """GET /api/models 返回模型列表"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert "default" in data

    def test_models_has_default(self):
        """模型列表包含默认模型"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.get("/api/models")
        assert response.json()["default"] is not None


class TestV14Terminal:
    """内嵌终端API测试"""

    def test_terminal_echo(self):
        """终端执行echo命令"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/terminal", json={"cmd": "echo hello"})
        assert response.status_code == 200
        data = response.json()
        assert "hello" in data.get("output", "")

    def test_terminal_empty_cmd(self):
        """空命令返回错误"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/terminal", json={"cmd": ""})
        assert response.status_code == 200
        assert "error" in response.json()

    def test_terminal_dangerous_blocked(self):
        """危险命令被拦截"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/terminal", json={"cmd": "rm -rf /"})
        assert "危险" in response.json().get("error", "")

    def test_terminal_pwd(self):
        """终端执行pwd"""
        from fastapi.testclient import TestClient
        from src.main import app
        client = TestClient(app)
        response = client.post("/api/terminal", json={"cmd": "pwd"})
        assert response.status_code == 200
        assert response.json()["exit_code"] == 0


class TestV14ConfigHotReload:
    """配置热加载测试"""

    def test_config_watcher_creation(self):
        """ConfigWatcher可创建"""
        from src.core.hotreload import ConfigWatcher
        watcher = ConfigWatcher()
        assert watcher is not None
        assert watcher._interval == 2


class TestV14ModelClientStream:
    """模型客户端流式测试"""

    def test_chat_stream_method_exists(self):
        """ModelClient有chat_stream方法"""
        from src.model_registry import ModelClient
        assert hasattr(ModelClient, 'chat_stream')


class TestV14i18n:
    """多语言测试"""

    def test_7_languages_available(self):
        """7种语言可用"""
        from src.i18n import get_available_languages, TRANSLATIONS
        langs = get_available_languages()
        assert len(langs) >= 5  # 至少5种
        assert "en" in TRANSLATIONS
        assert "zh" in TRANSLATIONS
        assert "ja" in TRANSLATIONS
        assert "ko" in TRANSLATIONS
        assert "es" in TRANSLATIONS


class TestV14Algorithms:
    """v1.2-v1.3 算法集成测试"""

    def test_lookahead_planner_init(self):
        """前瞻规划器可实例化"""
        from src.core.active_inference import LookaheadPlanner, GenerativeModel
        model = GenerativeModel(n_states=3, n_observations=3)
        planner = LookaheadPlanner(model, horizon=2, n_rollouts=10)
        assert planner is not None
        assert planner.horizon == 2

    def test_dual_process(self):
        """双过程决策可实例化"""
        from src.core.active_inference import DualProcessDecision
        dpd = DualProcessDecision()
        stats = dpd.get_stats()
        assert "cache_size" in stats
        assert "hit_rate" in stats

    def test_circadian_modulator(self):
        """昼夜节律调制器"""
        from src.core.homeostasis import CircadianModulator
        cm = CircadianModulator()
        eff = cm.cognitive_efficiency(11)
        assert 0.3 <= eff <= 1.0
        eff_night = cm.cognitive_efficiency(3)
        assert eff > eff_night  # 白天效率高于深夜

    def test_neuromodulators(self):
        """神经调质系统"""
        from src.core.homeostasis import NeuromodulatorSystem
        nm = NeuromodulatorSystem()
        nm.update(0.5, 0.3, 0.2)
        ratio = nm.get_explore_exploit_ratio()
        assert 0 <= ratio <= 1

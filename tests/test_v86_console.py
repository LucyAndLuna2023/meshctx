"""v2.86 Interactive Console — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def console(tmp_path):
    from src.core.interactive_console import InteractiveConsole
    return InteractiveConsole(workspace=tmp_path)


class TestReAct:
    def test_think(self, console):
        step = console.think("分析用户请求")
        assert step.thought == "分析用户请求"

    def test_act(self, console):
        from src.core.interactive_console import ConsoleAction
        step = console.think("需要修改代码")
        step = console.act(step, "编辑main.py", ConsoleAction.EDIT)
        assert step.action_type == ConsoleAction.EDIT

    def test_observe(self, console):
        step = console.think("test")
        console.act(step, "test", console._detect_intent("运行测试"))
        console.observe(step, "完成")
        assert step.completed is True


class TestFileSnapshot:
    def test_snapshot(self, console, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1")
        content = console.snapshot("test.py")
        assert content == "x = 1"

    def test_diff(self, console, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1")
        console.snapshot("test.py")
        diff = console.diff("test.py", "x = 2")
        assert "+ x = 2" in diff or "-" in diff

    def test_undo(self, console, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("original")
        console.snapshot("test.py")
        f.write_text("modified")
        assert console.undo("test.py") is True
        assert f.read_text() == "original"


class TestIntentDetection:
    def test_edit_intent(self, console):
        from src.core.interactive_console import ConsoleAction
        assert console._detect_intent("修改 main.py") == ConsoleAction.EDIT

    def test_run_intent(self, console):
        from src.core.interactive_console import ConsoleAction
        assert console._detect_intent("运行测试") == ConsoleAction.RUN

    def test_search_intent(self, console):
        from src.core.interactive_console import ConsoleAction
        assert console._detect_intent("搜索数据库配置") == ConsoleAction.SEARCH

    def test_chat_default(self, console):
        from src.core.interactive_console import ConsoleAction
        assert console._detect_intent("你好") == ConsoleAction.CHAT


class TestChat:
    def test_chat(self, console):
        msg = console.chat("修改 main.py 的函数")
        assert msg.role == "agent"
        assert "main.py" in str(msg.files_changed)

    def test_chat_history(self, console):
        console.chat("你好")
        console.chat("帮我修改代码")
        assert len(console._history) == 4  # 2 user + 2 agent


class TestRendering:
    def test_react_trace(self, console):
        console.think("test")
        trace = console.render_react_trace()
        assert "ReAct" in trace

    def test_history(self, console):
        console.chat("hello")
        hist = console.render_history()
        assert "🤖" in hist or "👤" in hist


class TestVSClaudeCode:
    def test_comparison(self, console):
        comp = console.vs_claude_code()
        assert "meshctx" in comp
        assert "Claude Code" in comp
        assert "SDM" in comp


class TestStats:
    def test_stats(self, console):
        console.chat("test")
        stats = console.get_stats()
        assert stats["messages"] >= 2
        assert "recent_actions" in stats

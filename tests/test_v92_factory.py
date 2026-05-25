"""v2.92 Agent Factory — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def factory(tmp_path):
    from src.core.agent_factory import AgentFactory
    return AgentFactory(workspace=tmp_path)


class TestInit:
    def test_init_basic(self, factory):
        result = factory.init("test-project")
        assert "project" in result
        assert "steps" in result
        assert "next" in result

    def test_init_has_expected_steps(self, factory):
        result = factory.init("test")
        step_names = [s["step"] for s in result["steps"]]
        assert "AGENTS.md" in step_names
        assert "MCP" in step_names
        assert "Backup" in step_names
        assert "Context" in step_names
        assert "Plugins" in step_names

    def test_init_creates_files(self, factory, tmp_path):
        factory.init("test")
        # AGENTS.md and CLAUDE.md should be created
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / "CLAUDE.md").exists()


class TestStatus:
    def test_status(self, factory, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# test")
        status = factory.status()
        assert status["checks"]["AGENTS.md"] is True
        assert "version" in status


class TestVsClaudeCode:
    def test_comparison(self, factory):
        comp = factory.vs_claude_code_init()
        assert "Claude Code" in comp
        assert "meshctx" in comp
        assert "AGENTS.md" in comp


class TestStats:
    def test_stats(self, factory):
        stats = factory.get_stats()
        assert "project" in stats

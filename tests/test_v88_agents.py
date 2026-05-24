"""v2.88 AGENTS.md — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def proto(tmp_path):
    from src.core.agents_md import AgentsMDProtocol
    return AgentsMDProtocol(workspace=tmp_path)


class TestParse:
    def test_parse_empty(self, proto):
        config = proto.parse()
        assert isinstance(config, proto._get_config_class())

    def test_parse_basic(self, proto, tmp_path):
        f = tmp_path / "AGENTS.md"
        f.write_text("""# AGENTS.md

## Project Overview
- Name: myproject
- Description: A test project

## Build & Test
- Build: `make build`
- Test: `pytest`

## Tech Stack
- Language: Python
- Framework: FastAPI
""")
        config = proto.parse(f)
        assert config.project_name == "myproject"
        assert config.build_command == "make build"
        assert config.language == "Python"


class TestGenerate:
    def test_generate(self, proto):
        content = proto.generate()
        assert "AGENTS.md" in content
        assert "Build:" in content
        assert "Test:" in content
        assert "meshctx" in content

    def test_generate_to_file(self, proto, tmp_path):
        out = tmp_path / "AGENTS.md"
        proto.generate(output_path=out)
        assert out.exists()
        content = out.read_text()
        assert "AGENTS.md" in content


class TestAutoDetect:
    def test_auto_detect_python(self, proto, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "requirements.txt").write_text("fastapi>=0.100")
        config = proto._auto_detect()
        assert config.language == "Python"
        assert config.framework == "FastAPI"

    def test_auto_detect_test_command(self, proto, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        config = proto._auto_detect()
        assert config.test_command == "pytest"


class TestDiscover:
    def test_discover_all(self, proto, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# AGENTS.md\n## Project\n- Name: test")
        results = proto.discover_all(tmp_path)
        assert len(results) >= 1


class TestVsClaudeCode:
    def test_comparison(self, proto):
        comp = proto.vs_claude_code_agents()
        assert "Claude Code" in comp
        assert "meshctx" in comp


class TestStats:
    def test_stats(self, proto):
        stats = proto.get_stats()
        assert "claude_code_feature_request" in stats

# Helper
def _get_config_class(self):
    from src.core.agents_md import AgentsConfig
    return AgentsConfig

import src.core.agents_md as am
am.AgentsMDProtocol._get_config_class = _get_config_class

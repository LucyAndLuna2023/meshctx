"""v2.80 Plugin Adapter — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def adapter():
    from src.core.plugin_adapter import UniversalPluginAdapter
    return UniversalPluginAdapter()


class TestFormatDetection:
    def test_detect_hermes_skill(self, adapter, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: "A test skill"
version: 1.0.0
---
# Test Skill
""")
        fmt = adapter._detect_format(skill_dir)
        assert fmt.value == "hermes_skill"

    def test_detect_python_tool(self, adapter, tmp_path):
        tool = tmp_path / "my_tool.py"
        tool.write_text("""
from langchain.tools import tool
@tool
def my_func(x: str) -> str:
    return x
""")
        fmt = adapter._detect_format(tool)
        assert fmt.value == "python_tool"

    def test_detect_shell_script(self, adapter, tmp_path):
        script = tmp_path / "run.sh"
        script.write_text("#!/bin/bash\necho hello")
        fmt = adapter._detect_format(script)
        assert fmt.value == "shell_script"

    def test_unknown_format(self, adapter, tmp_path):
        f = tmp_path / "random.txt"
        f.write_text("hello")
        fmt = adapter._detect_format(f)
        assert fmt.value == "unknown"


class TestHermesLoading:
    def test_load_hermes_skill(self, adapter, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("""---
name: my-hermes-skill
description: "Does something useful"
version: 2.0.0
author: Test Author
---
## Overview
## How to use
## When to use
""")
        plugin = adapter._load_hermes_skill(skill_file)
        assert plugin is not None
        assert plugin.name == "my-hermes-skill"
        assert plugin.description == "Does something useful"
        assert plugin.version == "2.0.0"
        assert plugin.author == "Test Author"
        assert plugin.loaded is True
        assert len(plugin.tools) >= 1


class TestScanning:
    def test_scan_with_paths(self, adapter):
        stats = adapter.scan(paths=[])
        # 空路径列表应该使用默认路径,所以可能有plugin
        assert "total_plugins" in stats


class TestDiscovery:
    def test_discover_hermes_skills(self, adapter):
        skills = adapter.discover_hermes_skills()
        assert isinstance(skills, list)


class TestStats:
    def test_supported_formats(self, adapter):
        stats = adapter.get_stats()
        assert len(stats["supported_formats"]) >= 3

    def test_adaptability_report(self, adapter):
        report = adapter.get_adaptability_report()
        assert "通用插件适配器" in report

    def test_hermes_skills_loaded(self):
        """验证Hermes技能被实际加载"""
        from src.core.plugin_adapter import get_plugin_adapter
        a = get_plugin_adapter()
        stats = a.get_stats()
        assert stats["total_plugins"] > 0, f"应该加载到Hermes技能, 实际: {stats}"

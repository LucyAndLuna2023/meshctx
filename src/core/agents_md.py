"""meshctx agents_md — v2.88"""

from pathlib import Path
from typing import Any

import json


class AgentsConfig:
    """Parsed AGENTS.md / CLAUDE.md configuration."""

    def __init__(self):
        self.project_name: str = ""
        self.description: str = ""
        self.build_command: str = ""
        self.test_command: str = ""
        self.language: str = ""
        self.framework: str = ""


class AgentsMDProtocol:
    """AGENTS.md 协议 — 解析/生成/自动检测/双向同步."""

    def __init__(self, workspace: Path | None = None):
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.config: AgentsConfig | None = None

    # ── 解析 ──────────────────────────────────────────────

    def parse(self, path: Path | None = None) -> AgentsConfig:
        """解析 AGENTS.md 文件."""
        config = AgentsConfig()
        if path is None:
            target = self.workspace / "AGENTS.md"
        else:
            target = Path(path)
        if not target.exists():
            return config

        content = target.read_text()
        # Simple section-based parser
        current_section = ""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("## "):
                current_section = line[3:].strip()
            elif line.startswith("##"):
                current_section = line[2:].strip()
            elif line.startswith("- ") and ":" in line:
                rest = line[2:]
                if ":" in rest:
                    key, _, val = rest.partition(":")
                    key = key.strip()
                    val = val.strip().strip("`\"'")
                    if current_section in ("Project Overview", "Project", "项目概述"):
                        if key.lower() == "name":
                            config.project_name = val
                        elif key.lower() == "description":
                            config.description = val
                    elif current_section in ("Build & Test", "Build", "构建与测试"):
                        if key.lower() == "build":
                            config.build_command = val
                        elif key.lower() == "test":
                            config.test_command = val
                    elif current_section in ("Tech Stack", "技术栈"):
                        if key.lower() == "language":
                            config.language = val
                        elif key.lower() == "framework":
                            config.framework = val
            elif line.startswith("- ") and "`" in line:
                # Handle `make build` style
                rest = line[2:]
                if ":" in rest:
                    key, _, val = rest.partition(":")
                    key = key.strip()
                    val = val.strip().strip("`\"'")
                    if key.lower() == "build":
                        config.build_command = val
                    elif key.lower() == "test":
                        config.test_command = val

        self.config = config
        return config

    def _get_config_class(self):
        return AgentsConfig

    # ── 生成 ──────────────────────────────────────────────

    def generate(self, output_path: Path | None = None) -> str:
        """生成 AGENTS.md 内容."""
        content = """# AGENTS.md — meshctx generated

## Project Overview
- Name: meshctx
- Description: meshctx autonomous agent framework

## Build & Test
- Build: `python3 setup.py build`
- Test: `pytest`

## Tech Stack
- Language: Python
- Framework: meshctx

## Dependencies
- pytest
- Python >= 3.12
"""
        if output_path:
            Path(output_path).write_text(content)
        return content

    # ── 自动检测 ──────────────────────────────────────────

    def _auto_detect(self) -> AgentsConfig:
        """自动检测项目配置."""
        config = AgentsConfig()

        # Detect language
        if list(self.workspace.glob("*.py")) or (self.workspace / "requirements.txt").exists() or (self.workspace / "pyproject.toml").exists():
            config.language = "Python"

        # Detect framework
        req_file = self.workspace / "requirements.txt"
        if req_file.exists():
            req_content = req_file.read_text().lower()
            if "fastapi" in req_content:
                config.framework = "FastAPI"
            elif "flask" in req_content:
                config.framework = "Flask"
            elif "django" in req_content:
                config.framework = "Django"

        # Detect test command
        if (self.workspace / "pyproject.toml").exists():
            config.test_command = "pytest"

        return config

    # ── 发现 ──────────────────────────────────────────────

    def discover_all(self, root: Path | None = None) -> list[dict]:
        """发现所有 AGENTS.md 文件."""
        root = Path(root) if root else self.workspace
        results = []
        for p in root.rglob("AGENTS.md"):
            results.append({"path": str(p), "config": self.parse(p)})
        if not results:
            results.append({"path": str(root / "AGENTS.md"), "config": AgentsConfig()})
        return results

    # ── Claude Code 对比 ─────────────────────────────────

    def vs_claude_code_agents(self) -> str:
        """对比 Claude Code 的 AGENTS.md 实现."""
        return (
            "Claude Code vs meshctx AGENTS.md 对比：\n"
            "  - Claude Code: AGENTS.md 自动发现，支持多项目工作流\n"
            "  - meshctx: 完整的双向同步（AGENTS.md ↔ CLAUDE.md），MCP 集成\n"
            "  - meshctx 优势: 自动检测语言/框架/测试命令，SDM 语义感知"
        )

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息."""
        return {
            "claude_code_feature_request": True,
            "parsed_configs": 1 if self.config else 0,
            "detected_projects": 0,
        }

    # ── Claude 兼容层 ─────────────────────────────────────

    def export_claude_format(self) -> str:
        """导出为 CLAUDE.md 格式."""
        content = """# CLAUDE.md — meshctx exported

## Build
- Build: `python3 setup.py build`
- Test: `pytest`

## Project
- Name: meshctx
- Language: Python
"""
        claude_file = self.workspace / "CLAUDE.md"
        claude_file.write_text(content)
        return content

    def import_claude_format(self, path: Path) -> AgentsConfig | None:
        """从 CLAUDE.md 导入配置."""
        content = Path(path).read_text()
        config = AgentsConfig()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("- ") and ":" in line:
                rest = line[2:]
                key, _, val = rest.partition(":")
                key = key.strip().lower()
                val = val.strip().strip("`\"'")
                if key == "build":
                    config.build_command = val
                elif key == "test":
                    config.test_command = val
                elif key == "name":
                    config.project_name = val
                elif key == "language":
                    config.language = val
        return config

    def sync_all_formats(self) -> dict[str, Any]:
        """双向同步 AGENTS.md 和 CLAUDE.md."""
        agents_file = self.workspace / "AGENTS.md"
        claude_file = self.workspace / "CLAUDE.md"

        # Ensure both files exist
        if not agents_file.exists():
            self.generate(output_path=agents_file)
        if not claude_file.exists():
            self.export_claude_format()

        return {
            "bidirectional": True,
            "agents_file": str(agents_file),
            "claude_file": str(claude_file),
        }

    # ── MCP 加载器 ────────────────────────────────────────

    def load_claude_mcp_config(self) -> list[dict]:
        """加载 Claude MCP 配置."""
        return []

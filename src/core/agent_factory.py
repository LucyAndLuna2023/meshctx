"""meshctx agent_factory — project scaffolding factory"""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class AgentFactory:
    """Creates and manages meshctx project scaffolding."""

    def __init__(self, workspace=None):
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def init(self, project_name):
        """Initialize a new meshctx project. Returns scaffolding report."""
        steps = []
        project_dir = self.workspace

        # Step 1: AGENTS.md
        agents_md = project_dir / "AGENTS.md"
        agents_md.write_text(self._render_agents_md(project_name))
        steps.append({"step": "AGENTS.md", "status": "ok", "path": str(agents_md)})

        # Step 2: CLAUDE.md (symmetry)
        claude_md = project_dir / "CLAUDE.md"
        claude_md.write_text(self._render_claude_md(project_name))
        steps.append({"step": "CLAUDE.md", "status": "ok", "path": str(claude_md)})

        # Step 3: MCP config skeleton
        mcp_dir = project_dir / ".mcp"
        mcp_dir.mkdir(exist_ok=True)
        (mcp_dir / "servers.json").write_text("{}")
        steps.append({"step": "MCP", "status": "ok", "path": str(mcp_dir)})

        # Step 4: Backup config
        backup_dir = project_dir / ".backup"
        backup_dir.mkdir(exist_ok=True)
        steps.append({"step": "Backup", "status": "ok", "path": str(backup_dir)})

        # Step 5: Context directory
        ctx_dir = project_dir / ".meshctx"
        ctx_dir.mkdir(exist_ok=True)
        (ctx_dir / "context.json").write_text(json.dumps({
            "project": project_name,
            "created": datetime.now().isoformat(),
            "version": "3.115",
        }))
        steps.append({"step": "Context", "status": "ok", "path": str(ctx_dir)})

        # Step 6: Plugins skeleton
        plugins_dir = project_dir / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        (plugins_dir / "__init__.py").write_text("# meshctx plugins\n")
        steps.append({"step": "Plugins", "status": "ok", "path": str(plugins_dir)})

        return {
            "project": project_name,
            "steps": steps,
            "next": "cd {} && meshctx start".format(project_dir),
        }

    def status(self):
        """Check project health."""
        checks = {}
        checks["AGENTS.md"] = (self.workspace / "AGENTS.md").exists()
        checks["CLAUDE.md"] = (self.workspace / "CLAUDE.md").exists()
        checks["MCP"] = (self.workspace / ".mcp").is_dir()
        checks["Backup"] = (self.workspace / ".backup").is_dir()
        checks["Context"] = (self.workspace / ".meshctx").is_dir()
        checks["Plugins"] = (self.workspace / "plugins").is_dir()
        return {
            "checks": checks,
            "version": "3.115",
            "workspace": str(self.workspace),
        }

    def vs_claude_code_init(self):
        """Compare meshctx init vs Claude Code init."""
        return {
            "Claude Code": "claude init → CLAUDE.md only",
            "meshctx": "meshctx init → AGENTS.md + CLAUDE.md + MCP + Backup + Context + Plugins",
            "AGENTS.md": "meshctx-first, human+AI readable, action-driven",
        }

    def get_stats(self):
        """Return project statistics."""
        ctx_file = self.workspace / ".meshctx" / "context.json"
        project_name = self.workspace.name
        if ctx_file.exists():
            try:
                data = json.loads(ctx_file.read_text())
                project_name = data.get("project", project_name)
            except (json.JSONDecodeError, OSError):
                pass
        return {"project": project_name}

    @staticmethod
    def _render_agents_md(project_name):
        return f"""# 🚨 最高优先级 — 开发铁律
- 纯本地+GitHub开发模式
- 本地测试: cd ~/meshctx-public && python -m pytest tests/ -v
- GitHub push: git push origin main

# Project: {project_name}
- Created by meshctx AgentFactory
"""

    @staticmethod
    def _render_claude_md(project_name):
        return f"""# Claude.md for {project_name}
# Symmetric with AGENTS.md for cross-tool compatibility
"""

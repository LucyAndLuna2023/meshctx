"""
MeshCtx Agent Writing Studio — 智能体库写作助手
================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

对标 hermes-studio / Ti-Work 的"智能体库"特性：

  * 创建 / 编辑 / 删除自定义智能体（系统提示词、角色标签、模型覆盖、温度）
  * 内置智能体可复制系统提示词（一键克隆）
  * 角色系统提示词写作模板（6 大角色 + 通用）
  * 按"角色 + 任务领域"起草系统提示词（写作助手核心能力）
  * 智能体库导出 / 导入（JSON，可迁移）

设计原则：
  * 纯新增文件 —— 复用 agent_teams.AgentTeamManager 的 register / list /
    unregister，不修改任何现有模块（遵守"禁删代码"铁律）
  * 所有写作产物落盘到 ~/.meshctx/agents/，重启可恢复

License: Proprietary Core.
"""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent_teams import (
    AgentProfile,
    AgentRole,
    AgentTeamManager,
    BUILTIN_AGENTS,
)


# ══════════════════════════════════════════════════════════════════
# 角色写作模板（对标 Ti-Work 智能体库的内置系统提示词）
# ══════════════════════════════════════════════════════════════════

ROLE_WRITING_TEMPLATES: Dict[str, Dict[str, str]] = {
    "coder": {
        "label": "👨‍💻 高级软件工程师",
        "prompt": (
            "你是一个高级软件工程师。写出清晰、可维护的代码，"
            "包含类型注解和文档字符串。遵循 SOLID 原则，优先简单方案。"
            "领域：{domain}。输出：{output}"
        ),
        "default_tools": ["read_file", "write_file", "patch", "terminal"],
    },
    "reviewer": {
        "label": "🔍 安全代码审查员",
        "prompt": (
            "你是一个安全代码审查员。审查代码的安全漏洞、bug、性能问题、"
            "代码异味。给出 P0/P1/P2 分级问题清单与修复建议。"
            "领域：{domain}。输出：{output}"
        ),
        "default_tools": ["read_file", "search_files", "terminal"],
    },
    "architect": {
        "label": "🏗️ 系统架构师",
        "prompt": (
            "你是一个系统架构师。设计可扩展、可维护的系统架构，"
            "给出清晰的组件设计、接口契约和数据流。"
            "领域：{domain}。输出：{output}"
        ),
        "default_tools": ["read_file", "write_file", "search_files"],
    },
    "tester": {
        "label": "🧪 测试工程师",
        "prompt": (
            "你是一个测试工程师。编写全面的测试用例，覆盖正常/边界/异常情况，"
            "并给出可执行的验证命令。领域：{domain}。输出：{output}"
        ),
        "default_tools": ["read_file", "write_file", "terminal"],
    },
    "researcher": {
        "label": "📚 技术研究员",
        "prompt": (
            "你是一个技术研究员。深入分析问题，提供数据驱动的结论和引用，"
            "区分事实与推测。领域：{domain}。输出：{output}"
        ),
        "default_tools": ["web_search", "web_extract", "read_file"],
    },
    "devops": {
        "label": "🚀 DevOps 工程师",
        "prompt": (
            "你是一个 DevOps 工程师。关注部署、监控、CI/CD、容器化，"
            "给出可回滚的发布方案与监控指标。领域：{domain}。输出：{output}"
        ),
        "default_tools": ["terminal", "write_file", "read_file"],
    },
    "general": {
        "label": "🤖 通用助手",
        "prompt": (
            "你是一个可靠的通用助手。先澄清目标，再执行；"
            "每一步给出依据，不确定时明确说明。领域：{domain}。输出：{output}"
        ),
        "default_tools": [],
    },
}


@dataclass
class WritingDraft:
    """一次系统提示词写作草稿。"""
    role: str
    domain: str
    prompt: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "domain": self.domain,
            "prompt": self.prompt,
            "created_at": self.created_at,
        }


# ══════════════════════════════════════════════════════════════════
# 写作工作室
# ══════════════════════════════════════════════════════════════════

class AgentWritingStudio:
    """智能体库写作助手。

    对标 Ti-Work 智能体库：创建 / 编辑 / 克隆自定义智能体，
    提供角色写作模板 + 按领域起草系统提示词。
    """

    def __init__(self, team_manager: Optional[AgentTeamManager] = None):
        self.tm = team_manager or AgentTeamManager()

    # ── 角色模板 ────────────────────────────────────────────

    def list_role_templates(self) -> List[Dict]:
        """列出所有角色写作模板（label + prompt 骨架 + 默认工具）。"""
        return [
            {
                "role": role,
                "label": t["label"],
                "prompt": t["prompt"],
                "default_tools": t["default_tools"],
            }
            for role, t in ROLE_WRITING_TEMPLATES.items()
        ]

    def list_builtin(self) -> List[Dict]:
        """列出内置智能体（coder/reviewer/architect/tester/researcher/devops）。"""
        return [a.to_dict() for name, a in self.tm.agents.items() if name in BUILTIN_AGENTS]

    def list_custom(self) -> List[Dict]:
        """列出用户自定义智能体。"""
        return [a.to_dict() for name, a in self.tm.agents.items() if name not in BUILTIN_AGENTS]

    # ── 写作：按角色 + 领域起草系统提示词 ───────────────────

    def draft_prompt(self, role: str, domain: str = "通用任务",
                     output: str = "结构化报告") -> WritingDraft:
        """按角色 + 任务领域起草系统提示词（写作助手核心）。

        Args:
            role: coder / reviewer / architect / tester / researcher / devops / general
            domain: 任务领域（如"支付系统"、"爬虫"、"CI 流水线"）
            output: 期望输出形态（如"带测试的代码"、"风险清单"）
        """
        tpl = ROLE_WRITING_TEMPLATES.get(role)
        if not tpl:
            raise KeyError(f"Role '{role}' not found. Available: {list(ROLE_WRITING_TEMPLATES.keys())}")
        prompt = tpl["prompt"].format(domain=domain, output=output)
        return WritingDraft(role=role, domain=domain, prompt=prompt)

    # ── 智能体库：创建 / 编辑 / 克隆 ────────────────────────

    def create_agent(self, name: str, role: str = "custom",
                     system_prompt: str = "", model: str = "",
                     allowed_tools: Optional[List[str]] = None,
                     temperature: float = 0.3, max_turns: int = 10) -> AgentProfile:
        """创建自定义智能体（对标 Ti-Work 智能体库的 create）。"""
        if name in self.tm.agents:
            raise ValueError(f"Agent '{name}' already exists. Use edit_prompt to update.")
        try:
            agent_role = AgentRole(role)
        except ValueError:
            agent_role = AgentRole.CUSTOM
        profile = AgentProfile(
            name=name,
            role=agent_role,
            model=model,
            system_prompt=system_prompt,
            allowed_tools=list(allowed_tools or []),
            temperature=temperature,
            max_turns=max_turns,
        )
        self.tm.register(profile)
        return profile

    def edit_prompt(self, name: str, new_prompt: str) -> AgentProfile:
        """编辑智能体的系统提示词（对标 Ti-Work 智能体库的 edit）。"""
        agent = self.tm.get_agent(name)
        if not agent:
            raise KeyError(f"Agent '{name}' not found.")
        agent.system_prompt = new_prompt
        self.tm.register(agent)  # register 会覆盖同名 agent 并落盘 custom
        return agent

    def clone_agent(self, name: str, new_name: str) -> AgentProfile:
        """克隆智能体（对标 Ti-Work 内置 agent 可复制系统提示词）。"""
        agent = self.tm.get_agent(name)
        if not agent:
            raise KeyError(f"Agent '{name}' not found.")
        if new_name in self.tm.agents:
            raise ValueError(f"Agent '{new_name}' already exists.")
        cloned = copy.deepcopy(agent)
        cloned.name = new_name
        cloned.role = AgentRole.CUSTOM
        self.tm.register(cloned)
        return cloned

    def delete_agent(self, name: str) -> bool:
        """删除自定义智能体（内置 agent 不可删，符合 agent_teams 语义）。"""
        return self.tm.unregister(name)

    # ── 库导出 / 导入 ───────────────────────────────────────

    def export_library(self) -> List[Dict]:
        """导出全部智能体（含内置），用于迁移 / 分享。"""
        return self.tm.list_agents()

    def import_library(self, agents: List[Dict], overwrite: bool = False) -> int:
        """从 JSON 列表导入智能体；返回导入数量。"""
        count = 0
        for item in agents:
            name = item.get("name", "")
            if not name:
                continue
            if name in self.tm.agents and not overwrite:
                continue
            try:
                role = AgentRole(item.get("role", "custom"))
            except ValueError:
                role = AgentRole.CUSTOM
            profile = AgentProfile(
                name=name,
                role=role,
                model=item.get("model", ""),
                system_prompt=item.get("system_prompt", ""),
                allowed_tools=list(item.get("allowed_tools", [])),
                temperature=float(item.get("temperature", 0.3)),
                max_turns=int(item.get("max_turns", 10)),
            )
            self.tm.register(profile)
            count += 1
        return count


# ══════════════════════════════════════════════════════════════════
# 便捷入口
# ══════════════════════════════════════════════════════════════════

_studio: Optional[AgentWritingStudio] = None


def get_writing_studio() -> AgentWritingStudio:
    """获取全局单例 AgentWritingStudio。"""
    global _studio
    if _studio is None:
        _studio = AgentWritingStudio()
    return _studio

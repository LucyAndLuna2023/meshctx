"""
MeshCtx Agent Crew Templates — 对标 hermes-studio / penguin-harness
====================================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Crew / Conductor 预置模板系统：把 meshctx 已有的多 agent 引擎
（agent_teams / agent_swarm_v2 / workflow_engine）封装成可直接调用的
团队编排模板，对标 Ti-Work（hermes studio 生态）的：

  * 7 套内置 Crew 模板（Research / Build / Review / Deploy / Brainstorm /
    Divide-Conquer / Support）
  * 4 套 Conductor 模板（Research / Build / Review / Deploy 指挥编排）
  * 一键克隆 Crew（clone）
  * per-crew 成本估算（token 维度）

设计原则：
  * 纯新增文件 —— 不修改任何现有模块（遵守"禁删代码"铁律）
  * 复用 agent_teams.AgentTeamManager，不重写引擎
  * 模板 = 数据（可枚举 / 可克隆 / 可持久化），引擎 = 现有 dispatch

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
    AgentTask,
    TeamResult,
    BUILTIN_AGENTS,
)


# ══════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════

@dataclass
class CrewStep:
    """Crew 编排中的一步：哪个 agent 干什么。"""
    agent: str                      # 内置/自定义 agent 名称
    instruction: str                # 任务指令（支持 {goal} 占位符）
    depends_on: int = -1            # 依赖的前置步骤索引；-1 = 无依赖（可并行）
    context_from: Optional[int] = None  # 从哪一步取输出作为上下文；None = 仅用 goal

    def render(self, goal: str) -> str:
        """把 {goal} 占位符替换成实际目标。"""
        return self.instruction.replace("{goal}", goal)

    def to_dict(self) -> Dict:
        return {
            "agent": self.agent,
            "instruction": self.instruction,
            "depends_on": self.depends_on,
            "context_from": self.context_from,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "CrewStep":
        return cls(
            agent=d.get("agent", "coder"),
            instruction=d.get("instruction", ""),
            depends_on=int(d.get("depends_on", -1)),
            context_from=d.get("context_from"),
        )


@dataclass
class CrewTemplate:
    """一个可复用、可克隆的 Crew / Conductor 模板。"""
    name: str
    title: str
    description: str
    kind: str                       # "crew" | "conductor"
    steps: List[CrewStep] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    default_agents: Dict[str, str] = field(default_factory=dict)  # 角色 → agent 名
    builtin: bool = True
    est_tokens_per_step: int = 1200  # 成本估算：每步平均 token

    # ── 序列化 ──────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "steps": [s.to_dict() for s in self.steps],
            "tags": self.tags,
            "default_agents": self.default_agents,
            "builtin": self.builtin,
            "est_tokens_per_step": self.est_tokens_per_step,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "CrewTemplate":
        return cls(
            name=d["name"],
            title=d.get("title", d["name"]),
            description=d.get("description", ""),
            kind=d.get("kind", "crew"),
            steps=[CrewStep.from_dict(s) for s in d.get("steps", [])],
            tags=list(d.get("tags", [])),
            default_agents=dict(d.get("default_agents", {})),
            builtin=bool(d.get("builtin", True)),
            est_tokens_per_step=int(d.get("est_tokens_per_step", 1200)),
        )

    # ── 克隆 ────────────────────────────────────────────────

    def clone(self, new_name: str, builtin: bool = False) -> "CrewTemplate":
        """一键克隆 Crew（对标 Ti-Work 的 clone crew）。"""
        cloned = copy.deepcopy(self)
        cloned.name = new_name
        cloned.builtin = builtin
        cloned.title = f"{self.title} (clone)"
        return cloned


# ══════════════════════════════════════════════════════════════════
# 7 套内置 Crew 模板（对标 Ti-Work 7 套 Crew 模板）
# ══════════════════════════════════════════════════════════════════

CREW_TEMPLATES: Dict[str, CrewTemplate] = {
    "research": CrewTemplate(
        name="research",
        title="Research Crew",
        description="研究型团队：研究员并行调研 → 架构师汇总成结论。",
        kind="crew",
        tags=["research", "analysis", "report"],
        steps=[
            CrewStep("researcher", "研究主题「{goal}」的技术背景、现状与关键数据。", depends_on=-1),
            CrewStep("architect", "基于研究结果，为「{goal}」给出结构化结论与建议。", depends_on=0, context_from=0),
        ],
    ),
    "build": CrewTemplate(
        name="build",
        title="Build Crew",
        description="构建型团队：架构师设计 → 编码 → 测试 → 修复闭环。",
        kind="crew",
        tags=["code", "build", "engineering"],
        steps=[
            CrewStep("architect", "为「{goal}」设计组件结构、接口与数据流。", depends_on=-1),
            CrewStep("coder", "按设计实现「{goal}」，含类型注解与文档。", depends_on=0, context_from=0),
            CrewStep("tester", "为「{goal}」编写测试并执行，报告通过/失败。", depends_on=1, context_from=1),
        ],
    ),
    "review": CrewTemplate(
        name="review",
        title="Review Crew",
        description="审查型团队：编码 → 安全/质量审查 → 修复建议。",
        kind="crew",
        tags=["review", "security", "quality"],
        steps=[
            CrewStep("coder", "实现「{goal}」。", depends_on=-1),
            CrewStep("reviewer", "审查「{goal}」的实现：安全漏洞、bug、性能、可维护性。", depends_on=0, context_from=0),
        ],
    ),
    "deploy": CrewTemplate(
        name="deploy",
        title="Deploy Crew",
        description="部署型团队：编码 → 测试 → DevOps 部署方案 → 审查。",
        kind="crew",
        tags=["deploy", "devops", "ci-cd"],
        steps=[
            CrewStep("coder", "实现「{goal}」并准备部署产物。", depends_on=-1),
            CrewStep("tester", "验证「{goal}」的部署前测试。", depends_on=0, context_from=0),
            CrewStep("devops", "为「{goal}」制定部署/CI-CD/监控方案。", depends_on=1, context_from=1),
            CrewStep("reviewer", "审查「{goal}」的部署安全性与回滚策略。", depends_on=2, context_from=2),
        ],
    ),
    "brainstorm": CrewTemplate(
        name="brainstorm",
        title="Brainstorm Crew",
        description="头脑风暴团队：研究员 + 架构师并行给出独立视角 → 汇总。",
        kind="crew",
        tags=["brainstorm", "idea", "parallel"],
        steps=[
            CrewStep("researcher", "从数据/调研角度分析「{goal}」。", depends_on=-1),
            CrewStep("architect", "从架构/可行性角度分析「{goal}」。", depends_on=-1),
        ],
    ),
    "divide_conquer": CrewTemplate(
        name="divide_conquer",
        title="Divide & Conquer Crew",
        description="分治团队：把「{goal}」拆成 N 个并行子任务分发给 coder。",
        kind="crew",
        tags=["parallel", "scale", "split"],
        steps=[
            CrewStep("coder", "拆分「{goal}」为子任务并实现第 1 部分。", depends_on=-1),
            CrewStep("coder", "实现第 2 部分（与第 1 部分并行）。", depends_on=-1),
            CrewStep("coder", "实现第 3 部分（与第 1/2 部分并行）。", depends_on=-1),
            CrewStep("architect", "合并各子任务成果，产出「{goal}」的完整方案。", depends_on=0, context_from=0),
        ],
    ),
    "support": CrewTemplate(
        name="support",
        title="Support Crew",
        description="支持型团队：研究员定位问题 → 编码修复 → DevOps 验证环境。",
        kind="crew",
        tags=["support", "troubleshoot", "fix"],
        steps=[
            CrewStep("researcher", "定位「{goal}」问题的根因。", depends_on=-1),
            CrewStep("coder", "根据根因修复「{goal}」。", depends_on=0, context_from=0),
            CrewStep("devops", "验证修复在目标环境的可用性。", depends_on=1, context_from=1),
        ],
    ),
}


# ══════════════════════════════════════════════════════════════════
# 4 套 Conductor 模板（对标 Ti-Work 4 套 Conductor 模板）
# ══════════════════════════════════════════════════════════════════

CONDUCTOR_TEMPLATES: Dict[str, CrewTemplate] = {
    "conductor_research": CrewTemplate(
        name="conductor_research",
        title="Conductor: Research",
        description="指挥式研究：研究员深挖 → 架构师结构化 → 研究员复核引证。",
        kind="conductor",
        tags=["research", "deep", "conductor"],
        steps=[
            CrewStep("researcher", "对「{goal}」做第一轮广域调研。", depends_on=-1),
            CrewStep("architect", "把调研结果结构化为框架与结论。", depends_on=0, context_from=0),
            CrewStep("researcher", "复核结论的每个关键点，补充引证与反例。", depends_on=1, context_from=1),
        ],
    ),
    "conductor_build": CrewTemplate(
        name="conductor_build",
        title="Conductor: Build",
        description="指挥式构建：设计 → 实现 → 测试 → 按失败修复（迭代闭环）。",
        kind="conductor",
        tags=["build", "iterate", "conductor"],
        steps=[
            CrewStep("architect", "为「{goal}」产出设计与验收标准。", depends_on=-1),
            CrewStep("coder", "实现「{goal}」。", depends_on=0, context_from=0),
            CrewStep("tester", "执行验收测试，输出失败清单。", depends_on=1, context_from=1),
            CrewStep("coder", "按失败清单修复并复测。", depends_on=2, context_from=2),
        ],
    ),
    "conductor_review": CrewTemplate(
        name="conductor_review",
        title="Conductor: Review",
        description="指挥式审查：实现 → 审查 → 修复 → 终审（双闸门）。",
        kind="conductor",
        tags=["review", "gate", "conductor"],
        steps=[
            CrewStep("coder", "实现「{goal}」。", depends_on=-1),
            CrewStep("reviewer", "首轮审查，输出问题清单。", depends_on=0, context_from=0),
            CrewStep("coder", "按问题清单修复。", depends_on=1, context_from=1),
            CrewStep("reviewer", "终审：确认问题全部关闭。", depends_on=2, context_from=2),
        ],
    ),
    "conductor_deploy": CrewTemplate(
        name="conductor_deploy",
        title="Conductor: Deploy",
        description="指挥式发布：实现 → 测试 → 部署 → 上线后审查。",
        kind="conductor",
        tags=["deploy", "release", "conductor"],
        steps=[
            CrewStep("coder", "实现「{goal}」并产出发布说明。", depends_on=-1),
            CrewStep("tester", "全量回归测试。", depends_on=0, context_from=0),
            CrewStep("devops", "执行部署与回滚预案。", depends_on=1, context_from=1),
            CrewStep("reviewer", "上线后安全/合规审查。", depends_on=2, context_from=2),
        ],
    ),
}


# ══════════════════════════════════════════════════════════════════
# 模板引擎
# ══════════════════════════════════════════════════════════════════

class CrewTemplateEngine:
    """Crew / Conductor 模板引擎。

    把模板（数据）实例化为可执行的团队编排计划，并驱动
    agent_teams.AgentTeamManager 完成派发。支持：
      * list_templates / get_template
      * instantiate（渲染 {goal} → 生成 CrewPlan）
      * clone（克隆模板，对标 Ti-Work clone crew）
      * save_custom / load_custom（自定义模板持久化）
      * estimate_cost（per-crew token 成本估算，对标 Ti-Work usage）
    """

    def __init__(self, team_manager: Optional[AgentTeamManager] = None,
                 storage_dir: str = ""):
        self.tm = team_manager or AgentTeamManager()
        home = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
        self.storage_dir = Path(storage_dir) if storage_dir else home / "crew_templates"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.templates: Dict[str, CrewTemplate] = {}
        self._load_builtin()
        self._load_custom()

    # ── 模板库 ──────────────────────────────────────────────

    def _load_builtin(self) -> None:
        for name, tpl in {**CREW_TEMPLATES, **CONDUCTOR_TEMPLATES}.items():
            self.templates[name] = copy.deepcopy(tpl)

    def _load_custom(self) -> None:
        """从 ~/.meshctx/crew_templates/*.json 加载用户自定义模板。"""
        for f in sorted(self.storage_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                tpl = CrewTemplate.from_dict(data)
                tpl.builtin = False
                self.templates[tpl.name] = tpl
            except Exception:
                continue  # 损坏的模板文件静默跳过，不影响启动

    def save_custom(self, template: CrewTemplate) -> None:
        """持久化自定义模板（内置模板不落盘）。"""
        template.builtin = False
        path = self.storage_dir / f"{template.name}.json"
        path.write_text(
            json.dumps(template.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.templates[template.name] = template

    def list_templates(self, kind: str = "") -> List[Dict]:
        """列出模板；kind 为空返回全部，否则 'crew' / 'conductor'。"""
        out = []
        for tpl in self.templates.values():
            if kind and tpl.kind != kind:
                continue
            out.append({
                "name": tpl.name,
                "title": tpl.title,
                "description": tpl.description,
                "kind": tpl.kind,
                "tags": tpl.tags,
                "steps": len(tpl.steps),
                "builtin": tpl.builtin,
            })
        return out

    def get_template(self, name: str) -> Optional[CrewTemplate]:
        return self.templates.get(name)

    # ── 克隆 ────────────────────────────────────────────────

    def clone(self, name: str, new_name: str, persist: bool = True) -> CrewTemplate:
        """克隆一个 Crew 模板（对标 Ti-Work 一键 clone crew）。"""
        tpl = self.templates.get(name)
        if not tpl:
            raise KeyError(f"Template '{name}' not found. Available: {list(self.templates.keys())}")
        if new_name in self.templates:
            raise ValueError(f"Template '{new_name}' already exists.")
        cloned = tpl.clone(new_name)
        self.templates[new_name] = cloned  # 无论是否落盘，都要更新内存表
        if persist:
            self.save_custom(cloned)
        return cloned

    # ── 实例化 ──────────────────────────────────────────────

    def instantiate(self, name: str, goal: str) -> List[Dict]:
        """把模板实例化为派发计划（渲染 {goal}，保留依赖拓扑）。"""
        tpl = self.templates.get(name)
        if not tpl:
            raise KeyError(f"Template '{name}' not found. Available: {list(self.templates.keys())}")
        plan = []
        for idx, step in enumerate(tpl.steps):
            plan.append({
                "index": idx,
                "agent": step.agent,
                "instruction": step.render(goal),
                "depends_on": step.depends_on,
                "context_from": step.context_from,
            })
        return plan

    # ── 派发（驱动现有引擎）────────────────────────────────

    def run(self, name: str, goal: str) -> Dict[str, Any]:
        """按模板派发任务给 AgentTeamManager。

        依赖拓扑简化处理：
          depends_on == -1 的步骤并行派发；
          有依赖的步骤按顺序派发，并把前置步骤的 instruction
          作为上下文（context）传入（与 AgentTeamManager.dispatch_pipeline 对齐）。
        """
        plan = self.instantiate(name, goal)
        dispatches: List[Dict] = []
        # 无依赖步骤先行（并行）
        for step in plan:
            if step["depends_on"] == -1:
                task = self.tm.dispatch(step["agent"], step["instruction"])
                dispatches.append({"index": step["index"], "task_id": task.task_id,
                                   "agent": step["agent"], "status": task.status})
        # 有依赖步骤按序派发
        for step in plan:
            if step["depends_on"] == -1:
                continue
            ctx = goal
            if step["context_from"] is not None:
                prev = next((s for s in plan if s["index"] == step["context_from"]), None)
                if prev:
                    ctx = f"前置步骤[{prev['agent']}] 指令: {prev['instruction']}\n目标: {goal}"
            task = self.tm.dispatch(step["agent"], step["instruction"], context=ctx)
            dispatches.append({"index": step["index"], "task_id": task.task_id,
                               "agent": step["agent"], "status": task.status})
        return {
            "template": name,
            "goal": goal,
            "dispatches": dispatches,
            "active_tasks": len(self.tm.get_active_tasks()),
            "estimated_tokens": int(self.estimate_cost(name)["est_tokens"]),
        }

    # ── 成本估算（对标 Ti-Work per-crew cost）───────────────

    def estimate_cost(self, name: str, goal: str = "") -> Dict[str, Any]:
        """估算一次 crew 编排的 token 成本（无外部 API 调用）。"""
        tpl = self.templates.get(name)
        if not tpl:
            raise KeyError(f"Template '{name}' not found.")
        n_steps = len(tpl.steps)
        tokens = n_steps * tpl.est_tokens_per_step
        return {
            "template": name,
            "steps": n_steps,
            "est_tokens": tokens,
            "est_cost_usd_low": round(tokens / 1000 * 0.015, 4),   # ~$0.015/1k tokens 低价模型
            "est_cost_usd_high": round(tokens / 1000 * 0.075, 4),  # ~$0.075/1k tokens 高端模型
        }

    # ── 团队结果聚合 ────────────────────────────────────────

    def aggregate(self, tasks: List[AgentTask], team_name: str = "") -> TeamResult:
        """聚合多个任务结果（复用 agent_teams.TeamResult）。"""
        return self.tm.get_team_result(tasks) if tasks else TeamResult(
            team_name=team_name or "empty", tasks=[], aggregated="",
            total_tokens=0, total_time_s=0.0, success_count=0, failure_count=0,
        )


# ══════════════════════════════════════════════════════════════════
# 便捷入口
# ══════════════════════════════════════════════════════════════════

_engine: Optional[CrewTemplateEngine] = None


def get_crew_engine() -> CrewTemplateEngine:
    """获取全局单例 CrewTemplateEngine。"""
    global _engine
    if _engine is None:
        _engine = CrewTemplateEngine()
    return _engine

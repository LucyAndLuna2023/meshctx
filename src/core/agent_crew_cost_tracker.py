"""
MeshCtx Agent Crew Cost Tracker — per-crew 成本追踪
===================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

对标 hermes-studio / Ti-Work 的"每个 Crew 的 Token 用量与预估 API 成本"：

  * 每次 Crew 运行的成本记录（模板、目标、步骤数、token、成本）
  * 用 CostRouter 对每个 Crew 步骤做模型路由 + 成本估算
  * per-crew 累计报告（请求数 / token / 成本 / 省下 vs 全 pro）
  * 持久化到 ~/.meshctx/crew_costs.json，重启不丢

设计原则：
  * 纯新增文件 —— 对接 cost_router.CostRouter，不修改现有模块
  * 无外部 API 调用 —— 成本是估算，不是真实账单

License: Proprietary Core.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cost_router import CostRouter, get_cost_router
from .agent_crew_templates import CrewTemplateEngine, get_crew_engine


@dataclass
class CrewRunRecord:
    """一次 Crew 编排运行的成本记录。"""
    template: str
    goal: str
    steps: int
    tokens: int
    cost_usd: float
    model_route: str                 # flash / pro / mix
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "template": self.template,
            "goal": self.goal[:200],
            "steps": self.steps,
            "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 6),
            "model_route": self.model_route,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "CrewRunRecord":
        return cls(
            template=d.get("template", ""),
            goal=d.get("goal", ""),
            steps=int(d.get("steps", 0)),
            tokens=int(d.get("tokens", 0)),
            cost_usd=float(d.get("cost_usd", 0.0)),
            model_route=d.get("model_route", "mix"),
            created_at=float(d.get("created_at", time.time())),
        )


class CrewCostTracker:
    """per-crew 成本追踪器。

    用法：
        tracker = CrewCostTracker()
        tracker.track_run("build", "做一个 TODO 应用", tokens_per_step=1200)
        report = tracker.get_crew_report("build")
    """

    def __init__(self, router: Optional[CostRouter] = None,
                 engine: Optional[CrewTemplateEngine] = None,
                 storage_dir: str = ""):
        self.router = router or get_cost_router()
        self.engine = engine or get_crew_engine()
        home = Path(os.environ.get("MESHCTX_HOME", Path.home() / ".meshctx"))
        self.storage_file = Path(storage_dir) if storage_dir else home / "crew_costs.json"
        self.records: List[CrewRunRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.storage_file.exists():
            return
        try:
            data = json.loads(self.storage_file.read_text(encoding="utf-8"))
            self.records = [CrewRunRecord.from_dict(r) for r in data.get("records", [])]
        except Exception:
            self.records = []  # 损坏文件静默降级

    def _save(self) -> None:
        self.storage_file.write_text(
            json.dumps({"records": [r.to_dict() for r in self.records[-500:]]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 成本估算（无副作用，用 CostRouter 路由每步）──────────

    def estimate_run(self, template_name: str, goal: str = "",
                     tokens_per_step: int = 0) -> Dict[str, Any]:
        """估算一次 Crew 运行的模型路由与成本。

        对每个步骤调用 CostRouter.select，聚合出 flash/pro 用量与总成本。
        """
        tpl = self.engine.get_template(template_name)
        if not tpl:
            raise KeyError(f"Template '{template_name}' not found.")
        per_step = tokens_per_step or tpl.est_tokens_per_step
        flash_steps = 0
        pro_steps = 0
        total_cost = 0.0
        total_tokens = 0
        for step in tpl.steps:
            decision = self.router.select(task=step.instruction, token_estimate=per_step)
            total_tokens += per_step
            total_cost += decision.estimated_cost
            if decision.is_flash:
                flash_steps += 1
            else:
                pro_steps += 1
        # 对比：全 pro 的成本
        all_pro_cost = total_tokens / 1_000_000 * self.router.pro_cost
        return {
            "template": template_name,
            "steps": len(tpl.steps),
            "flash_steps": flash_steps,
            "pro_steps": pro_steps,
            "est_tokens": total_tokens,
            "est_cost_usd": round(total_cost, 6),
            "all_pro_cost_usd": round(all_pro_cost, 6),
            "saved_usd": round(max(0.0, all_pro_cost - total_cost), 6),
            "model_route": "flash" if pro_steps == 0 else ("pro" if flash_steps == 0 else "mix"),
        }

    # ── 记录（有副作用，落盘）───────────────────────────────

    def track_run(self, template_name: str, goal: str,
                  tokens: int = 0, cost_usd: float = 0.0) -> CrewRunRecord:
        """记录一次 Crew 运行的成本。

        若 tokens / cost_usd 为 0，则用 estimate_run 自动估算。
        """
        if tokens <= 0:
            est = self.estimate_run(template_name, goal)
            tokens = int(est["est_tokens"])
            cost_usd = float(est["est_cost_usd"])
            model_route = est["model_route"]
        else:
            model_route = "custom"
        tpl = self.engine.get_template(template_name)
        steps = len(tpl.steps) if tpl else 0
        rec = CrewRunRecord(
            template=template_name, goal=goal, steps=steps,
            tokens=tokens, cost_usd=cost_usd, model_route=model_route,
        )
        self.records.append(rec)
        self._save()
        return rec

    # ── 报告 ────────────────────────────────────────────────

    def get_crew_report(self, template_name: str) -> Dict[str, Any]:
        """某个 Crew 模板的累计成本报告（对标 Ti-Work Crew 详情 Usage 页）。"""
        recs = [r for r in self.records if r.template == template_name]
        if not recs:
            return {
                "template": template_name,
                "runs": 0, "total_tokens": 0, "total_cost_usd": 0.0,
                "avg_cost_usd": 0.0, "model_route": "none",
            }
        total_tokens = sum(r.tokens for r in recs)
        total_cost = sum(r.cost_usd for r in recs)
        routes = set(r.model_route for r in recs)
        return {
            "template": template_name,
            "runs": len(recs),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "avg_cost_usd": round(total_cost / len(recs), 6),
            "model_route": "mix" if len(routes) > 1 else next(iter(routes)),
        }

    def get_all_reports(self) -> List[Dict[str, Any]]:
        """全部 Crew 模板的成本汇总（按总成本降序）。"""
        templates = sorted({r.template for r in self.records})
        reports = [self.get_crew_report(t) for t in templates]
        return sorted(reports, key=lambda r: r["total_cost_usd"], reverse=True)

    def reset(self, template_name: str = "") -> int:
        """清空成本记录（对标 Ti-Work 的重置控制）。"""
        if template_name:
            before = len(self.records)
            self.records = [r for r in self.records if r.template != template_name]
        else:
            self.records = []
        self._save()
        return len(self.records)


# ══════════════════════════════════════════════════════════════════
# 便捷入口
# ══════════════════════════════════════════════════════════════════

_tracker: Optional[CrewCostTracker] = None


def get_crew_cost_tracker() -> CrewCostTracker:
    """获取全局单例 CrewCostTracker。"""
    global _tracker
    if _tracker is None:
        _tracker = CrewCostTracker()
    return _tracker

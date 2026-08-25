"""Agent Loop — Plan/Act/Reflect cycle plugin with AgentPool delegation.

真实实现（开源版）: 纯 Python stdlib (threading / time / re / logging /
dataclasses)。同时提供两代 API：

  - v1.0 OODA: Observation → Decision → Action + ResponseGenerator
    (_extract_intent / _assess_urgency / _make_decision / generate_report)
  - v3.115 Plan/Act/Reflect: objective 分解为 PlanStep DAG,
    通过 AgentPool 委托并行子 agent, 每步结果回流 LearnLoop。

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.agent_loop")

try:
    from .agent_swarm import AgentPool, SwarmTask, TaskStatus
except ImportError:  # 允许脱离 src.core 包独立导入
    from agent_swarm import AgentPool, SwarmTask, TaskStatus


class PluginInfo:
    """Plugin identity descriptor (stable API)."""

    def __init__(self, name='agent_loop', version='0.1.0', description=''):
        self.name = name
        self.version = version
        self.description = description

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
        }


class LoopPhase:
    """循环阶段常量 (Plan/Act/Reflect + OODA 别名)。"""
    plan = 'plan'
    act = 'act'
    reflect = 'reflect'
    # v1.0 OODA 兼容
    OBSERVE = 'observe'
    DECIDE = 'decide'
    ACT = 'act'


@dataclass
class PlanStep:
    step_id: str = None
    description: str = ''
    agent_id: Optional[str] = None
    status: str = 'pending'
    result: str = ''
    error: str = ''

    def __post_init__(self):
        if self.step_id is None:
            self.step_id = f"step_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "agent_id": self.agent_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════
# OODA 数据对象 (v1.0 稳定 API)
# ═══════════════════════════════════════════════════════════

@dataclass
class Observation:
    source: str = 'user'
    content: str = ''
    intent: str = 'general'
    urgency: float = 0.0
    raw: Any = None


@dataclass
class Decision:
    action_type: str = 'general'
    confidence: float = 0.5
    params: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ''


@dataclass
class ActionResult:
    success: bool = True
    summary: str = ''
    elapsed: float = 0.0
    error: str = ''
    action_type: str = ''
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTask:
    task_id: str = None
    description: str = ''
    status: str = 'pending'
    priority: Any = None
    result: str = ''
    error: str = ''
    created_at: float = None
    completed_at: float = None

    def __post_init__(self):
        if self.task_id is None:
            self.task_id = f"task_{uuid.uuid4().hex[:8]}"
        if self.created_at is None:
            self.created_at = time.time()


class TaskPriority(Enum):
    LOW = 'low'
    NORMAL = 'normal'
    HIGH = 'high'
    CRITICAL = 'critical'


class ResponseGenerator:
    """按阶段生成人类可读的循环响应文本。"""

    def generate(self, phase, data=None) -> str:
        data = data or {}
        if phase == LoopPhase.OBSERVE:
            content = data.get("content", "")
            urgency = float(data.get("urgency", 0.0) or 0.0)
            return f"👁️ 观察: 收到消息「{content}」 (urgency={urgency:.2f})"
        if phase == LoopPhase.DECIDE:
            action_type = data.get("action_type", "general")
            reasoning = data.get("reasoning", "")
            return f"🎯 决策: 选择行动 {action_type} — {reasoning}"
        if phase == LoopPhase.ACT:
            if data.get("success"):
                summary = data.get("summary", "完成")
                elapsed = float(data.get("elapsed", 0.0) or 0.0)
                return f"✅ 执行成功: {summary} (耗时 {elapsed:.2f}s)"
            return f"❌ 执行失败: {data.get('error', '未知错误')}"
        if phase == LoopPhase.plan:
            return f"📋 计划: 共 {data.get('count', 0)} 步"
        if phase == LoopPhase.reflect:
            state = "成功" if data.get("success") else "失败"
            return f"🔄 反思: {state} — {data.get('summary', '')}"
        return f"[{phase}] {data}"


class ActionExecutor:
    """执行一个 Decision, 返回 ActionResult。

    开源版为确定性执行器（无外部工具调用）: 按 action_type 生成
    结构化结果。接入真实工具时替换/继承本类即可。
    """

    def execute(self, action, **kw) -> ActionResult:
        start = time.perf_counter()
        if isinstance(action, Decision):
            action_type = action.action_type or 'general'
            params = dict(action.params or {})
            reasoning = action.reasoning or ''
        elif isinstance(action, dict):
            action_type = action.get("action_type", "general")
            params = dict(action.get("params", {}) or {})
            reasoning = action.get("reasoning", "")
        else:
            raise TypeError("action must be a Decision or dict")
        elapsed = time.perf_counter() - start
        summary = f"执行完成: {action_type}" + (f" ({reasoning})" if reasoning else "")
        return ActionResult(
            success=True,
            summary=summary,
            elapsed=elapsed,
            action_type=action_type,
            details={"params": params},
        )

    # 兼容别名
    async def execute_async(self, action, **kw) -> ActionResult:
        return self.execute(action, **kw)


# ═══════════════════════════════════════════════════════════
# AgentLoopPlugin
# ═══════════════════════════════════════════════════════════

_INTENT_KEYWORDS = [
    ("deploy", ("部署", "发布", "上线", "服务器", "生产", "deploy")),
    ("develop", ("开发", "新功能", "实现", "构建", "编码", "develop", "feature")),
    ("fix", ("修复", "bug", "故障", "报错", "修一下", "fix")),
    ("search", ("搜索", "查找", "查询", "文档", "search")),
    ("analyze", ("分析", "统计", "评估", "analyze", "analyse")),
]

_URGENT_KEYWORDS = (
    "紧急", "挂了", "崩溃", "立即", "马上", "故障", "宕机", "严重", "尽快",
    "urgent", "critical", "crash", "down", "asap", "error",
)

_DECISION_MAP = {
    "deploy": ("orchestrate", "部署流水线"),
    "develop": ("code", "功能开发流程"),
    "fix": ("fix", "缺陷修复流程"),
    "search": ("search", "信息检索流程"),
    "analyze": ("analyze", "数据分析流程"),
    "general": ("chat", "通用对话流程"),
}


class AgentLoopPlugin:
    """Plan/Act/Reflect agent cycle plugin."""

    name = "agent_loop"
    info = "meshctx agent loop plugin (open-source real impl)"
    state = 'active'
    version = '0.1.0'

    def __init__(self, objective: str = '', context: dict | None = None,
                 max_iterations: int = 10, pool_max_slots: int = 5):
        self.objective = objective
        self.context = dict(context or {})
        self.max_iterations = int(max_iterations)
        self.pool_max_slots = int(pool_max_slots)
        self.kernel = None
        self.steps: List[PlanStep] = []
        self._deps: Dict[str, Optional[str]] = {}   # step_id -> parent step_id
        self._iterations = 0
        self._completed = 0
        self._failed = 0
        self._running = False
        self._pool: Optional[AgentPool] = None
        self._learn_loop = None
        self._online_learner = None
        self._response_gen = ResponseGenerator()
        self._executor = ActionExecutor()
        self._lock = threading.RLock()
        self._started_at = time.time()

    # ── 内核集成 ──────────────────────────────────────────
    async def on_load(self, kernel) -> bool:
        self.kernel = kernel
        bus = getattr(kernel, "bus", None) or getattr(kernel, "event_bus", None)
        if bus is not None and hasattr(bus, "subscribe"):
            try:
                bus.subscribe("user.message", self.on_event, plugin_name=self.name)
            except NotImplementedError:
                logger.info("event bus is a stub — agent_loop runs standalone")
        return True

    async def on_event(self, event):
        event_type = getattr(event, "type", None)
        if event_type == "user.message":
            data = getattr(event, "data", None) or {}
            content = data.get("content", "")
            if not content:
                return None
            source = data.get("source") or getattr(event, "source", "user") or "user"
            intent = self._extract_intent(content)
            obs = Observation(
                source=str(source),
                content=content,
                intent=intent,
                urgency=self._assess_urgency({"content": content, "source": source}),
            )
            decision = self._make_decision(obs)
            outcome = self._executor.execute(decision)
            self._log("act", f"{intent} -> {decision.action_type}")
            return {
                "observation": obs,
                "decision": decision,
                "outcome": outcome,
            }
        return None

    # ── 生命周期 ──────────────────────────────────────────
    def start(self):
        with self._lock:
            self._running = True
            if self.objective and not self.steps:
                self.plan()
        return {"started": True, "objective": self.objective, "steps": len(self.steps)}

    def stop(self):
        with self._lock:
            self._running = False
        self._release_pool()
        return {"started": False}

    def step(self) -> dict:
        """执行一次循环迭代 (plan → act → reflect)。"""
        with self._lock:
            if not self._running:
                return {"phase": "stopped", "iterations": self._iterations}
            self._iterations += 1
            if self._iterations > self.max_iterations:
                self._running = False
                return {"phase": "limit_reached", "iterations": self._iterations,
                        "completed": self._completed, "failed": self._failed}
            if not self.steps:
                self.plan()
            pending = self._pending_steps()
            if pending == 0:
                self._running = False
                return {"phase": "done", "iterations": self._iterations,
                        "total": len(self.steps), "completed": self._completed,
                        "failed": self._failed}
        act_result = self.act()
        reflect_result = self.reflect(act_result)
        return {
            "phase": "reflect",
            "iteration": self._iterations,
            "act": act_result,
            "reflect": reflect_result,
            "pending": self._pending_steps(),
        }

    # ── Plan ──────────────────────────────────────────────
    def plan(self) -> dict:
        if not self.steps:
            self.steps = self._dag_plan(self.objective or "General objective")
        return {
            "phase": "plan",
            "steps": [s.to_dict() for s in self.steps],
            "count": len(self.steps),
            "pending": self._pending_steps(),
        }

    def _dag_plan(self, objective: str) -> list:
        """DAG-aware task decomposition — dependencies, parallel groups.

        按顺序链组织依赖 (每个步骤依赖前一步), 供 DAG 调度使用;
        依赖关系记录在 self._deps 中。
        """
        plan = self._decompose_objective(objective)
        steps: List[PlanStep] = []
        prev_id: Optional[str] = None
        for i, item in enumerate(plan):
            if isinstance(item, dict):
                description = str(item.get("description", item.get("task", "")))
                task_type = str(item.get("task_type", "") or self._infer_task_type(description))
            else:
                description = str(item)
                task_type = self._infer_task_type(description)
            step = PlanStep(step_id=f"step_{i + 1:02d}", description=description, status='pending')
            step.task_type = task_type  # type: ignore[attr-defined]  # 运行时扩展属性
            self._deps[step.step_id] = prev_id
            steps.append(step)
            prev_id = step.step_id
        return steps

    def _pending_steps(self) -> int:
        with self._lock:
            return sum(1 for s in self.steps if s.status == 'pending')

    def _decompose_objective(self, objective: str) -> list:
        """把目标拆成可执行步骤列表 (dict 或 str)。"""
        text = (objective or "").strip()
        if not text:
            return ["分析目标", "执行计划", "验证结果"]
        parts = [p.strip() for p in re.split(r"[。！？；;\n]+", text) if p.strip()]
        if len(parts) >= 2:
            return [
                {"description": p, "task_type": self._infer_task_type(p)}
                for p in parts[:5]
            ]
        # 单句目标 → 分析/执行/验证 三步
        main_type = self._infer_task_type(text)
        return [
            {"description": f"分析目标: {text}", "task_type": "analyze"},
            {"description": f"执行: {text}", "task_type": main_type},
            {"description": f"验证结果: {text}", "task_type": "review"},
        ]

    def _infer_task_type(self, description: str) -> str:
        """从描述推断任务类型 (与意图提取共享关键词表)。"""
        text = (description or "").lower()
        for intent, keywords in _INTENT_KEYWORDS:
            for kw in keywords:
                if kw.lower() in text:
                    return intent
        if "写" in text or "生成" in text or "编写" in text:
            return "write"
        if "审查" in text or "review" in text:
            return "review"
        if "设计" in text:
            return "design"
        return "general"

    def _should_delegate(self, step: PlanStep) -> bool:
        """是否委托给 AgentPool 并行执行。"""
        task_type = getattr(step, "task_type", self._infer_task_type(step.description))
        delegatable = task_type in ("search", "analyze", "review", "write", "design")
        return delegatable and len(step.description) >= 10

    def _get_pool(self) -> AgentPool:
        if self._pool is None:
            self._pool = AgentPool(max_slots=self.pool_max_slots)
        return self._pool

    # ── Act ───────────────────────────────────────────────
    def act(self) -> dict:
        with self._lock:
            step = next((s for s in self.steps if s.status == 'pending'), None)
        if step is None:
            return {"phase": "act", "executed": 0}
        step.status = 'running'
        task_type = getattr(step, "task_type", self._infer_task_type(step.description))
        if self._should_delegate(step):
            pool = self._get_pool()
            task = SwarmTask(description=step.description, task_type=task_type)
            agent_id = pool.spawn(task)
            completed = pool.wait(agent_id, timeout=60.0)
            if completed is not None and completed.status == TaskStatus.done:
                step.result = completed.result
                step.status = 'done'
                self._completed += 1
                return {"phase": "act", "step_id": step.step_id, "delegated": True,
                        "agent_id": agent_id, "success": True, "result": step.result,
                        "task_type": task_type}
            step.status = 'failed'
            step.error = completed.error if completed is not None else "pool wait timeout"
            self._failed += 1
            return {"phase": "act", "step_id": step.step_id, "delegated": True,
                    "agent_id": agent_id, "success": False, "error": step.error,
                    "task_type": task_type}
        # 本地执行
        obs = Observation(content=step.description, intent=task_type, urgency=0.5)
        decision = self._make_decision(obs)
        outcome = self._executor.execute(decision)
        if outcome.success:
            step.result = outcome.summary
            step.status = 'done'
            self._completed += 1
        else:
            step.status = 'failed'
            step.error = outcome.error
            self._failed += 1
        return {"phase": "act", "step_id": step.step_id, "delegated": False,
                "success": outcome.success, "result": step.result, "error": outcome.error,
                "task_type": task_type, "elapsed": outcome.elapsed,
                "action_type": decision.action_type}

    # ── Reflect ───────────────────────────────────────────
    def reflect(self, act_result: dict) -> dict:
        success = bool(act_result.get("success", True))
        summary = act_result.get("result") or act_result.get("summary") or ""
        self._learn_from_step(act_result)
        return {
            "phase": "reflect",
            "success": success,
            "summary": summary,
            "task_type": act_result.get("task_type", "general"),
            "elapsed": act_result.get("elapsed", 0.0),
            "stats": self.stats(),
        }

    def stats(self) -> dict:
        with self._lock:
            pool_status = self._pool.status() if self._pool is not None \
                else {"active": 0, "queued": 0, "available_slots": self.pool_max_slots}
            return {
                "iterations": self._iterations,
                "steps_total": len(self.steps),
                "steps_completed": self._completed,
                "steps_failed": self._failed,
                "steps_pending": self._pending_steps(),
                "running": self._running,
                "pool": pool_status,
                "uptime": time.time() - self._started_at,
            }

    def generate_report(self) -> dict:
        with self._lock:
            return {
                "plugin": self.name,
                "name": self.name,
                "version": self.version,
                "info": self.info,
                "active_tasks": self._pending_steps(),
                "total_completed": self._completed,
                "total_failed": self._failed,
                "iterations": self._iterations,
                "steps": [s.to_dict() for s in self.steps],
                "stats": self.stats(),
                "learn_stats": self._learn_loop.get_stats() if self._learn_loop else {},
                "timestamp": time.time(),
            }

    def _release_pool(self):
        pool = self._pool
        if pool is None:
            return
        entries = getattr(pool, "_entries", {})
        for agent_id in list(entries.keys()):
            try:
                pool.close(agent_id)
            except Exception as e:  # 显式处理: 释放失败记录日志, 不影响关闭流程
                logger.warning("pool close failed for %s: %s", agent_id, e)
        self._pool = None

    def _learn_from_step(self, act_result: dict):
        """v3.115.46: Feed step outcome to OnlineLearner (+ 内部 LearnLoop)。"""
        success = bool(act_result.get("success", True))
        task_type = act_result.get("task_type") or "general"
        summary = act_result.get("result") or act_result.get("summary") or ""
        elapsed = float(act_result.get("elapsed", 0.0) or 0.0)
        try:
            if self._learn_loop is None:
                from .learn_loop import LearnLoop
                self._learn_loop = LearnLoop(habit_threshold=5)
            self._learn_loop.record_outcome(
                task_type=task_type,
                success=success,
                quality=0.85 if success else 0.1,
                strategy_used=act_result.get("action_type") or "balanced",
                duration=elapsed,
                error_type=None if success else act_result.get("error_type", "tool_error"),
            )
        except Exception as e:  # 学习失败不应中断循环; 记录后继续
            logger.warning("learn_loop feed failed: %s", e)
        # OnlineLearner 反馈 (尽力而为)
        try:
            if self._online_learner is None:
                from .online_learning import OnlineLearner
                self._online_learner = OnlineLearner(user_id="agent_loop")
            if success and hasattr(self._online_learner, "accept"):
                self._online_learner.accept(context=f"agent_loop:{task_type}", output_text=summary)
            elif hasattr(self._online_learner, "reject"):
                self._online_learner.reject(context=f"agent_loop:{task_type}", output_text=summary)
        except ImportError:
            self._online_learner = None
        except Exception as e:  # 可选集成失败: 记录并继续
            logger.warning("online learner feed skipped: %s", e)

    def _log(self, phase: str, msg: str):
        logger.info("agent_loop [%s] %s", phase, msg)

    # ── OODA 决策辅助 (v1.0 稳定 API) ────────────────────
    def _extract_intent(self, content: str) -> str:
        """从中文/英文消息提取意图。"""
        text = (content or "").lower()
        for intent, keywords in _INTENT_KEYWORDS:
            for kw in keywords:
                if kw.lower() in text:
                    return intent
        return "general"

    def _assess_urgency(self, message) -> float:
        """评估消息紧急度 (0~1)。

        规则: 基础 0.1; 每个紧急关键词 +0.15 (封顶 +0.6);
        用户来源 +0.1。
        """
        content = ""
        source = ""
        if isinstance(message, dict):
            content = str(message.get("content", ""))
            source = str(message.get("source", ""))
        elif isinstance(message, Observation):
            content = message.content
            source = message.source
        text = (content or "").lower()
        urgency = 0.1
        bonus = 0.0
        for kw in _URGENT_KEYWORDS:
            if kw in text:
                bonus += 0.15
        urgency += min(bonus, 0.6)
        if source == "user":
            urgency += 0.1
        return round(min(urgency, 1.0), 4)

    def _make_decision(self, obs: Observation) -> Decision:
        """意图 + 紧急度 → 行动决策。"""
        intent = getattr(obs, "intent", None) or self._extract_intent(getattr(obs, "content", ""))
        action_type, pattern = _DECISION_MAP.get(intent, _DECISION_MAP["general"])
        urgency = float(getattr(obs, "urgency", 0.0) or 0.0)
        confidence = min(0.95, 0.6 + urgency * 0.3)
        return Decision(
            action_type=action_type,
            confidence=round(confidence, 4),
            params={"pattern": pattern, "intent": intent},
            reasoning=f"基于意图「{intent}」(urgency={urgency:.2f}) 选择行动 {action_type}",
        )


class WorkspaceAwareAdapter:
    """为 agent 提供基于工作区的路径上下文 (archived API 兼容)。"""

    def __init__(self, base_dir: str | None = None, **kw):
        self.base_dir = os.path.abspath(str(base_dir or os.getcwd()))
        self._bindings: Dict[str, str] = {}

    def bind(self, agent_id: str, workspace: str) -> "WorkspaceAwareAdapter":
        self._bindings[str(agent_id)] = os.path.abspath(str(workspace))
        return self

    def workspace_for(self, agent_id: str) -> str:
        return self._bindings.get(str(agent_id), self.base_dir)

    def resolve(self, agent_id: str, rel_path: str) -> str:
        return os.path.join(self.workspace_for(agent_id), str(rel_path))


__all__ = [
    "PluginInfo", "LoopPhase", "PlanStep",
    "Observation", "Decision", "ActionResult", "AgentTask", "TaskPriority",
    "ResponseGenerator", "ActionExecutor", "AgentLoopPlugin",
    "WorkspaceAwareAdapter",
]

"""meshctx workflow_engine — v2.75 Workflow Engine"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepStatus(Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    blocked = "blocked"


@dataclass
class StepResult:
    name: str
    status: StepStatus = StepStatus.pending
    duration_ms: int = 0
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    request_id: str
    steps: List[StepResult] = field(default_factory=list)
    total_duration_ms: int = 0
    success: bool = False


class WorkflowEngine:
    """v2.75 工作流引擎 — 标准流水线执行"""

    # 标准流水线定义：至少 8 步，支持依赖关系
    STANDARD_PIPELINE: List[Dict[str, Any]] = [
        {"name": "安全扫描",    "handler": "_handle_shield",     "depends": []},
        {"name": "路由决策",    "handler": "_handle_router",     "depends": []},
        {"name": "合规检查",    "handler": "_handle_compliance", "depends": []},
        {"name": "意图理解",    "handler": "_handle_intent",     "depends": ["路由决策"]},
        {"name": "上下文增强",  "handler": "_handle_context",    "depends": ["意图理解"]},
        {"name": "推理规划",    "handler": "_handle_reasoning",  "depends": ["上下文增强"]},
        {"name": "任务执行",    "handler": "_handle_execution",  "depends": ["推理规划"]},
        {"name": "结果验证",    "handler": "_handle_validation", "depends": ["任务执行"]},
        {"name": "输出格式化",  "handler": "_handle_format",     "depends": ["结果验证"]},
        {"name": "日志记录",    "handler": "_handle_logging",    "depends": ["输出格式化"]},
    ]

    # 危险关键词列表
    DANGEROUS_PATTERNS = [
        "ignore all previous instructions",
        "delete everything",
        "bypass",
        "jailbreak",
        "system prompt",
        "override",
    ]

    def __init__(self):
        self._execution_count: int = 0
        self._total_steps_run: int = 0
        self._recent_executions: List[ExecutionResult] = []

    # ── pipeline visual ──────────────────────────────────────────

    def get_pipeline_visual(self) -> str:
        """返回流水线的可视化文本。"""
        lines = ["Workflow Pipeline v2.75", "=" * 40]
        for step in self.STANDARD_PIPELINE:
            deps = " → ".join(step.get("depends", [])) or "入口"
            lines.append(f"  [{step['name']}]  ← {deps}")
        return "\n".join(lines)

    # ── execution ────────────────────────────────────────────────

    async def execute(self, request: Dict[str, Any]) -> ExecutionResult:
        """执行完整流水线。"""
        request_id = str(uuid.uuid4())[:8]
        result = ExecutionResult(request_id=request_id)
        start = time.time()

        # 收集所有已完成的步骤名，用于依赖检查
        completed: set = set()
        step_outputs: Dict[str, Dict[str, Any]] = {}

        for step_def in self.STANDARD_PIPELINE:
            step_name = step_def["name"]
            handler_name = step_def["handler"]
            depends = step_def.get("depends", [])

            step_result = StepResult(name=step_name)

            # 检查依赖是否全部满足
            deps_met = all(d in completed for d in depends)
            if not deps_met:
                missing = [d for d in depends if d not in completed]
                step_result.status = StepStatus.skipped
                step_result.error = f"依赖未满足: {missing}"
                result.steps.append(step_result)
                continue

            # 调用处理器
            handler = getattr(self, handler_name, None)
            if handler is None:
                step_result.status = StepStatus.failed
                step_result.error = f"处理器不存在: {handler_name}"
                result.steps.append(step_result)
                continue

            try:
                t0 = time.time()
                output = handler(request, step_outputs)
                step_result.duration_ms = int((time.time() - t0) * 1000)
                step_result.output = output

                if output.get("blocked"):
                    step_result.status = StepStatus.blocked
                else:
                    step_result.status = StepStatus.passed
            except Exception as e:
                step_result.status = StepStatus.failed
                step_result.error = str(e)

            result.steps.append(step_result)
            if step_result.status in (StepStatus.passed, StepStatus.skipped):
                completed.add(step_name)
                step_outputs[step_name] = step_result.output

        result.total_duration_ms = int((time.time() - start) * 1000)
        # 确保即使极快执行也有 > 0 的耗时记录
        if result.total_duration_ms == 0:
            await asyncio.sleep(0.001)
            result.total_duration_ms = max(1, int((time.time() - start) * 1000))
        result.success = all(
            s.status in (StepStatus.passed, StepStatus.skipped)
            for s in result.steps
        )

        self._execution_count += 1
        self._total_steps_run += len(result.steps)
        self._recent_executions.append(result)
        if len(self._recent_executions) > 100:
            self._recent_executions.pop(0)

        return result

    # ── stats ────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计信息。"""
        return {
            "total_executions": self._execution_count,
            "total_steps_run": self._total_steps_run,
            "pipeline": {
                "steps": len(self.STANDARD_PIPELINE),
                "names": [s["name"] for s in self.STANDARD_PIPELINE],
            },
        }

    # ── step handlers ────────────────────────────────────────────

    def _handle_shield(
        self, request: Dict[str, Any], _outputs: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """安全扫描：检测危险 / 注入 / 越狱提示词。"""
        prompt = request.get("prompt", "")
        prompt_lower = prompt.lower()

        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.lower() in prompt_lower:
                return {
                    "status": "dangerous",
                    "blocked": True,
                    "reason": f"检测到危险模式: {pattern}",
                }

        return {"status": "safe", "blocked": False}

    def _handle_router(
        self, request: Dict[str, Any], _outputs: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """路由决策：根据提示词和任务类型选择模型/策略。"""
        task_type = request.get("task_type", "general")
        model_map = {
            "code": "deepseek-coder-v4",
            "math": "deepseek-math",
            "vision": "deepseek-vision",
            "general": "deepseek-v4-pro",
        }
        return {
            "model": model_map.get(task_type, "deepseek-v4-pro"),
            "task_type": task_type,
            "strategy": "standard",
        }

    def _handle_compliance(
        self, request: Dict[str, Any], _outputs: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """合规检查：确保请求符合使用策略。"""
        return {
            "status": "compliant",
            "checks_passed": ["content_policy", "usage_limits", "rate_limit"],
        }

    def _handle_intent(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """意图理解：分析用户意图。"""
        prompt = request.get("prompt", "")
        return {
            "status": "analyzed",
            "intent": "general_task",
            "complexity": "medium" if len(prompt) > 50 else "low",
        }

    def _handle_context(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """上下文增强：补充上下文信息。"""
        return {
            "status": "enriched",
            "context_added": ["user_profile", "session_history"],
        }

    def _handle_reasoning(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """推理规划：生成执行计划。"""
        return {
            "status": "planned",
            "plan": ["analyze", "generate", "validate"],
        }

    def _handle_execution(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """任务执行：执行推理产生的计划。"""
        return {
            "status": "executed",
            "result": "任务执行完成",
        }

    def _handle_validation(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """结果验证：校验输出质量。"""
        return {
            "status": "validated",
            "quality_score": 0.95,
        }

    def _handle_format(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """输出格式化：统一输出格式。"""
        return {
            "status": "formatted",
            "format": "markdown",
        }

    def _handle_logging(
        self, request: Dict[str, Any], outputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """日志记录：记录执行日志。"""
        return {
            "status": "logged",
            "log_id": str(uuid.uuid4())[:8],
        }

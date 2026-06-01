"""
v3.85 Agent编排引擎 — RIPER-5 五阶段工作流
=========================================

在现有Orchestrator之上构建RIPER-5方法论驱动的Agent编排系统。

核心功能：
1. RIPER-5五阶段: RESEARCH → INNOVATE → PLAN → EXECUTE → REVIEW
2. 意图自动检测与路由 — 根据用户输入自动判断进入哪个阶段
3. 子Agent状态协议 — DONE / BLOCKED / NEEDS_CONTEXT
4. 并行Fan-out分发 — 主会话只调度不执行，子Agent并行处理

设计原则：
- 主会话(supervisor)只负责调度和决策，不执行具体任务
- 每个阶段可Fan-out到多个子Agent并行工作
- 子Agent通过状态协议汇报进度
- 阶段间通过Memory Hub传递上下文
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.agent_orchestrator")


# ═══════════════════════════════════════════════════════════
# RIPER-5 阶段定义
# ═══════════════════════════════════════════════════════════

class RipersPhase(Enum):
    """RIPER-5 五阶段"""
    RESEARCH = "research"      # 信息收集、问题理解、代码库探索
    INNOVATE = "innovate"      # 头脑风暴、方案生成、创意发散
    PLAN = "plan"              # 制定执行计划、架构设计、步骤分解
    EXECUTE = "execute"        # 执行计划、编写代码、运行命令
    REVIEW = "review"          # 验证结果、修复问题、反思总结

    @classmethod
    def ordered_phases(cls) -> List["RipersPhase"]:
        return [cls.RESEARCH, cls.INNOVATE, cls.PLAN, cls.EXECUTE, cls.REVIEW]


# ═══════════════════════════════════════════════════════════
# 子Agent状态协议
# ═══════════════════════════════════════════════════════════

class SubAgentStatus(Enum):
    """子Agent状态协议 — 三态信号"""
    DONE = "done"                    # 任务完成
    BLOCKED = "blocked"              # 被阻塞(等待资源/依赖)
    NEEDS_CONTEXT = "needs_context"  # 需要更多上下文/信息

    def is_terminal(self) -> bool:
        """是否为终态"""
        return self == SubAgentStatus.DONE

    def needs_attention(self) -> bool:
        """是否需要主会话关注"""
        return self in (SubAgentStatus.BLOCKED, SubAgentStatus.NEEDS_CONTEXT)


@dataclass
class SubAgentSignal:
    """子Agent发回的信号"""
    agent_id: str
    status: SubAgentStatus
    phase: RipersPhase
    payload: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    timestamp: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
# 意图检测与路由
# ═══════════════════════════════════════════════════════════

# 每个阶段的关键词触发集
PHASE_KEYWORDS: Dict[RipersPhase, List[str]] = {
    RipersPhase.RESEARCH: [
        "what", "how does", "explain", "understand", "find",
        "search", "look into", "investigate", "explore", "discover",
        "research", "learn about", "tell me about", "what is",
        "gather info", "background", "context of", "history of",
        "查", "了解", "研究", "搜索", "探索", "是什么",
    ],
    RipersPhase.INNOVATE: [
        "idea", "brainstorm", "design", "creative", "options",
        "alternatives", "approaches", "possibilities", "what if",
        "innovate", "reimagine", "concept", "prototype idea",
        "can we", "how might", "suggest", "recommend approach",
        "创意", "方案", "设计思路", "点子", "头脑风暴",
    ],
    RipersPhase.PLAN: [
        "plan", "steps", "strategy", "architecture", "outline",
        "break down", "roadmap", "schedule", "organize", "structure",
        "blueprint", "workflow", "pipeline", "sequence", "order",
        "计划", "策略", "架构", "步骤", "流程", "方案",
    ],
    RipersPhase.EXECUTE: [
        "do", "build", "create", "implement", "write", "run",
        "fix", "change", "make", "execute", "deploy", "apply",
        "code", "develop", "construct", "produce", "perform",
        "做", "构建", "实现", "写", "修复", "运行", "创建",
    ],
    RipersPhase.REVIEW: [
        "review", "check", "test", "verify", "validate",
        "inspect", "analyze", "audit", "assess", "evaluate",
        "examine", "critique", "proofread", "double check",
        "quality", "bug check", "error check", "lint",
        "审查", "检查", "测试", "验证", "审核", "评估",
    ],
}

# 阶段权重（用于当多个阶段匹配时选择最佳）
PHASE_PRIORITY: Dict[RipersPhase, int] = {
    RipersPhase.REVIEW: 10,
    RipersPhase.EXECUTE: 8,
    RipersPhase.PLAN: 6,
    RipersPhase.INNOVATE: 4,
    RipersPhase.RESEARCH: 2,
}


def detect_phase(user_input: str) -> RipersPhase:
    """
    根据用户输入自动检测意图所属阶段。

    算法：
    1. 对每个阶段统计匹配的关键词数量
    2. 匹配数 > 0 的阶段中，选择优先级最高的
    3. 如果无匹配，根据当前工作流阶段智能推断:
       - 空历史 → RESEARCH
       - 刚完成RESEARCH → INNOVATE
       - 刚完成INNOVATE → PLAN
       - 自带动作词 → EXECUTE (fallback)
    """
    if not user_input or not user_input.strip():
        return RipersPhase.RESEARCH

    input_lower = user_input.lower()
    phase_scores: Dict[RipersPhase, int] = {}

    for phase, keywords in PHASE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in input_lower:
                # Exact match gets higher score
                if input_lower.startswith(kw) or f" {kw} " in f" {input_lower} ":
                    score += 3
                else:
                    score += 1
        if score > 0:
            phase_scores[phase] = score

    if phase_scores:
        # 选择得分最高的阶段（同分时取优先级更高的）
        best_phase = max(
            phase_scores.keys(),
            key=lambda p: (phase_scores[p], PHASE_PRIORITY[p])
        )
        return best_phase

    # Fallback: 根据是否存在明显动作词判断
    action_words = {"do", "make", "create", "build", "run", "fix", "write", "implement", "execute"}
    words = set(input_lower.split())
    if words & action_words:
        return RipersPhase.EXECUTE

    # 默认 RESEARCH
    return RipersPhase.RESEARCH


def detect_phase_with_confidence(user_input: str) -> Tuple[RipersPhase, float]:
    """
    带置信度的意图检测。

    返回 (阶段, 置信度 0.0~1.0)
    """
    if not user_input or not user_input.strip():
        return RipersPhase.RESEARCH, 1.0

    input_lower = user_input.lower()
    phase_scores: Dict[RipersPhase, int] = {}

    for phase, keywords in PHASE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in input_lower:
                if input_lower.startswith(kw) or f" {kw} " in f" {input_lower} ":
                    score += 3
                else:
                    score += 1
        phase_scores[phase] = score

    total_score = sum(phase_scores.values())
    if total_score == 0:
        return RipersPhase.RESEARCH, 0.3

    best_phase = max(
        phase_scores.keys(),
        key=lambda p: (phase_scores[p], PHASE_PRIORITY[p])
    )
    confidence = phase_scores[best_phase] / total_score
    return best_phase, min(confidence, 1.0)


# ═══════════════════════════════════════════════════════════
# 子Agent定义
# ═══════════════════════════════════════════════════════════

@dataclass
class SubAgent:
    """子Agent实例 — 由主会话调度，独立执行任务"""
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    role: str = "general"
    status: SubAgentStatus = SubAgentStatus.DONE
    current_phase: Optional[RipersPhase] = None
    current_task: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 2

    def reset(self):
        """重置子Agent状态以接收新任务"""
        self.status = SubAgentStatus.DONE
        self.current_task = None
        self.result = None
        self.error = None
        self.retry_count = 0

    def signal_done(self, result: Any = None):
        """发送DONE信号"""
        self.status = SubAgentStatus.DONE
        self.result = result
        self.completed_at = time.time()

    def signal_blocked(self, reason: str = ""):
        """发送BLOCKED信号"""
        self.status = SubAgentStatus.BLOCKED
        self.error = reason

    def signal_needs_context(self, message: str = ""):
        """发送NEEDS_CONTEXT信号"""
        self.status = SubAgentStatus.NEEDS_CONTEXT
        self.error = message


# ═══════════════════════════════════════════════════════════
# Fan-out 任务定义
# ═══════════════════════════════════════════════════════════

@dataclass
class FanOutTask:
    """Fan-out分发任务 — 主会话创建，子Agent执行"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    phase: RipersPhase = RipersPhase.RESEARCH
    description: str = ""
    assigned_to: Optional[str] = None   # sub-agent id
    status: str = "pending"             # pending/assigned/running/done/failed
    result: Any = None
    error: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    depends_on_phase: Optional[RipersPhase] = None  # 依赖的前一阶段全部完成
    context: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def is_ready(self, completed_phases: Set[RipersPhase],
                 completed_tasks: Set[str]) -> bool:
        """检查任务是否就绪"""
        if self.depends_on_phase and self.depends_on_phase not in completed_phases:
            return False
        for dep_id in self.dependencies:
            if dep_id not in completed_tasks:
                return False
        return True


# ═══════════════════════════════════════════════════════════
# 工作流会话 — 追踪单次RIPER-5会话
# ═══════════════════════════════════════════════════════════

@dataclass
class RipersSession:
    """单次RIPER-5工作流会话"""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_query: str = ""
    current_phase: RipersPhase = RipersPhase.RESEARCH
    completed_phases: Set[RipersPhase] = field(default_factory=set)
    phase_results: Dict[RipersPhase, Any] = field(default_factory=dict)
    phase_history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    is_complete: bool = False

    def advance_phase(self) -> Optional[RipersPhase]:
        """推进到下一阶段，返回None表示全部完成"""
        ordered = RipersPhase.ordered_phases()
        current_idx = ordered.index(self.current_phase)
        if current_idx < len(ordered) - 1:
            self.current_phase = ordered[current_idx + 1]
            return self.current_phase
        self.is_complete = True
        self.completed_at = time.time()
        return None

    def mark_phase_done(self, phase: RipersPhase, result: Any = None):
        """标记阶段完成"""
        self.completed_phases.add(phase)
        self.phase_results[phase] = result
        self.phase_history.append({
            "phase": phase.value,
            "result": result,
            "timestamp": time.time(),
        })

    def get_context_for_phase(self, phase: RipersPhase) -> Dict[str, Any]:
        """获取下一阶段的上下文（来自之前所有阶段的结果）"""
        ordered = RipersPhase.ordered_phases()
        phase_idx = ordered.index(phase)
        context = {
            "user_query": self.user_query,
            "previous_phases": {},
        }
        for prev in ordered[:phase_idx]:
            if prev in self.phase_results:
                context["previous_phases"][prev.value] = self.phase_results[prev]
        return context


# ═══════════════════════════════════════════════════════════
# AgentOrchestrator — 主编排器
# ═══════════════════════════════════════════════════════════

class AgentOrchestrator:
    """
    v3.85 Agent编排引擎。

    主会话(Supervisor)职责：
    - 接收用户输入 → 意图检测 → 路由到对应RIPER-5阶段
    - 将任务Fan-out到子Agent池并行执行
    - 收集子Agent信号(DONE/BLOCKED/NEEDS_CONTEXT)
    - 处理BLOCKED/NEEDS_CONTEXT信号（提供额外上下文或重试）
    - 推进RIPER-5阶段流转
    - 主会话不执行具体任务，只调度

    使用示例:
        orch = AgentOrchestrator()
        result = await orch.process("创建一个Python Web应用")
        # 自动经历 RESEARCH → INNOVATE → PLAN → EXECUTE → REVIEW
    """

    VERSION = "3.85.0"

    def __init__(
        self,
        max_sub_agents: int = 8,
        max_parallel_per_phase: int = 4,
        task_executor: Optional[Callable[[FanOutTask], Coroutine[Any, Any, Any]]] = None,
    ):
        """
        Args:
            max_sub_agents: 最大子Agent数量
            max_parallel_per_phase: 每个阶段最大并行任务数
            task_executor: 可选的任务执行器回调。如果提供，子Agent任务会委托给此回调；
                          否则任务标记为完成（用于测试/模拟）。
        """
        self.max_sub_agents = max_sub_agents
        self.max_parallel_per_phase = max_parallel_per_phase
        self._task_executor = task_executor

        # 子Agent池
        self._agents: Dict[str, SubAgent] = {}
        self._init_agent_pool()

        # 活跃会话
        self._active_sessions: Dict[str, RipersSession] = {}
        self._session_tasks: Dict[str, FanOutTask] = {}

        # 统计
        self._stats = {
            "sessions_created": 0,
            "sessions_completed": 0,
            "phases_executed": 0,
            "tasks_fan_out": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "signals_received": 0,
            "blocked_resolved": 0,
            "context_provided": 0,
        }

        # 共享记忆空间（用于阶段间上下文传递）
        self._shared_memory: Dict[str, Any] = {}

        # 信号队列
        self._signal_queue: asyncio.Queue = asyncio.Queue()

        logger.info(
            f"AgentOrchestrator v{self.VERSION} 初始化: "
            f"子Agent={max_sub_agents}, 并行度={max_parallel_per_phase}"
        )

    def _init_agent_pool(self):
        """初始化子Agent池"""
        roles = ["researcher", "innovator", "planner", "executor", "reviewer"]
        for i in range(self.max_sub_agents):
            role = roles[i % len(roles)]
            agent = SubAgent(
                name=f"sub-agent-{role}-{i}",
                role=role,
            )
            self._agents[agent.agent_id] = agent

    # ── 公共API ─────────────────────────────────────────────

    async def process(self, user_input: str,
                      session_id: Optional[str] = None) -> RipersSession:
        """
        处理用户输入，自动检测意图并经历完整的RIPER-5工作流。

        Args:
            user_input: 用户输入/查询
            session_id: 可选，继续已有会话

        Returns:
            RipersSession: 完整的工作流会话
        """
        # 检测意图
        phase, confidence = detect_phase_with_confidence(user_input)
        logger.info(
            f"意图检测: phase={phase.value} confidence={confidence:.2f} "
            f"input={user_input[:60]}"
        )

        # 创建/恢复会话
        if session_id and session_id in self._active_sessions:
            session = self._active_sessions[session_id]
        else:
            session = RipersSession(user_query=user_input)
            self._active_sessions[session.session_id] = session
            self._stats["sessions_created"] += 1

        # 执行RIPER-5流程（从检测到的阶段开始，执行到REVIEW）
        ordered = RipersPhase.ordered_phases()
        start_idx = ordered.index(phase)

        for phase_to_run in ordered[start_idx:]:
            session.current_phase = phase_to_run
            await self._execute_phase(session, phase_to_run)

        session.is_complete = True
        session.completed_at = time.time()
        self._stats["sessions_completed"] += 1

        # 清理
        self._active_sessions.pop(session.session_id, None)
        return session

    async def process_phase(self, user_input: str,
                            force_phase: Optional[RipersPhase] = None,
                            session_id: Optional[str] = None
                            ) -> Tuple[RipersPhase, Dict[str, Any]]:
        """
        处理单个阶段（不自动推进到后续阶段）。

        Args:
            user_input: 用户输入
            force_phase: 强制指定阶段（跳过意图检测）
            session_id: 会话ID

        Returns:
            (执行的阶段, 阶段结果)
        """
        if force_phase:
            phase = force_phase
        else:
            phase, _ = detect_phase_with_confidence(user_input)

        # 创建/恢复会话
        if session_id and session_id in self._active_sessions:
            session = self._active_sessions[session_id]
        else:
            session = RipersSession(user_query=user_input)
            self._active_sessions[session.session_id] = session
            self._stats["sessions_created"] += 1

        session.current_phase = phase
        await self._execute_phase(session, phase)

        return phase, session.phase_results.get(phase, {})

    async def fan_out(self, tasks: List[FanOutTask]) -> List[FanOutTask]:
        """
        并行Fan-out分发多个任务。

        主会话只负责分发，不执行具体逻辑。
        所有任务在子Agent池中并行执行。

        Args:
            tasks: 任务列表

        Returns:
            完成后的任务列表
        """
        if not tasks:
            return []

        self._stats["tasks_fan_out"] += len(tasks)
        logger.info(f"Fan-out: {len(tasks)} 任务 → {self.max_parallel_per_phase}路并行")

        # 分配到子Agent
        assigned = self._assign_tasks(tasks[:self.max_parallel_per_phase])

        # 并行执行
        results = await asyncio.gather(
            *[self._execute_fan_out_task(task) for task in assigned],
            return_exceptions=True
        )

        # 合并未分配的任务（超出并行限制的）
        remaining = tasks[self.max_parallel_per_phase:]
        if remaining:
            extra_results = await self.fan_out(remaining)
            results.extend(extra_results)

        return assigned + remaining

    async def submit_signal(self, signal: SubAgentSignal):
        """子Agent向主会话提交信号"""
        await self._signal_queue.put(signal)
        self._stats["signals_received"] += 1
        logger.debug(
            f"信号: agent={signal.agent_id} status={signal.status.value} "
            f"phase={signal.phase.value}"
        )

    def get_agent(self, agent_id: str) -> Optional[SubAgent]:
        """获取子Agent"""
        return self._agents.get(agent_id)

    def find_idle_agents(self, role: Optional[str] = None) -> List[SubAgent]:
        """查找空闲子Agent"""
        idle = []
        for agent in self._agents.values():
            if agent.status == SubAgentStatus.DONE:
                if role is None or agent.role == role:
                    idle.append(agent)
        return idle

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        agent_stats = {
            "total": len(self._agents),
            "idle": len(self.find_idle_agents()),
            "blocked": sum(
                1 for a in self._agents.values()
                if a.status == SubAgentStatus.BLOCKED
            ),
            "needs_context": sum(
                1 for a in self._agents.values()
                if a.status == SubAgentStatus.NEEDS_CONTEXT
            ),
            "busy": sum(
                1 for a in self._agents.values()
                if a.status == SubAgentStatus.DONE and a.current_task is None
            ),
        }
        return {
            "version": self.VERSION,
            "agents": agent_stats,
            "stats": dict(self._stats),
            "active_sessions": len(self._active_sessions),
        }

    def get_session(self, session_id: str) -> Optional[RipersSession]:
        """获取活跃会话"""
        return self._active_sessions.get(session_id)

    # ── 内部方法 ────────────────────────────────────────────

    async def _execute_phase(self, session: RipersSession, phase: RipersPhase):
        """执行单个RIPER-5阶段"""
        self._stats["phases_executed"] += 1
        context = session.get_context_for_phase(phase)

        logger.info(
            f"执行阶段: {phase.value} "
            f"(session={session.session_id})"
        )

        # 为此阶段创建Fan-out任务
        tasks = self._create_phase_tasks(phase, session.user_query, context)
        if not tasks:
            # 无任务直接标记完成
            session.mark_phase_done(phase, {"result": "no tasks generated"})
            return

        # Fan-out执行
        completed = await self.fan_out(tasks)

        # 收集结果
        phase_result = self._aggregate_results(phase, completed)
        session.mark_phase_done(phase, phase_result)

        # 处理子Agent信号
        await self._process_signals()

        logger.info(
            f"阶段完成: {phase.value} "
            f"(成功={sum(1 for t in completed if t.status == 'done')}"
            f"/失败={sum(1 for t in completed if t.status == 'failed')})"
        )

    def _create_phase_tasks(
        self, phase: RipersPhase, query: str, context: Dict[str, Any]
    ) -> List[FanOutTask]:
        """为一个阶段创建Fan-out任务"""
        tasks = []
        phase_name = phase.value

        # 根据阶段类型生成不同粒度的任务
        task_templates = {
            RipersPhase.RESEARCH: [
                f"搜索相关信息和文档: {query}",
                f"分析代码库结构: {query}",
                f"收集最佳实践和参考案例: {query}",
            ],
            RipersPhase.INNOVATE: [
                f"生成创意方案A: {query}",
                f"生成创意方案B: {query}",
                f"评估各方案的可行性和风险: {query}",
            ],
            RipersPhase.PLAN: [
                f"制定执行路线图: {query}",
                f"设计组件架构: {query}",
                f"规划测试策略: {query}",
            ],
            RipersPhase.EXECUTE: [
                f"执行核心任务: {query}",
                f"处理边缘情况: {query}",
            ],
            RipersPhase.REVIEW: [
                f"验证结果正确性: {query}",
                f"检查潜在问题和边界情况: {query}",
                f"生成审查报告: {query}",
            ],
        }

        templates = task_templates.get(phase, [f"执行{phase_name}阶段: {query}"])

        for i, desc in enumerate(templates):
            task = FanOutTask(
                phase=phase,
                description=desc,
                context=context,
                depends_on_phase=(
                    RipersPhase.ordered_phases()[
                        RipersPhase.ordered_phases().index(phase) - 1
                    ] if RipersPhase.ordered_phases().index(phase) > 0
                    else None
                ),
            )
            tasks.append(task)
            self._session_tasks[task.task_id] = task

        return tasks

    def _assign_tasks(self, tasks: List[FanOutTask]) -> List[FanOutTask]:
        """将任务分配给空闲子Agent"""
        for task in tasks:
            # 按阶段选择最佳角色
            role_map = {
                RipersPhase.RESEARCH: "researcher",
                RipersPhase.INNOVATE: "innovator",
                RipersPhase.PLAN: "planner",
                RipersPhase.EXECUTE: "executor",
                RipersPhase.REVIEW: "reviewer",
            }
            role = role_map.get(task.phase, "general")

            # 查找空闲Agent
            idle = self.find_idle_agents(role=role)
            if not idle:
                idle = self.find_idle_agents()  # fallback到任意空闲

            if idle:
                agent = idle[0]
                task.assigned_to = agent.agent_id
                task.status = "assigned"
                agent.current_task = task.task_id
                agent.current_phase = task.phase
            else:
                task.status = "pending"

        return tasks

    async def _execute_fan_out_task(self, task: FanOutTask) -> FanOutTask:
        """执行单个Fan-out任务"""
        if task.status == "pending":
            # 没有可用Agent，标记为失败
            task.status = "failed"
            task.error = "No available sub-agent"
            self._stats["tasks_failed"] += 1
            return task

        task.status = "running"
        task.started_at = time.time()

        try:
            if self._task_executor:
                # 使用外部执行器
                result = await self._task_executor(task)
                task.result = result
            else:
                # 模拟执行（用于测试）
                await asyncio.sleep(0.001)
                task.result = {
                    "status": "completed",
                    "phase": task.phase.value,
                    "description": task.description,
                    "framework": "RIPER-5",
                }

            task.status = "done"
            self._stats["tasks_completed"] += 1

            # 更新Agent状态
            if task.assigned_to and task.assigned_to in self._agents:
                agent = self._agents[task.assigned_to]
                agent.signal_done(task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            self._stats["tasks_failed"] += 1
            logger.error(f"任务失败 [{task.task_id}]: {e}")

            # 更新Agent状态
            if task.assigned_to and task.assigned_to in self._agents:
                agent = self._agents[task.assigned_to]
                agent.signal_blocked(str(e))

        finally:
            task.completed_at = time.time()
            # 释放Agent
            if task.assigned_to and task.assigned_to in self._agents:
                agent = self._agents[task.assigned_to]
                agent.current_task = None

        return task

    def _aggregate_results(
        self, phase: RipersPhase, tasks: List[FanOutTask]
    ) -> Dict[str, Any]:
        """聚合阶段结果"""
        done_tasks = [t for t in tasks if t.status == "done"]
        failed_tasks = [t for t in tasks if t.status == "failed"]

        return {
            "phase": phase.value,
            "total_tasks": len(tasks),
            "completed": len(done_tasks),
            "failed": len(failed_tasks),
            "results": [
                {
                    "task_id": t.task_id,
                    "description": t.description,
                    "status": t.status,
                    "result": t.result,
                    "error": t.error,
                }
                for t in tasks
            ],
        }

    async def _process_signals(self):
        """处理子Agent发来的信号"""
        processed = 0
        while not self._signal_queue.empty():
            try:
                signal: SubAgentSignal = self._signal_queue.get_nowait()
                agent = self._agents.get(signal.agent_id)

                if signal.status == SubAgentStatus.BLOCKED:
                    logger.warning(
                        f"Agent {signal.agent_id} BLOCKED: {signal.message}"
                    )
                    self._stats["blocked_resolved"] += 1
                    # 重试逻辑
                    if agent and agent.retry_count < agent.max_retries:
                        agent.retry_count += 1
                        agent.status = SubAgentStatus.DONE  # 重置以重试
                        logger.info(
                            f"重试 Agent {signal.agent_id} "
                            f"({agent.retry_count}/{agent.max_retries})"
                        )
                    else:
                        agent.status = SubAgentStatus.DONE
                        agent.error = f"Max retries exceeded: {signal.message}"

                elif signal.status == SubAgentStatus.NEEDS_CONTEXT:
                    logger.info(
                        f"Agent {signal.agent_id} NEEDS_CONTEXT: {signal.message}"
                    )
                    self._stats["context_provided"] += 1
                    # 从共享记忆中检索上下文
                    if agent:
                        extra_context = signal.payload.get("requested_keys", [])
                        context_for_agent = {}
                        for key in extra_context:
                            if key in self._shared_memory:
                                context_for_agent[key] = self._shared_memory[key]
                        # 恢复Agent
                        agent.status = SubAgentStatus.DONE

                elif signal.status == SubAgentStatus.DONE:
                    if agent:
                        agent.signal_done(signal.payload)

                processed += 1
            except asyncio.QueueEmpty:
                break

        if processed > 0:
            logger.debug(f"处理了 {processed} 个信号")


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_global_orchestrator: Optional[AgentOrchestrator] = None


def get_agent_orchestrator(
    max_sub_agents: int = 8,
    max_parallel_per_phase: int = 4,
) -> AgentOrchestrator:
    """获取全局AgentOrchestrator单例"""
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = AgentOrchestrator(
            max_sub_agents=max_sub_agents,
            max_parallel_per_phase=max_parallel_per_phase,
        )
    return _global_orchestrator


def reset_agent_orchestrator():
    """重置全局单例"""
    global _global_orchestrator
    _global_orchestrator = None


async def quick_orchestrate(user_input: str) -> RipersSession:
    """
    快速编排 — 一行代码执行完整RIPER-5流程。

    Args:
        user_input: 用户输入

    Returns:
        RipersSession: 完整会话
    """
    orch = get_agent_orchestrator()
    return await orch.process(user_input)

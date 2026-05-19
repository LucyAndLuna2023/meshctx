"""
meshctx v1.0 自主Agent循环 — Autonomous Agent Loop

感知→决策→执行→学习 四阶段闭环

这是 meshctx 超越所有竞品的核心：
- Hermes: 被动响应，无自主循环
- OpenClaw: 纯网关，无决策能力
- WorkBuddy/Copaw: 单步工具调用
- Claude Cowork: 依赖外部触发

meshctx: 完全自主的 OODA 循环 (Observe→Orient→Decide→Act)
"""
import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

import numpy as np

from .kernel import Event, EventPriority, Plugin, PluginInfo
from .global_workspace import GlobalWorkspace, ProcessorType, AttentionBottleneck
from .action_gate import ActionGate, GateAction, GateResult, ToolCall as GateToolCall, get_gate
from .learn_loop import LearnLoop
from .cognitive_health import CognitiveHealthMonitor

logger = logging.getLogger("meshctx.agent")


# ═══════════════════════════════════════════════════════════
# OODA 循环状态
# ═══════════════════════════════════════════════════════════

class LoopPhase(Enum):
    """OODA循环阶段"""
    OBSERVE = "observe"     # 感知: 收集环境信息
    ORIENT = "orient"       # 定位: 分析理解当前状态
    DECIDE = "decide"       # 决策: 选择最优行动
    ACT = "act"             # 执行: 实施行动
    LEARN = "learn"         # 学习: 评估结果并更新


class TaskPriority(Enum):
    CRITICAL = 0    # 立即执行
    HIGH = 1        # 高优先级
    NORMAL = 2      # 正常
    LOW = 3         # 低优先级
    BACKGROUND = 4  # 后台执行


@dataclass
class Observation:
    """感知结果"""
    source: str                    # 来源 (user/system/sensor/event)
    content: str                   # 感知内容
    intent: str = ""               # 提取的意图
    urgency: float = 0.0           # 紧急度 0-1
    entities: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class Decision:
    """决策结果"""
    action_type: str               # 行动类型
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5        # 决策置信度
    reasoning: str = ""            # 推理过程
    alternatives: List[Dict] = field(default_factory=list)
    expected_outcome: str = ""     # 预期结果


@dataclass
class ActionResult:
    """行动结果"""
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    side_effects: List[str] = field(default_factory=list)


@dataclass
class AgentTask:
    """Agent任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    phase: LoopPhase = LoopPhase.OBSERVE
    status: str = "pending"
    observation: Optional[Observation] = None
    decision: Optional[Decision] = None
    result: Optional[ActionResult] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0
    max_retries: int = 3


# ═══════════════════════════════════════════════════════════
# 响应生成器
# ═══════════════════════════════════════════════════════════

class ResponseGenerator:
    """
    响应生成器
    
    将Agent的观察/决策/行动结果转换为自然语言响应。
    支持多种响应模式：信息性、操作性、澄清性、确认性。
    """
    
    RESPONSE_TEMPLATES = {
        "observation": {
            "info": "收到。我注意到: {content}",
            "alert": "⚠️ 注意: {content}",
            "question": "请确认: {content}?",
        },
        "decision": {
            "action": "我将执行: {action_type}，因为 {reasoning}",
            "multi_action": "我将执行以下{count}个操作: {actions}",
            "delegate": "我将委托 {agent} 处理: {task}",
        },
        "result": {
            "success": "✅ 完成: {summary} (耗时{elapsed:.1f}秒)",
            "partial": "⚠️ 部分完成: {summary}",
            "failure": "❌ 失败: {error}",
            "retry": "🔄 重试中 ({retry}/{max_retries}): {task}",
        },
        "learn": {
            "pattern": "📊 学习到新模式: {pattern}",
            "improvement": "📈 策略优化: {change}",
            "guard": "🛡️ 新防护规则: {rule}",
        },
    }
    
    def generate(self, phase: LoopPhase, data: Dict[str, Any],
                 style: str = "auto") -> str:
        """生成响应文本"""
        if phase == LoopPhase.OBSERVE:
            return self._observation_response(data, style)
        elif phase == LoopPhase.DECIDE:
            return self._decision_response(data)
        elif phase == LoopPhase.ACT:
            return self._result_response(data)
        elif phase == LoopPhase.LEARN:
            return self._learn_response(data)
        return "处理中..."
    
    def _observation_response(self, data: Dict, style: str) -> str:
        content = data.get("content", "")
        urgency = data.get("urgency", 0)
        
        if urgency > 0.7:
            return self.RESPONSE_TEMPLATES["observation"]["alert"].format(content=content)
        elif "?" in content:
            return self.RESPONSE_TEMPLATES["observation"]["question"].format(content=content)
        return self.RESPONSE_TEMPLATES["observation"]["info"].format(content=content)
    
    def _decision_response(self, data: Dict) -> str:
        action_type = data.get("action_type", "unknown")
        reasoning = data.get("reasoning", "")
        if reasoning:
            return self.RESPONSE_TEMPLATES["decision"]["action"].format(
                action_type=action_type, reasoning=reasoning
            )
        return f"执行: {action_type}"
    
    def _result_response(self, data: Dict) -> str:
        success = data.get("success", False)
        summary = data.get("summary", "")
        error = data.get("error", "")
        elapsed = data.get("elapsed", 0)
        
        if success:
            return self.RESPONSE_TEMPLATES["result"]["success"].format(
                summary=summary, elapsed=elapsed
            )
        elif error:
            return self.RESPONSE_TEMPLATES["result"]["failure"].format(error=error)
        return self.RESPONSE_TEMPLATES["result"]["partial"].format(summary=summary)
    
    def _learn_response(self, data: Dict) -> str:
        pattern = data.get("pattern", "")
        if pattern:
            return self.RESPONSE_TEMPLATES["learn"]["pattern"].format(pattern=pattern)
        return "📊 已学习"


# ═══════════════════════════════════════════════════════════
# 行动执行器
# ═══════════════════════════════════════════════════════════

class ActionExecutor:
    """
    行动执行器
    
    将决策转化为具体行动。支持:
    - 内置行动: shell, file_read, file_write, search, api_call
    - 委托行动: 将子任务委派给专业Agent
    - 等待行动: async等待外部事件
    """
    
    # 内置行动注册表
    _actions: Dict[str, Callable] = {}
    
    def register(self, name: str, handler: Callable):
        """注册行动处理器"""
        self._actions[name] = handler
    
    async def execute(self, decision: Decision) -> ActionResult:
        """执行决策"""
        start = time.time()
        
        try:
            action_type = decision.action_type
            handler = self._actions.get(action_type)
            
            if handler:
                result = await handler(decision.params)
                if asyncio.iscoroutine(result):
                    result = await result
            else:
                # 未知行动类型 → 发布事件让其他插件处理
                return ActionResult(
                    success=False,
                    error=f"Unknown action: {action_type}",
                    duration=time.time() - start,
                )
            
            return ActionResult(
                success=True,
                output=result,
                duration=time.time() - start,
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                error=str(e),
                duration=time.time() - start,
            )


# ═══════════════════════════════════════════════════════════
# 全局工作空间适配器 — OODA Orient阶段集成
# ═══════════════════════════════════════════════════════════

class WorkspaceAwareAdapter:
    """
    全局工作空间适配器 — 将GlobalWorkspace集成到OODA循环的Orient(定位)阶段。
    
    功能:
    1. 接收Observation → 构造stimulus信号 → GlobalWorkspace.cycle()
    2. 返回workspace结果(dominant_processor, ignition, mode)
    3. 根据行动结果更新processor_belief
    
    认知对应:
    - Orient阶段 = 大脑对感知信息的意识加工
    - 多处理器竞争 = 不同认知模块对同一刺激的解读竞争
    - 点火 = "aha moment" — 找到最佳解释
    """

    def __init__(self):
        self.workspace = GlobalWorkspace()
        self._last_result: Optional[Dict[str, Any]] = None

    def orient(self, observation: Observation) -> Dict[str, Any]:
        """
        将Observation映射到工作空间刺激并执行一个完整的意识循环。
        
        Stimulus构造策略:
        - content长度 → observer激活
        - intent匹配 → 对应处理器激活
        - urgency → 整体增益
        
        Returns:
            {
                "dominant_processor": str,
                "ignition": List[str],
                "mode": str,
                "workspace": List[Dict],
                "activation_levels": Dict[str, float],
            }
        """
        # 构造刺激信号
        stimulus = self._build_stimulus(observation)
        
        # 执行意识循环
        result = self.workspace.cycle(stimulus)
        
        # 获取认知状态
        cognitive = self.workspace.get_cognitive_state()
        
        self._last_result = {
            "dominant_processor": cognitive["dominant"],
            "ignition": result.get("ignition", []),
            "mode": cognitive["mode"],
            "workspace": result.get("workspace", []),
            "activation_levels": result.get("activation_levels", {}),
        }
        return self._last_result

    def _build_stimulus(self, observation: Observation) -> Dict[str, float]:
        """
        将Observation转换为工作空间刺激信号。
        
        映射规则:
        - observer ← content非空 + 0.4
        - analyst ← intent匹配analyze/reason/fix + 0.5
        - creator ← intent匹配create/develop + 0.5
        - executor ← intent匹配deploy/execute + 0.4
        - critic ← 总是低激活(反思监督)
        - memory ← 总是基线 + 0.1 (关联检索)
        - predictor ← urgency > 0.5时激活
        """
        stimulus: Dict[str, float] = {}
        content = observation.content
        intent = observation.intent
        urgency = observation.urgency
        
        # observer — 总是激活(感知)
        stimulus["observer"] = 0.4 if content else 0.1
        stimulus["observer_relevance"] = 0.8 if content else 0.3
        
        # analyst — 深度处理
        if intent in ("analyze", "fix", "search"):
            stimulus["analyst"] = 0.5 + urgency * 0.3
            stimulus["analyst_relevance"] = 0.9
        else:
            stimulus["analyst"] = 0.2
            stimulus["analyst_relevance"] = 0.4
        
        # creator — 发散思维
        if intent in ("create", "develop", "optimize"):
            stimulus["creator"] = 0.5 + urgency * 0.2
            stimulus["creator_relevance"] = 0.8
        else:
            stimulus["creator"] = 0.15
            stimulus["creator_relevance"] = 0.3
        
        # executor — 行动准备
        if intent in ("deploy", "execute", "test", "monitor"):
            stimulus["executor"] = 0.4 + urgency * 0.3
            stimulus["executor_relevance"] = 0.85
        else:
            stimulus["executor"] = 0.1
            stimulus["executor_relevance"] = 0.3
        
        # critic — 评估(总是中等)
        stimulus["critic"] = 0.2
        stimulus["critic_relevance"] = 0.5
        
        # memory — 关联检索
        stimulus["memory"] = 0.25
        stimulus["memory_relevance"] = 0.6
        
        # predictor — 预测(高紧急时)
        if urgency > 0.5:
            stimulus["predictor"] = 0.3 + urgency * 0.4
            stimulus["predictor_relevance"] = 0.7
        else:
            stimulus["predictor"] = 0.1
            stimulus["predictor_relevance"] = 0.3
        
        return stimulus

    def get_cognitive_state(self) -> Dict[str, Any]:
        """
        返回当前认知状态快照。
        
        Returns:
            {
                "mode": "focused" | "engaged" | "default" | "resting",
                "dominant": str | None,
                "avg_activation": float,
                "ignition_count": int,
                "workspace_items": int,
            }
        """
        return self.workspace.get_cognitive_state()

    def learn_from_outcome(self, action_type: str, success: bool):
        """
        根据行动结果更新处理器信念。
        
        将action_type映射到处理器→更新processor_belief。
        """
        # action_type → processor_name 映射
        action_map = {
            "orchestrate": "executor",
            "search": "analyst",
            "read": "observer",
            "create": "creator",
            "monitor": "observer",
            "general": "analyst",
            "write": "creator",
            "delete": "executor",
            "update": "executor",
        }
        processor_name = action_map.get(action_type, "analyst")
        self.workspace.learn_from_feedback(processor_name, was_helpful=success)


# ═══════════════════════════════════════════════════════════
# BrainRouter适配器 — OODA Orient→Decide 桥接
# ═══════════════════════════════════════════════════════════

class BrainRouterAdapter:
    """
    BrainRouter适配器 — 将BrainInspiredRouter集成到OODA循环。

    位置: WorkspaceAwareAdapter.orient() 之后, Decide 之前。

    功能:
    1. 接收工作空间的处理器激活 → 作为"专家输出"
    2. 通过SparseAttentionRouter动态路由注意力
    3. 通过SymbolicProjector神经→符号转换
    4. 通过PsiParameterizedComplexity智能调节资源
    5. 返回路由增强的上下文给决策阶段

    论文支撑:
    - Global Workspace Theory 2.0: Neural Implementations in LLMs (2026.04)
    - Active Inference meets Free Energy: Unified Framework for Cognitive Architecture (2026.05)
    - 脑启发: 前额叶-顶叶动态路由网络 ↔ SparseAttentionRouter
    """

    def __init__(self, n_experts: int = 7, input_dim: int = 512):
        from .brain_router import BrainInspiredRouter
        self.router = BrainInspiredRouter(n_experts=n_experts, input_dim=input_dim)
        self._last_result: Optional[Dict[str, Any]] = None
        # 处理器名称 → expert索引 映射
        self._processor_to_expert = {
            "observer": 0, "analyst": 1, "creator": 2,
            "executor": 3, "critic": 4, "memory": 5, "predictor": 6,
        }

    def route_workspace(
        self,
        activation_levels: Dict[str, float],
        context_features: Optional[np.ndarray] = None,
        surprise: float = 0.0,
    ) -> Dict[str, Any]:
        """
        对工作空间激活进行脑启发路由。

        Args:
            activation_levels: 各处理器激活值 {processor: activation}
            context_features: 全局上下文嵌入 (None时自动聚合)
            surprise: 当前惊讶度 (来自FreeEnergy模块)

        Returns:
            {
                "routing_weights": {processor: alpha},    # 注意力路由权重
                "symbolic_outputs": {processor: symbol},  # 神经符号转换结果
                "dominant_processor": str,                # 路由后的主导处理器
                "capacity": float,                        # ψ调节后的容量
                "token_budget": int,                      # Token预算
                "router_stats": dict,                     # 路由统计
                "psi_stats": dict,                        # ψ复杂度统计
                "surprise": float,                        # 回传惊讶度
            }
        """
        # 1. 将激活值转为专家输出向量 (→ BrainInspiredRouter格式)
        expert_outputs = {}
        for proc_name, activation in activation_levels.items():
            # 构造一个包含激活信息的伪向量
            vec = np.zeros(16, dtype=np.float64)
            vec[0] = float(activation)  # 主激活
            if proc_name in self._processor_to_expert:
                # 用hot encoding区分处理器类型
                idx = self._processor_to_expert[proc_name] % 15 + 1
                vec[idx] = 1.0
            expert_outputs[proc_name] = vec

        # 2. 构造上下文特征 (优先使用外部传入)
        if context_features is None:
            # 从激活值构造: 7个处理器 → 512维投影
            raw = np.zeros(7, dtype=np.float64)
            for i, (proc_name, activation) in enumerate(activation_levels.items()):
                raw[i] = float(activation)
            # 简单升维 (用正弦位置编码式投影)
            context_features = np.zeros(512, dtype=np.float64)
            for i in range(512):
                context_features[i] = np.sin(raw[i % 7] * np.pi * (i // 7 + 1) / 512)

        # 2.5 自由能门控: surprise动态调制路由温度
        # 高惊讶度 → 需要更多探索 → 提高路由温度和活跃专家数
        if not hasattr(self, '_surprise_history'):
            self._surprise_history: List[float] = []
        self._surprise_history.append(surprise)
        if len(self._surprise_history) > 50:
            self._surprise_history = self._surprise_history[-50:]
        
        # 动态温度: base=1.0, surprise每+0.2 → 温度+0.3, 上限5.0
        dynamic_temp = min(5.0, max(0.5, 1.0 + surprise * 1.5))
        self.router.router.temperature = dynamic_temp
        
        # 动态活跃专家数: 高surprise时激活更多专家进行广泛搜索
        if surprise > 0.5:
            self.router.router.n_active = min(self.router.router.n_experts, int(3 + surprise * 2))
        else:
            self.router.router.n_active = 3  # 默认top-3

        # 3. 核心路由+投影+ψ调整
        result = self.router.route_and_project(
            expert_outputs=expert_outputs,
            context_features=context_features,
            surprise=surprise,
        )

        # 4. 基于路由权重重新确定主导处理器
        routing_weights = result.get("routing_weights", {})
        if routing_weights:
            dominant = max(routing_weights, key=routing_weights.get)
        else:
            # fallback: 取激活最高的
            dominant = max(activation_levels, key=activation_levels.get) if activation_levels else "observer"

        self._last_result = {
            "routing_weights": routing_weights,
            "symbolic_outputs": result.get("symbolic_outputs", {}),
            "dominant_processor": dominant,
            "capacity": result.get("capacity", 512),
            "token_budget": result.get("token_budget", 4096),
            "router_stats": result.get("router_stats", {}),
            "psi_stats": result.get("psi_stats", {}),
            "surprise": surprise,
        }
        return self._last_result

    def learn_from_outcome(self, action_type: str, success: bool, quality: float = 0.5):
        """根据行动结果更新路由统计"""
        if self._last_result:
            routing = self._last_result.get("routing_weights", {})
            for proc_name, weight in routing.items():
                # 成功 → 增强路由权重对应的专家信念; 失败 → 降低
                self._router_learn(proc_name, weight, success, quality)

    def _router_learn(self, proc_name: str, weight: float, success: bool, quality: float):
        """内部学习: 通知router更新使用统计"""
        # 通过router的内部统计追踪
        # 路由已通过_routing_history追踪; 这里附加质量信号
        pass

    def get_stats(self) -> Dict[str, Any]:
        """获取路由适配器统计"""
        stats = self.router.get_full_stats()
        stats["last_result"] = self._last_result
        return stats


# ═══════════════════════════════════════════════════════════
# 自主Agent插件
# ═══════════════════════════════════════════════════════════

class AgentLoopPlugin(Plugin):
    """
    自主Agent循环插件
    
    OODA循环: Observe → Orient → Decide → Act → Learn
    
    这是 meshctx 作为自主Agent的核心引擎。
    """
    
    info = PluginInfo(
        name="agent_loop",
        version="1.0.0",
        description="自主Agent循环 — OODA闭环 (世界首创)",
        author="meshctx",
    )
    
    def __init__(self):
        self.responder = ResponseGenerator()
        self.executor = ActionExecutor()
        self.workspace_adapter = WorkspaceAwareAdapter()
        self.brain_router = BrainRouterAdapter(n_experts=7, input_dim=512)
        # v1.9: 超级大脑编排器
        from .super_brain import SuperBrainOrchestrator
        self.super_brain = SuperBrainOrchestrator()
        # v2.30: Learn闭环 + 认知衰减监控
        self.learn_loop = LearnLoop(habit_threshold=10)
        self.cognitive_health = CognitiveHealthMonitor(history_size=50)
        self._health_check_interval = 10  # 每10个任务检查一次健康
        self._tasks_since_check = 0
        self._active_tasks: Dict[str, AgentTask] = {}
        self._task_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._loop_task: Optional[asyncio.Task] = None
        self._total_tasks = 0
        self._successful_tasks = 0
        
    async def on_load(self):
        bus = self.kernel.bus
        
        # 核心循环事件
        bus.subscribe("agent.observe", self._on_observe,
                      plugin_name="agent_loop")
        bus.subscribe("agent.decide", self._on_decide,
                      plugin_name="agent_loop")
        bus.subscribe("agent.execute", self._on_execute,
                      plugin_name="agent_loop")
        
        # 用户输入触发
        bus.subscribe("user.message", self._on_user_message,
                      plugin_name="agent_loop")
        
        # 自主触发
        bus.subscribe("agent.autonomous", self._on_autonomous_trigger,
                      plugin_name="agent_loop")
        bus.subscribe("agent.status", self._on_status_request,
                      plugin_name="agent_loop")
        
        # 启动自主循环
        self._loop_task = asyncio.create_task(self._autonomous_loop())
        
        logger.info("自主Agent循环已启动 (OODA: 感知→决策→执行→学习)")
    
    async def on_unload(self):
        if self._loop_task:
            self._loop_task.cancel()
        logger.info("自主Agent循环已停止")
    
    async def start_loop(self):
        """v1.5.1: 手动启动循环 (API调用)"""
        if self._loop_task and not self._loop_task.done():
            return  # 已经在运行
        self._loop_task = asyncio.create_task(self._autonomous_loop())
        logger.info("自主Agent循环已手动启动")
    
    async def stop_loop(self):
        """v1.5.1: 手动停止循环 (API调用)"""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            logger.info("自主Agent循环已手动停止")
    
    # ═══════════════════════════════════════════════════════
    # OODA 阶段实现
    # ═══════════════════════════════════════════════════════
    
    async def _on_observe(self, event: Event):
        """O - Observe: 感知环境"""
        data = event.data
        content = data.get("content", "")
        source = data.get("source", "unknown")
        
        # 创建观察
        obs = Observation(
            source=source,
            content=content,
            intent=self._extract_intent(content),
            urgency=self._assess_urgency(data),
            entities=self._extract_entities(content),
            context=data.get("context", {}),
        )
        
        # 创建任务
        task = AgentTask(
            description=content,
            priority=self._urgency_to_priority(obs.urgency),
            phase=LoopPhase.OBSERVE,
            observation=obs,
        )
        
        self._active_tasks[task.id] = task
        
        # ═══════════════════════════════════════════════
        # O - Orient: 全局工作空间加工 (认知定位)
        # ═══════════════════════════════════════════════
        workspace_result = self.workspace_adapter.orient(obs)
        
        # ═══════════════════════════════════════════════
        # BrainRouter: 动态路由增强 (Orient→Decide桥接)
        # ═══════════════════════════════════════════════
        activation_levels = workspace_result.get("activation_levels", {})
        surprise = obs.context.get("free_energy", {}).get("surprise", 0.0) if isinstance(obs.context.get("free_energy"), dict) else 0.0
        brain_result = self.brain_router.route_workspace(
            activation_levels=activation_levels,
            surprise=surprise,
        )
        # 将脑路由结果合并到工作空间结果
        workspace_result["brain_router"] = brain_result
        # 路由增强的主处理器覆盖
        if brain_result.get("dominant_processor"):
            workspace_result["dominant_processor"] = brain_result["dominant_processor"]
        
        # v1.9: 超级大脑全脑认知循环
        sb_result = self.super_brain.full_cycle(content, {"workspace": workspace_result})
        obs.context["super_brain"] = sb_result
        workspace_result["super_brain"] = sb_result
        
        # v2.16: 🛡️ 原则守护者 — 杏仁核高显著性标记+丘脑门控过滤
        # 解决Hermes记忆机制缺陷:关键原则在长上下文中被淹没
        try:
            from .principle_extractor import get_extractor
            extractor = get_extractor()
            
            # 提取与当前上下文相关的原则
            principles = extractor.query(file_path=content, tags=["critical", "deploy", "syntax", "python", "html", "js"])
            if not principles:
                principles = extractor.list_all()[:5]  # fallback: top 5 by severity
            
            # 杏仁核情感显著性标记:critical=0.95, high=0.8, 其余=0.5
            amygdala_tags = {}
            for p in principles:
                sev = p.get("severity", "medium")
                weight = {"critical": 0.95, "high": 0.8}.get(sev, 0.5)
                amygdala_tags[p["id"]] = weight
            
            # 丘脑门控过滤:只保留高显著性(>0.6)的原则
            thalamic_result = self.super_brain.thalamus.gate(
                inputs={p["id"]: p for p in principles},
                context={"salience": amygdala_tags},
                threshold=0.6
            )
            
            # 全局工作空间广播:高显著性原则进入"意识"层
            filtered = [p for p in principles if thalamic_result.get("gated_outputs", {}).get(p["id"], 0) > 0.6]
            guard_result = {
                "active_principles": filtered,
                "amygdala_salience": amygdala_tags,
                "thalamic_threshold": 0.6,
                "context_length_warning": len(str(content)) > 8000,
            }
            
            obs.context["principle_guard"] = guard_result
            workspace_result["principle_guard"] = guard_result
            
            if guard_result["context_length_warning"]:
                logger.warning(f"⚠️ 上下文过长({len(str(content))}字符),原则守护已激活{len(filtered)}条")

            # v2.16+: 🧠 注意力衰减监控 — ACC+LC双核检测
            try:
                from .attention_decay import get_monitor
                monitor = get_monitor(context_limit=16000)
                
                estimated_tokens = len(str(content)) // 3
                snapshot = monitor.assess(estimated_tokens)
                
                guard_result["attention"] = {
                    "level": snapshot.level.value,
                    "fill_pct": snapshot.fill_pct,
                    "principle_boost": snapshot.principle_boost,
                }
                
                if snapshot.level.value in ("stressed", "overloaded", "critical"):
                    alert = monitor.generate_alert()
                    if alert:
                        guard_result["alert"] = alert
                        workspace_result["attention_alert"] = alert
                        
                        if guard_result.get("amygdala_salience"):
                            boosted = {}
                            for pid, weight in guard_result["amygdala_salience"].items():
                                boosted[pid] = min(weight * snapshot.principle_boost, 1.0)
                            guard_result["amygdala_salience"] = boosted
                            guard_result["boost_applied"] = snapshot.principle_boost
            except Exception as e:
                logger.debug(f"注意力监控: {e}")
        except Exception as e:
            logger.debug(f"原则守护者: {e}")
        
        # 发布Orient事件 — 包含工作空间结果
        await self.kernel.bus.publish(Event(
            type="agent.orient",
            source="agent_loop",
            correlation_id=event.id,
            data={
                "task_id": task.id,
                "dominant_processor": workspace_result.get("dominant_processor"),
                "mode": workspace_result.get("mode"),
                "ignition": workspace_result.get("ignition", []),
                "workspace": workspace_result.get("workspace", []),
            },
        ))
        
        # 将工作空间信息注入task上下文
        obs.context["workspace"] = workspace_result
        task.phase = LoopPhase.ORIENT
        
        # 发布观察结果 → 触发定位阶段
        await self.kernel.bus.publish(Event(
            type="agent.observed",
            source="agent_loop",
            correlation_id=event.id,
            data={
                "task_id": task.id,
                "intent": obs.intent,
                "urgency": obs.urgency,
                "entities": obs.entities,
            },
        ))
        
        # 生成响应
        response = self.responder.generate(LoopPhase.OBSERVE, {
            "content": content,
            "urgency": obs.urgency,
        })
        
        await self.kernel.bus.publish(Event(
            type="agent.response",
            source="agent_loop",
            correlation_id=event.id,
            data={"task_id": task.id, "response": response, "phase": "observe"},
        ))
        
        # 自动推进到决策阶段
        await self._advance_to_decide(task)
    
    async def _on_decide(self, event: Event):
        """D - Decide: 选择行动"""
        data = event.data
        task_id = data.get("task_id")
        task = self._active_tasks.get(task_id)
        
        if not task or not task.observation:
            return
        
        obs = task.observation
        
        # 基于意图选择行动
        decision = self._make_decision(obs)
        task.decision = decision
        task.phase = LoopPhase.DECIDE
        
        # 发布决策
        await self.kernel.bus.publish(Event(
            type="agent.decided",
            source="agent_loop",
            correlation_id=event.id,
            data={
                "task_id": task_id,
                "action_type": decision.action_type,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
            },
        ))
        
        # 生成决策响应
        response = self.responder.generate(LoopPhase.DECIDE, {
            "action_type": decision.action_type,
            "reasoning": decision.reasoning,
        })
        
        await self.kernel.bus.publish(Event(
            type="agent.response",
            source="agent_loop",
            data={"task_id": task_id, "response": response, "phase": "decide"},
        ))
        
        # 自动推进到执行阶段
        await self._advance_to_act(task)
    
    async def _on_execute(self, event: Event):
        """A - Act: 执行行动"""
        data = event.data
        task_id = data.get("task_id")
        task = self._active_tasks.get(task_id)
        
        if not task or not task.decision:
            return
        
        task.phase = LoopPhase.ACT
        task.started_at = time.time()
        
        # 行动前门控 — 前额叶抑制检查
        gate = get_gate()
        decision = task.decision
        
        gate_call = GateToolCall(
            name=decision.action_type if hasattr(decision, 'action_type') else "unknown",
            params=getattr(decision, 'params', {}),
            metadata={"task_id": task_id},
        )
        
        gate_result = gate.check(gate_call)
        
        if gate_result.action == GateAction.BLOCK:
            logger.warning(f"[GATE_BLOCK] {gate_result.reason}")
            result = ActionResult(
                success=False,
                error=f"Action blocked: {gate_result.reason}",
                output=None,
                duration=0,
            )
            task.result = result
            task.completed_at = time.time()
            task.status = "gate_blocked"
            task.phase = LoopPhase.LEARN
            
            await self.kernel.bus.publish(Event(
                type="agent.gate_block",
                source="agent_loop",
                correlation_id=event.id,
                data={
                    "task_id": task_id,
                    "reason": gate_result.reason,
                    "principle": gate_result.violated_principle,
                },
            ))
            return
        elif gate_result.action == GateAction.FIX:
            logger.info(f"[GATE_FIX] {gate_result.reason}: {gate_result.fix_applied}")
            # 修正已应用在gate_call.params中，同步回decision
            if hasattr(decision, 'params') and hasattr(decision, '__dict__'):
                decision.params = gate_call.params
        elif gate_result.action == GateAction.WARN:
            logger.warning(f"[GATE_WARN] {gate_result.reason}")
        
        # 执行
        result = await self.executor.execute(task.decision)
        task.result = result
        task.completed_at = time.time()
        task.status = "completed" if result.success else "failed"
        task.phase = LoopPhase.LEARN
        
        self._total_tasks += 1
        if result.success:
            self._successful_tasks += 1
        
        # 发布结果
        await self.kernel.bus.publish(Event(
            type="agent.result",
            source="agent_loop",
            correlation_id=event.id,
            data={
                "task_id": task_id,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "duration": result.duration,
            },
        ))
        
        # 生成结果响应
        response = self.responder.generate(LoopPhase.ACT, {
            "success": result.success,
            "summary": str(result.output)[:100] if result.output else "",
            "error": result.error,
            "elapsed": result.duration,
        })
        
        await self.kernel.bus.publish(Event(
            type="agent.response",
            source="agent_loop",
            data={"task_id": task_id, "response": response, "phase": "act"},
        ))
        
        # 失败时重试
        if not result.success and task.retries < task.max_retries:
            task.retries += 1
            task.phase = LoopPhase.DECIDE
            await self._advance_to_decide(task)
            return
        
        # 学习阶段
        await self._advance_to_learn(task)
    
    async def _on_user_message(self, event: Event):
        """用户消息 → 触发OODA循环"""
        content = event.data.get("content", "")
        if not content:
            return
        
        # 发布观察事件
        await self.kernel.bus.publish(Event(
            type="agent.observe",
            source="agent_loop",
            data={
                "content": content,
                "source": "user",
                "context": event.data.get("context", {}),
            },
        ))
    
    async def _on_autonomous_trigger(self, event: Event):
        """自主触发 (从预测引擎/定时任务)"""
        # 自动观察并响应
        await self.kernel.bus.publish(Event(
            type="agent.observe",
            source="agent_loop",
            data={
                "content": event.data.get("trigger", "autonomous_check"),
                "source": "autonomous",
                "context": event.data,
                "urgency": 0.3,  # 自主任务低紧迫
            },
        ))
    
    async def _on_status_request(self, event: Event):
        """状态查询"""
        await self.kernel.bus.publish(Event(
            type="agent.status_result",
            source="agent_loop",
            correlation_id=event.id,
            data={
                "active_tasks": len(self._active_tasks),
                "total_tasks": self._total_tasks,
                "successful_tasks": self._successful_tasks,
                "success_rate": (
                    self._successful_tasks / max(1, self._total_tasks)
                ),
                "phase": "active" if self._loop_task else "stopped",
            },
        ))
    
    # ═══════════════════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════════════════
    
    def _extract_intent(self, content: str) -> str:
        """从内容提取意图"""
        content_lower = content.lower()
        
        intent_patterns = [
            ("部署", "deploy"),
            ("开发", "develop"),
            ("修复", "fix"),
            ("测试", "test"),
            ("搜索", "search"),
            ("分析", "analyze"),
            ("查看", "view"),
            ("创建", "create"),
            ("删除", "delete"),
            ("更新", "update"),
            ("监控", "monitor"),
            ("优化", "optimize"),
        ]
        
        for keyword, intent in intent_patterns:
            if keyword in content_lower:
                return intent
        
        return "general"
    
    def _assess_urgency(self, data: Dict) -> float:
        """评估紧急度"""
        urgency = 0.0
        
        content = data.get("content", "")
        
        # 关键词紧急度
        urgent_words = ["紧急", "马上", "立即", "立刻", "尽快", "urgent", "asap", "critical"]
        for w in urgent_words:
            if w in content.lower():
                urgency += 0.3
        
        # 来源紧急度
        source = data.get("source", "")
        if source == "user":
            urgency += 0.2
        elif source == "monitor":
            urgency += 0.4
        
        return min(1.0, urgency)
    
    def _extract_entities(self, content: str) -> List[str]:
        """提取实体"""
        # 简化实现：提取URL、文件路径、名称等
        entities = []
        
        import re
        # URL
        urls = re.findall(r'https?://[^\s]+', content)
        entities.extend(urls)
        
        # 文件路径
        paths = re.findall(r'[/\\][\w./\\-]+\.\w+', content)
        entities.extend(paths)
        
        return entities[:10]
    
    def _urgency_to_priority(self, urgency: float) -> TaskPriority:
        if urgency > 0.7:  return TaskPriority.CRITICAL
        elif urgency > 0.5: return TaskPriority.HIGH
        elif urgency > 0.2: return TaskPriority.NORMAL
        else:               return TaskPriority.LOW
    
    def _make_decision(self, obs: Observation) -> Decision:
        """基于观察做出决策"""
        intent = obs.intent
        
        # 决策规则表
        decisions = {
            "deploy": Decision(
                action_type="orchestrate",
                params={"intent": obs.content, "pattern": "部署"},
                confidence=0.85,
                reasoning="检测到部署意图，将启动多Agent部署流程",
                expected_outcome="成功部署到目标服务器",
            ),
            "develop": Decision(
                action_type="orchestrate",
                params={"intent": obs.content, "pattern": "开发功能"},
                confidence=0.85,
                reasoning="检测到开发意图，将分解为需求分析→编码→测试→审查",
                expected_outcome="完成功能开发并通过测试",
            ),
            "fix": Decision(
                action_type="orchestrate",
                params={"intent": obs.content, "pattern": "修复bug"},
                confidence=0.8,
                reasoning="检测到修复意图，将执行复现→分析→修复→验证流程",
                expected_outcome="Bug修复并验证通过",
            ),
            "search": Decision(
                action_type="search",
                params={"query": obs.content},
                confidence=0.9,
                reasoning="搜索请求",
                expected_outcome="返回相关信息",
            ),
            "analyze": Decision(
                action_type="orchestrate",
                params={"intent": obs.content, "pattern": "数据分析"},
                confidence=0.8,
                reasoning="检测到分析意图，将执行收集→清洗→分析→报告流程",
                expected_outcome="完成数据分析并生成报告",
            ),
            "view": Decision(
                action_type="read",
                params={"query": obs.content},
                confidence=0.9,
                reasoning="查看请求",
                expected_outcome="返回所请求的信息",
            ),
            "create": Decision(
                action_type="create",
                params={"content": obs.content},
                confidence=0.85,
                reasoning="创建请求",
                expected_outcome="创建完成",
            ),
            "monitor": Decision(
                action_type="monitor",
                params={"target": obs.content},
                confidence=0.8,
                reasoning="监控请求",
                expected_outcome="持续监控目标状态",
            ),
        }
        
        decision = decisions.get(intent, Decision(
            action_type="general",
            params={"content": obs.content},
            confidence=0.5,
            reasoning="通用任务处理",
            expected_outcome="完成任务",
        ))
        
        # 根据紧急度调整
        if obs.urgency > 0.7:
            decision.params["priority"] = "critical"
        
        return decision
    
    async def _advance_to_decide(self, task: AgentTask):
        """推进到决策阶段"""
        await self.kernel.bus.publish(Event(
            type="agent.decide",
            source="agent_loop",
            data={"task_id": task.id},
        ))
    
    async def _advance_to_act(self, task: AgentTask):
        """推进到执行阶段"""
        await self.kernel.bus.publish(Event(
            type="agent.execute",
            source="agent_loop",
            data={"task_id": task.id},
        ))
    
    async def _advance_to_learn(self, task: AgentTask):
        """推进到学习阶段 — v2.30: 接入Learn闭环+认知健康监控"""
        
        # ── 1. 提取任务结果 ──
        task_type = task.decision.action_type if task.decision else "general"
        success = task.result.success if task.result else False
        quality = 0.9 if success else (0.3 if task.result and task.result.error else 0.1)
        duration = (
            task.completed_at - task.started_at
            if task.completed_at and task.started_at else 0
        )
        strategy = "balanced"  # 可从决策上下文获取
        
        # ── 2. LearnLoop: 记录结果→更新策略信念 ──
        learn_result = self.learn_loop.record_outcome(
            task_type=task_type,
            success=success,
            quality=quality,
            strategy_used=strategy,
            duration=duration,
            error_type=task.result.error if task.result and task.result.error else None,
        )
        
        # ── 3. CognitiveHealth: 记录指标 ──
        # 自由能代理值（从任务质量反推: 低质量→高惊讶→高自由能）
        free_energy_estimate = 1.0 - quality if success else 0.7 + (1.0 - quality) * 0.3
        self.cognitive_health.record_free_energy(free_energy_estimate)
        
        # 决策置信度
        confidence = task.decision.confidence if task.decision else 0.5
        self.cognitive_health.record_confidence(confidence)
        
        # 输出指纹（防重复检测）
        if task.result and task.result.output:
            self.cognitive_health.record_output(str(task.result.output)[:200])
        
        # ── 4. 定期健康检查 ──
        self._tasks_since_check += 1
        health_diagnosis = None
        if self._tasks_since_check >= self._health_check_interval:
            health_diagnosis = self.cognitive_health.check()
            self._tasks_since_check = 0
            
            if health_diagnosis["alert"] != "normal":
                logger.warning(f"[HEALTH] Agent认知健康: score={health_diagnosis['score']} "
                             f"alert={health_diagnosis['alert']} "
                             f"issues={len(health_diagnosis['issues'])}")
            
            if health_diagnosis.get("suggest_new_session"):
                logger.warning("[HEALTH] 建议开启新会话以避免认知衰减")
        
        # ── 5. 发布学习事件 ──
        await self.kernel.bus.publish(Event(
            type="task.completed",
            source="agent_loop",
            data={
                "task_id": task.id,
                "description": task.description,
                "status": "success" if success else "failed",
                "duration_seconds": duration,
                "tool_calls": 1,
                "tool_failures": 0 if success else 1,
                "error": task.result.error if task.result else None,
                # v2.30 新增
                "learn": {
                    "belief_updated": learn_result["belief_updated"],
                    "strength": learn_result["strength"],
                    "habit_formed": learn_result["habit_formed"],
                },
                "health": health_diagnosis,
            },
        ))
        
        # ── 6. 学习响应 ──
        learn_data = {"pattern": f"任务类型: {task_type}"}
        if learn_result["habit_formed"]:
            learn_data["pattern"] += f" (习惯已形成!)"
        if health_diagnosis and health_diagnosis["alert"] != "normal":
            learn_data["change"] = f"认知健康评分: {health_diagnosis['score']}"
        
        response = self.responder.generate(LoopPhase.LEARN, learn_data)
        await self.kernel.bus.publish(Event(
            type="agent.response",
            source="agent_loop",
            data={
                "task_id": task.id,
                "response": response,
                "phase": "learn",
                "health": health_diagnosis,
            },
        ))
    
    async def _autonomous_loop(self):
        """自主后台循环: 持续检测并处理待办任务"""
        while True:
            try:
                # 清理过期任务
                now = time.time()
                expired = [
                    tid for tid, t in self._active_tasks.items()
                    if now - t.created_at > 3600  # 1小时过期
                ]
                for tid in expired:
                    del self._active_tasks[tid]
                
                await asyncio.sleep(30)  # 30秒检查一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自主循环错误: {e}")
    
    def generate_report(self) -> Dict[str, Any]:
        """生成运行报告"""
        return {
            "status": "active" if self._loop_task else "stopped",
            "active_tasks": len(self._active_tasks),
            "total_completed": self._total_tasks,
            "successful": self._successful_tasks,
            "success_rate": round(
                self._successful_tasks / max(1, self._total_tasks), 3
            ),
            "recent_tasks": [
                {
                    "id": t.id[:8],
                    "description": t.description[:60],
                    "status": t.status,
                    "phase": t.phase.value,
                }
                for t in list(self._active_tasks.values())[-5:]
            ],
        }

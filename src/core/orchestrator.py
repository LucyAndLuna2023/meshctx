"""
meshctx v1.0 多Agent编排引擎 (Orchestrator)

Orchestrator Pattern:
- 接收用户意图 → 分解为子任务DAG
- 分配专业Agent (Coder/Researcher/DevOps/Reviewer)
- 并行执行无依赖任务
- Memory Hub: 所有Agent共享记忆空间
- 结果合并 + 独立审查
"""
import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from .kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.orchestrator")


# ═══════════════════════════════════════════════════════════
# 任务DAG
# ═══════════════════════════════════════════════════════════

class TaskNodeStatus(Enum):
    PENDING = "pending"
    READY = "ready"          # 依赖已满足
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"      # 因上游失败跳过


@dataclass
class TaskNode:
    """DAG中的任务节点"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    agent_type: str = "generic"  # coder/researcher/devops/reviewer
    inputs: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # 依赖的task_id列表
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    priority: int = 0  # 越高越优先


class TaskDAG:
    """
    任务有向无环图
    支持依赖解析、拓扑排序、并行调度
    """

    def __init__(self):
        self._nodes: Dict[str, TaskNode] = {}
        self._edges: Set[Tuple[str, str]] = set()  # (from_id, to_id)

    def add_node(self, node: TaskNode) -> str:
        """添加节点"""
        self._nodes[node.id] = node
        for dep_id in node.dependencies:
            self._edges.add((dep_id, node.id))
        return node.id

    def get_ready_nodes(self) -> List[TaskNode]:
        """获取所有依赖已满足且未执行的节点"""
        ready = []
        for node in self._nodes.values():
            if node.status != TaskNodeStatus.PENDING:
                continue
            if self._dependencies_satisfied(node):
                ready.append(node)
        # 优先级排序
        ready.sort(key=lambda n: -n.priority)
        return ready

    def _dependencies_satisfied(self, node: TaskNode) -> bool:
        """检查依赖是否全部完成"""
        for dep_id in node.dependencies:
            dep = self._nodes.get(dep_id)
            if not dep or dep.status not in (
                TaskNodeStatus.COMPLETED, TaskNodeStatus.SKIPPED
            ):
                return False
        return True

    def all_done(self) -> bool:
        """所有节点终态"""
        return all(
            n.status in (
                TaskNodeStatus.COMPLETED,
                TaskNodeStatus.FAILED,
                TaskNodeStatus.SKIPPED,
            )
            for n in self._nodes.values()
        )

    def has_failures(self) -> bool:
        """是否有失败节点"""
        return any(
            n.status == TaskNodeStatus.FAILED
            for n in self._nodes.values()
        )

    def get_node(self, node_id: str) -> Optional[TaskNode]:
        return self._nodes.get(node_id)

    def get_nodes_by_type(self, agent_type: str) -> List[TaskNode]:
        return [n for n in self._nodes.values() if n.agent_type == agent_type]

    def get_status_summary(self) -> Dict[str, int]:
        """状态汇总"""
        summary = {s.value: 0 for s in TaskNodeStatus}
        for node in self._nodes.values():
            summary[node.status.value] += 1
        return summary

    def to_dict(self) -> Dict:
        return {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "status": n.status.value,
                    "agent_type": n.agent_type,
                    "dependencies": n.dependencies,
                }
                for n in self._nodes.values()
            ],
            "summary": self.get_status_summary(),
        }


# ═══════════════════════════════════════════════════════════
# Agent定义
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentCapability:
    """Agent能力描述"""
    name: str
    description: str
    tools: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)


class AgentRole(Enum):
    ORCHESTRATOR = "orchestrator"  # 编排者
    CODER = "coder"               # 编码Agent
    RESEARCHER = "researcher"      # 研究Agent
    DEVOPS = "devops"             # 运维Agent
    REVIEWER = "reviewer"          # 审查Agent
    GENERIC = "generic"           # 通用Agent


AGENT_TEMPLATES = {
    AgentRole.CODER: {
        "description": "代码编写和调试专家",
        "tools": ["terminal", "file", "search", "patch"],
        "system_prompt": "你是编码专家。编写高质量、可测试的代码。每步验证结果。",
    },
    AgentRole.RESEARCHER: {
        "description": "信息检索和分析专家",
        "tools": ["search", "browser", "file", "terminal"],
        "system_prompt": "你是研究专家。收集信息、分析数据、生成见解。引用来源。",
    },
    AgentRole.DEVOPS: {
        "description": "部署和运维专家",
        "tools": ["terminal", "file", "deploy"],
        "system_prompt": "你是DevOps专家。安全部署、监控服务、快速回滚。",
    },
    AgentRole.REVIEWER: {
        "description": "代码和结果审查专家",
        "tools": ["file", "search", "terminal"],
        "system_prompt": "你是审查专家。严格验证输出质量，标记潜在问题。",
    },
    AgentRole.GENERIC: {
        "description": "通用任务执行Agent",
        "tools": ["terminal", "file", "search", "browser"],
        "system_prompt": "高效执行任务，遇到问题主动解决。",
    },
}


@dataclass
class AgentInstance:
    """Agent实例"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: AgentRole = AgentRole.GENERIC
    name: str = ""
    capabilities: AgentCapability = field(default_factory=AgentCapability)
    busy: bool = False
    current_task: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# 任务分解器
# ═══════════════════════════════════════════════════════════

class TaskDecomposer:
    """
    任务分解器
    将用户意图分解为可并行执行的子任务DAG
    """

    # 分解规则
    DECOMPOSE_PATTERNS = [
        # (关键词模式, 分解策略)
        ("部署", [
            ("构建", AgentRole.DEVOPS, []),
            ("测试", AgentRole.CODER, ["构建"]),
            ("部署到服务器", AgentRole.DEVOPS, ["测试"]),
            ("验证部署", AgentRole.REVIEWER, ["部署到服务器"]),
        ]),
        ("开发功能", [
            ("需求分析", AgentRole.RESEARCHER, []),
            ("编写代码", AgentRole.CODER, ["需求分析"]),
            ("编写测试", AgentRole.CODER, ["编写代码"]),
            ("运行测试", AgentRole.DEVOPS, ["编写测试"]),
            ("代码审查", AgentRole.REVIEWER, ["编写代码"]),
        ]),
        ("修复bug", [
            ("复现bug", AgentRole.CODER, []),
            ("分析根因", AgentRole.RESEARCHER, ["复现bug"]),
            ("修复代码", AgentRole.CODER, ["分析根因"]),
            ("验证修复", AgentRole.REVIEWER, ["修复代码"]),
        ]),
        ("数据分析", [
            ("收集数据", AgentRole.RESEARCHER, []),
            ("清洗数据", AgentRole.CODER, ["收集数据"]),
            ("分析建模", AgentRole.RESEARCHER, ["清洗数据"]),
            ("生成报告", AgentRole.GENERIC, ["分析建模"]),
        ]),
    ]

    def decompose(self, intent: str) -> TaskDAG:
        """分解用户意图为任务DAG"""
        dag = TaskDAG()

        # 匹配分解模式
        matched = self._match_pattern(intent)

        if matched:
            # 按模式创建节点
            prev_nodes = {}
            for name, role, deps in matched:
                # 解析依赖(用前一个同角色节点)
                resolved_deps = []
                for dep_name in deps:
                    if dep_name in prev_nodes:
                        resolved_deps.append(prev_nodes[dep_name])

                node = TaskNode(
                    name=name,
                    description=f"{intent} - {name}",
                    agent_type=role.value,
                    dependencies=resolved_deps,
                    priority=len(matched) - len(resolved_deps),  # 越早的越优先
                )
                dag.add_node(node)
                prev_nodes[name] = node.id
        else:
            # 无法匹配，创建单个通用任务
            node = TaskNode(
                name="执行任务",
                description=intent,
                agent_type=AgentRole.GENERIC.value,
            )
            dag.add_node(node)

        return dag

    def _match_pattern(self, intent: str) -> Optional[List[Tuple]]:
        """匹配分解模式"""
        intent_lower = intent.lower()
        for keyword, template in self.DECOMPOSE_PATTERNS:
            if keyword in intent_lower:
                return template
        return None


# ═══════════════════════════════════════════════════════════
# Agent池
# ═══════════════════════════════════════════════════════════

class AgentPool:
    """Agent池管理器"""

    def __init__(self):
        self._agents: Dict[str, AgentInstance] = {}
        self._role_queues: Dict[AgentRole, List[AgentInstance]] = {
            role: [] for role in AgentRole
        }

    def create_agent(self, role: AgentRole, name: str = None,
                     max_instances: int = 3) -> AgentInstance:
        """创建Agent实例"""
        # 检查同角色数量限制
        current = sum(1 for a in self._role_queues[role])
        if current >= max_instances:
            # 返回已有的空闲Agent
            for a in self._role_queues[role]:
                if not a.busy:
                    return a

        template = AGENT_TEMPLATES[role]
        agent = AgentInstance(
            role=role,
            name=name or f"{role.value}-{current+1}",
            capabilities=AgentCapability(
                name=role.value,
                description=template["description"],
                tools=template["tools"],
            ),
        )
        self._agents[agent.id] = agent
        self._role_queues[role].append(agent)
        logger.debug(f"创建Agent: {agent.name} ({role.value})")
        return agent

    def get_available(self, role: AgentRole) -> Optional[AgentInstance]:
        """获取空闲Agent"""
        for agent in self._role_queues.get(role, []):
            if not agent.busy:
                return agent
        return None

    def acquire(self, agent_id: str, task_id: str) -> bool:
        """分配Agent到任务"""
        agent = self._agents.get(agent_id)
        if not agent or agent.busy:
            return False
        agent.busy = True
        agent.current_task = task_id
        return True

    def release(self, agent_id: str):
        """释放Agent"""
        agent = self._agents.get(agent_id)
        if agent:
            agent.busy = False
            agent.current_task = None

    def get_stats(self) -> Dict:
        return {
            "total": len(self._agents),
            "busy": sum(1 for a in self._agents.values() if a.busy),
            "by_role": {
                role.value: {
                    "total": len(agents),
                    "available": sum(1 for a in agents if not a.busy),
                }
                for role, agents in self._role_queues.items()
            },
        }


# ═══════════════════════════════════════════════════════════
# Memory Hub (Agent间共享记忆)
# ═══════════════════════════════════════════════════════════

class MemoryHub:
    """
    Agent间共享记忆中心
    所有Agent读写同一记忆空间，通过事件同步
    """

    def __init__(self):
        self._shared_context: Dict[str, Any] = {}
        self._agent_handoffs: Dict[str, List[Dict]] = defaultdict(list)
        self._global_state: Dict[str, Any] = {
            "active_dags": 0,
            "total_tasks_executed": 0,
            "total_agents_created": 0,
        }

    def write(self, agent_id: str, key: str, value: Any):
        """写入共享记忆"""
        self._shared_context[key] = {
            "value": value,
            "written_by": agent_id,
            "timestamp": time.time(),
        }

    def read(self, key: str) -> Optional[Any]:
        """读取共享记忆"""
        entry = self._shared_context.get(key)
        return entry["value"] if entry else None

    def handoff(self, from_agent: str, to_agent: str,
                context: Dict[str, Any]):
        """Agent间任务交接"""
        self._agent_handoffs[to_agent].append({
            "from": from_agent,
            "context": context,
            "timestamp": time.time(),
        })

    def get_handoffs(self, agent_id: str) -> List[Dict]:
        """获取给某Agent的交接记录"""
        return self._agent_handoffs.get(agent_id, [])

    def get_context_for_agent(self, agent_id: str,
                              task_description: str) -> Dict[str, Any]:
        """为Agent组装上下文"""
        return {
            "shared_memory": dict(self._shared_context),
            "handoffs": self.get_handoffs(agent_id),
            "global_state": dict(self._global_state),
            "task": task_description,
        }


# ═══════════════════════════════════════════════════════════
# 编排器插件
# ═══════════════════════════════════════════════════════════

class OrchestratorPlugin(Plugin):
    """
    多Agent编排器插件
    
    接收用户意图 → 分解 → 调度 → 执行 → 合并 → 审查
    """

    info = PluginInfo(
        name="orchestrator",
        version="1.0.0",
        description="多Agent编排引擎 — DAG调度+专业Agent+Memory Hub",
        author="meshctx",
    )

    def __init__(self):
        self.decomposer = TaskDecomposer()
        self.agent_pool = AgentPool()
        self.memory_hub = MemoryHub()
        self._active_dags: Dict[str, TaskDAG] = {}
        self._dag_tasks: Dict[str, asyncio.Task] = {}

    async def on_load(self):
        """注册事件处理器"""
        bus = self.kernel.bus

        bus.subscribe("orchestrator.execute", self._on_execute_request,
                      plugin_name="orchestrator")
        bus.subscribe("orchestrator.status", self._on_status_request,
                      plugin_name="orchestrator")
        bus.subscribe("task.result", self._on_task_result,
                      plugin_name="orchestrator")

        # 预创建Agent池
        for role in [AgentRole.CODER, AgentRole.RESEARCHER,
                     AgentRole.DEVOPS, AgentRole.REVIEWER]:
            self.agent_pool.create_agent(role)

        logger.info(f"编排器已加载: Agent池={self.agent_pool.get_stats()}")

    async def on_unload(self):
        """取消所有运行中的DAG"""
        for task in self._dag_tasks.values():
            task.cancel()
        logger.info("编排器已卸载")

    # ── 事件处理器 ────────────────────────────────────────

    async def _on_execute_request(self, event: Event):
        """执行请求: 分解意图并开始调度"""
        intent = event.data.get("intent", "")
        if not intent:
            return

        # 1. 分解为DAG
        dag = self.decomposer.decompose(intent)
        dag_id = str(uuid.uuid4())
        self._active_dags[dag_id] = dag
        self.memory_hub._global_state["active_dags"] = len(self._active_dags)

        logger.info(f"DAG创建: {dag_id[:8]} ({len(dag._nodes)}节点) ← {intent[:50]}")

        # 发布DAG创建事件
        await self.kernel.bus.publish(Event(
            type="dag.created",
            source="orchestrator",
            correlation_id=event.id,
            data={
                "dag_id": dag_id,
                "intent": intent,
                "node_count": len(dag._nodes),
                "dag": dag.to_dict(),
            },
        ))

        # 2. 开始调度
        schedule_task = asyncio.create_task(self._schedule_dag(dag_id))
        self._dag_tasks[dag_id] = schedule_task

    async def _on_status_request(self, event: Event):
        """状态查询"""
        dag_id = event.data.get("dag_id")
        if dag_id and dag_id in self._active_dags:
            dag = self._active_dags[dag_id]
            status = dag.to_dict()
        else:
            status = {
                "active_dags": len(self._active_dags),
                "agent_pool": self.agent_pool.get_stats(),
            }

        await self.kernel.bus.publish(Event(
            type="orchestrator.status_result",
            source="orchestrator",
            correlation_id=event.id,
            data=status,
        ))

    async def _on_task_result(self, event: Event):
        """子任务结果回调"""
        task_id = event.data.get("task_id")
        success = event.data.get("success", False)
        result = event.data.get("result")

        # 更新对应DAG中的节点
        for dag_id, dag in self._active_dags.items():
            node = dag.get_node(task_id)
            if node:
                if success:
                    node.status = TaskNodeStatus.COMPLETED
                    node.result = result
                    node.completed_at = time.time()
                else:
                    node.status = TaskNodeStatus.FAILED
                    node.error = event.data.get("error", "未知错误")

                # 写入Memory Hub
                self.memory_hub.write(
                    node.agent_type, f"task_{task_id}",
                    {"status": node.status.value, "result": result},
                )
                break

    # ── DAG调度 ───────────────────────────────────────────

    async def _schedule_dag(self, dag_id: str):
        """调度DAG中的任务(并行执行无依赖节点)"""
        dag = self._active_dags.get(dag_id)
        if not dag:
            return

        max_parallel = 4
        start_time = time.time()

        while not dag.all_done():
            ready_nodes = dag.get_ready_nodes()

            if not ready_nodes:
                # 没有就绪节点但DAG未完成 → 检查是否有卡住的
                if dag.has_failures():
                    # 跳过依赖失败节点的任务
                    self._skip_downstream(dag)
                await asyncio.sleep(0.1)
                continue

            # 并行执行就绪节点
            batch = ready_nodes[:max_parallel]
            tasks = []
            for node in batch:
                node.status = TaskNodeStatus.RUNNING
                node.started_at = time.time()
                tasks.append(self._execute_node(node))

            await asyncio.gather(*tasks, return_exceptions=True)

        # DAG完成
        duration = time.time() - start_time
        summary = dag.get_status_summary()

        await self.kernel.bus.publish(Event(
            type="dag.completed",
            source="orchestrator",
            data={
                "dag_id": dag_id,
                "duration_seconds": round(duration, 1),
                "summary": summary,
            },
        ))

        logger.info(
            f"DAG完成: {dag_id[:8]} "
            f"({summary['completed']}成功/{summary['failed']}失败) "
            f"耗时{duration:.1f}s"
        )

        # 清理
        self._active_dags.pop(dag_id, None)
        self._dag_tasks.pop(dag_id, None)

    async def _execute_node(self, node: TaskNode):
        """执行单个节点"""
        # 获取Agent
        role = AgentRole(node.agent_type) if node.agent_type in [
            r.value for r in AgentRole
        ] else AgentRole.GENERIC

        agent = self.agent_pool.get_available(role)
        if not agent:
            agent = self.agent_pool.create_agent(role)

        if not self.agent_pool.acquire(agent.id, node.id):
            node.status = TaskNodeStatus.FAILED
            node.error = "无法分配Agent"
            return

        try:
            # 组装上下文
            context = self.memory_hub.get_context_for_agent(
                agent.id, node.description
            )

            # 发布任务到Agent执行
            await self.kernel.bus.publish(Event(
                type="agent.task_assigned",
                source="orchestrator",
                data={
                    "task_id": node.id,
                    "agent_id": agent.id,
                    "agent_role": role.value,
                    "description": node.description,
                    "context": context,
                    "timeout_seconds": node.timeout_seconds,
                },
                priority=EventPriority.HIGH,
            ))

            # 等待结果(通过task.result事件回调)
            timeout = node.timeout_seconds
            poll_interval = 0.5
            elapsed = 0
            while elapsed < timeout:
                if node.status in (
                    TaskNodeStatus.COMPLETED,
                    TaskNodeStatus.FAILED,
                ):
                    break
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            if node.status == TaskNodeStatus.RUNNING:
                node.status = TaskNodeStatus.FAILED
                node.error = "执行超时"

        except Exception as e:
            node.status = TaskNodeStatus.FAILED
            node.error = str(e)
            logger.error(f"节点 [{node.name}] 异常: {e}")
        finally:
            self.agent_pool.release(agent.id)

            # 发布元认知评估事件
            await self.kernel.bus.publish(Event(
                type="task.completed",
                source="orchestrator",
                data={
                    "task_id": node.id,
                    "description": node.description,
                    "status": (
                        "success" if node.status == TaskNodeStatus.COMPLETED
                        else "failed"
                    ),
                    "duration_seconds": (
                        time.time() - node.started_at
                        if node.started_at else 0
                    ),
                    "tool_calls": 0,   # 由实际执行者更新
                    "tool_failures": 0,
                    "error": node.error,
                },
                priority=EventPriority.LOW,
            ))

    def _skip_downstream(self, dag: TaskDAG):
        """跳过依赖失败节点的下游任务"""
        for node_id, node in dag._nodes.items():
            if node.status == TaskNodeStatus.PENDING:
                # 检查是否有失败的依赖
                for dep_id in node.dependencies:
                    dep = dag.get_node(dep_id)
                    if dep and dep.status == TaskNodeStatus.FAILED:
                        node.status = TaskNodeStatus.SKIPPED
                        break

"""
多Agent协作系统 — Multi-Agent Collaboration
=======================================

在GlobalWorkspace之上构建跨Agent消息传递和协作机制。

核心概念：
1. AgentNode — 一个独立的Agent实例（有自己的GlobalWorkspace+ActiveInference）
2. AgentRegistry — 注册/发现/监控所有Agent节点
3. MessageBus — 跨Agent的异步消息总线（P2P + 广播）
4. CollaborationProtocol — 协作协议（委托/投票/共识）

使用场景：
- 一个Agent负责搜索，另一个负责分析，第三个负责报告
- Agent间通过MessageBus交换发现/分析/结论
"""

import asyncio
import time
import uuid
import json
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Callable, Any, Awaitable
from collections import defaultdict

logger = logging.getLogger(__name__)


# ── 消息系统 ──────────────────────────────────────────────

class MessageType(Enum):
    REQUEST = "request"          # 请求协作
    RESPONSE = "response"        # 协作响应
    BROADCAST = "broadcast"      # 广播消息
    STATUS = "status"            # 状态更新
    ERROR = "error"              # 错误通知
    HEARTBEAT = "heartbeat"      # 心跳


@dataclass
class AgentMessage:
    """Agent间消息"""
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    msg_type: MessageType = MessageType.BROADCAST
    sender_id: str = ""
    target_id: str = ""           # "" = 广播
    topic: str = "general"
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl: int = 30                 # 消息生命周期（秒）
    priority: int = 5             # 1(低)~10(高)

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl


@dataclass
class AgentCapability:
    """Agent能力声明"""
    name: str
    version: str = "1.0"
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    description: str = ""
    max_concurrent_tasks: int = 3


# 预定义能力常量
AgentCapability.SEARCH = AgentCapability(name="search", description="搜索与信息检索", inputs=["query"], outputs=["results"])
AgentCapability.ANALYZE = AgentCapability(name="analyze", description="数据分析与推理", inputs=["data"], outputs=["insights"])
AgentCapability.CODE = AgentCapability(name="code", description="代码编写与调试", inputs=["spec"], outputs=["code"])
AgentCapability.WRITE = AgentCapability(name="write", description="文档撰写与编辑", inputs=["topic"], outputs=["document"])
AgentCapability.GENERAL = AgentCapability(name="general", description="通用任务处理", inputs=["task"], outputs=["result"])


# ── Agent节点 ──────────────────────────────────────────────

class AgentNode:
    """
    一个独立的Agent节点。
    拥有自己的ID、能力声明、状态和消息处理循环。
    """

    def __init__(self, agent_id: str, name: str,
                 capabilities: List[AgentCapability] = None):
        self.agent_id = agent_id
        self.name = name
        self.capabilities = capabilities or [
            AgentCapability(name="chat", description="General chat agent")
        ]
        self.status = "idle"  # idle/busy/error/offline
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._bus: Optional["MessageBus"] = None
        self._running = False
        self._task_count = 0
        self._max_tasks = 5
        self._start_time = time.time()
        self._processed_messages = 0
        self._memory: Dict[str, Any] = {}

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    @property
    def can_accept_tasks(self) -> bool:
        return self._task_count < self._max_tasks and self.status != "error"

    def set_bus(self, bus: "MessageBus"):
        self._bus = bus

    async def start(self):
        """启动消息处理循环"""
        self._running = True
        self.status = "idle"
        logger.info(f"Agent {self.name} ({self.agent_id}) started")
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._message_queue.get(), timeout=1.0
                )
                self._processed_messages += 1
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Agent {self.name} error: {e}")
                self.status = "error"

    async def stop(self):
        self._running = False
        self.status = "offline"

    async def receive(self, msg: AgentMessage):
        """接收消息（被MessageBus调用）"""
        await self._message_queue.put(msg)

    async def send(self, target_id: str, topic: str,
                   payload: dict, msg_type: MessageType = MessageType.REQUEST):
        """发送消息到另一个Agent"""
        if self._bus is None:
            raise RuntimeError("Agent not connected to a MessageBus")
        msg = AgentMessage(
            msg_type=msg_type,
            sender_id=self.agent_id,
            target_id=target_id,
            topic=topic,
            payload=payload,
        )
        await self._bus.send(msg)

    async def broadcast(self, topic: str, payload: dict):
        """广播消息给所有Agent"""
        if self._bus is None:
            raise RuntimeError("Agent not connected to a MessageBus")
        msg = AgentMessage(
            msg_type=MessageType.BROADCAST,
            sender_id=self.agent_id,
            topic=topic,
            payload=payload,
        )
        await self._bus.broadcast(msg)

    async def _handle_message(self, msg: AgentMessage):
        """处理收到的消息——子类重写此方法实现具体逻辑"""
        if msg.is_expired():
            logger.debug(f"Dropping expired message {msg.msg_id}")
            return

        if msg.msg_type == MessageType.REQUEST:
            # 默认实现：回复能力声明
            await self.send(
                target_id=msg.sender_id,
                topic=msg.topic,
                payload={
                    "status": self.status,
                    "capabilities": [c.name for c in self.capabilities],
                    "task_count": self._task_count,
                },
                msg_type=MessageType.RESPONSE
            )
        elif msg.msg_type == MessageType.BROADCAST:
            logger.debug(f"Broadcast from {msg.sender_id}: {msg.topic}")
            # 默认只记录不处理

    def get_info(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "capabilities": [c.name for c in self.capabilities],
            "uptime": self.uptime,
            "processed_messages": self._processed_messages,
            "task_count": self._task_count,
            "max_tasks": self._max_tasks,
        }


# ── 消息总线 ──────────────────────────────────────────────

class MessageBus:
    """
    异步消息总线，支持P2P和广播。
    维护Agent注册表，负责消息路由。
    """

    def __init__(self):
        self._agents: Dict[str, AgentNode] = {}
        self._topics: Dict[str, Set[str]] = defaultdict(set)  # topic→agent_ids
        self._message_history: List[AgentMessage] = []
        self._max_history = 1000

    def register(self, agent: AgentNode) -> None:
        """注册Agent到总线"""
        self._agents[agent.agent_id] = agent
        agent.set_bus(self)
        # 按能力注册主题
        for cap in agent.capabilities:
            self._topics[cap.name].add(agent.agent_id)
        logger.info(f"Registered agent: {agent.name} ({agent.agent_id})")

    def unregister(self, agent_id: str) -> None:
        """取消注册"""
        self._agents.pop(agent_id, None)
        for topic in self._topics:
            self._topics[topic].discard(agent_id)

    def get_agent(self, agent_id: str) -> Optional[AgentNode]:
        return self._agents.get(agent_id)

    def find_agents_by_capability(self, capability: str) -> List[AgentNode]:
        """按能力查找Agent"""
        return [
            self._agents[aid] for aid in self._topics.get(capability, set())
            if aid in self._agents
        ]

    def find_idle_agent(self, capability: str) -> Optional[AgentNode]:
        """找到最空闲的具有指定能力的Agent"""
        candidates = self.find_agents_by_capability(capability)
        idle = [a for a in candidates if a.can_accept_tasks]
        if not idle:
            return None
        return min(idle, key=lambda a: a._task_count)

    async def send(self, msg: AgentMessage) -> bool:
        """发送P2P消息"""
        target = self._agents.get(msg.target_id)
        if target is None:
            logger.warning(f"Agent {msg.target_id} not found")
            return False
        await target.receive(msg)
        self._record_message(msg)
        return True

    async def broadcast(self, msg: AgentMessage) -> int:
        """广播消息给所有Agent（可选按topic过滤）"""
        sent_count = 0
        targets = (
            [aid for aid in self._topics.get(msg.topic, set())]
            if msg.topic != "general" else list(self._agents.keys())
        )
        for aid in targets:
            agent = self._agents.get(aid)
            if agent and aid != msg.sender_id:
                await agent.receive(msg)
                sent_count += 1
        self._record_message(msg)
        return sent_count

    async def heartbeat_all(self) -> Dict[str, str]:
        """向所有Agent发送心跳，返回状态字典"""
        statuses = {}
        for aid, agent in self._agents.items():
            try:
                statuses[aid] = agent.status
            except Exception:
                statuses[aid] = "offline"
        return statuses

    def _record_message(self, msg: AgentMessage):
        self._message_history.append(msg)
        if len(self._message_history) > self._max_history:
            self._message_history = self._message_history[-self._max_history:]

    def get_stats(self) -> dict:
        return {
            "total_agents": len(self._agents),
            "topics": {t: len(ids) for t, ids in self._topics.items()},
            "message_history": len(self._message_history),
            "agents": {aid: agent.status for aid, agent in self._agents.items()},
        }


# ── 协作协议 ──────────────────────────────────────────────

class CollaborationProtocol:
    """
    协作协议——Agent间的协作模式。
    
    支持的协议：
    - DELEGATE: 委托一个Agent执行任务
    - VOTE: 多个Agent投票决策
    - CONSENSUS: 达成共识（需要多数同意）
    - ENSEMBLE: 多个Agent独立执行后汇总
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._pending_votes: Dict[str, List[dict]] = defaultdict(list)
        self._vote_timeout = 10.0

    async def delegate(self, from_agent: AgentNode, capability: str,
                       task: dict) -> Optional[AgentNode]:
        """委托任务给一个具有指定能力的Agent"""
        target = self.bus.find_idle_agent(capability)
        if target is None:
            logger.warning(f"No idle agent with capability '{capability}'")
            return None
        await from_agent.send(
            target_id=target.agent_id,
            topic=capability,
            payload={"task": task, "delegator": from_agent.agent_id},
            msg_type=MessageType.REQUEST
        )
        target._task_count += 1
        return target

    async def vote(self, initiator: AgentNode, question: str,
                   options: List[str], min_votes: int = 3) -> Optional[str]:
        """发起投票——收集多个Agent的意见"""
        vote_id = str(uuid.uuid4())[:8]
        votes = []

        # 向所有Agent广播投票请求
        await initiator.broadcast(
            topic="vote",
            payload={
                "vote_id": vote_id,
                "question": question,
                "options": options,
                "initiator": initiator.agent_id,
            }
        )

        # 等待投票（超时模式）
        deadline = time.time() + self._vote_timeout
        while time.time() < deadline and len(votes) < min_votes:
            await asyncio.sleep(0.5)
            # 从消息历史收集投票响应
            for msg in self.bus._message_history[-50:]:
                if (msg.topic == "vote_response"
                        and msg.payload.get("vote_id") == vote_id
                        and msg.payload.get("choice") in options
                        and msg.sender_id != initiator.agent_id):
                    if msg.sender_id not in [v["agent"] for v in votes]:
                        votes.append({
                            "agent": msg.sender_id,
                            "choice": msg.payload["choice"],
                            "confidence": msg.payload.get("confidence", 0.5),
                        })

        if not votes:
            return None

        # 加权投票（置信度越高权重越大）
        score = defaultdict(float)
        total_weight = 0.0
        for v in votes:
            score[v["choice"]] += v["confidence"]
            total_weight += v["confidence"]
        if total_weight == 0:
            return None
        return max(score, key=score.get)

    async def ensemble(self, initiator: AgentNode, task: dict,
                       capability: str = "analyze") -> List[dict]:
        """多个Agent独立执行同一任务后汇总结果"""
        agents = self.bus.find_agents_by_capability(capability)
        results = []

        if len(agents) < 2:
            logger.warning(f"Not enough agents for ensemble (need 2, got {len(agents)})")
            return results

        for agent in agents[:3]:  # 最多3个
            if agent.can_accept_tasks and agent.agent_id != initiator.agent_id:
                await initiator.send(
                    target_id=agent.agent_id,
                    topic=capability,
                    payload={"task": task, "ensemble": True},
                    msg_type=MessageType.REQUEST
                )

        # 简单等待（实际应异步收集）
        await asyncio.sleep(2.0)
        return results


# ── 管理器 ──────────────────────────────────────────────

class AgentManager:
    """
    Agent管理器——管理所有Agent节点的生命周期。
    负责启动/停止/监控/发现。
    """

    def __init__(self):
        self.bus = MessageBus()
        self.protocol = CollaborationProtocol(self.bus)
        self._agents: Dict[str, AgentNode] = {}
        self._running = False

    def create_agent(self, agent_id: str, name: str,
                     capabilities: List[AgentCapability] = None) -> AgentNode:
        """创建并注册Agent"""
        agent = AgentNode(agent_id, name, capabilities)
        self._agents[agent_id] = agent
        self.bus.register(agent)
        return agent

    async def start_all(self):
        """启动所有Agent"""
        self._running = True
        tasks = []
        for agent in self._agents.values():
            tasks.append(asyncio.create_task(agent.start()))
        logger.info(f"Started {len(tasks)} agents")
        # 让心跳循环run
        await self._heartbeat_loop()

    async def stop_all(self):
        """停止所有Agent"""
        self._running = False
        for agent in self._agents.values():
            await agent.stop()
        logger.info("All agents stopped")

    async def _heartbeat_loop(self):
        """定期心跳检查所有Agent状态"""
        while self._running:
            await asyncio.sleep(30)
            statuses = await self.bus.heartbeat_all()
            for aid, status in statuses.items():
                if status == "offline" and aid in self._agents:
                    logger.warning(f"Agent {aid} went offline, removing")
                    self.bus.unregister(aid)
                    del self._agents[aid]

    def get_summary(self) -> dict:
        return {
            "agent_count": len(self._agents),
            "agents": {aid: agent.get_info() for aid, agent in self._agents.items()},
            "bus": self.bus.get_stats(),
        }


# ═══════════════════════════════════════════════════════════
# 任务分解引擎 v2.0
# ═══════════════════════════════════════════════════════════

class TaskDecomposer:
    """
    将复杂任务递归分解为可并行执行的子任务。
    
    策略:
    - 识别独立子任务 → 并行执行
    - 识别依赖关系 → 串行执行
    - 识别可拆分数据 → 分片并行(MapReduce)
    """

    def __init__(self):
        self.max_depth = 3
        self.max_subtasks = 8

    def decompose(self, task: dict, depth: int = 0) -> List[dict]:
        """
        分解任务。返回子任务列表，每个子任务包含:
        - id, description, type, dependencies, priority
        """
        if depth >= self.max_depth:
            return [task]

        task_type = task.get("type", "general")
        subtasks = []

        if task_type == "research":
            subtasks = self._decompose_research(task)
        elif task_type == "code":
            subtasks = self._decompose_code(task)
        elif task_type == "analysis":
            subtasks = self._decompose_analysis(task)
        elif task_type == "report":
            subtasks = self._decompose_report(task)
        else:
            subtasks = self._decompose_generic(task)

        # 递归分解
        if depth + 1 < self.max_depth:
            decomposed = []
            for st in subtasks:
                decomposed.extend(self.decompose(st, depth + 1))
            subtasks = decomposed[:self.max_subtasks]

        return subtasks

    def _decompose_research(self, task: dict) -> List[dict]:
        topic = task.get("description", "")
        tid = task.get("id", "task")
        return [
            {"id": f"{tid}_search", "description": f"搜索: {topic}", "type": "search", "dependencies": []},
            {"id": f"{tid}_analyze", "description": f"分析: {topic}", "type": "analyze", "dependencies": [f"{tid}_search"]},
            {"id": f"{tid}_summarize", "description": f"总结: {topic}", "type": "write", "dependencies": [f"{tid}_analyze"]},
        ]

    def _decompose_code(self, task: dict) -> List[dict]:
        desc = task.get("description", "")
        tid = task.get("id", "task")
        return [
            {"id": f"{tid}_design", "description": f"设计: {desc}", "type": "analyze", "dependencies": []},
            {"id": f"{tid}_implement", "description": f"实现: {desc}", "type": "code", "dependencies": [f"{tid}_design"]},
            {"id": f"{tid}_test", "description": f"测试: {desc}", "type": "code", "dependencies": [f"{tid}_implement"]},
            {"id": f"{tid}_review", "description": f"审查: {desc}", "type": "analyze", "dependencies": [f"{tid}_test"]},
        ]

    def _decompose_analysis(self, task: dict) -> List[dict]:
        desc = task.get("description", "")
        tid = task.get("id", "task")
        return [
            {"id": f"{tid}_collect", "description": f"收集数据: {desc}", "type": "search", "dependencies": []},
            {"id": f"{tid}_process", "description": f"处理数据: {desc}", "type": "analyze", "dependencies": [f"{tid}_collect"]},
            {"id": f"{tid}_conclude", "description": f"得出结论: {desc}", "type": "analyze", "dependencies": [f"{tid}_process"]},
        ]

    def _decompose_report(self, task: dict) -> List[dict]:
        desc = task.get("description", "")
        tid = task.get("id", "task")
        return [
            {"id": f"{tid}_outline", "description": f"大纲: {desc}", "type": "analyze", "dependencies": []},
            {"id": f"{tid}_write", "description": f"撰写: {desc}", "type": "write", "dependencies": [f"{tid}_outline"]},
            {"id": f"{tid}_polish", "description": f"润色: {desc}", "type": "write", "dependencies": [f"{tid}_write"]},
        ]

    def _decompose_generic(self, task: dict) -> List[dict]:
        desc = task.get("description", "")
        tid = task.get("id", "task")
        # 最小分解: 计划→执行→验证
        return [
            {"id": f"{tid}_plan", "description": f"计划: {desc}", "type": "analyze", "dependencies": []},
            {"id": f"{tid}_exec", "description": f"执行: {desc}", "type": "general", "dependencies": [f"{tid}_plan"]},
            {"id": f"{tid}_verify", "description": f"验证: {desc}", "type": "analyze", "dependencies": [f"{tid}_exec"]},
        ]


# ═══════════════════════════════════════════════════════════
# 并行执行引擎 v2.0
# ═══════════════════════════════════════════════════════════

class ParallelExecutor:
    """
    并行执行任务分解后的子任务。
    
    特性:
    - 自动识别无依赖子任务并行执行
    - 依赖解析(DAG拓扑排序)
    - 超时控制
    - 结果合并
    """

    def __init__(self, manager: AgentManager, bus: MessageBus):
        self.manager = manager
        self.bus = bus
        self.decomposer = TaskDecomposer()
        self.timeout_per_task = 30  # 秒

    async def execute_task(self, task: dict) -> dict:
        """
        执行一个复杂任务:
        1. 分解为子任务
        2. 按依赖关系并行/串行执行
        3. 合并结果
        """
        task_id = task.get("id", str(uuid.uuid4())[:8])
        subtasks = self.decomposer.decompose(task)

        logger.info(f"Task {task_id}: decomposed into {len(subtasks)} subtasks")

        # 构建依赖图
        completed = {}
        results = []
        pending = list(subtasks)
        start_time = time.time()

        while pending:
            # 找出所有依赖已完成的子任务
            ready = [
                st for st in pending
                if all(dep in completed for dep in st.get("dependencies", []))
            ]

            if not ready:
                # 循环依赖或全部pending都有未完成依赖
                logger.warning(f"Task {task_id}: deadlock detected, breaking")
                break

            # 并行执行所有ready任务
            if len(ready) == 1:
                r = await self._execute_single(ready[0], task_id)
                completed[ready[0]["id"]] = r
                results.append(r)
                pending.remove(ready[0])
            else:
                # 真正并行
                coros = [self._execute_single(st, task_id) for st in ready]
                batch_results = await asyncio.gather(*coros, return_exceptions=True)
                for st, r in zip(ready, batch_results):
                    if isinstance(r, Exception):
                        completed[st["id"]] = {"error": str(r), "subtask_id": st["id"]}
                        results.append(completed[st["id"]])
                    else:
                        completed[st["id"]] = r
                        results.append(r)
                    pending.remove(st)

            # 超时
            if time.time() - start_time > self.timeout_per_task * len(subtasks):
                logger.warning(f"Task {task_id}: timeout")
                break

        return {
            "task_id": task_id,
            "description": task.get("description", ""),
            "subtasks_total": len(subtasks),
            "subtasks_completed": len(completed),
            "results": results,
            "merged": self._merge_results(results),
        }

    async def _execute_single(self, subtask: dict, parent_id: str) -> dict:
        """执行单个子任务 — 委托给最合适的Agent"""
        st_type = subtask.get("type", "general")
        capability_map = {
            "search": "search",
            "analyze": "analyze",
            "code": "code",
            "write": "write",
            "general": "general",
        }
        capability = capability_map.get(st_type, "general")

        # 找到最空闲的Agent
        agent = self.bus.find_idle_agent(capability)
        if agent is None:
            # 回退: 找任意可用的
            for a in self.bus._agents.values():
                if a.can_accept_tasks:
                    agent = a
                    break

        if agent is None:
            return {
                "subtask_id": subtask["id"],
                "status": "failed",
                "error": "No available agent",
            }

        # 模拟执行 (实际应通过LLM调用)
        try:
            result = {
                "subtask_id": subtask["id"],
                "agent": agent.name,
                "agent_id": agent.agent_id,
                "capability": capability,
                "status": "completed",
                "description": subtask.get("description", ""),
                "type": st_type,
                "output": f"[{agent.name}] executed: {subtask.get('description','')}",
            }
            agent._task_count += 1
            return result
        except Exception as e:
            return {
                "subtask_id": subtask["id"],
                "status": "failed",
                "error": str(e),
            }

    def _merge_results(self, results: List[dict]) -> dict:
        """合并所有子任务结果"""
        completed = [r for r in results if r.get("status") == "completed"]
        failed = [r for r in results if r.get("status") == "failed"]

        # 提取所有输出
        outputs = [r.get("output", "") for r in completed]

        return {
            "completed_count": len(completed),
            "failed_count": len(failed),
            "agents_used": list(set(r.get("agent", "?") for r in completed)),
            "summary": " | ".join(outputs[:5]) if outputs else "No output",
            "all_outputs": outputs,
        }

    def get_execution_plan(self, task: dict) -> dict:
        """返回执行计划(不实际执行)"""
        subtasks = self.decomposer.decompose(task)
        return {
            "task": task.get("description", ""),
            "subtasks": [
                {
                    "id": st["id"],
                    "description": st["description"],
                    "type": st["type"],
                    "dependencies": st.get("dependencies", []),
                    "parallel_group": len(st.get("dependencies", [])),
                }
                for st in subtasks
            ],
            "total_subtasks": len(subtasks),
            "estimated_agents": min(len(subtasks), 4),
            "parallelism": "DAG (拓扑排序 + 并行批次)",
        }


# ═══════════════════════════════════════════════════════════
# 预定义专业Agent工厂
# ═══════════════════════════════════════════════════════════

class AgentFactory:
    """一键创建专业Agent团队"""

    @staticmethod
    def create_team(manager: AgentManager) -> Dict[str, AgentNode]:
        """创建默认Agent团队: 搜索/分析/代码/写作/通用"""
        agents = {}

        agents["searcher"] = manager.create_agent(
            "searcher", "🔍 Searcher",
            [AgentCapability.SEARCH, AgentCapability.GENERAL]
        )
        agents["analyst"] = manager.create_agent(
            "analyst", "📊 Analyst",
            [AgentCapability.ANALYZE, AgentCapability.GENERAL]
        )
        agents["coder"] = manager.create_agent(
            "coder", "💻 Coder",
            [AgentCapability.CODE, AgentCapability.GENERAL]
        )
        agents["writer"] = manager.create_agent(
            "writer", "✍️ Writer",
            [AgentCapability.WRITE, AgentCapability.GENERAL]
        )
        agents["general"] = manager.create_agent(
            "general", "🤖 General",
            [AgentCapability.GENERAL]
        )

        return agents


# ── 全局单例 ──────────────────────────────────────────

_global_manager: Optional[AgentManager] = None
_global_executor: Optional[ParallelExecutor] = None


def get_manager() -> AgentManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = AgentManager()
    return _global_manager


def get_executor() -> ParallelExecutor:
    global _global_executor
    mgr = get_manager()
    if _global_executor is None:
        _global_executor = ParallelExecutor(mgr, mgr.bus)
    return _global_executor

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

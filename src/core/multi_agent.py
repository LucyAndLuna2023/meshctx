"""
meshctx Multi-Agent Orchestrator v3.50 — 多专家Agent协调系统 (真实实现)
============================================================
管理多个 specialist agent 的生命周期，提供智能对话路由、
Agent间通信、上下文隔离和结果聚合。

核心概念:
  与 agent_swarm 的区别:
    - agent_swarm: 同质 Worker 池 → 任务分解 + 并行执行
    - multi_agent: 异质 Specialist 池 → 意图路由 + 专家协作

架构:
  1. AgentRegistry — 注册/管理 specialist agent 元数据
  2. IntentRouter — 根据消息意图路由到正确的 specialist
  3. _Bus — Agent 间异步消息传递
  4. ContextManager — 每个 agent 独立的上下文窗口
  5. ResultAggregator — 多 agent 并行处理结果聚合
  6. MultiAgentOrchestrator — 顶层编排器
"""
# 真实实现 (2026-08-25, 004meshctx 审计): 原 stub 已全部替换为真实功能。
# 保持公开 API 签名不变, 内存版实现, 纯 stdlib。
from __future__ import annotations
import asyncio
import logging
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.multi_agent")


class AgentStatus(str, Enum):
    IDLE = 'idle'
    BUSY = 'busy'
    OFFLINE = 'offline'
    ERROR = 'error'
    DRAINING = 'draining'


class MessagePriority(str, Enum):
    LOW = 'low'
    NORMAL = 'normal'
    HIGH = 'high'
    URGENT = 'urgent'


@dataclass
class AgentHandle:
    """Agent 句柄 — 指向注册的 specialist agent"""
    agent_id: str = None
    name: str = ''
    role: str = ''
    tools: List[str] = None
    capabilities: List[str] = None
    status: AgentStatus = None
    registered_at: float = None
    last_active: float = 0.0
    total_handled: int = 0
    total_errors: int = 0
    avg_response_ms: float = 0.0
    context_size: int = 0
    max_context_size: int = 50
    metadata: Dict = None

    def to_dict(self, **kw) -> Dict:
        d = {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "tools": self.tools or [],
            "capabilities": self.capabilities or [],
            "status": self.status.value if self.status else "idle",
            "registered_at": self.registered_at,
            "last_active": self.last_active,
            "total_handled": self.total_handled,
            "total_errors": self.total_errors,
            "avg_response_ms": self.avg_response_ms,
            "context_size": self.context_size,
            "max_context_size": self.max_context_size,
            "metadata": self.metadata or {},
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict, **kw) -> 'AgentHandle':
        handle = cls(
            agent_id=d.get("agent_id"),
            name=d.get("name", ""),
            role=d.get("role", ""),
            tools=d.get("tools") or [],
            capabilities=d.get("capabilities") or [],
            status=AgentStatus(d.get("status", "idle")),
            registered_at=d.get("registered_at"),
            last_active=d.get("last_active", 0.0),
            total_handled=d.get("total_handled", 0),
            total_errors=d.get("total_errors", 0),
            avg_response_ms=d.get("avg_response_ms", 0.0),
            context_size=d.get("context_size", 0),
            max_context_size=d.get("max_context_size", 50),
            metadata=d.get("metadata") or {},
        )
        return handle


@dataclass
class _Msg:
    """Agent 间传递的消息"""
    message_id: str = ''
    from_agent: str = ''
    to_agent: str = ''
    content: str = ''
    message_type: str = 'text'
    priority: MessagePriority = None
    context: Dict = None
    created_at: float = None
    ttl: int = 300

    def __post_init__(self):
        if not self.message_id:
            self.message_id = str(uuid.uuid4())[:12]
        if self.priority is None:
            self.priority = MessagePriority.NORMAL
        if self.created_at is None:
            self.created_at = time.time()

    def is_expired(self, **kw) -> bool:
        return (time.time() - (self.created_at or 0)) > self.ttl


@dataclass
class AgentResult:
    """Agent 处理结果"""
    agent_id: str = None
    message_id: str = ''
    content: str = ''
    status: str = 'success'
    confidence: float = 1.0
    duration_ms: float = 0.0
    metadata: Dict = None
    created_at: float = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self, **kw) -> Dict:
        return {
            "agent_id": self.agent_id,
            "message_id": self.message_id,
            "content": self.content,
            "status": self.status,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata or {},
            "created_at": self.created_at,
        }


@dataclass
class RouteDecision:
    """路由决策结果"""
    target_agent: Optional[AgentHandle] = None
    confidence: float = 0.0
    reasoning: str = ''
    alternatives: List[Tuple[AgentHandle, float]] = None
    rule_matched: str = ''


# ── 关键词 → 能力 默认路由词典 (轻量意图识别) ────────────────
_DEFAULT_ROUTING_KEYWORDS: Dict[str, List[str]] = {
    "code": ["python", "代码", "编程", "bug", "debug", "重构", "refactor", "函数", "算法"],
    "security": ["安全", "漏洞", "vulnerability", "审计", "audit", "渗透", "pentest", "攻击"],
    "data": ["数据", "分析", "data", "sql", "数据库", "报表", "统计"],
    "writing": ["写作", "文案", "文章", "write", "翻译", "translate", "summary"],
    "research": ["研究", "调研", "research", "资料", "文献", "调查"],
    "planning": ["计划", "规划", "计划书", "roadmap", "策略"],
}


class IntentRouter:
    """意图路由器 — 根据消息内容和上下文决定路由到哪个 specialist"""
    def __init__(self, **kw):
        self._rules: Dict[str, Dict] = {}
        self._stats: Dict[str, Any] = {"routes": 0, "rule_hits": 0, "keyword_hits": 0, "fallbacks": 0}

    def _score_agent(self, message: str, agent: AgentHandle) -> Tuple[float, str]:
        """按关键词命中打分。返回 (score, matched_pattern)。"""
        text = (message or "").lower()
        score = 0.0
        matched = ""
        caps = " ".join(agent.capabilities or []).lower()
        role = (agent.role or "").lower()
        for cap, kws in _DEFAULT_ROUTING_KEYWORDS.items():
            if cap in caps or cap in role:
                for kw in kws:
                    if kw.lower() in text:
                        score += 0.6
                        matched = kw
        return score, matched

    def route(self, message: str, agents: Dict[str, AgentHandle], context: Dict = None, preferred_agent: str = '') -> RouteDecision:
        """路由消息到最合适的 agent"""
        self._stats["routes"] += 1
        if preferred_agent and preferred_agent in agents:
            return RouteDecision(
                target_agent=agents[preferred_agent], confidence=1.0,
                reasoning=f"preferred agent: {preferred_agent}", rule_matched="preferred")

        # 1) 显式自定义规则 (正则)
        for name, rule in self._rules.items():
            try:
                if re.search(rule["pattern"], message, re.IGNORECASE):
                    target = agents.get(rule["target"])
                    if target:
                        self._stats["rule_hits"] += 1
                        return RouteDecision(
                            target_agent=target, confidence=rule.get("confidence", 0.9),
                            reasoning=f"rule '{name}' matched", rule_matched=name)
            except re.error:
                continue

        # 2) 关键词打分
        scored: List[Tuple[AgentHandle, float]] = []
        for agent in agents.values():
            if agent.status == AgentStatus.OFFLINE:
                continue
            s, _ = self._score_agent(message, agent)
            if s > 0:
                scored.append((agent, s))
        if scored:
            scored.sort(key=lambda x: -x[1])
            self._stats["keyword_hits"] += 1
            best, best_score = scored[0]
            return RouteDecision(
                target_agent=best, confidence=min(1.0, best_score),
                reasoning=f"keyword match (score={best_score:.2f})",
                alternatives=scored[1:4])

        # 3) 兜底: 第一个 idle 在线 agent
        self._stats["fallbacks"] += 1
        for agent in agents.values():
            if agent.status in (None, AgentStatus.IDLE, AgentStatus.BUSY):
                return RouteDecision(
                    target_agent=agent, confidence=0.2,
                    reasoning="no keyword/rule match, fallback to first agent")
        return RouteDecision(target_agent=None, confidence=0.0, reasoning="no agents available")

    def add_rule(self, name: str, pattern: str, target: str, confidence: float = 0.9):
        """添加自定义路由规则"""
        self._rules[name] = {"pattern": pattern, "target": target, "confidence": confidence}
        return True

    def remove_rule(self, name: str, **kw) -> bool:
        """删除路由规则"""
        return self._rules.pop(name, None) is not None

    def get_routing_stats(self, **kw) -> Dict:
        return dict(self._stats)


class _Bus:
    """Agent 间异步消息总线 (内存版, 线程安全)"""
    def __init__(self, max_queue_size: int = 100, **kw):
        self._queues: Dict[str, deque] = {}
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size
        self._stats = {"sent": 0, "broadcast": 0, "dropped": 0}

    def send(self, message: _Msg, **kw) -> bool:
        """发送消息到指定 agent 的 inbox"""
        with self._lock:
            q = self._queues.setdefault(message.to_agent, deque(maxlen=self._max_queue_size))
            if len(q) >= self._max_queue_size:
                self._stats["dropped"] += 1
                return False
            q.append(message)
            self._stats["sent"] += 1
            return True

    def _broadcast(self, message: _Msg, **kw) -> bool:
        """广播消息到所有 agent (不含发送者)"""
        sent = 0
        with self._lock:
            for aid, q in list(self._queues.items()):
                if aid == message.from_agent:
                    continue
                if len(q) < self._max_queue_size:
                    m = _Msg(
                        message_id=str(uuid.uuid4())[:12], from_agent=message.from_agent,
                        to_agent=aid, content=message.content,
                        message_type=message.message_type, priority=message.priority,
                        context=message.context, ttl=message.ttl)
                    q.append(m)
                    sent += 1
            self._stats["broadcast"] += 1
        return sent > 0

    def receive(self, agent_id: str, limit: int = 10, **kw) -> List[_Msg]:
        """从 agent 的 inbox 接收消息"""
        out: List[_Msg] = []
        with self._lock:
            q = self._queues.get(agent_id)
            if not q:
                return out
            for _ in range(min(limit, len(q))):
                out.append(q.popleft())
        return out

    def peek(self, agent_id: str, limit: int = 10, **kw) -> List[_Msg]:
        """查看 inbox 但不消费消息"""
        with self._lock:
            q = self._queues.get(agent_id)
            if not q:
                return []
            return list(q)[:limit]

    def get_inbox_size(self, agent_id: str, **kw) -> int:
        with self._lock:
            return len(self._queues.get(agent_id, ()))

    def clear_inbox(self, agent_id: str, **kw):
        with self._lock:
            self._queues[agent_id] = deque(maxlen=self._max_queue_size)

    def remove_agent(self, agent_id: str, **kw):
        """移除 agent 的消息队列"""
        with self._lock:
            self._queues.pop(agent_id, None)

    def get_bus_stats(self, **kw) -> Dict:
        with self._lock:
            return {
                "sent": self._stats["sent"],
                "broadcast": self._stats["broadcast"],
                "dropped": self._stats["dropped"],
                "queues": {aid: len(q) for aid, q in self._queues.items()},
            }


class ContextManager:
    """Agent 上下文管理器 — 每个 agent 独立上下文窗口"""
    def __init__(self, **kw):
        self._contexts: Dict[str, List[Dict]] = {}
        self._lock = threading.Lock()

    def add_message(self, agent_id: str, message: Dict, max_size: int = 50):
        """向 agent 上下文添加消息"""
        with self._lock:
            ctx = self._contexts.setdefault(agent_id, [])
            ctx.append(message)
            if len(ctx) > max_size:
                # 裁剪并保留摘要
                overflow = ctx[: len(ctx) - max_size]
                summary = self._summarize(overflow)
                ctx[:] = ctx[-max_size:]
                if summary:
                    ctx.insert(0, {"role": "system", "content": summary, "summary": True})

    def get_context(self, agent_id: str, **kw) -> List[Dict]:
        with self._lock:
            return list(self._contexts.get(agent_id, []))

    def get_summary(self, agent_id: str, **kw) -> str:
        """获取 agent 上下文摘要"""
        with self._lock:
            ctx = self._contexts.get(agent_id, [])
        return self._summarize(ctx)

    def get_full_context(self, agent_id: str, **kw) -> Dict:
        """获取 agent 完整上下文 (当前消息 + 摘要)"""
        with self._lock:
            ctx = list(self._contexts.get(agent_id, []))
        return {"messages": ctx, "summary": self._summarize(ctx), "size": len(ctx)}

    def clear_context(self, agent_id: str, **kw):
        with self._lock:
            self._contexts.pop(agent_id, None)

    def _summarize(self, messages: List[Dict], **kw) -> str:
        """从被裁剪的消息中提取摘要"""
        if not messages:
            return ""
        roles = [m.get("role", "?") for m in messages[-20:]]
        chars = sum(len(str(m.get("content", ""))) for m in messages)
        return f"({len(messages)} msgs, roles: {','.join(dict.fromkeys(roles))[:60]}, ~{chars} chars)"

    def get_all_context_stats(self, **kw) -> Dict:
        with self._lock:
            return {aid: len(ctx) for aid, ctx in self._contexts.items()}


class MultiAgentOrchestrator:
    """多 Agent 编排器 (真实实现)"""
    def __init__(self, max_agents: int = 20, default_timeout: float = 300.0, **kw):
        self.max_agents = max_agents
        self.default_timeout = default_timeout
        self._agents: Dict[str, AgentHandle] = {}
        self._handlers: Dict[str, Callable] = {}
        self._router = IntentRouter()
        self._bus = _Bus()
        self._context = ContextManager()
        self._results: Dict[str, AgentResult] = {}
        self._tasks: Dict[str, Dict] = {}
        self._collaborations: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._started = False
        self._cleanup_task = None

    async def start(self):
        """启动编排器"""
        self._started = True
        self._cleanup_task = asyncio.get_event_loop().create_task(self._cleanup_loop())
        return True

    async def stop(self):
        """停止编排器"""
        self._started = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except (asyncio.CancelledError, Exception):
                pass
        return True

    async def _cleanup_loop(self):
        """后台清理循环 — 清理过期消息"""
        while self._started:
            await asyncio.sleep(60)
            try:
                for aid in list(self._agents.keys()):
                    # 丢弃过期消息
                    for m in self._bus.peek(aid, limit=1000):
                        if m.is_expired():
                            self._bus.receive(aid, limit=1)
            except Exception as e:
                logger.warning(f"multi_agent cleanup error: {e}")

    def register_agent(self, name: str, role: str, tools: List[str] = None, capabilities: List[str] = None, metadata: Dict = None, agent_id: str = '') -> AgentHandle:
        """注册一个 specialist agent"""
        with self._lock:
            if len(self._agents) >= self.max_agents:
                raise RuntimeError(f"max agents reached ({self.max_agents})")
            if not agent_id:
                agent_id = name.replace(" ", "_").lower() + "_" + str(uuid.uuid4())[:6]
            handle = AgentHandle(
                agent_id=agent_id, name=name, role=role,
                tools=tools or [], capabilities=capabilities or [],
                status=AgentStatus.IDLE, registered_at=time.time(),
                metadata=metadata or {})
            self._agents[agent_id] = handle
            self._bus._queues.setdefault(agent_id, deque(maxlen=self._bus._max_queue_size))
            return handle

    def unregister_agent(self, agent_id: str, **kw) -> bool:
        with self._lock:
            ok = self._agents.pop(agent_id, None) is not None
        if ok:
            self._bus.remove_agent(agent_id)
            self._context.clear_context(agent_id)
        return ok

    def get_agent(self, agent_id: str, **kw) -> Optional[AgentHandle]:
        return self._agents.get(agent_id)

    def list_agents(self, status: AgentStatus = None, **kw) -> List[AgentHandle]:
        if status is None:
            return list(self._agents.values())
        return [a for a in self._agents.values() if a.status == status]

    def set_agent_status(self, agent_id: str, status: AgentStatus, **kw):
        a = self._agents.get(agent_id)
        if a:
            a.status = status
            a.last_active = time.time()
        return a

    def register_handler(self, agent_id: str, handler: Callable[[str, Dict], Any]):
        """注册 agent 的消息处理回调"""
        self._handlers[agent_id] = handler
        return True

    def route_message(self, message: str, context: Dict = None, preferred_agent: str = '') -> Optional[AgentHandle]:
        """路由消息到最合适的 specialist agent"""
        decision = self._router.route(message, self._agents, context, preferred_agent)
        if decision.target_agent:
            decision.target_agent.last_active = time.time()
        return decision.target_agent

    def route_with_decision(self, message: str, context: Dict = None, preferred_agent: str = '') -> RouteDecision:
        """路由消息并返回完整决策 (包含备选方案)"""
        decision = self._router.route(message, self._agents, context, preferred_agent)
        if decision.target_agent:
            decision.target_agent.last_active = time.time()
        return decision

    def broadcast(self, message: str, exclude: List[str] = None, message_type: str = 'notify', priority: MessagePriority = MessagePriority.NORMAL) -> int:
        """广播消息到所有 agent"""
        exclude = set(exclude or [])
        sent = 0
        for aid in list(self._agents.keys()):
            if aid in exclude:
                continue
            m = _Msg(from_agent="system", to_agent=aid, content=message,
                     message_type=message_type, priority=priority)
            if self._bus.send(m):
                sent += 1
        return sent

    def send_agent_message(self, from_agent: str, to_agent: str, content: str, message_type: str = 'text', priority: MessagePriority = MessagePriority.NORMAL, context: Dict = None) -> bool:
        """Agent 间直接消息"""
        if to_agent not in self._agents:
            return False
        m = _Msg(from_agent=from_agent, to_agent=to_agent, content=content,
                 message_type=message_type, priority=priority, context=context)
        return self._bus.send(m)

    def get_agent_messages(self, agent_id: str, limit: int = 10, **kw) -> List[_Msg]:
        return self._bus.receive(agent_id, limit=limit)

    def aggregate_results(self, results: List[AgentResult], **kw) -> Dict:
        """聚合多个 agent 的结果"""
        if not results:
            return {"count": 0, "status": "empty"}
        success = [r for r in results if r.status == "success"]
        return {
            "count": len(results),
            "success_count": len(success),
            "status": "success" if len(success) == len(results) else "partial",
            "avg_confidence": round(sum(r.confidence for r in results) / len(results), 4) if results else 0,
            "results": [r.to_dict() for r in results],
        }

    def get_orchestrator_status(self, **kw) -> Dict:
        return {
            "started": self._started,
            "agent_count": len(self._agents),
            "agents": [a.to_dict() for a in self._agents.values()],
            "bus": self._bus.get_bus_stats(),
            "contexts": self._context.get_all_context_stats(),
            "router": self._router.get_routing_stats(),
        }

    def get_agent_status(self, agent_id: str, **kw) -> Optional[Dict]:
        a = self._agents.get(agent_id)
        if not a:
            return None
        d = a.to_dict()
        d["inbox_size"] = self._bus.get_inbox_size(agent_id)
        d["context"] = self._context.get_context(agent_id)
        return d

    def add_context(self, agent_id: str, message: Dict, **kw):
        self._context.add_message(agent_id, message, max_size=kw.get("max_size", 50))

    def get_context(self, agent_id: str, **kw) -> List[Dict]:
        return self._context.get_context(agent_id)

    def clear_agent_context(self, agent_id: str, **kw):
        self._context.clear_context(agent_id)

    def form_collaboration(self, task: str, agents: List[str], strategy: str = 'sequential') -> Dict:
        """组建 agent 协作组共同完成任务"""
        valid = [a for a in agents if a in self._agents]
        if not valid:
            return {"ok": False, "reason": "no valid agents"}
        collab_id = str(uuid.uuid4())[:12]
        entry = {
            "collab_id": collab_id, "task": task, "agents": valid,
            "strategy": strategy, "created_at": time.time(), "status": "formed",
        }
        self._collaborations[collab_id] = entry
        return {"ok": True, **entry}

    def spawn_agent(self, name: str, role: str = '通用助手', capabilities: list = None, metadata: dict = None):
        return self.register_agent(name, role, capabilities=capabilities, metadata=metadata)

    def dispatch_task(self, task: str, target_agent: str = '', strategy: str = 'round_robin'):
        """派发任务。target_agent 指定则直发; 否则按策略选择。"""
        task_id = str(uuid.uuid4())[:12]
        if target_agent and target_agent in self._agents:
            target = target_agent
        elif strategy == "round_robin":
            agents = sorted(self._agents.keys())
            if not agents:
                return {"ok": False, "task_id": task_id, "reason": "no agents"}
            idx = int(time.time()) % len(agents)
            target = agents[idx]
        else:
            decision = self._router.route(task, self._agents)
            target = decision.target_agent.agent_id if decision.target_agent else ""
            if not target:
                return {"ok": False, "task_id": task_id, "reason": "no suitable agent"}
        self._tasks[task_id] = {
            "task_id": task_id, "task": task, "target_agent": target,
            "status": "dispatched", "created_at": time.time(), "result": None,
        }
        self._agents[target].total_handled += 1
        return {"ok": True, "task_id": task_id, "target_agent": target}

    def collect_result(self, task_id: str, agent_id: str, content: str, status: str = 'success'):
        task = self._tasks.get(task_id)
        if not task:
            return {"ok": False, "reason": "unknown task"}
        task["status"] = status
        task["result"] = content
        task["completed_at"] = time.time()
        r = AgentResult(agent_id=agent_id, content=content, status=status)
        self._results[task_id] = r
        return {"ok": True, "task_id": task_id}

    def get_task_result(self, task_id: str, **kw):
        task = self._tasks.get(task_id)
        if not task:
            return None
        out = dict(task)
        out["result_obj"] = self._results.get(task_id)
        return out

    def get_cluster_status(self, **kw):
        return {
            "agents": len(self._agents),
            "online": sum(1 for a in self._agents.values() if a.status != AgentStatus.OFFLINE),
            "tasks": len(self._tasks),
            "tasks_done": sum(1 for t in self._tasks.values() if t["status"] == "success"),
            "collaborations": len(self._collaborations),
            "started": self._started,
        }


class MultiAgentPlugin:
    """meshctx Plugin 适配器"""
    info = "info"
    state = 'inactive'

    def __init__(self, **kw):
        self.name = "multi_agent"
        self.version = "3.50"
        self.description = "Multi-Agent Orchestrator"
        self._orch: Optional[MultiAgentOrchestrator] = None
        self.state = 'inactive'

    async def on_load(self, kernel) -> bool:
        try:
            self._orch = get_multi_agent()
            if kernel and hasattr(kernel, "plugins") and not kernel.plugins.get("multi_agent"):
                kernel.plugins.register(self)
            self.state = 'active'
            return True
        except Exception as e:
            logger.warning(f"multi_agent plugin on_load failed: {e}")
            return False

    async def on_unload(self, kernel) -> bool:
        if self._orch:
            try:
                await self._orch.stop()
            except Exception:
                pass
        self.state = 'inactive'
        return True

    def generate_report(self, **kw) -> Dict:
        if self._orch:
            return self._orch.get_orchestrator_status()
        return {"state": self.state, "agents": 0}


_orch_instance: Optional[MultiAgentOrchestrator] = None
_orch_lock = threading.Lock()


def get_multi_agent() -> MultiAgentOrchestrator:
    """获取 MultiAgentOrchestrator 全局实例，自动创建"""
    global _orch_instance
    with _orch_lock:
        if _orch_instance is None:
            _orch_instance = MultiAgentOrchestrator()
        return _orch_instance


def init_multi_agent(max_agents: int = 20, default_timeout: float = 300.0) -> MultiAgentOrchestrator:
    """初始化 MultiAgentOrchestrator 全局单例"""
    global _orch_instance
    with _orch_lock:
        _orch_instance = MultiAgentOrchestrator(max_agents=max_agents, default_timeout=default_timeout)
        return _orch_instance


class MessageType:
    """v1.6 Message type enum (compat)"""
    BROADCAST = 'broadcast'
    UNICAST = 'unicast'
    MULTICAST = 'multicast'
    RESPONSE = 'response'
    ERROR = 'error'


@dataclass
class AgentCapability:
    """v1.6 Agent capability descriptor"""
    name: str = None
    description: str = ''
    inputs: List[str] = None
    outputs: List[str] = None


@dataclass
class AgentMessage:
    """v1.6 Agent message — unified with v3.50 fields for internal compat"""
    sender_id: str = ''
    target_id: str = ''
    topic: str = ''
    payload: Any = None
    msg_id: str = ''
    msg_type: str = None
    timestamp: float = None
    ttl: float = 60.0

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = str(uuid.uuid4())[:12]
        if self.msg_type is None:
            self.msg_type = MessageType.BROADCAST
        if self.timestamp is None:
            self.timestamp = time.time()

    def is_expired(self) -> bool:
        return (time.time() - (self.timestamp or 0)) > (self.ttl or 60)


class AgentNode:
    """v1.6 Agent node — async-capable agent with capabilities"""
    MAX_TASKS = 2

    def __init__(self, agent_id: str, name: str, capabilities: List[AgentCapability] = None):
        self.agent_id = agent_id
        self.name = name
        self.capabilities = list(capabilities) if capabilities else []
        self.status = "idle"
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._task_count = 0
        self.processed_messages = 0
        self._running = False
        self._bus: Optional['MessageBus'] = None  # register 时绑定

    def can_accept_tasks(self) -> bool:
        return self._task_count < self.MAX_TASKS

    def get_info(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "capabilities": [c.name for c in self.capabilities],
            "task_count": self._task_count,
            "processed_messages": self.processed_messages,
        }

    def _resolve_bus(self):
        """优先使用注册时绑定的 bus, 否则回退全局 _default_bus (兼容旧行为)。"""
        if self._bus is not None:
            return self._bus
        from src.core.multi_agent import _default_bus
        return _default_bus

    async def send(self, target_id: str, topic: str, payload: Any = None):
        """发送消息给目标 agent (通过注册时的 bus 或全局 bus)"""
        bus = self._resolve_bus()
        if bus is None:
            return False
        msg = AgentMessage(sender_id=self.agent_id, target_id=target_id, topic=topic, payload=payload)
        return await bus.send(msg)

    async def broadcast(self, topic: str, payload: Any = None):
        bus = self._resolve_bus()
        if bus is None:
            return False
        sent = 0
        for aid in list(bus._agents.keys()):
            if aid == self.agent_id:
                continue
            msg = AgentMessage(sender_id=self.agent_id, target_id=aid, topic=topic, payload=payload)
            if await bus.send(msg):
                sent += 1
        return sent > 0

    async def start(self):
        self._running = True
        self.status = "idle"
        return True

    async def stop(self):
        self._running = False
        self.status = "idle"
        return True


_default_bus: Optional['MessageBus'] = None


class MessageBus:
    """v1.6 Message bus — async agent messaging"""
    def __init__(self):
        self._agents: Dict[str, AgentNode] = {}
        self._stats = {"sent": 0, "delivered": 0, "failed": 0}

    def register(self, agent: AgentNode):
        self._agents[agent.agent_id] = agent
        agent._bus = self  # 绑定 agent 到本 bus

    def unregister(self, agent_id: str):
        self._agents.pop(agent_id, None)

    def get_agent(self, agent_id: str):
        return self._agents.get(agent_id)

    async def send(self, msg: AgentMessage) -> bool:
        self._stats["sent"] += 1
        return await self._deliver(msg)

    async def _deliver(self, msg: AgentMessage) -> bool:
        target = self._agents.get(msg.target_id)
        if target is None:
            self._stats["failed"] += 1
            return False
        try:
            await target._message_queue.put(msg)
            target.processed_messages += 1
            self._stats["delivered"] += 1
            return True
        except Exception:
            self._stats["failed"] += 1
            return False

    def find_agents_by_capability(self, cap_name: str) -> List[AgentNode]:
        return [a for a in self._agents.values()
                if any(c.name == cap_name for c in a.capabilities)]

    def find_idle_agent(self, cap_name: str):
        for a in self.find_agents_by_capability(cap_name):
            if a.can_accept_tasks():
                return a
        return None

    def get_stats(self) -> Dict:
        topics: Dict[str, int] = {}
        for a in self._agents.values():
            for c in a.capabilities:
                topics[c.name] = topics.get(c.name, 0) + 1
        return {
            "total_agents": len(self._agents),
            "sent": self._stats["sent"],
            "delivered": self._stats["delivered"],
            "failed": self._stats["failed"],
            "topics": topics,
        }


class CollaborationProtocol:
    """v1.6 Collaboration protocol — delegate tasks to idle agents"""
    def __init__(self, bus: MessageBus):
        self.bus = bus

    async def delegate(self, agent: AgentNode, capability: str, task: Dict) -> Optional[AgentNode]:
        target = self.bus.find_idle_agent(capability)
        if target is None:
            return None
        msg = AgentMessage(sender_id=agent.agent_id, target_id=target.agent_id,
                           topic=capability, payload=task)
        if not await self.bus.send(msg):
            return None
        target._task_count += 1
        return target


class AgentManager:
    """v1.6 Agent manager — create and manage agents"""
    def __init__(self):
        self._agents: Dict[str, AgentNode] = {}
        self._bus = MessageBus()

    def create_agent(self, agent_id: str, name: str, capabilities: List[AgentCapability] = None) -> AgentNode:
        agent = AgentNode(agent_id, name, capabilities)
        self._agents[agent_id] = agent
        self._bus.register(agent)
        return agent

    def get_summary(self) -> Dict:
        stats = self._bus.get_stats()
        return {
            "agent_count": len(self._agents),
            "agents": {aid: a.get_info() for aid, a in self._agents.items()},
            "bus": stats,
        }


__all__ = ["AgentStatus", "MessagePriority", "AgentHandle", "AgentResult", "RouteDecision",
           "IntentRouter", "_Bus", "ContextManager", "MultiAgentOrchestrator",
           "MultiAgentPlugin", "get_multi_agent", "init_multi_agent",
           "MessageType", "AgentCapability", "AgentMessage", "AgentNode",
           "MessageBus", "CollaborationProtocol", "AgentManager"]


# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "AgentFactory":
        return getattr(__import__("src.core.agent_factory", fromlist=["AgentFactory"]), "AgentFactory", None)
    if name == "get_manager":
        return get_multi_agent
    if name == "get_executor":
        return get_multi_agent
    raise AttributeError(name)
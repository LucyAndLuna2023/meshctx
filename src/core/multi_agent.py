"""
meshctx Multi-Agent Orchestrator v3.50 — 多专家Agent协调系统
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
  3. MessageBus — Agent 间异步消息传递
  4. ContextManager — 每个 agent 独立的上下文窗口
  5. ResultAggregator — 多 agent 并行处理结果聚合
  6. MultiAgentOrchestrator — 顶层编排器

使用示例:
  orch = get_multi_agent()
  
  # 注册专家
  orch.register_agent("code_expert", "代码专家", ["python", "debugging", "refactor"])
  orch.register_agent("security_expert", "安全专家", ["audit", "vulnerability", "pentest"])
  
  # 路由消息
  handle = orch.route_message("帮我审查这段代码的安全性", context={})
  # → 路由到 security_expert
  
  # 广播
  results = orch.broadcast("系统启动完成，各Agent就位")
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.multi_agent")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

class AgentStatus(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"
    ERROR = "error"
    DRAINING = "draining"     # 不再接收新任务, 等待当前任务完成


class MessagePriority(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class AgentHandle:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Agent 句柄 — 指向注册的 specialist agent"""
    agent_id: str
    name: str = ""
    role: str = ""                         # 专长领域描述
    tools: List[str] = field(default_factory=list)  # 可用工具列表
    capabilities: List[str] = field(default_factory=list)  # 能力标签
    status: AgentStatus = AgentStatus.IDLE
    registered_at: float = field(default_factory=time.time)
    last_active: float = 0.0
    total_handled: int = 0
    total_errors: int = 0
    avg_response_ms: float = 0.0
    context_size: int = 0                  # 当前上下文消息数
    max_context_size: int = 50             # 上下文窗口上限
    metadata: Dict = field(default_factory=dict)  # 扩展元数据

    def to_dict(self, **kw) -> Dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "tools": self.tools,
            "capabilities": self.capabilities,
            "status": self.status.value,
            "registered_at": self.registered_at,
            "last_active": self.last_active,
            "total_handled": self.total_handled,
            "total_errors": self.total_errors,
            "avg_response_ms": self.avg_response_ms,
            "context_size": self.context_size,
            "max_context_size": self.max_context_size,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict, **kw) -> "AgentHandle":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class AgentMessage:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Agent 间传递的消息"""
    message_id: str = ""
    from_agent: str = ""                  # 发送者 agent_id
    to_agent: str = ""                     # 接收者 agent_id (空=广播)
    content: str = ""
    message_type: str = "text"             # text / task / result / query / notify
    priority: MessagePriority = MessagePriority.NORMAL
    context: Dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    ttl: int = 300                         # 消息存活秒数 (0=永久)

    def is_expired(self, **kw) -> bool:
        if self.ttl <= 0:
            return False
        return (time.time() - self.created_at) > self.ttl


@dataclass
class AgentResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Agent 处理结果"""
    agent_id: str
    message_id: str = ""
    content: str = ""
    status: str = "success"               # success / error / timeout / declined
    confidence: float = 1.0               # 0-1 置信度
    duration_ms: float = 0.0
    metadata: Dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self, **kw) -> Dict:
        return {
            "agent_id": self.agent_id,
            "message_id": self.message_id,
            "content": self.content,
            "status": self.status,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class RouteDecision:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """路由决策结果"""
    target_agent: Optional[AgentHandle] = None
    confidence: float = 0.0
    reasoning: str = ""
    alternatives: List[Tuple[AgentHandle, float]] = field(default_factory=list)
    rule_matched: str = ""                 # 匹配的路由规则


# ═══════════════════════════════════════════════════════════
# IntentRouter — 意图路由引擎
# ═══════════════════════════════════════════════════════════

class IntentRouter:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """
    意图路由器 — 根据消息内容和上下文决定路由到哪个 specialist

    路由策略 (优先级从高到低):
      1. 显式指令: "@agent_name" 直接指定
      2. 关键词匹配: 消息中的关键词 → 能力标签
      3. 语义路由: 简单的语义相关性评分
      4. 默认路由: 回退到通用 agent 或第一个 idle agent
    """

    # 领域关键词 → 能力映射
    DOMAIN_KEYWORDS: Dict[str, List[str]] = {
        "code": [
            "代码", "编程", "python", "javascript", "函数", "类", "bug", "debug",
            "重构", "refactor", "算法", "algorithm", "code", "programming",
            "编译", "compile", "测试", "test", "lint", "type hint", "类型",
        ],
        "security": [
            "安全", "漏洞", "审计", "渗透", "加密", "security", "vulnerability",
            "audit", "pentest", "crypto", "密钥", "secret", "注入", "injection",
            "xss", "csrf", "sql injection", "认证", "authorization",
        ],
        "data": [
            "数据", "数据库", "sql", "查询", "分析", "data", "database",
            "query", "etl", "pandas", "dataframe", "统计", "statistics",
            "可视化", "visualization", "图表", "chart",
        ],
        "devops": [
            "部署", "deploy", "docker", "kubernetes", "k8s", "ci/cd",
            "服务器", "server", "nginx", "配置", "config", "监控", "monitor",
            "日志", "log", "pipeline", "构建", "build",
        ],
        "writing": [
            "写", "文档", "文档", "documentation", "readme", "报告", "report",
            "摘要", "summary", "翻译", "translate", "文章", "article",
            "博客", "blog", "邮件", "email",
        ],
        "research": [
            "研究", "调研", "分析", "research", "调查", "比较", "compare",
            "论文", "paper", "文献", "literature", "综述", "review",
        ],
        "design": [
            "设计", "UI", "UX", "界面", "design", "架构", "architecture",
            "模式", "pattern", "系统设计", "system design", "前端", "frontend",
        ],
    }

    # 工具 → 能力映射
    TOOL_CAPABILITY: Dict[str, str] = {
        "python": "code",
        "bash": "code",
        "firecrawl": "research",
        "browser": "research",
        "image_gen": "design",
        "git": "devops",
        "docker": "devops",
        "sql": "data",
    }

    def __init__(self, **kw):
        # 路由规则 (用户可配置)
        self.rules: List[Dict] = []
        # 路由历史, 用于学习
        self._route_history: deque = deque(maxlen=500)
        # 统计
        self._stats = {
            "total_routes": 0,
            "explicit_routes": 0,     # @agent_name
            "keyword_routes": 0,      # 关键词匹配
            "semantic_routes": 0,     # 语义路由
            "default_routes": 0,      # 回退路由
        }

    def route(
        self,
        message: str,
        agents: Dict[str, AgentHandle],
        context: Dict = None,
        preferred_agent: str = "",
    ) -> RouteDecision:
        """
        路由消息到最合适的 agent

        Args:
            message: 用户消息
            agents: 可用 agent 注册表 {agent_id: AgentHandle}
            context: 对话上下文
            preferred_agent: 优先指定的 agent_id

        Returns:
            RouteDecision 包含目标 agent + 置信度
        """
        self._stats["total_routes"] += 1
        idle_agents = {
            aid: a for aid, a in agents.items()
            if a.status == AgentStatus.IDLE
        }
        available_agents = idle_agents if idle_agents else agents

        if not available_agents:
            return RouteDecision(
                reasoning="没有可用 agent",
                confidence=0.0,
            )

        # 策略1: 显式指令 @agent_name
        if preferred_agent and preferred_agent in agents:
            self._stats["explicit_routes"] += 1
            return RouteDecision(
                target_agent=agents[preferred_agent],
                confidence=1.0,
                reasoning=f"显式指定: @{preferred_agent}",
                rule_matched="explicit",
            )

        # 检查消息中的 @mention
        import re
        mention_pattern = re.compile(r'@(\w+)')
        mentions = mention_pattern.findall(message)
        for mention in mentions:
            for aid, agent in available_agents.items():
                if (mention.lower() == agent.name.lower() or
                        mention.lower() == aid.lower()):
                    self._stats["explicit_routes"] += 1
                    return RouteDecision(
                        target_agent=agent,
                        confidence=1.0,
                        reasoning=f"@mention 匹配: @{mention}",
                        rule_matched="mention",
                    )

        # 策略2: 自定义路由规则
        for rule in self.rules:
            pattern = rule.get("pattern", "")
            target = rule.get("target", "")
            if pattern and target:
                try:
                    if re.search(pattern, message, re.IGNORECASE):
                        if target in available_agents:
                            self._stats["keyword_routes"] += 1
                            return RouteDecision(
                                target_agent=available_agents[target],
                                confidence=rule.get("confidence", 0.9),
                                reasoning=f"规则匹配: {rule.get('name', pattern)}",
                                rule_matched=f"rule:{rule.get('name', '')}",
                            )
                except re.error:
                    pass

        # 策略3: 关键词 → 能力标签匹配
        message_lower = message.lower()
        domain_scores: Dict[str, float] = defaultdict(float)

        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw.lower() in message_lower:
                    # 更长的关键词匹配权重更高
                    score += len(kw) * 0.5
            if score > 0:
                domain_scores[domain] = score

        # 策略4: 工具名称匹配
        for tool, domain in self.TOOL_CAPABILITY.items():
            if tool.lower() in message_lower:
                domain_scores[domain] += 3.0

        # 按领域分数排序 agent
        if domain_scores:
            agent_scores = []
            for aid, agent in available_agents.items():
                score = 0.0
                agent_domains = set(agent.capabilities)
                for domain, ds in domain_scores.items():
                    if domain in agent_domains:
                        score += ds
                if score > 0:
                    agent_scores.append((agent, score))

            if agent_scores:
                agent_scores.sort(key=lambda x: -x[1])
                top_agent, top_score = agent_scores[0]
                confidence = min(0.95, top_score / 15.0)  # 归一化到 0-0.95

                alternatives = [
                    (a, min(0.8, s / 15.0))
                    for a, s in agent_scores[1:4]
                ]

                self._stats["keyword_routes"] += 1
                top_keywords = sorted(domain_scores, key=domain_scores.get, reverse=True)[:3]
                return RouteDecision(
                    target_agent=top_agent,
                    confidence=confidence,
                    reasoning=f"关键词匹配领域: {', '.join(top_keywords)}",
                    alternatives=alternatives,
                    rule_matched="keyword",
                )

        # 策略5: 语义路由 — 简单 Jaccard 相似度
        best_agent = None
        best_score = 0.0
        message_words = set(message_lower.split())

        for aid, agent in available_agents.items():
            # 构建 agent 的关键词集合
            agent_text = f"{agent.name} {agent.role} {' '.join(agent.capabilities)} {' '.join(agent.tools)}"
            agent_words = set(agent_text.lower().split())

            if not message_words or not agent_words:
                continue

            intersection = message_words & agent_words
            union = message_words | agent_words
            jaccard = len(intersection) / len(union) if union else 0

            if jaccard > best_score:
                best_score = jaccard
                best_agent = agent

        if best_agent and best_score > 0.02:
            self._stats["semantic_routes"] += 1
            return RouteDecision(
                target_agent=best_agent,
                confidence=min(0.8, best_score * 20),
                reasoning=f"语义相似度: {best_score:.4f}",
                rule_matched="semantic",
            )

        # 策略6: 默认路由 — 第一个 idle agent 或通用 agent
        self._stats["default_routes"] += 1

        # 优先选 "general" 或 "default" agent
        for aid, agent in available_agents.items():
            if "general" in agent.capabilities or "default" in agent.capabilities:
                return RouteDecision(
                    target_agent=agent,
                    confidence=0.3,
                    reasoning="默认路由: 通用 agent",
                    rule_matched="default_general",
                )

        # 回退到第一个可用 agent
        default_agent = next(iter(available_agents.values()))
        return RouteDecision(
            target_agent=default_agent,
            confidence=0.1,
            reasoning="默认路由: 第一个可用 agent",
            rule_matched="default_first",
        )

    def add_rule(self, name: str, pattern: str, target: str,
                 confidence: float = 0.9):
        """添加自定义路由规则"""
        self.rules.append({
            "name": name,
            "pattern": pattern,
            "target": target,
            "confidence": confidence,
        })
        logger.info(f"Added routing rule: {name} → {target}")

    def remove_rule(self, name: str, **kw) -> bool:
        """删除路由规则"""
        for i, rule in enumerate(self.rules):
            if rule["name"] == name:
                self.rules.pop(i)
                return True
        return False

    def get_routing_stats(self, **kw) -> Dict:
        return dict(self._stats)


# ═══════════════════════════════════════════════════════════
# MessageBus — Agent 间消息总线
# ═══════════════════════════════════════════════════════════

class MessageBus:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """
    Agent 间异步消息总线

    特征:
      - 点对点消息 (to_agent 指定)
      - 广播消息 (to_agent 为空)
      - 消息队列 (每个 agent 独立的 inbox)
      - TTL 过期机制
    """

    def __init__(self, max_queue_size: int = 100, **kw):
        self.max_queue_size = max_queue_size
        # 每个 agent 的消息队列
        self._inboxes: Dict[str, deque] = defaultdict(deque)
        # 消息历史
        self._message_history: deque = deque(maxlen=1000)
        # 统计
        self._stats = {
            "total_sent": 0,
            "total_delivered": 0,
            "total_expired": 0,
            "total_dropped": 0,
        }

    def send(self, message: AgentMessage, **kw) -> bool:
        """
        发送消息到指定 agent 的 inbox

        Args:
            message: 要发送的消息

        Returns:
            是否成功入队
        """
        if not message.to_agent:
            # 广播: 发送到所有 agent
            return self._broadcast(message)

        self._stats["total_sent"] += 1

        inbox = self._inboxes[message.to_agent]
        if len(inbox) >= self.max_queue_size:
            # 队列满 → 丢弃最旧的消息
            inbox.popleft()
            self._stats["total_dropped"] += 1
            logger.warning(f"Inbox full for {message.to_agent}, dropped oldest message")

        inbox.append(message)
        self._message_history.append(message)
        self._stats["total_delivered"] += 1

        logger.debug(f"Message {message.message_id}: {message.from_agent} → {message.to_agent} [{message.priority.value}]")
        return True

    def _broadcast(self, message: AgentMessage, **kw) -> bool:
        """广播消息到所有 agent"""
        sent_count = 0
        for agent_id in list(self._inboxes.keys()):
            broadcast_msg = AgentMessage(
                message_id=message.message_id,
                from_agent=message.from_agent,
                to_agent=agent_id,
                content=message.content,
                message_type=message.message_type,
                priority=message.priority,
                context=message.context,
                created_at=message.created_at,
                ttl=message.ttl,
            )
            inbox = self._inboxes[agent_id]
            if len(inbox) >= self.max_queue_size:
                inbox.popleft()
            inbox.append(broadcast_msg)
            sent_count += 1

        self._message_history.append(message)
        self._stats["total_sent"] += sent_count
        self._stats["total_delivered"] += sent_count
        return sent_count > 0

    def receive(self, agent_id: str, limit: int = 10, **kw) -> List[AgentMessage]:
        """
        从 agent 的 inbox 接收消息

        Args:
            agent_id: Agent ID
            limit: 最大返回数量

        Returns:
            消息列表 (按时间排序)
        """
        inbox = self._inboxes.get(agent_id)
        if not inbox:
            return []

        messages = []
        expired_count = 0

        # 收集非过期消息
        while inbox and len(messages) < limit:
            msg = inbox.popleft()
            if msg.is_expired():
                expired_count += 1
                continue
            messages.append(msg)

        self._stats["total_expired"] += expired_count
        return messages

    def peek(self, agent_id: str, limit: int = 10, **kw) -> List[AgentMessage]:
        """查看 inbox 但不消费消息"""
        inbox = self._inboxes.get(agent_id)
        if not inbox:
            return []
        return [
            msg for msg in list(inbox)[:limit]
            if not msg.is_expired()
        ]

    def get_inbox_size(self, agent_id: str, **kw) -> int:
        """获取 inbox 大小"""
        inbox = self._inboxes.get(agent_id)
        return len(inbox) if inbox else 0

    def clear_inbox(self, agent_id: str, **kw):
        """清空 agent 的 inbox"""
        if agent_id in self._inboxes:
            self._inboxes[agent_id].clear()

    def remove_agent(self, agent_id: str, **kw):
        """移除 agent 的消息队列"""
        self._inboxes.pop(agent_id, None)

    def get_bus_stats(self, **kw) -> Dict:
        return {
            "total_sent": self._stats["total_sent"],
            "total_delivered": self._stats["total_delivered"],
            "total_expired": self._stats["total_expired"],
            "total_dropped": self._stats["total_dropped"],
            "active_inboxes": len(self._inboxes),
            "total_pending": sum(len(q) for q in self._inboxes.values()),
            "history_size": len(self._message_history),
        }


# ═══════════════════════════════════════════════════════════
# ContextManager — 上下文隔离
# ═══════════════════════════════════════════════════════════

class ContextManager:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """
    Agent 上下文管理器 — 每个 agent 独立上下文窗口

    功能:
      - 上下文隔离: 每个 agent 维护独立的消息历史
      - 窗口管理: 自动裁剪超出 max_context_size 的旧消息
      - 上下文摘要: 当消息被裁剪时，生成摘要保留关键信息
    """

    def __init__(self, **kw):
        # {agent_id: [messages]}
        self._contexts: Dict[str, List[Dict]] = defaultdict(list)
        # 上下文摘要
        self._summaries: Dict[str, str] = {}

    def add_message(self, agent_id: str, message: Dict,
                    max_size: int = 50):
        """
        向 agent 上下文添加消息

        Args:
            agent_id: Agent ID
            message: 消息 dict (含 role, content 等)
            max_size: 上下文窗口上限
        """
        context = self._contexts[agent_id]
        context.append(message)

        # 如果超过窗口大小, 裁剪旧消息并生成摘要
        if len(context) > max_size:
            evicted = context[:len(context) - max_size]
            self._contexts[agent_id] = context[-max_size:]

            # 生成摘要
            if evicted:
                summary = self._summaries.get(agent_id, "")
                new_summary = self._summarize(evicted)
                self._summaries[agent_id] = (
                    f"{summary}\n{new_summary}" if summary else new_summary
                )[-1000:]  # 摘要上限 1000 字符

    def get_context(self, agent_id: str, **kw) -> List[Dict]:
        """获取 agent 的完整上下文"""
        return self._contexts.get(agent_id, [])

    def get_summary(self, agent_id: str, **kw) -> str:
        """获取 agent 上下文摘要"""
        return self._summaries.get(agent_id, "")

    def get_full_context(self, agent_id: str, **kw) -> Dict:
        """
        获取 agent 完整上下文 (当前消息 + 摘要)

        Returns:
            {"messages": [...], "summary": "...", "message_count": N}
        """
        context = self._contexts.get(agent_id, [])
        return {
            "messages": context,
            "summary": self._summaries.get(agent_id, ""),
            "message_count": len(context),
        }

    def clear_context(self, agent_id: str, **kw):
        """清空 agent 上下文"""
        self._contexts.pop(agent_id, None)
        self._summaries.pop(agent_id, None)

    def _summarize(self, messages: List[Dict], **kw) -> str:
        """从被裁剪的消息中提取摘要"""
        if not messages:
            return ""

        # 简单摘要: 提取每条消息的前60字符
        parts = []
        for msg in messages:
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))[:80]
            if content:
                parts.append(f"[{role}] {content}")

        return " | ".join(parts[-5:])  # 只保留最近5条

    def get_all_context_stats(self, **kw) -> Dict:
        """获取所有 agent 的上下文统计"""
        return {
            aid: {
                "messages": len(ctx),
                "has_summary": bool(self._summaries.get(aid)),
                "summary_length": len(self._summaries.get(aid, "")),
            }
            for aid, ctx in self._contexts.items()
        }


# ═══════════════════════════════════════════════════════════
# MultiAgentOrchestrator — 顶层编排器
# ═══════════════════════════════════════════════════════════

class MultiAgentOrchestrator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """
    多 Agent 编排器

    职责:
      - 管理 specialist agent 注册/注销
      - 智能路由消息到正确的 specialist
      - 协调 agent 间通信
      - 管理上下文隔离
      - 聚合多 agent 并行处理结果
    """

    def __init__(self, max_agents: int = 20, default_timeout: float = 300.0, **kw):
        self.max_agents = max_agents
        self.default_timeout = default_timeout

        # Agent 注册表
        self._agents: Dict[str, AgentHandle] = {}

        # 子模块
        self.router = IntentRouter()
        self.message_bus = MessageBus()
        self.context_manager = ContextManager()

        # 处理回调: 当消息被路由到 agent 时调用
        # callback(agent_id, message, context) → AgentResult
        self._handlers: Dict[str, Callable] = {}

        # 统计
        self._stats = {
            "total_messages_routed": 0,
            "total_broadcasts": 0,
            "total_errors": 0,
            "started_at": time.time(),
        }

        # 后台任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        # v3.51: task dispatch tracking
        self._task_results: Dict[str, AgentResult] = {}
        self._task_counter: int = 0
        self._round_robin_index: int = 0

        logger.info(f"MultiAgentOrchestrator initialized: max_agents={max_agents}")

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self):
        """启动编排器"""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("MultiAgentOrchestrator started")

    async def stop(self):
        """停止编排器"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("MultiAgentOrchestrator stopped")

    async def _cleanup_loop(self):
        """后台清理循环 — 清理过期消息"""
        while self._running:
            await asyncio.sleep(60)
            # 清理过期消息
            for agent_id in list(self._agents.keys()):
                inbox_size = self.message_bus.get_inbox_size(agent_id)
                if inbox_size > 0:
                    # receive 会自动跳过过期消息
                    self.message_bus.receive(agent_id, limit=inbox_size)

    # ── Agent 注册 ────────────────────────────────────────

    def register_agent(
        self,
        name: str,
        role: str,
        tools: List[str] = None,
        capabilities: List[str] = None,
        metadata: Dict = None,
        agent_id: str = "",
    ) -> AgentHandle:
        """
        注册一个 specialist agent

        Args:
            name: Agent 名称
            role: 专长领域描述
            tools: 可用工具列表
            capabilities: 能力标签
            metadata: 扩展元数据
            agent_id: 指定 ID (空=自动生成)

        Returns:
            AgentHandle

        Raises:
            ValueError: 超出最大 agent 数量
        """
        if not agent_id:
            agent_id = f"agent-{name.lower().replace(' ', '_')}"

        if len(self._agents) >= self.max_agents and agent_id not in self._agents:
            raise ValueError(
                f"Max agents ({self.max_agents}) reached. "
                f"Unregister some agents first."
            )

        handle = AgentHandle(
            agent_id=agent_id,
            name=name,
            role=role,
            tools=tools or [],
            capabilities=capabilities or [],
            metadata=metadata or {},
        )
        self._agents[agent_id] = handle

        # 初始化 inbox
        self.message_bus._inboxes.setdefault(agent_id, deque())

        logger.info(f"Agent registered: {agent_id} ({name}) — {role}")
        return handle

    def unregister_agent(self, agent_id: str, **kw) -> bool:
        """
        注销 agent

        Args:
            agent_id: Agent ID

        Returns:
            是否成功
        """
        if agent_id not in self._agents:
            return False

        # 清理上下文
        self.context_manager.clear_context(agent_id)
        # 清理消息队列
        self.message_bus.remove_agent(agent_id)
        # 清理 handler
        self._handlers.pop(agent_id, None)
        # 移除注册
        del self._agents[agent_id]

        logger.info(f"Agent unregistered: {agent_id}")
        return True

    def get_agent(self, agent_id: str, **kw) -> Optional[AgentHandle]:
        """获取 agent 句柄"""
        return self._agents.get(agent_id)

    def list_agents(self, status: AgentStatus = None, **kw) -> List[AgentHandle]:
        """列出所有 agent"""
        agents = list(self._agents.values())
        if status:
            agents = [a for a in agents if a.status == status]
        return agents

    def set_agent_status(self, agent_id: str, status: AgentStatus, **kw):
        """设置 agent 状态"""
        if agent_id in self._agents:
            self._agents[agent_id].status = status
            if status == AgentStatus.IDLE:
                self._agents[agent_id].last_active = time.time()

    def register_handler(
        self, agent_id: str,
        handler: Callable[[str, Dict], Any]
    ):
        """
        注册 agent 的消息处理回调

        Args:
            agent_id: Agent ID
            handler: async 回调 (agent_id, message_dict) → result
        """
        self._handlers[agent_id] = handler
        logger.debug(f"Handler registered for {agent_id}")

    # ── 消息路由 ──────────────────────────────────────────

    def route_message(
        self,
        message: str,
        context: Dict = None,
        preferred_agent: str = "",
    ) -> Optional[AgentHandle]:
        """
        路由消息到最合适的 specialist agent

        Args:
            message: 用户消息
            context: 对话上下文
            preferred_agent: 优先指定的 agent_id

        Returns:
            路由目标 AgentHandle 或 None
        """
        self._stats["total_messages_routed"] += 1

        decision = self.router.route(
            message=message,
            agents=self._agents,
            context=context,
            preferred_agent=preferred_agent,
        )

        if decision.target_agent:
            logger.info(
                f"Route: '{message[:60]}' → {decision.target_agent.name} "
                f"(confidence={decision.confidence:.2f}, "
                f"reason={decision.rule_matched})"
            )

            # 添加到目标 agent 的上下文
            self.context_manager.add_message(
                decision.target_agent.agent_id,
                {
                    "role": "user",
                    "content": message,
                    "context": context or {},
                    "routed_by": decision.rule_matched,
                    "routing_confidence": decision.confidence,
                    "timestamp": time.time(),
                },
                max_size=decision.target_agent.max_context_size,
            )

        return decision.target_agent

    def route_with_decision(
        self,
        message: str,
        context: Dict = None,
        preferred_agent: str = "",
    ) -> RouteDecision:
        """
        路由消息并返回完整决策 (包含备选方案)

        Args:
            message: 用户消息
            context: 对话上下文
            preferred_agent: 优先指定的 agent_id

        Returns:
            RouteDecision
        """
        self._stats["total_messages_routed"] += 1

        decision = self.router.route(
            message=message,
            agents=self._agents,
            context=context,
            preferred_agent=preferred_agent,
        )

        if decision.target_agent:
            # 添加上下文
            self.context_manager.add_message(
                decision.target_agent.agent_id,
                {
                    "role": "user",
                    "content": message,
                    "context": context or {},
                    "routed_by": decision.rule_matched,
                    "routing_confidence": decision.confidence,
                    "timestamp": time.time(),
                },
                max_size=decision.target_agent.max_context_size,
            )

        return decision

    # ── 广播 ──────────────────────────────────────────────

    def broadcast(
        self,
        message: str,
        exclude: List[str] = None,
        message_type: str = "notify",
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> int:
        """
        广播消息到所有 agent

        Args:
            message: 消息内容
            exclude: 排除的 agent_id 列表
            message_type: 消息类型
            priority: 优先级

        Returns:
            发送目标数
        """
        self._stats["total_broadcasts"] += 1
        exclude = exclude or []

        msg = AgentMessage(
            message_id=str(uuid.uuid4())[:12],
            from_agent="orchestrator",
            content=message,
            message_type=message_type,
            priority=priority,
        )

        # 发送到所有 agent (除了排除列表)
        targets = [aid for aid in self._agents if aid not in exclude]

        for agent_id in targets:
            msg.to_agent = agent_id
            self.message_bus.send(msg)

        logger.info(f"Broadcast: '{message[:60]}' → {len(targets)} agents")
        return len(targets)

    # ── Agent 间通信 ──────────────────────────────────────

    def send_agent_message(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: str = "text",
        priority: MessagePriority = MessagePriority.NORMAL,
        context: Dict = None,
    ) -> bool:
        """
        Agent 间直接消息

        Args:
            from_agent: 发送者 agent_id
            to_agent: 接收者 agent_id
            content: 消息内容
            message_type: 消息类型
            priority: 优先级
            context: 附加上下文

        Returns:
            是否发送成功
        """
        if from_agent not in self._agents:
            logger.warning(f"Sending agent not found: {from_agent}")
            return False
        if to_agent not in self._agents:
            logger.warning(f"Receiving agent not found: {to_agent}")
            return False

        msg = AgentMessage(
            message_id=str(uuid.uuid4())[:12],
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            message_type=message_type,
            priority=priority,
            context=context or {},
        )

        return self.message_bus.send(msg)

    def get_agent_messages(self, agent_id: str, limit: int = 10, **kw) -> List[AgentMessage]:
        """获取 agent 的待处理消息"""
        return self.message_bus.receive(agent_id, limit=limit)

    # ── 结果聚合 ──────────────────────────────────────────

    def aggregate_results(self, results: List[AgentResult], **kw) -> Dict:
        """
        聚合多个 agent 的结果

        Args:
            results: Agent 结果列表

        Returns:
            聚合结果 dict
        """
        if not results:
            return {"status": "empty", "content": "", "results": []}

        success_results = [r for r in results if r.status == "success"]
        error_results = [r for r in results if r.status == "error"]
        declined_results = [r for r in results if r.status == "declined"]

        # 按置信度排序
        success_results.sort(key=lambda r: -r.confidence)

        # 合并内容
        combined_parts = []
        for r in success_results:
            combined_parts.append(
                f"## {r.agent_id} (confidence={r.confidence:.2f})\n{r.content}"
            )

        # 计算整体置信度
        avg_confidence = (
            sum(r.confidence for r in success_results) / max(len(success_results), 1)
        ) if success_results else 0.0

        return {
            "status": "success" if success_results else ("error" if error_results else "declined"),
            "content": "\n\n".join(combined_parts),
            "results": [r.to_dict() for r in results],
            "summary": {
                "total": len(results),
                "success": len(success_results),
                "error": len(error_results),
                "declined": len(declined_results),
                "avg_confidence": round(avg_confidence, 3),
                "total_duration_ms": round(sum(r.duration_ms for r in results), 1),
            },
        }

    # ── 状态/统计 ─────────────────────────────────────────

    def get_orchestrator_status(self, **kw) -> Dict:
        """获取编排器完整状态"""
        agent_summary = []
        for agent in self._agents.values():
            agent_summary.append({
                "agent_id": agent.agent_id,
                "name": agent.name,
                "status": agent.status.value,
                "total_handled": agent.total_handled,
                "context_size": agent.context_size,
                "capabilities": agent.capabilities,
            })

        return {
            "orchestrator": {
                "running": self._running,
                "uptime_seconds": round(time.time() - self._stats["started_at"], 1),
                "total_agents": len(self._agents),
                "max_agents": self.max_agents,
                "total_messages_routed": self._stats["total_messages_routed"],
                "total_broadcasts": self._stats["total_broadcasts"],
                "total_errors": self._stats["total_errors"],
            },
            "agents": agent_summary,
            "router": self.router.get_routing_stats(),
            "message_bus": self.message_bus.get_bus_stats(),
            "contexts": self.context_manager.get_all_context_stats(),
        }

    def get_agent_status(self, agent_id: str, **kw) -> Optional[Dict]:
        """获取单个 agent 的详细状态"""
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        return {
            **agent.to_dict(),
            "context": self.context_manager.get_full_context(agent_id),
            "inbox_size": self.message_bus.get_inbox_size(agent_id),
        }

    # ── 上下文管理 ────────────────────────────────────────

    def add_context(self, agent_id: str, message: Dict, **kw):
        """向 agent 添加上下文消息"""
        agent = self._agents.get(agent_id)
        max_size = agent.max_context_size if agent else 50
        self.context_manager.add_message(agent_id, message, max_size)

    def get_context(self, agent_id: str, **kw) -> List[Dict]:
        """获取 agent 上下文"""
        return self.context_manager.get_context(agent_id)

    def clear_agent_context(self, agent_id: str, **kw):
        """清空 agent 上下文"""
        self.context_manager.clear_context(agent_id)

    # ── 快捷协作 ──────────────────────────────────────────

    def form_collaboration(
        self,
        task: str,
        agents: List[str],
        strategy: str = "sequential",
    ) -> Dict:
        """
        组建 agent 协作组共同完成任务

        Args:
            task: 任务描述
            agents: 参与的 agent_id 列表
            strategy: 协作策略
                - "sequential": 流水线模式 (A→B→C)
                - "parallel": 并行模式 (所有 agent 同时处理)
                - "review": 审查模式 (A 处理 → B 审查)

        Returns:
            协作配置 dict
        """
        valid_agents = []
        for aid in agents:
            if aid in self._agents:
                valid_agents.append(aid)
            else:
                logger.warning(f"Agent not found for collaboration: {aid}")

        if not valid_agents:
            return {"status": "error", "reason": "No valid agents"}

        collaboration_id = str(uuid.uuid4())[:8]

        # 通知协作组
        for aid in valid_agents:
            self.message_bus.send(AgentMessage(
                message_id=f"collab-{collaboration_id}",
                from_agent="orchestrator",
                to_agent=aid,
                content=f"[协作任务] {task}",
                message_type="task",
                priority=MessagePriority.HIGH,
                context={
                    "collaboration_id": collaboration_id,
                    "strategy": strategy,
                    "team": valid_agents,
                },
            ))

        logger.info(
            f"Collaboration '{collaboration_id}' formed: "
            f"{len(valid_agents)} agents, strategy={strategy}"
        )

        return {
            "collaboration_id": collaboration_id,
            "agents": valid_agents,
            "strategy": strategy,
            "task": task,
            "status": "formed",
        }

    # ── Spawn / Dispatch / Cluster (v3.51) ──────────────────

    def spawn_agent(
        self,
        name: str,
        role: str = "通用助手",
        capabilities: list = None,
        metadata: dict = None,
    ):
        agent_id = f"worker-{name.lower().replace(' ', '_')}-{uuid.uuid4().hex[:6]}"
        return self.register_agent(
            name=name,
            role=role,
            capabilities=capabilities or ["general"],
            metadata=metadata or {},
            agent_id=agent_id,
        )

    def dispatch_task(
        self,
        task: str,
        target_agent: str = "",
        strategy: str = "round_robin",
    ):
        task_id = f"task-{self._task_counter:04d}"
        self._task_counter += 1
        assigned = []

        if strategy == "broadcast":
            for aid, agent in self._agents.items():
                if agent.status in (AgentStatus.IDLE, AgentStatus.BUSY):
                    self.message_bus.send(AgentMessage(
                        message_id=task_id,
                        from_agent="orchestrator",
                        to_agent=aid,
                        content=task,
                        message_type="task",
                        priority=MessagePriority.NORMAL,
                        context={"task_id": task_id, "strategy": strategy},
                    ))
                    assigned.append(aid)
        elif target_agent and target_agent in self._agents:
            self.message_bus.send(AgentMessage(
                message_id=task_id,
                from_agent="orchestrator",
                to_agent=target_agent,
                content=task,
                message_type="task",
                priority=MessagePriority.HIGH,
                context={"task_id": task_id, "strategy": "direct"},
            ))
            assigned.append(target_agent)
        else:
            idle_agents = [
                aid for aid, a in self._agents.items()
                if a.status == AgentStatus.IDLE
            ]
            if not idle_agents:
                idle_agents = list(self._agents.keys())
            if not idle_agents:
                return {"task_id": task_id, "error": "No agents available", "assigned_to": []}

            if strategy == "least_loaded":
                target = min(idle_agents, key=lambda aid: self._agents[aid].context_size)
            else:
                self._round_robin_index = self._round_robin_index % len(idle_agents)
                target = idle_agents[self._round_robin_index]
                self._round_robin_index += 1

            self.message_bus.send(AgentMessage(
                message_id=task_id,
                from_agent="orchestrator",
                to_agent=target,
                content=task,
                message_type="task",
                priority=MessagePriority.NORMAL,
                context={"task_id": task_id, "strategy": strategy},
            ))
            assigned.append(target)
            if target in self._agents:
                self._agents[target].status = AgentStatus.BUSY

        logger.info(f"Dispatch {task_id}: '{task[:50]}' -> {assigned} (strategy={strategy})")
        return {
            "task_id": task_id,
            "assigned_to": assigned,
            "strategy": strategy,
            "task": task,
        }

    def collect_result(self, task_id: str, agent_id: str, content: str,
                       status: str = "success"):
        agent = self._agents.get(agent_id)
        if agent:
            agent.status = AgentStatus.IDLE
            agent.total_handled += 1
            agent.last_active = time.time()
        result = AgentResult(
            agent_id=agent_id,
            message_id=task_id,
            content=content,
            status=status,
        )
        self._task_results[task_id] = result
        logger.info(f"Result collected: {task_id} <- {agent_id}: {status}")
        return result

    def get_task_result(self, task_id: str, **kw):
        return self._task_results.get(task_id)

    def get_cluster_status(self, **kw):
        base = self.get_orchestrator_status()
        base["tasks"] = {
            "total_dispatched": self._task_counter,
            "results_collected": len(self._task_results),
            "pending_tasks": self._task_counter - len(self._task_results),
        }
        for a in base.get("agents", []):
            a["inbox_size"] = self.message_bus.get_inbox_size(a["agent_id"])
        return base


# ═══════════════════════════════════════════════════════════
# Plugin 适配
# ═══════════════════════════════════════════════════════════

class MultiAgentPlugin:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """meshctx Plugin 适配器"""
    info = type('Info', (), {
        'name': 'multi_agent',
        'version': '3.50',
        'dependencies': [],
        'category': 'infrastructure',
        'description': '多Agent编排系统 — 意图路由 + Agent间通信 + 上下文隔离 + 结果聚合',
    })()
    state = "inactive"

    def __init__(self, **kw):
        self.orchestrator: Optional[MultiAgentOrchestrator] = None

    async def on_load(self, kernel) -> bool:
        try:
            self.orchestrator = MultiAgentOrchestrator()
            await self.orchestrator.start()
            kernel.multi_agent = self.orchestrator
            self.state = "active"
            # 注册全局实例
            global _orchestrator
            _orchestrator = self.orchestrator
            logger.info("MultiAgentPlugin activated")
            return True
        except Exception as e:
            logger.error(f"MultiAgentPlugin load failed: {e}")
            return False

    async def on_unload(self, kernel) -> bool:
        if self.orchestrator:
            await self.orchestrator.stop()
        self.state = "inactive"
        return True

    def generate_report(self, **kw) -> Dict:
        if self.orchestrator:
            return self.orchestrator.get_orchestrator_status()
        return {"status": "not_initialized"}


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_orchestrator: Optional[MultiAgentOrchestrator] = None


def get_multi_agent() -> MultiAgentOrchestrator:
    """获取 MultiAgentOrchestrator 全局实例，自动创建"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()
    return _orchestrator


def init_multi_agent(
    max_agents: int = 20,
    default_timeout: float = 300.0,
) -> MultiAgentOrchestrator:
    """
    初始化 MultiAgentOrchestrator 全局单例

    Args:
        max_agents: 最大 agent 数量
        default_timeout: 默认超时 (秒)

    Returns:
        MultiAgentOrchestrator 实例
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator(
            max_agents=max_agents,
            default_timeout=default_timeout,
        )
    return _orchestrator

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)


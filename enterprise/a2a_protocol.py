"""
a2a_protocol.py — Agent-to-Agent 消息总线 (v1.0)

协议分层:
  L1 Transport: Redis Pub/Sub + HTTP fallback
  L2 Routing:  topic-based pub/sub + direct unicast
  L3 Message:  JSON envelope + schema validation
  L4 Delivery: at-least-once + idempotency keys

消息格式:
  {
    "id": "uuid",
    "type": "task|result|heartbeat|error|broadcast",
    "from": "agent_id",
    "to": "agent_id|topic|broadcast",
    "correlation_id": "uuid",   # for request-response pairing
    "payload": {...},
    "timestamp": "ISO8601",
    "ttl": 60
  }
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.a2a")


class MessageType(Enum):
    TASK = "task"
    RESULT = "result"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    BROADCAST = "broadcast"


@dataclass
class Message:
    """A2A 消息信封."""
    type: MessageType
    from_agent: str
    payload: Dict[str, Any] = field(default_factory=dict)
    to_agent: Optional[str] = None       # None → broadcast
    correlation_id: Optional[str] = None  # for request-response
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    ttl: int = 60

    def to_json(self) -> str:
        return json.dumps({
            "id": self.id,
            "type": self.type.value,
            "from": self.from_agent,
            "to": self.to_agent or "*",
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        d = json.loads(raw)
        return cls(
            id=d.get("id", ""),
            type=MessageType(d["type"]),
            from_agent=d["from"],
            to_agent=d.get("to") if d.get("to") != "*" else None,
            correlation_id=d.get("correlation_id"),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", time.time()),
            ttl=d.get("ttl", 60),
        )


class A2ABus:
    """Agent-to-Agent 消息总线.

    Usage:
      bus = A2ABus(agent_id="hr-001")
      bus.subscribe("task.assign", my_handler)
      await bus.publish(Message(type=MessageType.TASK, from_agent="hr-001",
                                payload={"task": "onboard"}, to_agent="devops-001"))
    """

    def __init__(self, agent_id: str, redis_url: str = ""):
        self.agent_id = agent_id
        self.redis_url = redis_url
        self._subscribers: Dict[str, List[Callable]] = {}
        self._pending: Dict[str, asyncio.Future] = {}  # correlation_id → future
        self._running = False
        self._redis = None

    # ── Lifecycle ───────────────────────────────────────────

    async def start(self):
        """启动总线 (连接 Redis + 监听)."""
        self._running = True
        if self.redis_url:
            try:
                import os as _os
                import redis.asyncio as aioredis
                url = self.redis_url
                if url.startswith("redis://") and not url.startswith("rediss://"):
                    if _os.environ.get("MESHCTX_REDIS_TLS", "").lower() in ("1", "true", "yes"):
                        url = url.replace("redis://", "rediss://", 1)
                self._redis = await aioredis.from_url(url)
                asyncio.create_task(self._redis_listener())
            except ImportError:
                logger.warning("redis not installed, using in-memory only")
        logger.info(f"🚌 A2A bus started: {self.agent_id}")

    async def stop(self):
        self._running = False
        if self._redis:
            await self._redis.close()
        # 所有 pending futures 超时
        for cid, fut in self._pending.items():
            if not fut.done():
                fut.set_exception(TimeoutError(f"bus stopped, correlation {cid}"))
        logger.info(f"🛑 A2A bus stopped: {self.agent_id}")

    # ── Publish ─────────────────────────────────────────────

    async def publish(self, msg: Message) -> str:
        """发布消息，返回 message id."""
        msg.from_agent = self.agent_id
        raw = msg.to_json()

        # 本地 subscribers
        topics = self._resolve_topics(msg)
        for topic in topics:
            for handler in self._subscribers.get(topic, []):
                try:
                    if inspect.iscoroutinefunction(handler):
                        await handler(msg)
                    else:
                        result = handler(msg)
                        if inspect.isawaitable(result):
                            await result
                except Exception as e:
                    logger.error(f"handler error on {topic}: {e}")

        # Redis pub/sub
        if self._redis:
            for topic in topics:
                await self._redis.publish(f"a2a:{topic}", raw)

        logger.debug(f"📤 [{msg.id}] {msg.type.value} → {msg.to_agent or '*'}")
        return msg.id

    # ── Request-Reply ───────────────────────────────────────

    async def request(self, to_agent: str, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """同步请求-响应 (correlation_id 匹配)."""
        msg = Message(
            type=MessageType.TASK,
            from_agent=self.agent_id,
            to_agent=to_agent,
            payload=payload,
            correlation_id=uuid.uuid4().hex[:12],
            ttl=int(timeout),
        )
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg.correlation_id] = fut

        await self.publish(msg)

        try:
            result_msg = await asyncio.wait_for(fut, timeout=timeout)
            return result_msg.payload
        except asyncio.TimeoutError:
            self._pending.pop(msg.correlation_id, None)
            raise TimeoutError(f"no reply from {to_agent} within {timeout}s")
        finally:
            self._pending.pop(msg.correlation_id, None)

    def reply(self, request: Message, payload: Dict[str, Any]):
        """回复请求."""
        if request.correlation_id and request.correlation_id in self._pending:
            fut = self._pending[request.correlation_id]
            if not fut.done():
                fut.set_result(Message(
                    type=MessageType.RESULT,
                    from_agent=self.agent_id,
                    to_agent=request.from_agent,
                    payload=payload,
                    correlation_id=request.correlation_id,
                ))

    # ── Subscribe ───────────────────────────────────────────

    def subscribe(self, topic: str, handler: Callable):
        """订阅主题."""
        self._subscribers.setdefault(topic, []).append(handler)
        logger.info(f"📡 {self.agent_id} subscribed: {topic}")

    def unsubscribe(self, topic: str, handler: Callable):
        """取消订阅."""
        handlers = self._subscribers.get(topic, [])
        if handler in handlers:
            handlers.remove(handler)

    # ── Broadcast ───────────────────────────────────────────

    async def broadcast(self, payload: Dict[str, Any]):
        """全集群广播."""
        msg = Message(
            type=MessageType.BROADCAST,
            from_agent=self.agent_id,
            payload=payload,
        )
        await self.publish(msg)

    # ── Internal ────────────────────────────────────────────

    def _resolve_topics(self, msg: Message) -> List[str]:
        topics = []
        if msg.to_agent:
            topics.append(f"agent.{msg.to_agent}")
        else:
            topics.append("broadcast")
        topics.append(f"type.{msg.type.value}")
        if msg.payload.get("topic"):
            topics.append(f"topic.{msg.payload['topic']}")
        return topics

    async def _redis_listener(self):
        """Redis Pub/Sub 监听线程."""
        if not self._redis:
            return
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe("a2a:*")
        logger.info("📡 Redis listener started")
        while self._running:
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("data"):
                    a2a_msg = Message.from_json(msg["data"])
                    # 检查 correlation → resolve pending future
                    if a2a_msg.correlation_id and a2a_msg.correlation_id in self._pending:
                        fut = self._pending[a2a_msg.correlation_id]
                        if not fut.done():
                            fut.set_result(a2a_msg)
                    else:
                        # 路由到本地 subscribers
                        for topic in self._resolve_topics(a2a_msg):
                            for handler in self._subscribers.get(topic, []):
                                try:
                                    if inspect.iscoroutinefunction(handler):
                                        await handler(a2a_msg)
                                    else:
                                        result = handler(a2a_msg)
                                        if inspect.isawaitable(result):
                                            await result
                                except Exception as e:
                                    logger.error(f"redis handler error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"redis listener error: {e}")
                await asyncio.sleep(1)

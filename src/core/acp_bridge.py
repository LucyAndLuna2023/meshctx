"""ACP Bridge — Agent Communication Protocol bridge (v3.115+)

Implements ACP (Agent Communication Protocol) for inter-agent messaging.
Supports JSON serialization, session handshake, message routing, and
tool_call/tool_result/error/session events.

Zero pip dependencies — Python stdlib only.
"""
__all__ = ['logger', 'ACPMessageType', 'ACPMessage', 'ACPError', 'MessageHandler', 'ACPRouter', 'ACPBridge', 'get_acp_bridge', 'reset_acp_bridge']


import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Message types ─────────────────────────────────────────────────────

class ACPMessageType(str, Enum):
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    SESSION_INIT = "session_init"
    SESSION_CLOSE = "session_close"
    HEARTBEAT = "heartbeat"
    BROADCAST = "broadcast"


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class ACPMessage:
    """A single ACP message."""
    type: ACPMessageType
    session_id: str = ""
    msg_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type if isinstance(self.type, str) else self.type.value,
            "session_id": self.session_id,
            "msg_id": self.msg_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ACPMessage":
        msg_type = d.get("type", "tool_call")
        if isinstance(msg_type, str):
            try:
                msg_type = ACPMessageType(msg_type)
            except ValueError:
                msg_type = ACPMessageType.TOOL_CALL
        return cls(
            type=msg_type,
            session_id=d.get("session_id", ""),
            msg_id=d.get("msg_id", ""),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class ACPError:
    """Structured ACP error."""
    code: str = "UNKNOWN"
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# ── Message handlers ──────────────────────────────────────────────────

MessageHandler = Callable[[ACPMessage], Optional[ACPMessage]]


class ACPRouter:
    """Routes incoming ACP messages to registered handlers by type."""

    def __init__(self):
        self._handlers: Dict[ACPMessageType, List[MessageHandler]] = {}
        self._default_handler: Optional[MessageHandler] = None
        self._lock = threading.RLock()

    def register(self, msg_type: ACPMessageType, handler: MessageHandler):
        """Register a handler for a message type."""
        with self._lock:
            self._handlers.setdefault(msg_type, []).append(handler)

    def set_default(self, handler: MessageHandler):
        """Set fallback handler for unregistered types."""
        self._default_handler = handler

    def route(self, msg: ACPMessage) -> List[ACPMessage]:
        """Route a message to handlers, return any responses."""
        responses = []
        with self._lock:
            handlers = self._handlers.get(msg.type, [])
            for h in handlers:
                try:
                    resp = h(msg)
                    if resp:
                        responses.append(resp)
                except Exception as e:
                    logger.error("ACP handler error: %s", e)

            if not handlers and self._default_handler:
                try:
                    resp = self._default_handler(msg)
                    if resp:
                        responses.append(resp)
                except Exception as e:
                    logger.error("ACP default handler error: %s", e)

        return responses


# ── ACP Bridge ────────────────────────────────────────────────────────

class ACPBridge:
    """ACP communication bridge — serialize/deserialize, send/recv, handshake.

    Uses in-process queues for local communication. Can be extended with
    socket/HTTP transports.
    """

    def __init__(self, agent_id: str = "", max_queue: int = 256):
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self._inbox: queue.Queue = queue.Queue(maxsize=max_queue)
        self._outbox: queue.Queue = queue.Queue(maxsize=max_queue)
        self._router = ACPRouter()
        self._sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> info
        self._lock = threading.RLock()
        self._running = False

    # -- Serialization --

    @staticmethod
    def serialize(msg: ACPMessage) -> str:
        """Serialize an ACPMessage to JSON string."""
        return json.dumps(msg.to_dict(), ensure_ascii=False)

    @staticmethod
    def deserialize(raw: str) -> ACPMessage:
        """Deserialize JSON string to ACPMessage."""
        return ACPMessage.from_dict(json.loads(raw))

    # -- Send / Recv --

    def send(self, msg: ACPMessage, timeout: float = 5.0) -> bool:
        """Send a message to the outbox queue."""
        if not msg.msg_id:
            msg.msg_id = uuid.uuid4().hex[:12]
        if not msg.timestamp:
            msg.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            self._outbox.put(msg, timeout=timeout)
            return True
        except queue.Full:
            logger.warning("ACP outbox full, message dropped: %s", msg.msg_id)
            return False

    def recv(self, timeout: float = 5.0) -> Optional[ACPMessage]:
        """Receive a message from the inbox queue."""
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def receive_all(self, max_messages: int = 100) -> List[ACPMessage]:
        """Drain all pending inbox messages."""
        messages = []
        for _ in range(max_messages):
            msg = self.recv(timeout=0.1)
            if msg is None:
                break
            messages.append(msg)
        return messages

    # -- Handshake --

    def handshake(self, client_info: Dict[str, Any]) -> Dict[str, Any]:
        """Perform ACP handshake, return session info.

        Args:
          client_info: dict with client_id, capabilities, version, etc.
        """
        session_id = uuid.uuid4().hex[:16]
        session = {
            "session_id": session_id,
            "client_id": client_info.get("client_id", "unknown"),
            "capabilities": client_info.get("capabilities", []),
            "version": client_info.get("version", "0.1"),
            "created_at": time.time(),
            "last_seen": time.time(),
        }
        with self._lock:
            self._sessions[session_id] = session

        # Send session_init acknowledgment
        ack = ACPMessage(
            type=ACPMessageType.SESSION_INIT,
            session_id=session_id,
            payload={"status": "connected", "agent_id": self.agent_id, **session},
        )
        self.send(ack)

        logger.info("ACP handshake: session=%s client=%s", session_id,
                    client_info.get("client_id"))
        return session

    def close_session(self, session_id: str):
        """Close a session."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

        close_msg = ACPMessage(
            type=ACPMessageType.SESSION_CLOSE,
            session_id=session_id,
            payload={"status": "closed"},
        )
        self.send(close_msg)

    # -- Tool call helpers --

    def call_tool(self, session_id: str, tool_name: str,
                  tool_args: Dict[str, Any]) -> str:
        """Send a tool_call message and return msg_id."""
        msg = ACPMessage(
            type=ACPMessageType.TOOL_CALL,
            session_id=session_id,
            payload={"tool": tool_name, "args": tool_args},
        )
        self.send(msg)
        return msg.msg_id

    def return_result(self, session_id: str, msg_id: str,
                      result: Any, error: str = None):
        """Send a tool_result (or error) message."""
        payload = {"result": result, "msg_id": msg_id}
        if error:
            payload["error"] = error
        msg = ACPMessage(
            type=ACPMessageType.ERROR if error else ACPMessageType.TOOL_RESULT,
            session_id=session_id,
            payload=payload,
        )
        self.send(msg)

    # -- Router access --

    @property
    def router(self) -> ACPRouter:
        return self._router

    # -- Lifecycle --

    def start(self):
        self._running = True
        logger.info("ACP Bridge started: %s", self.agent_id)

    def stop(self):
        self._running = False
        # Close all sessions
        with self._lock:
            sids = list(self._sessions.keys())
        for sid in sids:
            self.close_session(sid)
        logger.info("ACP Bridge stopped: %s", self.agent_id)

    def stats(self) -> dict:
        with self._lock:
            return {
                "agent_id": self.agent_id,
                "running": self._running,
                "inbox_size": self._inbox.qsize(),
                "outbox_size": self._outbox.qsize(),
                "active_sessions": len(self._sessions),
                "sessions": list(self._sessions.keys()),
            }


# ── Global bridge instance ───────────────────────────────────────────

_bridge: Optional[ACPBridge] = None
_bridge_lock = threading.Lock()


def get_acp_bridge(agent_id: str = "") -> ACPBridge:
    """Get or create the global ACP bridge singleton."""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = ACPBridge(agent_id=agent_id)
        return _bridge


def reset_acp_bridge():
    """Reset the global bridge (for testing)."""
    global _bridge
    with _bridge_lock:
        if _bridge:
            _bridge.stop()
        _bridge = None


# ── _P universal proxy (backward compat) ──────────────────────────────


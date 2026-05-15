"""
MeshCtx Agent Self-Monitor — Real-time Agent Metrics
======================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.
"""
import time
import threading
from typing import Dict, List, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class AgentMetrics:
    """Real-time agent metrics."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_chat_messages: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0
    sandbox_executions: int = 0
    web_searches: int = 0
    file_reads: int = 0
    windows_commands: int = 0
    brain_cycles: int = 0
    memory_items: int = 0
    uptime_seconds: float = 0
    start_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class AgentMonitor:
    """Thread-safe agent activity monitor."""

    def __init__(self):
        self._metrics = AgentMetrics()
        self._lock = threading.Lock()

    def record_chat(self, tokens: int = 0, latency_ms: float = 0):
        with self._lock:
            self._metrics.total_chat_messages += 1
            self._metrics.total_tokens += tokens
            if latency_ms > 0:
                n = self._metrics.total_chat_messages
                self._metrics.avg_latency_ms = (
                    self._metrics.avg_latency_ms * (n - 1) + latency_ms
                ) / n
            self._metrics.last_activity = time.time()

    def record_task(self, success: bool = True):
        with self._lock:
            if success:
                self._metrics.tasks_completed += 1
            else:
                self._metrics.tasks_failed += 1
            self._metrics.last_activity = time.time()

    def record_sandbox(self):
        with self._lock:
            self._metrics.sandbox_executions += 1
            self._metrics.last_activity = time.time()

    def record_search(self):
        with self._lock:
            self._metrics.web_searches += 1
            self._metrics.last_activity = time.time()

    def record_file_read(self):
        with self._lock:
            self._metrics.file_reads += 1
            self._metrics.last_activity = time.time()

    def record_windows(self):
        with self._lock:
            self._metrics.windows_commands += 1
            self._metrics.last_activity = time.time()

    def record_brain_cycle(self):
        with self._lock:
            self._metrics.brain_cycles += 1
            self._metrics.last_activity = time.time()

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            m = self._metrics
            return {
                "uptime_seconds": round(time.time() - m.start_time, 1),
                "tasks": {"completed": m.tasks_completed, "failed": m.tasks_failed},
                "chat": {"messages": m.total_chat_messages, "tokens": m.total_tokens,
                         "avg_latency_ms": round(m.avg_latency_ms, 1)},
                "tools": {
                    "sandbox": m.sandbox_executions,
                    "search": m.web_searches,
                    "file_reads": m.file_reads,
                    "windows": m.windows_commands,
                },
                "brain_cycles": m.brain_cycles,
                "memory_items": m.memory_items,
                "last_activity_ago": round(time.time() - m.last_activity, 1),
                "health": "healthy" if (time.time() - m.last_activity) < 300 else "idle",
            }


# Global singleton
_monitor = AgentMonitor()


def get_monitor() -> AgentMonitor:
    return _monitor

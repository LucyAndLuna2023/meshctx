"""Task Progress — task queue with priority, async processing, and singleton."""
from __future__ import annotations

import asyncio
import heapq
import time
import uuid
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(order=True)
class _Task:
    sort_key: Any = field(compare=True)
    id: str = field(compare=False)
    name: str = field(compare=False)
    priority: Priority = field(compare=False, default=Priority.NORMAL)
    created_at: float = field(compare=False, default_factory=time.time)


class TaskQueue:
    """Priority task queue with enqueue/dequeue/process."""

    def __init__(self):
        self._heap: List[_Task] = []
        self._counter = 0

    def enqueue(self, name: str, priority: Priority = Priority.NORMAL) -> str:
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        task = _Task(
            sort_key=(-priority.value, self._counter),
            id=task_id,
            name=name,
            priority=priority,
        )
        self._counter += 1
        heapq.heappush(self._heap, task)
        return task_id

    def dequeue(self) -> Optional[_Task]:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)

    async def process(self, handler: Callable, max_tasks: int = 100) -> List[Any]:
        results = []
        count = 0
        while self._heap and count < max_tasks:
            task = self.dequeue()
            if task is None:
                break
            result = handler(task)
            results.append(result)
            count += 1
            await asyncio.sleep(0)
        return results


_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue


class ProgressEngine:
    """任务进度引擎 — cli.py `meshctx tasks` 命令所需 (2026-08-25 004meshctx 审计补齐)。

    此前 _known 映射声明 get_progress_engine 但模块无此符号 → `meshctx tasks` 崩溃。
    基于真实 TaskQueue 实现, 提供 history/stats/list_active 等 CLI 契约。
    """
    def __init__(self, queue: Optional[TaskQueue] = None):
        self._queue = queue or get_task_queue()
        self._history: List[Dict[str, Any]] = []

    def submit(self, name: str, priority: Priority = Priority.NORMAL) -> str:
        task_id = self._queue.enqueue(name, priority)
        self._history.append({"id": task_id, "name": name, "status": "queued", "progress": 0})
        return task_id

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    def get_stats(self) -> Dict[str, Any]:
        active = sum(1 for h in self._history if h["status"] in ("queued", "running"))
        completed = sum(1 for h in self._history if h["status"] == "done")
        failed = sum(1 for h in self._history if h["status"] == "failed")
        return {"active": active, "completed": completed, "failed": failed}

    def list_active(self) -> List[Dict[str, Any]]:
        return [h for h in self._history if h["status"] in ("queued", "running")]

    def update(self, task_id: str, status: str = None, progress: int = None, result: Any = None):
        for h in self._history:
            if h["id"] == task_id:
                if status is not None:
                    h["status"] = status
                if progress is not None:
                    h["progress"] = progress
                if result is not None:
                    h["result"] = result
                return h
        return None


_engine: Optional[ProgressEngine] = None


def get_progress_engine() -> ProgressEngine:
    global _engine
    if _engine is None:
        _engine = ProgressEngine()
    return _engine

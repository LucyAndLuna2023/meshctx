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

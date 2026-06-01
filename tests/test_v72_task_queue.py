"""v3.72 Task Queue — tests"""
import pytest
from src.core.task_progress import TaskQueue, Priority, get_task_queue

def handler(task):
    return f"done:{task.name}"

class TestQueue:
    def test_enqueue(self):
        q = TaskQueue()
        tid = q.enqueue("test", priority=Priority.HIGH)
        assert tid.startswith("task-")

    def test_dequeue(self):
        q = TaskQueue()
        q.enqueue("a", priority=Priority.LOW)
        q.enqueue("b", priority=Priority.CRITICAL)
        t = q.dequeue()
        assert t is not None; assert t.priority == Priority.CRITICAL.value

    def test_process(self):
        q = TaskQueue()
        q.enqueue("x"); q.enqueue("y")
        import asyncio
        results = asyncio.run(q.process(handler, max_tasks=2))
        assert len(results) == 2

    def test_singleton(self):
        assert get_task_queue() is get_task_queue()

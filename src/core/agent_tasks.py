"""
meshctx agent_tasks — asynchronous task queue & scheduling for agent workflows.
Manages task CRUD, scheduling, dependencies, prioritization, and work stealing.

Key capabilities:
  - AgentTask: task dataclass with id, status, priority, dependencies
  - TaskQueue: priority queue with dependency resolution
  - TaskScheduler: interval/cron-based scheduling
  - TaskManager: main orchestrator combining queue + scheduler + executor
"""
from __future__ import annotations

import heapq
import pathlib
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

TASKS_DIR = pathlib.Path.home() / ".meshctx" / "tasks"
TASKS_DIR.mkdir(parents=True, exist_ok=True)


# ── Enums ──────────────────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"            # Waiting on dependencies


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass(order=True)
class AgentTask:
    """A task in the agent task queue."""
    # sortable fields (priority desc, created asc)
    _priority_val: int = field(default=1, compare=True)
    _created_at: float = field(default_factory=time.time, compare=True)

    # non-sortable fields
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12], compare=False)
    name: str = ""
    title: str = ""
    description: str = ""
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False)
    priority: TaskPriority = field(default=TaskPriority.NORMAL, compare=False)
    dependencies: List[str] = field(default_factory=list, compare=False)
    dependents: List[str] = field(default_factory=list, compare=False)
    payload: Any = field(default=None, compare=False)
    result: Any = field(default=None, compare=False)
    error: str = field(default="", compare=False)
    retries: int = 0
    max_retries: int = 3
    timeout: float = 300.0
    tags: List[str] = field(default_factory=list, compare=False)
    updated_at: float = field(default_factory=time.time, compare=False)

    def __post_init__(self):
        if self.title and not self.name:
            self.name = self.title
        self._priority_val = -self.priority.value  # Negate for max-heap
        self._created_at = self._created_at or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "tags": self.tags,
            "error": self.error,
        }


# ── Task Queue ────────────────────────────────────────────────────────────

class TaskQueue:
    """Priority task queue with dependency resolution."""

    def __init__(self, max_size: int = 10000):
        self._heap: List[AgentTask] = []
        self._by_id: Dict[str, AgentTask] = {}
        self._lock = threading.Lock()
        self.max_size = max_size

    def push(self, task: AgentTask) -> bool:
        """Push a task onto the queue."""
        with self._lock:
            if len(self._heap) >= self.max_size:
                return False
            self._by_id[task.id] = task
            heapq.heappush(self._heap, task)
            return True

    def pop(self) -> Optional[AgentTask]:
        """Pop the highest-priority ready task."""
        with self._lock:
            ready = self._get_ready()
            if not ready:
                return None
            # Remove from heap (heapq doesn't support remove, so rebuild)
            task = ready[0]
            self._heap = [t for t in self._heap if t.id != task.id]
            heapq.heapify(self._heap)
            return task

    def peek(self) -> Optional[AgentTask]:
        """Peek at the highest-priority ready task without removing."""
        with self._lock:
            ready = self._get_ready()
            return ready[0] if ready else None

    def get(self, task_id: str) -> Optional[AgentTask]:
        """Get a task by ID."""
        with self._lock:
            return self._by_id.get(task_id)

    def remove(self, task_id: str) -> bool:
        """Remove a task by ID."""
        with self._lock:
            if task_id not in self._by_id:
                return False
            task = self._by_id.pop(task_id)
            self._heap = [t for t in self._heap if t.id != task_id]
            heapq.heapify(self._heap)
            # Unblock dependents
            for dep_id in task.dependents:
                dep = self._by_id.get(dep_id)
                if dep and dep.status == TaskStatus.BLOCKED:
                    dep.status = TaskStatus.PENDING
            return True

    def update(self, task_id: str, **kwargs) -> Optional[AgentTask]:
        """Update task fields."""
        with self._lock:
            task = self._by_id.get(task_id)
            if not task:
                return None
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            task.updated_at = time.time()
            if "priority" in kwargs:
                task._priority_val = -task.priority.value
            return task

    def size(self) -> int:
        return len(self._heap)

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def clear(self) -> None:
        with self._lock:
            self._heap.clear()
            self._by_id.clear()

    def list_by_status(self, status: TaskStatus) -> List[AgentTask]:
        """List tasks by status."""
        with self._lock:
            return [t for t in self._by_id.values() if t.status == status]

    def list_by_tag(self, tag: str) -> List[AgentTask]:
        """List tasks by tag."""
        with self._lock:
            return [t for t in self._by_id.values() if tag in t.tags]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            counts = defaultdict(int)
            for t in self._by_id.values():
                counts[t.status.value] += 1
            counts["total"] = len(self._by_id)
            return dict(counts)

    def _get_ready(self) -> List[AgentTask]:
        """Get tasks that are ready (no blocked dependencies)."""
        ready: List[AgentTask] = []
        for task in self._heap:
            if task.status == TaskStatus.BLOCKED:
                continue
            if task.status not in (TaskStatus.PENDING,):
                continue
            # Check dependencies
            blocked = False
            for dep_id in task.dependencies:
                dep = self._by_id.get(dep_id)
                if dep and dep.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                    blocked = True
                    break
            if not blocked:
                ready.append(task)
        return ready


# ── Task Scheduler ────────────────────────────────────────────────────────

class TaskScheduler:
    """Schedules recurring tasks at intervals or cron-like patterns."""

    @dataclass
    class ScheduledTask:
        task_id: str
        interval: float               # Seconds between runs
        next_run: float
        max_runs: int = -1            # -1 = unlimited
        run_count: int = 0
        fn: Callable = field(default=lambda: None)

    def __init__(self):
        self._tasks: Dict[str, TaskScheduler.ScheduledTask] = {}
        self._lock = threading.Lock()

    def schedule(
        self, task_id: str, interval: float, fn: Callable, max_runs: int = -1,
    ) -> None:
        """Schedule a recurring task."""
        with self._lock:
            self._tasks[task_id] = TaskScheduler.ScheduledTask(
                task_id=task_id,
                interval=interval,
                next_run=time.time() + interval,
                max_runs=max_runs,
                fn=fn,
            )

    def unschedule(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def get_due(self) -> List[TaskScheduler.ScheduledTask]:
        """Get all tasks due for execution."""
        now = time.time()
        due: List[TaskScheduler.ScheduledTask] = []
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if task.next_run <= now:
                    if task.max_runs < 0 or task.run_count < task.max_runs:
                        due.append(task)
                        task.run_count += 1
                        task.next_run = now + task.interval
                    else:
                        del self._tasks[task_id]
        return due

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "scheduled_count": len(self._tasks),
                "tasks": [
                    {"id": t.task_id, "interval": t.interval, "runs": t.run_count}
                    for t in self._tasks.values()
                ],
            }


# ── Task Executor ─────────────────────────────────────────────────────────

class TaskExecutor:
    """Executes tasks with retry logic and timeout."""

    def __init__(self, queue: TaskQueue, max_workers: int = 4):
        self.queue = queue
        self.max_workers = max_workers
        self._running: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._handlers: Dict[str, Callable] = {}
        self._results: Dict[str, Any] = {}
        self._shutdown = threading.Event()

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register a handler function for a task type (tag-based)."""
        self._handlers[task_type] = handler

    def execute(self, task: AgentTask) -> threading.Thread:
        """Execute a task in a background thread."""
        def _run():
            task.status = TaskStatus.RUNNING
            task.updated_at = time.time()

            for attempt in range(task.max_retries + 1):
                try:
                    # Find handler by matching tags
                    handler = None
                    for tag in task.tags:
                        if tag in self._handlers:
                            handler = self._handlers[tag]
                            break

                    if handler:
                        result = handler(task.payload)
                    else:
                        result = None  # No handler — just mark complete

                    task.result = result
                    task.status = TaskStatus.COMPLETED
                    self._results[task.id] = result
                    break

                except Exception as e:
                    task.error = str(e)
                    task.retries = attempt + 1
                    if attempt >= task.max_retries:
                        task.status = TaskStatus.FAILED
                    else:
                        time.sleep(0.5 * (attempt + 1))

            task.updated_at = time.time()
            # Unblock dependents
            for dep_id in task.dependents:
                dep = self.queue.get(dep_id)
                if dep and dep.status == TaskStatus.BLOCKED:
                    all_deps_done = all(
                        self.queue.get(d) and self.queue.get(d).status in (
                            TaskStatus.COMPLETED, TaskStatus.CANCELLED
                        )
                        for d in dep.dependencies
                    )
                    if all_deps_done:
                        dep.status = TaskStatus.PENDING

            with self._lock:
                self._running.pop(task.id, None)

        t = threading.Thread(target=_run, daemon=True)
        with self._lock:
            self._running[task.id] = t
        t.start()
        return t

    def get_result(self, task_id: str) -> Optional[Any]:
        return self._results.get(task_id)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self.queue.get(task_id)
            if task and task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.CANCELLED
                task.updated_at = time.time()
                return True
            return False

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": len(self._running),
                "max_workers": self.max_workers,
                "handlers": list(self._handlers.keys()),
                "completed": len(self._results),
            }


# ── Main Task Manager ─────────────────────────────────────────────────────

class TaskManager:
    """Main orchestrator for agent task management.

    Combines queue, scheduler, and executor into a unified task system.
    """

    def __init__(self, max_workers: int = 4):
        self.queue = TaskQueue()
        self.scheduler = TaskScheduler()
        self.executor = TaskExecutor(self.queue, max_workers=max_workers)
        self._tick_thread: Optional[threading.Thread] = None
        self._tick_interval = 1.0
        self._shutdown = threading.Event()

    # ── Task CRUD ─────────────────────────────────────────────────────

    def create_task(
        self, name: str, description: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        dependencies: List[str] = None, tags: List[str] = None,
        payload: Any = None,
    ) -> AgentTask:
        """Create and enqueue a new task."""
        task = AgentTask(
            name=name,
            description=description,
            priority=priority,
            dependencies=dependencies or [],
            tags=tags or [],
            payload=payload,
        )

        # Check if blocked by dependencies
        for dep_id in task.dependencies:
            dep = self.queue.get(dep_id)
            if dep and dep.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                task.status = TaskStatus.BLOCKED
                # Register as dependent
                dep.dependents.append(task.id)
                break

        self.queue.push(task)
        return task

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self.queue.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        task = self.queue.get(task_id)
        if not task:
            return False
        if task.status == TaskStatus.RUNNING:
            self.executor.cancel(task_id)
        if task.status in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            return self.queue.update(task_id, status=TaskStatus.CANCELLED)
        return False

    def remove_task(self, task_id: str) -> bool:
        return self.queue.remove(task_id)

    # ── Scheduling ────────────────────────────────────────────────────

    def schedule_recurring(
        self, name: str, interval: float, handler: Callable,
        payload: Any = None, max_runs: int = -1,
    ) -> str:
        """Schedule a recurring task with a handler."""
        task = self.create_task(name=name, tags=["recurring"], payload=payload)
        self.executor.register_handler("recurring", handler)
        self.scheduler.schedule(task.id, interval, handler, max_runs=max_runs)
        return task.id

    # ── Execution ─────────────────────────────────────────────────────

    def register_handler(self, task_type: str, handler: Callable) -> None:
        self.executor.register_handler(task_type, handler)

    def execute_next(self) -> Optional[AgentTask]:
        """Execute the next ready task."""
        task = self.queue.pop()
        if task:
            self.executor.execute(task)
        return task

    def execute_all(self) -> int:
        """Execute all ready tasks."""
        count = 0
        while True:
            task = self.execute_next()
            if not task:
                break
            count += 1
        return count

    def get_result(self, task_id: str) -> Optional[Any]:
        return self.executor.get_result(task_id)

    # ── Background Tick ───────────────────────────────────────────────

    def start_tick(self, interval: float = 1.0) -> None:
        """Start background tick loop — processes due scheduled tasks."""
        self._tick_interval = interval
        self._shutdown.clear()

        def _tick():
            while not self._shutdown.is_set():
                # Process scheduled tasks
                for scheduled in self.scheduler.get_due():
                    task = self.queue.get(scheduled.task_id)
                    if task:
                        # Re-create task if it was completed
                        new_task = self.create_task(
                            name=task.name, tags=["recurring"],
                            payload=task.payload, priority=task.priority,
                        )
                        self.executor.execute(new_task)

                # Execute ready tasks
                self.execute_all()

                self._shutdown.wait(self._tick_interval)

        self._tick_thread = threading.Thread(target=_tick, daemon=True)
        self._tick_thread.start()

    def stop_tick(self) -> None:
        self._shutdown.set()
        if self._tick_thread:
            self._tick_thread.join(timeout=5)

    # ── Query ─────────────────────────────────────────────────────────

    def list_tasks(self, status: TaskStatus = None) -> List[Dict[str, Any]]:
        if status:
            tasks = self.queue.list_by_status(status)
        else:
            tasks = list(self.queue._by_id.values())
        return [t.to_dict() for t in tasks]

    def find_by_tag(self, tag: str) -> List[AgentTask]:
        return self.queue.list_by_tag(tag)

    def stats(self) -> Dict[str, Any]:
        return {
            "queue": self.queue.stats(),
            "scheduler": self.scheduler.stats(),
            "executor": self.executor.stats(),
        }

    def shutdown(self) -> None:
        self.stop_tick()
        self.queue.clear()


# ── Global instance ───────────────────────────────────────────────────────

_task_manager: Optional[TaskManager] = None


def get_task_manager(max_workers: int = 4) -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager(max_workers=max_workers)
    return _task_manager

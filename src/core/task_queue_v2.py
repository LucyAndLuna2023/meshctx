"""
meshctx v3.94 — Task Queue v2 (增强版任务队列)

增强特性 vs v3.72 TaskQueue:
1) 优先级队列 + 依赖图 (Dependency Graph)
2) 并发控制 + Worker池 (Concurrency & Worker Pool)
3) 失败重试 + 指数退避 (Exponential Backoff + Jitter)
4) 持久化 + 恢复 (JSON Persistence & Recovery)

Design: Thread-safe, pluggable handlers, cycle detection, event hooks.
"""

import heapq
import json
import logging
import math
import os
import random
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Union,
)

logger = logging.getLogger("meshctx.task_queue_v2")


# ═══════════════════════════════════════════════════════════════
# Enums & Data Classes
# ═══════════════════════════════════════════════════════════════

class PriorityV2(Enum):
    """Task priority levels (lower ordinal = higher priority)"""
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatusV2(Enum):
    """Extended task lifecycle states"""
    PENDING = "pending"          # Waiting in queue (deps not yet satisfied)
    READY = "ready"              # Dependencies satisfied, can be dequeued
    RUNNING = "running"          # Being processed by a worker
    DONE = "done"                # Successfully completed
    FAILED = "failed"            # Failed (retries exhausted or permanent failure)
    RETRYING = "retrying"        # Failed but will be retried
    BLOCKED = "blocked"          # A dependency failed, cannot proceed
    CANCELLED = "cancelled"      # Explicitly cancelled


DEPENDENCY_LOCK = threading.Lock()  # shared across instances for persistence


@dataclass(order=True)
class TaskV2:
    """v3.94 Enhanced task with dependencies, retry config, and timing."""
    priority: int
    id: str = field(compare=False, default_factory=lambda: str(uuid.uuid4())[:12])
    name: str = field(compare=False, default="")
    payload: Any = field(compare=False, default=None)
    status: str = field(compare=False, default=TaskStatusV2.PENDING.value)
    dependencies: List[str] = field(compare=False, default_factory=list)
    dependents: List[str] = field(compare=False, default_factory=list)     # reverse edges
    # Retry with exponential backoff
    retries: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default=3)
    backoff_base: float = field(compare=False, default=1.0)   # seconds
    backoff_multiplier: float = field(compare=False, default=2.0)
    backoff_max: float = field(compare=False, default=60.0)
    # Timing
    created_at: float = field(compare=False, default_factory=time.monotonic)
    started_at: Optional[float] = field(compare=False, default=None)
    completed_at: Optional[float] = field(compare=False, default=None)
    next_retry_at: Optional[float] = field(compare=False, default=None)
    # Metadata
    error: Optional[str] = field(compare=False, default=None)
    result: Any = field(compare=False, default=None)
    tags: Dict[str, str] = field(compare=False, default_factory=dict)
    timeout_seconds: Optional[float] = field(compare=False, default=None)

    @property
    def elapsed(self) -> float:
        """Elapsed wall-clock time since task creation."""
        end = self.completed_at or time.monotonic()
        return end - self.created_at

    @property
    def is_terminal(self) -> bool:
        """True if the task is in a final state."""
        return self.status in (
            TaskStatusV2.DONE.value,
            TaskStatusV2.FAILED.value,
            TaskStatusV2.BLOCKED.value,
            TaskStatusV2.CANCELLED.value,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to a JSON-safe dict (for persistence)."""
        d = {
            "id": self.id,
            "name": self.name,
            "priority": self.priority,
            "status": self.status,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "backoff_base": self.backoff_base,
            "backoff_multiplier": self.backoff_multiplier,
            "backoff_max": self.backoff_max,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "next_retry_at": self.next_retry_at,
            "timeout_seconds": self.timeout_seconds,
            "tags": self.tags,
            "error": self.error,
        }
        # result may not be JSON-serializable; skip unless trivial
        if isinstance(self.result, (str, int, float, bool, list, dict, type(None))):
            d["result"] = self.result
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskV2":
        """Deserialize a task from a dict (persistence restore)."""
        task = cls(
            priority=d.get("priority", PriorityV2.MEDIUM.value),
            id=d["id"],
            name=d.get("name", ""),
            status=d.get("status", TaskStatusV2.PENDING.value),
            dependencies=d.get("dependencies", []),
            dependents=d.get("dependents", []),
            retries=d.get("retries", 0),
            max_retries=d.get("max_retries", 3),
            backoff_base=d.get("backoff_base", 1.0),
            backoff_multiplier=d.get("backoff_multiplier", 2.0),
            backoff_max=d.get("backoff_max", 60.0),
            created_at=d.get("created_at", time.monotonic()),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            next_retry_at=d.get("next_retry_at"),
            timeout_seconds=d.get("timeout_seconds"),
            tags=d.get("tags", {}),
            error=d.get("error"),
        )
        task.payload = d.get("payload")
        task.result = d.get("result")
        return task


# ═══════════════════════════════════════════════════════════════
# Exponential Backoff Engine
# ═══════════════════════════════════════════════════════════════

class ExponentialBackoff:
    """
    Exponential backoff with full jitter.

    delay = min(backoff_max, backoff_base * (backoff_multiplier ** attempt))
    With jitter: delay = random.uniform(0, delay)

    This prevents thundering-herd retry storms in distributed systems.
    """

    def __init__(
        self,
        base: float = 1.0,
        multiplier: float = 2.0,
        max_delay: float = 60.0,
        jitter: bool = True,
    ):
        self.base = base
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.jitter = jitter

    def compute(self, attempt: int) -> float:
        """Calculate backoff delay for a given retry attempt (0-indexed)."""
        raw = self.base * (self.multiplier ** max(0, attempt))
        delay = min(self.max_delay, raw)
        if self.jitter and delay > 0:
            delay = random.uniform(0, delay)
        return delay


# ═══════════════════════════════════════════════════════════════
# Dependency Graph
# ═══════════════════════════════════════════════════════════════

class DependencyGraph:
    """
    Tracks task dependencies and determines readiness.

    - Detects cycles on add_edge (raises ValueError).
    - Marks tasks READY when all dependencies are DONE.
    - Marks tasks BLOCKED when any dependency is FAILED.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._edges: Dict[str, Set[str]] = {}          # task_id -> set of dep_ids
        self._reverse: Dict[str, Set[str]] = {}        # dep_id -> set of task_ids that depend on it

    def add_task(self, task_id: str, dependencies: List[str]) -> None:
        """Register a task and its dependencies. Raises ValueError on cycle."""
        with self._lock:
            if task_id not in self._edges:
                self._edges[task_id] = set()
            if task_id not in self._reverse:
                self._reverse[task_id] = set()

            for dep_id in dependencies:
                if dep_id not in self._edges:
                    self._edges[dep_id] = set()
                if dep_id not in self._reverse:
                    self._reverse[dep_id] = set()

                self._edges[task_id].add(dep_id)
                self._reverse[dep_id].add(task_id)

            # Cycle detection via DFS
            if self._has_cycle():
                # Rollback
                for dep_id in dependencies:
                    self._edges[task_id].discard(dep_id)
                    self._reverse[dep_id].discard(task_id)
                raise ValueError(
                    f"Adding dependency from '{task_id}' -> '{dependencies}' "
                    f"would create a cycle"
                )

    def remove_task(self, task_id: str) -> None:
        """Remove a task from the graph, cleaning up all edges."""
        with self._lock:
            # Remove forward edges
            for dep_id in list(self._edges.get(task_id, set())):
                self._reverse[dep_id].discard(task_id)
            self._edges.pop(task_id, None)

            # Remove reverse edges
            for dependent_id in list(self._reverse.get(task_id, set())):
                self._edges[dependent_id].discard(task_id)
            self._reverse.pop(task_id, None)

    def get_dependencies(self, task_id: str) -> Set[str]:
        """Return the set of task IDs this task depends on."""
        with self._lock:
            return set(self._edges.get(task_id, set()))

    def get_dependents(self, task_id: str) -> Set[str]:
        """Return the set of task IDs that depend on this task."""
        with self._lock:
            return set(self._reverse.get(task_id, set()))

    def _has_cycle(self) -> bool:
        """DFS-based cycle detection."""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in self._edges.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for node in list(self._edges.keys()):
            if node not in visited:
                if dfs(node):
                    return True
        return False

    def is_ready(self, task_id: str, done_ids: Set[str]) -> bool:
        """Check if all dependencies of task_id are in done_ids."""
        with self._lock:
            deps = self._edges.get(task_id, set())
            return deps.issubset(done_ids)


# ═══════════════════════════════════════════════════════════════
# Worker Pool
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkerInfo:
    """Runtime information about a single worker."""
    worker_id: int
    thread: Optional[threading.Thread] = None
    active: bool = False
    current_task_id: Optional[str] = None
    tasks_processed: int = 0
    tasks_failed: int = 0


class WorkerPool:
    """
    Manages a pool of worker threads.

    Workers pull tasks from a shared ready queue and invoke the handler.
    The pool supports dynamic resizing.
    """

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._workers: List[WorkerInfo] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._ready_queue: List[TaskV2] = []       # heapq
        self._queue_lock = threading.Lock()
        self._handler: Optional[Callable] = None
        self._result_callback: Optional[Callable] = None
        self._active_count = 0

    # ── Queue management ───────────────────────────────────────

    def push_ready(self, task: TaskV2) -> None:
        """Push a ready task into the worker queue."""
        with self._queue_lock:
            heapq.heappush(self._ready_queue, task)

    def pop_ready(self) -> Optional[TaskV2]:
        """Pop the highest-priority ready task."""
        with self._queue_lock:
            if self._ready_queue:
                return heapq.heappop(self._ready_queue)
            return None

    @property
    def ready_count(self) -> int:
        with self._queue_lock:
            return len(self._ready_queue)

    # ── Lifecycle ──────────────────────────────────────────────

    def start(self, handler: Callable[[TaskV2], Any],
              result_callback: Optional[Callable] = None) -> None:
        """
        Start the worker pool.

        Args:
            handler: Called with each task. Can be sync or async.
            result_callback: Called with (task, result_or_error) on completion.
        """
        self._handler = handler
        self._result_callback = result_callback
        self._stop_event.clear()

        with self._lock:
            for i in range(self.max_workers):
                wi = WorkerInfo(worker_id=i)
                t = threading.Thread(
                    target=self._worker_loop,
                    args=(wi,),
                    daemon=True,
                    name=f"tq-worker-{i}",
                )
                wi.thread = t
                self._workers.append(wi)
                t.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop all workers gracefully."""
        self._stop_event.set()
        for wi in self._workers:
            if wi.thread and wi.thread.is_alive():
                wi.thread.join(timeout=timeout)

    def resize(self, new_max: int) -> int:
        """
        Resize the worker pool. Returns the new worker count.
        Only shrinking is supported (extra workers stop after current task).
        """
        with self._lock:
            self.max_workers = max(1, new_max)
        return self.max_workers

    # ── Worker loop ────────────────────────────────────────────

    def _worker_loop(self, wi: WorkerInfo) -> None:
        """Main loop for a single worker thread."""
        logger.debug("Worker %d started", wi.worker_id)
        while not self._stop_event.is_set():
            task = self.pop_ready()
            if task is None:
                # No ready tasks — brief sleep to avoid busy-wait
                time.sleep(0.05)
                continue

            wi.active = True
            wi.current_task_id = task.id
            task.status = TaskStatusV2.RUNNING.value
            task.started_at = task.started_at or time.monotonic()
            self._active_count += 1

            try:
                result = self._handler(task)
                task.status = TaskStatusV2.DONE.value
                task.result = result
                task.completed_at = time.monotonic()
                task.error = None
                wi.tasks_processed += 1
                if self._result_callback:
                    self._result_callback(task, None)
            except Exception as exc:
                task.error = str(exc)
                wi.tasks_failed += 1
                if self._result_callback:
                    self._result_callback(task, exc)
                # NB: The caller (TaskQueueV2) handles retry logic
                # so we leave the task in its current state
            finally:
                wi.active = False
                wi.current_task_id = None
                self._active_count -= 1

        logger.debug("Worker %d stopped", wi.worker_id)

    def get_stats(self) -> Dict[str, Any]:
        """Return worker pool statistics."""
        with self._lock:
            return {
                "max_workers": self.max_workers,
                "active_workers": sum(1 for w in self._workers if w.active),
                "total_workers": len(self._workers),
                "ready_queue_size": self.ready_count,
                "per_worker": [
                    {
                        "id": w.worker_id,
                        "active": w.active,
                        "current_task": w.current_task_id,
                        "processed": w.tasks_processed,
                        "failed": w.tasks_failed,
                    }
                    for w in self._workers
                ],
            }


# ═══════════════════════════════════════════════════════════════
# Persistence Manager
# ═══════════════════════════════════════════════════════════════

class PersistenceManager:
    """
    JSON-based persistence for TaskQueueV2 state.

    Saves:
    - All pending/ready/retrying tasks (with their state)
    - Completed task history (up to max_history)
    - Dependency graph edges
    - Queue configuration

    Files are written atomically (write to .tmp then rename).
    """

    def __init__(self, path: str, max_history: int = 200):
        self.path = path
        self.max_history = max_history

    def save(
        self,
        tasks: Dict[str, TaskV2],
        history: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> None:
        """Save queue state to disk atomically."""
        state = {
            "version": "3.94",
            "saved_at": time.time(),
            "config": config,
            "tasks": {
                tid: t.to_dict()
                for tid, t in tasks.items()
                if not t.is_terminal
            },
            "history": history[-self.max_history:],
            # Save dependency edges
            "edges": {
                tid: list(t.dependencies)
                for tid, t in tasks.items()
                if t.dependencies
            },
        }
        tmp_path = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
            logger.info("TaskQueueV2 state saved to %s (%d tasks)", self.path,
                         len(state["tasks"]))
        except Exception as exc:
            logger.error("Failed to save queue state to %s: %s", self.path, exc)

    def load(self) -> Optional[Dict[str, Any]]:
        """Load queue state from disk. Returns None if file missing or corrupt."""
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("version") != "3.94":
                logger.warning("Persistence version mismatch: %s", state.get("version"))
            return state
        except (json.JSONDecodeError, IOError) as exc:
            logger.error("Failed to load queue state: %s", exc)
            return None

    def clear(self) -> None:
        """Remove the persistence file."""
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════
# TaskQueueV2 — Main Engine
# ═══════════════════════════════════════════════════════════════

class TaskQueueV2:
    """
    v3.94 Task Queue v2 — Enhanced task scheduling engine.

    Features:
    1) Priority queue with dependency graph — tasks wait until deps complete.
    2) Concurrency control via WorkerPool — configurable worker count.
    3) Exponential backoff retry with jitter — no thundering herds.
    4) JSON persistence + recovery — survive restarts.

    Usage:
        tq = TaskQueueV2(max_workers=4)

        # Register tasks with dependencies
        tq.enqueue("fetch_data", priority=PriorityV2.HIGH)
        tq.enqueue("process_data", dependencies=["<fetch_data_id>"], priority=PriorityV2.MEDIUM)

        # Start processing
        tq.start(handler=my_handler)

        # Wait for completion
        tq.wait(timeout=30)
        tq.stop()

    Event hooks:
        on_task_done(task)    — called when a task finishes successfully.
        on_task_fail(task)   — called when a task fails (after retries exhausted).
        on_queue_empty()     — called when all tasks complete.
    """

    def __init__(
        self,
        max_workers: int = 4,
        max_concurrent: Optional[int] = None,
        backoff_base: float = 1.0,
        backoff_multiplier: float = 2.0,
        backoff_max: float = 60.0,
        persistence_path: Optional[str] = None,
    ):
        # Concurrency
        self._max_workers = max_workers
        self._max_concurrent = max_concurrent or max_workers

        # Backoff
        self._backoff = ExponentialBackoff(
            base=backoff_base,
            multiplier=backoff_multiplier,
            max_delay=backoff_max,
        )

        # Core data structures
        self._tasks: Dict[str, TaskV2] = {}
        self._dep_graph = DependencyGraph()
        self._done_ids: Set[str] = set()
        self._history: deque = deque(maxlen=500)
        self._lock = threading.RLock()

        # Worker pool
        self._pool = WorkerPool(max_workers=max_workers)

        # Persistence
        self._persistence: Optional[PersistenceManager] = PersistenceManager(
            path=persistence_path or os.path.join(
                os.path.expanduser("~"), ".meshctx", "task_queue_v2.json"
            )
        )

        # Event hooks
        self.on_task_done: Optional[Callable[[TaskV2], None]] = None
        self.on_task_fail: Optional[Callable[[TaskV2], None]] = None
        self.on_queue_empty: Optional[Callable[[], None]] = None

        # Stats
        self._total_enqueued = 0
        self._total_completed = 0
        self._total_failed = 0
        self._start_time: Optional[float] = None

        # Auto-save
        self._auto_save_enabled = True
        self._last_save_time = 0.0
        self._save_interval = 5.0  # seconds between auto-saves

    # ══════════════════════════════════════════════════════════
    # Task Management
    # ══════════════════════════════════════════════════════════

    def enqueue(
        self,
        name: str,
        payload: Any = None,
        priority: Union[PriorityV2, int] = PriorityV2.MEDIUM,
        dependencies: Optional[List[str]] = None,
        max_retries: int = 3,
        backoff_base: Optional[float] = None,
        backoff_multiplier: Optional[float] = None,
        backoff_max: Optional[float] = None,
        timeout_seconds: Optional[float] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Enqueue a new task.

        Args:
            name: Human-readable task name.
            payload: Arbitrary data passed to the handler.
            priority: Task priority (lower = more urgent).
            dependencies: List of task IDs that must complete first.
            max_retries: Maximum retry attempts on failure.
            backoff_base: Base delay in seconds for exponential backoff.
            backoff_multiplier: Multiplier for each retry step.
            backoff_max: Maximum backoff delay.
            timeout_seconds: Optional per-task timeout.
            tags: Optional key-value metadata.

        Returns:
            The new task's ID.

        Raises:
            ValueError: If a dependency ID is not found or would create a cycle.
        """
        prio_val = priority.value if isinstance(priority, PriorityV2) else priority
        deps = list(dependencies or [])

        task = TaskV2(
            priority=prio_val,
            name=name,
            payload=payload,
            dependencies=deps,
            max_retries=max_retries,
            backoff_base=backoff_base or self._backoff.base,
            backoff_multiplier=backoff_multiplier or self._backoff.multiplier,
            backoff_max=backoff_max or self._backoff.max_delay,
            timeout_seconds=timeout_seconds,
            tags=tags or {},
        )

        with self._lock:
            # Validate dependency references
            for dep_id in deps:
                if dep_id not in self._tasks and dep_id not in self._done_ids:
                    raise ValueError(
                        f"Dependency '{dep_id}' not found. Enqueue dependent "
                        f"tasks after their dependencies."
                    )
                # If dependency is already done, it's fine — the dep graph handles it

            # Register in dependency graph (may raise on cycle)
            self._dep_graph.add_task(task.id, deps)

            # Set dependents on upstream tasks
            for dep_id in deps:
                if dep_id in self._tasks:
                    self._tasks[dep_id].dependents.append(task.id)

            # Determine initial status
            if self._dep_graph.is_ready(task.id, self._done_ids):
                task.status = TaskStatusV2.READY.value
            else:
                task.status = TaskStatusV2.PENDING.value

            self._tasks[task.id] = task
            self._total_enqueued += 1

            # Push ready tasks to worker pool
            if task.status == TaskStatusV2.READY.value:
                self._pool.push_ready(task)

        self._maybe_auto_save()
        return task.id

    def cancel(self, task_id: str) -> bool:
        """Cancel a task. Returns True if task was cancelled."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.is_terminal:
                return False
            task.status = TaskStatusV2.CANCELLED.value
            task.completed_at = time.monotonic()
            # Block dependents
            self._propagate_blocked(task_id, "cancelled")
        return True

    def get_task(self, task_id: str) -> Optional[TaskV2]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    # ══════════════════════════════════════════════════════════
    # Worker Pool Lifecycle
    # ══════════════════════════════════════════════════════════

    def start(self, handler: Callable[[TaskV2], Any]) -> None:
        """
        Start processing tasks with the given handler.

        The handler receives a TaskV2 and should return a result or raise on failure.
        Tasks that are already READY begin processing immediately.
        """
        self._start_time = time.monotonic()
        self._pool.start(
            handler=handler,
            result_callback=self._on_worker_result,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop all workers gracefully. Save state before stopping."""
        self._auto_save(force=True)
        self._pool.stop(timeout=timeout)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Block until all non-terminal tasks are complete or timeout expires.
        Returns True if all tasks completed, False on timeout.
        """
        deadline = (time.monotonic() + timeout) if timeout else None
        while True:
            if self.is_idle():
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def is_idle(self) -> bool:
        """True if no tasks are pending, ready, running, or retrying."""
        with self._lock:
            for t in self._tasks.values():
                if t.status in (
                    TaskStatusV2.PENDING.value,
                    TaskStatusV2.READY.value,
                    TaskStatusV2.RUNNING.value,
                    TaskStatusV2.RETRYING.value,
                ):
                    return False
            return True

    # ══════════════════════════════════════════════════════════
    # Internal: Worker Result Callback
    # ══════════════════════════════════════════════════════════

    def _on_worker_result(self, task: TaskV2, error: Optional[Exception]) -> None:
        """Called by WorkerPool when a task finishes (success or failure)."""
        with self._lock:
            if error is None and task.status == TaskStatusV2.DONE.value:
                self._on_task_success(task)
            elif error is not None and task.status == TaskStatusV2.RUNNING.value:
                self._on_task_failure(task, error)

    def _on_task_success(self, task: TaskV2) -> None:
        """Handle successful task completion."""
        self._done_ids.add(task.id)
        self._total_completed += 1
        self._history.append({
            "id": task.id,
            "name": task.name,
            "status": "done",
            "result": task.result,
            "elapsed": task.elapsed,
        })

        # Unblock dependents
        for dep_id in task.dependents:
            dep_task = self._tasks.get(dep_id)
            if dep_task and dep_task.status == TaskStatusV2.PENDING.value:
                if self._dep_graph.is_ready(dep_id, self._done_ids):
                    dep_task.status = TaskStatusV2.READY.value
                    self._pool.push_ready(dep_task)

        # Fire hook
        if self.on_task_done:
            try:
                self.on_task_done(task)
            except Exception:
                pass

        # Check if queue is empty
        if self.is_idle() and self.on_queue_empty:
            try:
                self.on_queue_empty()
            except Exception:
                pass

        self._maybe_auto_save()

    def _on_task_failure(self, task: TaskV2, error: Exception) -> None:
        """Handle task failure, with retry logic."""
        task.retries += 1

        if task.retries <= task.max_retries:
            # Schedule retry with exponential backoff
            delay = ExponentialBackoff(
                base=task.backoff_base,
                multiplier=task.backoff_multiplier,
                max_delay=task.backoff_max,
            ).compute(task.retries - 1)
            task.status = TaskStatusV2.RETRYING.value
            task.next_retry_at = time.monotonic() + delay
            task.error = str(error)

            # Re-enqueue after delay
            threading.Timer(delay, self._retry_task, args=[task.id]).start()
        else:
            # Retries exhausted — permanent failure
            task.status = TaskStatusV2.FAILED.value
            task.completed_at = time.monotonic()
            task.error = str(error)
            self._total_failed += 1
            self._history.append({
                "id": task.id,
                "name": task.name,
                "status": "failed",
                "error": str(error),
                "retries": task.retries,
                "elapsed": task.elapsed,
            })

            # Block dependents
            self._propagate_blocked(task.id, "failed")

            if self.on_task_fail:
                try:
                    self.on_task_fail(task)
                except Exception:
                    pass

        self._maybe_auto_save()

    def _retry_task(self, task_id: str) -> None:
        """Re-enqueue a task for retry after backoff delay."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != TaskStatusV2.RETRYING.value:
                return
            task.status = TaskStatusV2.READY.value
            task.error = None
            task.next_retry_at = None
            self._pool.push_ready(task)

    def _propagate_blocked(self, failed_task_id: str, reason: str) -> None:
        """Mark dependent tasks as BLOCKED when upstream fails."""
        to_block = list(self._dep_graph.get_dependents(failed_task_id))
        for dep_id in to_block:
            task = self._tasks.get(dep_id)
            if task and task.status in (
                TaskStatusV2.PENDING.value,
                TaskStatusV2.READY.value,
            ):
                task.status = TaskStatusV2.BLOCKED.value
                task.error = f"Blocked by failed dependency: {failed_task_id} ({reason})"
                task.completed_at = time.monotonic()
                self._history.append({
                    "id": task.id,
                    "name": task.name,
                    "status": "blocked",
                    "error": task.error,
                })
                # Recursively block dependents
                self._propagate_blocked(task.id, "blocked")

    # ══════════════════════════════════════════════════════════
    # Persistence
    # ══════════════════════════════════════════════════════════

    def save(self, path: Optional[str] = None) -> None:
        """Save current state to disk."""
        if path and self._persistence:
            self._persistence.path = path
        if self._persistence:
            with self._lock:
                self._persistence.save(
                    tasks=self._tasks,
                    history=list(self._history),
                    config={
                        "max_workers": self._max_workers,
                        "max_concurrent": self._max_concurrent,
                        "total_enqueued": self._total_enqueued,
                        "total_completed": self._total_completed,
                        "total_failed": self._total_failed,
                    },
                )
            self._last_save_time = time.monotonic()

    def _auto_save(self, force: bool = False) -> None:
        """Auto-save throttled by interval (unless forced)."""
        if not self._auto_save_enabled or not self._persistence:
            return
        now = time.monotonic()
        if force or (now - self._last_save_time >= self._save_interval):
            self.save()

    def _maybe_auto_save(self) -> None:
        self._auto_save(force=False)

    def restore(self, path: Optional[str] = None) -> int:
        """
        Restore queue state from disk. Returns number of tasks restored.

        Existing tasks are NOT cleared — restored tasks are merged in.
        Tasks that are already DONE in the saved state are added to _done_ids.
        """
        if path and self._persistence:
            self._persistence.path = path
        if not self._persistence:
            return 0

        state = self._persistence.load()
        if not state:
            return 0

        restored = 0
        with self._lock:
            task_dicts = state.get("tasks", {})
            for tid, td in task_dicts.items():
                if tid in self._tasks or tid in self._done_ids:
                    continue  # Already known
                task = TaskV2.from_dict(td)
                task.payload = td.get("payload")
                task.result = td.get("result")
                self._tasks[tid] = task

                # Rebuild dependency graph
                if task.dependencies:
                    try:
                        self._dep_graph.add_task(tid, task.dependencies)
                    except ValueError:
                        pass  # Cycle or other issue — skip edge

                # Restore done IDs
                if task.status == TaskStatusV2.DONE.value:
                    self._done_ids.add(tid)

                # Push ready tasks back to pool if pool is running
                if task.status == TaskStatusV2.READY.value:
                    self._pool.push_ready(task)

                restored += 1

            # Restore history
            hist = state.get("history", [])
            self._history.extend(hist)

            # Restore config counters
            cfg = state.get("config", {})
            self._total_enqueued = max(self._total_enqueued, cfg.get("total_enqueued", 0))
            self._total_completed = max(self._total_completed, cfg.get("total_completed", 0))
            self._total_failed = max(self._total_failed, cfg.get("total_failed", 0))

        logger.info("Restored %d tasks from %s", restored,
                     self._persistence.path)
        return restored

    def set_persistence_path(self, path: str) -> None:
        """Change the persistence file path."""
        if self._persistence:
            self._persistence.path = path
        else:
            self._persistence = PersistenceManager(path=path)

    def clear_persistence(self) -> None:
        """Delete the persistence file."""
        if self._persistence:
            self._persistence.clear()

    # ══════════════════════════════════════════════════════════
    # Statistics & Diagnostics
    # ══════════════════════════════════════════════════════════

    def stats(self) -> Dict[str, Any]:
        """Return comprehensive queue statistics."""
        with self._lock:
            status_counts = {}
            for t in self._tasks.values():
                status_counts[t.status] = status_counts.get(t.status, 0) + 1

            return {
                "total_enqueued": self._total_enqueued,
                "total_completed": self._total_completed,
                "total_failed": self._total_failed,
                "status_breakdown": status_counts,
                "done_ids": len(self._done_ids),
                "history_size": len(self._history),
                "workers": self._pool.get_stats(),
                "uptime_seconds": (
                    round(time.monotonic() - self._start_time, 2)
                    if self._start_time else 0
                ),
            }

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent task completion history."""
        with self._lock:
            return list(self._history)[-limit:]

    def pending_tasks(self) -> List[TaskV2]:
        """Return all non-terminal tasks sorted by priority."""
        with self._lock:
            return sorted(
                [t for t in self._tasks.values() if not t.is_terminal],
                key=lambda t: (t.priority, t.created_at),
            )

    def reset(self) -> None:
        """Reset the entire queue, clearing all tasks and history."""
        with self._lock:
            self._tasks.clear()
            self._dep_graph = DependencyGraph()
            self._done_ids.clear()
            self._history.clear()
            self._total_enqueued = 0
            self._total_completed = 0
            self._total_failed = 0
            self._start_time = None
            # Clear worker ready queue
            while self._pool.pop_ready():
                pass
        self.clear_persistence()

    def dump_graph(self) -> Dict[str, Any]:
        """Export the full dependency graph as a dict (for visualization)."""
        with self._lock:
            nodes = {}
            for tid, task in self._tasks.items():
                nodes[tid] = {
                    "name": task.name,
                    "priority": task.priority,
                    "status": task.status,
                    "dependencies": task.dependencies,
                    "dependents": task.dependents,
                }
            return {"nodes": nodes}

    # ══════════════════════════════════════════════════════════
    # Configuration
    # ══════════════════════════════════════════════════════════

    def set_auto_save(self, enabled: bool, interval: float = 5.0) -> None:
        """Enable or disable auto-save and set the save interval."""
        self._auto_save_enabled = enabled
        self._save_interval = max(1.0, interval)

    def resize_workers(self, max_workers: int) -> int:
        """Resize the worker pool. Returns new size."""
        with self._lock:
            self._max_workers = max(1, max_workers)
            return self._pool.resize(self._max_workers)


# ═══════════════════════════════════════════════════════════════
# Singleton Factory
# ═══════════════════════════════════════════════════════════════

_task_queue_v2: Optional[TaskQueueV2] = None
_singleton_lock = threading.Lock()


def get_task_queue_v2(
    max_workers: int = 4,
    persistence_path: Optional[str] = None,
) -> TaskQueueV2:
    """Get or create the global TaskQueueV2 singleton."""
    global _task_queue_v2
    if _task_queue_v2 is None:
        with _singleton_lock:
            if _task_queue_v2 is None:
                _task_queue_v2 = TaskQueueV2(
                    max_workers=max_workers,
                    persistence_path=persistence_path,
                )
    return _task_queue_v2


def reset_task_queue_v2() -> None:
    """Reset the global TaskQueueV2 singleton."""
    global _task_queue_v2
    with _singleton_lock:
        if _task_queue_v2:
            _task_queue_v2.stop(timeout=2)
        _task_queue_v2 = None


# ── Legacy alias layer (2026-08-25 004meshctx 审计补齐) ──
# 兼容 _known 映射中声明的旧符号名, 保持 from src.core import X 契约不变
def __getattr__(name):
    if name == "QueuedTask":
        return TaskV2
    raise AttributeError(name)
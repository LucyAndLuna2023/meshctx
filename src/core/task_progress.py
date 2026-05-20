"""
Background Task Progress Engine — v2.45
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
实时追踪后台任务进度，支持SSE推送和WebSocket通知。
对标Claude Code的进度条/spinner功能。

特性:
- 任务注册+进度更新+完成通知
- SSE流式推送进度 (text/event-stream)
- WebSocket实时推送 (通过realtime_push hub)
- 进度百分比+阶段描述+预估剩余时间
- 任务历史+统计
- 自动清理过期任务
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TaskProgress:
    """单个任务的进度快照"""
    task_id: str
    name: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    progress: float = 0.0  # 0.0 - 100.0
    stage: str = ""
    message: str = ""
    total_steps: int = 0
    current_step: int = 0
    estimated_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    error: Optional[str] = None
    result: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status,
            "progress": round(self.progress, 2),
            "stage": self.stage,
            "message": self.message,
            "total_steps": self.total_steps,
            "current_step": self.current_step,
            "estimated_seconds": round(self.estimated_seconds, 1),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


class TaskProgressEngine:
    """后台任务进度追踪引擎"""

    def __init__(self, max_history: int = 100):
        self._tasks: Dict[str, TaskProgress] = {}
        self._history: List[TaskProgress] = []
        self._max_history = max_history
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}  # task_id -> set of queues
        self._global_subscribers: Set[asyncio.Queue] = set()  # all-task subscribers

    # ── Task Lifecycle ────────────────────────────────

    def create_task(self, name: str, total_steps: int = 0,
                    estimated_seconds: float = 0.0) -> TaskProgress:
        """创建新任务, 返回TaskProgress对象"""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = TaskProgress(
            task_id=task_id,
            name=name,
            status="pending",
            total_steps=total_steps,
            estimated_seconds=estimated_seconds,
        )
        self._tasks[task_id] = task
        self._subscribers[task_id] = set()
        return task

    def start_task(self, task_id: str) -> Optional[TaskProgress]:
        """标记任务开始执行"""
        task = self._tasks.get(task_id)
        if task:
            task.status = "running"
            task.started_at = time.time()
            self._notify_subscribers(task_id, task)
        return task

    def update_progress(self, task_id: str, progress: float,
                        stage: str = "", message: str = "",
                        current_step: int = 0) -> Optional[TaskProgress]:
        """更新任务进度"""
        task = self._tasks.get(task_id)
        if task:
            task.progress = min(100.0, max(0.0, progress))
            task.stage = stage
            task.message = message
            task.current_step = current_step
            task.elapsed_seconds = time.time() - task.started_at if task.started_at else 0
            self._notify_subscribers(task_id, task)
        return task

    def complete_task(self, task_id: str, result: Any = None) -> Optional[TaskProgress]:
        """标记任务完成"""
        task = self._tasks.get(task_id)
        if task:
            task.status = "completed"
            task.progress = 100.0
            task.completed_at = time.time()
            task.result = result
            task.elapsed_seconds = task.completed_at - task.started_at if task.started_at else 0
            self._notify_subscribers(task_id, task)
            self._archive_task(task)
        return task

    def fail_task(self, task_id: str, error: str) -> Optional[TaskProgress]:
        """标记任务失败"""
        task = self._tasks.get(task_id)
        if task:
            task.status = "failed"
            task.error = error
            task.completed_at = time.time()
            task.elapsed_seconds = task.completed_at - task.started_at if task.started_at else 0
            self._notify_subscribers(task_id, task)
            self._archive_task(task)
        return task

    def cancel_task(self, task_id: str, reason: str = "") -> Optional[TaskProgress]:
        """取消任务"""
        task = self._tasks.get(task_id)
        if task:
            task.status = "cancelled"
            task.message = reason or "任务已取消"
            task.completed_at = time.time()
            self._notify_subscribers(task_id, task)
            self._archive_task(task)
        return task

    # ── Progress Context Manager ──────────────────────

    def track(self, name: str, total_steps: int = 0,
              estimated_seconds: float = 0.0):
        """上下文管理器: 自动追踪任务进度

        Usage:
            async with engine.track("文件处理", total_steps=10) as task:
                for i in range(10):
                    await process_file(i)
                    task.update(i * 10, f"处理第{i+1}个文件")
        """
        return _TaskTracker(self, name, total_steps, estimated_seconds)

    # ── Subscribe (SSE) ──────────────────────────────

    def subscribe(self, task_id: Optional[str] = None) -> asyncio.Queue:
        """订阅进度更新, 返回异步队列"""
        queue: asyncio.Queue = asyncio.Queue()
        if task_id:
            if task_id not in self._subscribers:
                self._subscribers[task_id] = set()
            self._subscribers[task_id].add(queue)
        else:
            self._global_subscribers.add(queue)
        return queue

    def unsubscribe(self, task_id: Optional[str], queue: asyncio.Queue):
        """取消订阅"""
        if task_id and task_id in self._subscribers:
            self._subscribers[task_id].discard(queue)
        else:
            self._global_subscribers.discard(queue)

    # ── Query ─────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[TaskProgress]:
        return self._tasks.get(task_id)

    def list_active(self) -> List[TaskProgress]:
        """列出活跃任务 (pending + running)"""
        return [t for t in self._tasks.values()
                if t.status in ("pending", "running")]

    def list_all(self) -> List[TaskProgress]:
        """列出所有任务"""
        return list(self._tasks.values())

    def get_history(self, limit: int = 20) -> List[Dict]:
        """获取已完成任务历史"""
        return [t.to_dict() for t in self._history[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self._tasks) + len(self._history)
        active = len([t for t in self._tasks.values() if t.status in ("pending", "running")])
        completed = len([t for t in self._history if t.status == "completed"])
        failed = len([t for t in self._history if t.status == "failed"])
        return {
            "total_tracked": total,
            "active": active,
            "completed": completed,
            "failed": failed,
            "pending": len(self._tasks),
        }

    # ── Cleanup ───────────────────────────────────────

    def cleanup(self, max_age_seconds: float = 3600):
        """清理超过指定时间的已完成/失败任务"""
        cutoff = time.time() - max_age_seconds
        removed = 0
        for task_id in list(self._tasks.keys()):
            task = self._tasks[task_id]
            if task.status in ("completed", "failed", "cancelled"):
                if task.completed_at and task.completed_at < cutoff:
                    del self._tasks[task_id]
                    self._subscribers.pop(task_id, None)
                    removed += 1
        return removed

    # ── Internal ──────────────────────────────────────

    def _notify_subscribers(self, task_id: str, task: TaskProgress):
        """通知订阅者"""
        data = task.to_dict()

        # 通知特定任务订阅者
        for queue in self._subscribers.get(task_id, set()).copy():
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                pass

        # 通知全局订阅者
        for queue in self._global_subscribers.copy():
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                pass

        # 尝试通过 realtime_push 推送
        try:
            from .realtime_push import get_hub
            get_hub().broadcast("task_progress", data)
        except Exception:
            pass

    def _archive_task(self, task: TaskProgress):
        """归档已完成的任务"""
        self._tasks.pop(task.task_id, None)
        self._subscribers.pop(task.task_id, None)
        self._history.append(task)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


class _TaskTracker:
    """任务追踪上下文管理器"""

    def __init__(self, engine: TaskProgressEngine, name: str,
                 total_steps: int, estimated_seconds: float):
        self.engine = engine
        self.task = engine.create_task(name, total_steps, estimated_seconds)

    async def __aenter__(self):
        self.engine.start_task(self.task.task_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.engine.fail_task(self.task.task_id, str(exc_val))
        elif self.task.status == "running":
            self.engine.complete_task(self.task.task_id)

    def update(self, progress: float, message: str = "", stage: str = "",
               current_step: int = 0):
        self.engine.update_progress(
            self.task.task_id, progress, stage, message, current_step)


# 单例
_engine: Optional[TaskProgressEngine] = None


def get_progress_engine() -> TaskProgressEngine:
    global _engine
    if _engine is None:
        _engine = TaskProgressEngine()
    return _engine

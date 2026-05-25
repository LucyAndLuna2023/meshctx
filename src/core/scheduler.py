"""Cron Task Scheduler — v2.98"""
import asyncio, logging, time, heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

@dataclass(order=True)
class ScheduledTask:
    priority: int
    run_at: float = field(compare=True)
    name: str = field(compare=False)
    func: Callable = field(compare=False, default=None)
    recurring_seconds: float = field(compare=False, default=0)
    last_run: float = field(compare=False, default=0)
    run_count: int = field(compare=False, default=0)

class TaskScheduler:
    def __init__(self):
        self._queue: List[ScheduledTask] = []
        self._history: deque = deque(maxlen=100)
        self._running = False

    def schedule(self, name: str, func: Callable, delay_seconds: float = 0, recurring: float = 0, priority: int = 0) -> str:
        task = ScheduledTask(priority=-priority, run_at=time.time()+delay_seconds, name=name, func=func, recurring_seconds=recurring)
        heapq.heappush(self._queue, task); return name

    async def run_loop(self):
        self._running = True
        while self._running:
            now = time.time()
            while self._queue and self._queue[0].run_at <= now:
                task = heapq.heappop(self._queue)
                try:
                    if task.func:
                        if asyncio.iscoroutinefunction(task.func):
                            await task.func()
                        else:
                            task.func()
                    task.last_run = now; task.run_count += 1
                    self._history.append({"task": task.name, "time": now, "ok": True})
                    if task.recurring_seconds > 0:
                        task.run_at = now + task.recurring_seconds
                        heapq.heappush(self._queue, task)
                except Exception as e:
                    self._history.append({"task": task.name, "time": now, "ok": False, "error": str(e)[:100]})
            await asyncio.sleep(0.5)

    def stop(self): self._running = False
    def pending_count(self) -> int: return len(self._queue)
    def get_stats(self) -> Dict:
        return {"pending": len(self._queue), "completed": len(self._history), "running": self._running,
                "recent": list(self._history)[-5:]}

_scheduler: Optional[TaskScheduler] = None
def get_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None: _scheduler = TaskScheduler()
    return _scheduler

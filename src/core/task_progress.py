"""
meshctx v3.72 — Agent Task Queue (Agent任务队列)

优先级任务队列+并发控制+重试
"""
import logging, time, asyncio, heapq
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Callable, Any, Optional

logger = logging.getLogger("meshctx.task_queue")

class Priority(Enum):
    CRITICAL=0; HIGH=1; MEDIUM=2; LOW=3

@dataclass(order=True)
class Task:
    priority: int
    id: str=field(compare=False,default="")
    name: str=field(compare=False,default="")
    payload: Any=field(compare=False,default=None)
    status: str=field(compare=False,default="pending")
    retries: int=field(compare=False,default=0)
    max_retries: int=field(compare=False,default=3)

class TaskQueue:
    def __init__(self, max_concurrent: int=5):
        self._queue: List[Task]=[]; self._history: deque=deque(maxlen=100)
        self._max_concurrent=max_concurrent; self._running=0
    
    def enqueue(self, name: str, payload: Any=None, priority: Priority=Priority.MEDIUM, max_retries: int=3) -> str:
        task = Task(priority=priority.value, id=f"task-{int(time.time()*1000)}",
                     name=name, payload=payload, max_retries=max_retries)
        heapq.heappush(self._queue, task)
        return task.id
    
    def dequeue(self) -> Optional[Task]:
        if not self._queue or self._running >= self._max_concurrent: return None
        task = heapq.heappop(self._queue)
        self._running += 1; task.status = "running"
        return task
    
    async def process(self, handler: Callable, max_tasks: int=10) -> List[Dict]:
        results = []
        for _ in range(max_tasks):
            task = self.dequeue()
            if not task: break
            try:
                result = await handler(task) if asyncio.iscoroutinefunction(handler) else handler(task)
                task.status = "done"; results.append({"id":task.id,"name":task.name,"status":"done","result":result})
            except Exception as e:
                task.retries += 1
                if task.retries < task.max_retries:
                    task.status = "pending"; heapq.heappush(self._queue, task)
                    results.append({"id":task.id,"name":task.name,"status":"retrying","retry":task.retries})
                else:
                    task.status = "failed"; results.append({"id":task.id,"name":task.name,"status":"failed","error":str(e)})
            finally:
                self._running = max(0, self._running-1)
        self._history.extend(results)
        return results
    
    def get_stats(self) -> Dict:
        return {"queued": len(self._queue), "running": self._running,
                "history": len(self._history), "pending_priority": 
                {p.name:sum(1 for t in self._queue if t.priority==p.value) for p in Priority}}

_queue = None
def get_task_queue(mc=5):
    global _queue
    if _queue is None: _queue = TaskQueue(mc)
    return _queue

# Backward compat
def get_progress_engine():
    return get_task_queue()

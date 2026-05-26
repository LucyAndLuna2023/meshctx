"""Work Queue — v3.25"""
import logging, queue, threading, time
from typing import Any, Callable, Dict, List, Optional
logger = logging.getLogger(__name__)

class WorkQueue:
    def __init__(self, max_workers: int = 4):
        self._queue: queue.Queue = queue.Queue()
        self._results: Dict[str, Any] = {}
        self._workers: List[threading.Thread] = []
        self._running = False
        self.max_workers = max_workers
    
    def start(self):
        self._running = True
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start(); self._workers.append(t)
    
    def _worker(self):
        while self._running:
            try:
                task_id, func, args, kwargs = self._queue.get(timeout=1)
                try: self._results[task_id] = func(*args, **kwargs)
                except Exception as e: self._results[task_id] = {"error": str(e)}
                self._queue.task_done()
            except queue.Empty: continue
    
    def submit(self, task_id: str, func: Callable, *args, **kwargs) -> str:
        self._queue.put((task_id, func, args, kwargs)); return task_id
    
    def result(self, task_id: str) -> Optional[Any]: return self._results.get(task_id)
    
    def stop(self): self._running = False
    def pending(self) -> int: return self._queue.qsize()
    def get_stats(self) -> Dict:
        return {"pending": self.pending(), "completed": len(self._results),
                "workers": len(self._workers), "max_workers": self.max_workers}

_queue_mgr: Optional[WorkQueue] = None
def get_work_queue() -> WorkQueue:
    global _queue_mgr
    if _queue_mgr is None: _queue_mgr = WorkQueue()
    return _queue_mgr

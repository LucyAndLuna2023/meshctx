"""
meshctx ScheduleWakeup — 自调度循环唤醒
对标: Claude Code ScheduleWakeup
"""
import time, threading
from typing import Callable, Optional

_wakeups: dict[str, dict] = {}
_wakeup_lock = threading.Lock()

def schedule_wakeup(task_id: str, callback: Callable, 
                    interval_seconds: int = 60, 
                    max_iterations: int = 0,
                    immediate: bool = True) -> str:
    """创建一个周期性自唤醒任务
    
    Args:
        task_id: 唯一标识
        callback: 每次唤醒执行的函数
        interval_seconds: 间隔秒数
        max_iterations: 最大迭代次数(0=无限)
        immediate: 是否立即执行第一次
    """
    with _wakeup_lock:
        if task_id in _wakeups and _wakeups[task_id].get("running"):
            return f"Wakeup({task_id}) already running"
        
        state = {
            "task_id": task_id,
            "interval": interval_seconds,
            "max_iterations": max_iterations,
            "iteration": 0,
            "running": True,
            "last_run": 0,
            "thread": None
        }
        
        def _loop():
            if immediate:
                try:
                    callback()
                except Exception as e:
                    print(f"Wakeup({task_id}) error: {e}")
                state["iteration"] += 1
                state["last_run"] = time.time()
            
            while state["running"]:
                time.sleep(interval_seconds)
                if not state["running"]:
                    break
                try:
                    callback()
                except Exception as e:
                    print(f"Wakeup({task_id}) error: {e}")
                state["iteration"] += 1
                state["last_run"] = time.time()
                
                if max_iterations > 0 and state["iteration"] >= max_iterations:
                    state["running"] = False
                    break
        
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        state["thread"] = t
        _wakeups[task_id] = state
    
    return f"Wakeup({task_id}) started, interval={interval_seconds}s"

def schedule_cancel(task_id: str) -> str:
    """取消自唤醒任务"""
    with _wakeup_lock:
        if task_id in _wakeups:
            _wakeups[task_id]["running"] = False
            del _wakeups[task_id]
            return f"Wakeup({task_id}) cancelled"
    return f"Wakeup({task_id}) not found"

def schedule_list() -> list:
    """列出所有活跃的自唤醒任务"""
    return [{"id": k, "interval": v["interval"], 
             "iteration": v["iteration"], "running": v["running"]}
            for k, v in _wakeups.items()]

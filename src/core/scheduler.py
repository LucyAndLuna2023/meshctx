"""
meshctx Scheduler (v3.115.16)
Lightweight async task scheduler — periodic tasks, delayed execution.
"""
import asyncio
import logging
import time
from typing import Dict, Callable, Awaitable, Optional

logger = logging.getLogger("meshctx.scheduler")

_scheduled_tasks: Dict[str, asyncio.Task] = {}
_running = False


async def _run_periodic(name: str, interval_seconds: float, coro_func: Callable[..., Awaitable],
                        *args, **kwargs):
    """Internal: run a coroutine periodically."""
    logger.debug(f"Scheduler: {name} started (every {interval_seconds}s)")
    while _running:
        start = time.time()
        try:
            await coro_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Scheduler task '{name}' failed: {e}")
        
        elapsed = time.time() - start
        sleep_time = max(0, interval_seconds - elapsed)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)


def schedule_periodic(name: str, interval_seconds: float, coro_func: Callable[..., Awaitable],
                      *args, **kwargs):
    """Schedule a coroutine to run periodically.
    
    Args:
        name: Unique task name (replaces existing task with same name)
        interval_seconds: Seconds between executions
        coro_func: Async function to call
    """
    global _running
    _running = True
    
    # Cancel existing task with same name
    if name in _scheduled_tasks:
        _scheduled_tasks[name].cancel()
    
    task = asyncio.ensure_future(_run_periodic(name, interval_seconds, coro_func, *args, **kwargs))
    _scheduled_tasks[name] = task
    return task


def schedule_delayed(name: str, delay_seconds: float, coro_func: Callable[..., Awaitable],
                     *args, **kwargs):
    """Schedule a coroutine to run once after a delay."""
    async def _delayed():
        await asyncio.sleep(delay_seconds)
        try:
            await coro_func(*args, **kwargs)
        finally:
            _scheduled_tasks.pop(name, None)
    
    task = asyncio.ensure_future(_delayed())
    _scheduled_tasks[name] = task
    return task


def cancel(name: str):
    """Cancel a scheduled task by name."""
    task = _scheduled_tasks.pop(name, None)
    if task:
        task.cancel()


def cancel_all():
    """Cancel all scheduled tasks."""
    global _running
    _running = False
    for name, task in list(_scheduled_tasks.items()):
        task.cancel()
    _scheduled_tasks.clear()


def list_tasks() -> dict:
    """List all scheduled tasks with their status."""
    return {
        name: {
            "running": not task.done(),
            "cancelled": task.cancelled(),
        }
        for name, task in _scheduled_tasks.items()
    }

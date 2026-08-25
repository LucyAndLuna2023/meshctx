"""
meshctx Monitoring Module (v3.115.16)
Lightweight process metrics collection — RSS, CPU, request counts.
"""
import os
import time
import threading
from typing import Dict, Optional

_METRICS: Dict[str, float] = {}
_LOCK = threading.Lock()
_START_TIME = time.time()

# CPU delta sampling state (per 002 audit: cumulative avg → delta)
_last_utime: int = 0
_last_stime: int = 0
_last_cpu_sample: float = 0.0


def get_memory_rss_mb() -> float:
    """Get current process RSS in MB (跨平台, 2026-08-25 004meshctx 审计修复).

    Linux: /proc/<pid>/statm; 其他平台: psutil 优先, 否则 0 降级。
    """
    try:
        # 非 Linux 平台: psutil 优先 (macOS/Windows 无 /proc)
        if not os.path.exists("/proc"):
            try:
                import psutil
                return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 2)
            except Exception:
                return 0.0
        with open(f"/proc/{os.getpid()}/statm") as f:
            fields = f.read().split()
            # statm[1] = RSS in pages (4KB each)
            rss_pages = int(fields[1])
            return (rss_pages * 4) / 1024  # Convert to MB
    except Exception:
        return 0.0


def get_cpu_percent() -> float:
    """Get CPU usage via /proc/stat delta sampling (跨平台, 2026-08-25 审计修复).

    Linux: /proc/<pid>/stat delta; 其他平台: psutil 优先。
    """
    global _last_utime, _last_stime, _last_cpu_sample
    try:
        # 非 Linux 平台: psutil 优先 (macOS/Windows 无 /proc, 原实现恒 0 假数据)
        if not os.path.exists("/proc"):
            try:
                import psutil
                return round(psutil.Process(os.getpid()).cpu_percent(interval=None), 2)
            except Exception:
                return 0.0
        with open(f"/proc/{os.getpid()}/stat") as f:
            fields = f.read().split()
            utime = int(fields[13])
            stime = int(fields[14])

        now = time.time()
        clk_tck = os.sysconf(os.sysconf_names['SC_CLK_TCK'])

        if _last_cpu_sample > 0 and now > _last_cpu_sample:
            delta_time = now - _last_cpu_sample
            delta_total = (utime + stime) - (_last_utime + _last_stime)
            cpu_pct = (delta_total / clk_tck) / delta_time * 100
        else:
            cpu_pct = 0.0

        _last_utime = utime
        _last_stime = stime
        _last_cpu_sample = now
        return min(100.0, max(0.0, cpu_pct))
    except Exception:
        return 0.0


def increment_counter(name: str, delta: int = 1):
    """Increment a named counter (thread-safe)."""
    with _LOCK:
        _METRICS[name] = _METRICS.get(name, 0) + delta


def set_gauge(name: str, value: float):
    """Set a named gauge value."""
    with _LOCK:
        _METRICS[name] = value


def get_metrics() -> dict:
    """Get all collected metrics + system stats."""
    with _LOCK:
        result = dict(_METRICS)
    result['memory_rss_mb'] = get_memory_rss_mb()
    result['uptime_seconds'] = time.time() - _START_TIME
    result['cpu_percent'] = get_cpu_percent()
    return result


def record_request(method: str, path: str, status_code: int, duration_ms: float):
    """Record an HTTP request for metrics."""
    increment_counter(f"http.{status_code}")
    increment_counter("http.total")
    path_group = path.split("/")[1] if len(path) > 1 else "/"
    increment_counter(f"http.path.{path_group}")


class MetricsMiddleware:
    """ASGI middleware for automatic request metrics collection."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        start = time.time()
        status_code = 500
        
        async def _send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
        
        try:
            await self.app(scope, receive, _send)
        finally:
            duration_ms = (time.time() - start) * 1000
            path = scope.get("path", "/")
            method = scope.get("method", "GET")
            record_request(method, path, status_code, duration_ms)

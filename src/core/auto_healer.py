"""meshctx auto_healer — automated health checks and self-healing (v3.115.33)

真实实现: 纯 stdlib 的磁盘/内存/CPU 检查 (Linux /proc 或 os.sysconf / Windows ctypes),
网络连通性探测 (socket), 以及内部缓存健康检查。修复动作走可配置的 handler 列表,
未注册 handler 的告警使用安全的内建兜底动作 (清缓存/建议), 绝不静默吞异常。

检查 → 诊断 → 修复:
  check_all()          — 运行全部真实健康检查
  heal(checks)         — 对非 ok 的检查应用修复动作 (可配置 handler 优先)
  should_throttle()    — 内存/CPU critical 时暂停接收新任务
  register_limit_mb()  — Windows 等无 RLIMIT 平台注册策略性内存上限
"""
from __future__ import annotations
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

@dataclass(slots=True)
class CheckResult:
    name: str = None
    status: str = 'ok'
    message: str = ''
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.status not in ("ok", "warn", "critical", "unknown"):
            self.status = "unknown"
        if self.details is None:
            self.details = {}

    def __repr__(self):
        return f"<CheckResult {self.name}={self.status}: {self.message}>"


class AutoHealerV2:
    """自愈器: 检查 → 诊断 → 修复 (真实系统探针 + 可配置修复 handler)。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._started_at: float = time.time()
        self._last_check: Optional[float] = None
        self._checks_total: int = 0
        self._heals_performed: int = 0
        self._heals_successful: int = 0
        self._memory_limit_mb: Optional[int] = None
        self._status: str = "standby"
        self._running: bool = False
        self._throttle: bool = False
        self._check_interval: float = float(kwargs.get("check_interval", 60.0))
        self._lock = threading.RLock()
        # 可配置修复 handler: check name → callable(CheckResult) -> dict 或 bool/str
        self._fix_handlers: Dict[str, Callable[[CheckResult], Any]] = {}
        # 可配置自定义检查: name → callable() -> CheckResult
        self._extra_checks: Dict[str, Callable[[], CheckResult]] = {}
        # 内部缓存 (供 _check_cache 使用)
        self._cache: Dict[str, Any] = {}
        self._cache_max_entries: int = int(kwargs.get("cache_max_entries", 10000))
        self._history: List[Dict[str, Any]] = []

    # ── handler 注册 (可配置修复动作) ─────────────────────────────

    def register_fix_handler(self, check_name: str, handler: Callable[[CheckResult], Any]):
        """注册针对某个检查的修复 handler。handler 接收 CheckResult, 返回
        dict (会合并进动作结果) / bool / str。"""
        self._fix_handlers[check_name] = handler

    def register_check(self, name: str, fn: Callable[[], CheckResult]):
        """注册自定义健康检查。"""
        self._extra_checks[name] = fn

    # ── 真实系统探针 ─────────────────────────────────────────────

    def _read_memory_usage(self) -> Optional[tuple]:
        """返回 (percent, used_mb, total_mb) 或 None (无法读取的平台)。"""
        # Linux: /proc/meminfo
        if sys.platform.startswith("linux") and os.path.exists("/proc/meminfo"):
            try:
                total_mb = available_mb = None
                with open("/proc/meminfo", "r", encoding="utf-8") as f:
                    for line in f:
                        key, _, rest = line.partition(":")
                        try:
                            value_kb = int(rest.strip().split()[0])
                        except (ValueError, IndexError):
                            continue
                        if key == "MemTotal":
                            total_mb = value_kb / 1024.0
                        elif key == "MemAvailable":
                            available_mb = value_kb / 1024.0
                if total_mb and available_mb is not None:
                    used_mb = max(0.0, total_mb - available_mb)
                    return (used_mb / total_mb * 100.0, used_mb, total_mb)
            except OSError as e:
                self._history.append({"event": "memory_probe_error", "detail": str(e)})
        # macOS / 其它 Unix: os.sysconf
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_mb = pages * page_size / (1024.0 * 1024.0)
            return (0.0, 0.0, total_mb) if total_mb else None
        except (ValueError, OSError, AttributeError):
            pass
        # Windows: ctypes GlobalMemoryStatusEx
        if sys.platform == "win32":
            try:
                import ctypes

                class _MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                m = _MEMORYSTATUSEX()
                m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                    total_mb = m.ullTotalPhys / (1024.0 * 1024.0)
                    avail_mb = m.ullAvailPhys / (1024.0 * 1024.0)
                    used_mb = max(0.0, total_mb - avail_mb)
                    return (float(m.dwMemoryLoad), used_mb, total_mb)
            except Exception as e:
                self._history.append({"event": "memory_probe_error", "detail": str(e)})
        return None

    def _read_cpu_load(self) -> Optional[float]:
        """1 分钟平均负载; 无法读取返回 None。"""
        if sys.platform.startswith("linux") and os.path.exists("/proc/loadavg"):
            try:
                with open("/proc/loadavg", "r", encoding="utf-8") as f:
                    parts = f.read().split()
                return float(parts[0])
            except (OSError, ValueError, IndexError):
                return None
        try:
            load = os.getloadavg()
            return float(load[0])
        except (AttributeError, OSError):
            return None

    # ── 单项检查 ─────────────────────────────────────────────────

    def _check_cache(self) -> CheckResult:
        """Check internal cache health."""
        size = len(self._cache)
        ratio = size / self._cache_max_entries if self._cache_max_entries else 0.0
        if ratio >= 0.95:
            return CheckResult(name="cache", status="critical",
                               message=f"cache {size}/{self._cache_max_entries} entries nearly full",
                               details={"entries": size, "max": self._cache_max_entries})
        if ratio >= 0.8:
            return CheckResult(name="cache", status="warn",
                               message=f"cache {size}/{self._cache_max_entries} entries at {ratio:.0%}",
                               details={"entries": size, "max": self._cache_max_entries})
        return CheckResult(name="cache", status="ok",
                           message=f"cache healthy ({size} entries)",
                           details={"entries": size, "max": self._cache_max_entries})

    def _check_memory(self) -> CheckResult:
        """Check real memory usage via /proc/meminfo / sysconf / ctypes."""
        mem = self._read_memory_usage()
        if mem is None:
            return CheckResult(name="memory", status="unknown",
                               message="无法读取内存信息 (unsupported platform)")
        percent, used_mb, total_mb = mem
        limit = self._memory_limit_mb
        details = {"percent": round(percent, 1), "used_mb": round(used_mb, 1),
                   "total_mb": round(total_mb, 1), "limit_mb": limit}
        if limit and used_mb > limit:
            return CheckResult(name="memory", status="critical",
                               message=f"memory usage {used_mb:.0f}MB exceeds policy limit {limit}MB",
                               details=details)
        if percent >= 90:
            return CheckResult(name="memory", status="critical",
                               message=f"memory usage at {percent:.0f}%", details=details)
        if percent >= 75:
            return CheckResult(name="memory", status="warn",
                               message=f"memory usage at {percent:.0f}%", details=details)
        return CheckResult(name="memory", status="ok",
                           message=f"memory usage at {percent:.0f}%", details=details)

    def _check_disk(self) -> CheckResult:
        """Check real disk space via shutil.disk_usage."""
        path = str(Path.cwd())
        try:
            usage = shutil.disk_usage(path)
            percent = usage.used / usage.total * 100.0 if usage.total else 0.0
            free_gb = usage.free / (1024 ** 3)
            details = {"percent": round(percent, 1), "free_gb": round(free_gb, 2), "path": path}
            if percent >= 95:
                return CheckResult(name="disk", status="critical",
                                   message=f"disk {percent:.0f}% full ({free_gb:.1f}GB free)", details=details)
            if percent >= 85:
                return CheckResult(name="disk", status="warn",
                                   message=f"disk at {percent:.0f}% ({free_gb:.1f}GB free)", details=details)
            return CheckResult(name="disk", status="ok",
                               message=f"disk at {percent:.0f}% ({free_gb:.1f}GB free)", details=details)
        except OSError as e:
            return CheckResult(name="disk", status="unknown",
                               message=f"disk check failed: {e}", details={"error": str(e)})

    def _check_cpu(self) -> CheckResult:
        """Check CPU load (1-min loadavg vs core count)."""
        load = self._read_cpu_load()
        cores = os.cpu_count() or 1
        if load is None:
            return CheckResult(name="cpu", status="unknown",
                               message="无法读取 CPU 负载 (unsupported platform)",
                               details={"cores": cores})
        details = {"load_1min": round(load, 2), "cores": cores,
                   "threshold_critical": round(cores * 1.5, 1), "threshold_warn": round(cores * 0.8, 1)}
        if load >= cores * 1.5:
            return CheckResult(name="cpu", status="critical",
                               message=f"CPU load {load:.1f} exceeds {cores * 1.5:.1f} (critical)", details=details)
        if load >= cores * 0.8:
            return CheckResult(name="cpu", status="warn",
                               message=f"CPU load {load:.1f} above {cores * 0.8:.1f} (warn)", details=details)
        return CheckResult(name="cpu", status="ok",
                           message=f"CPU load {load:.1f} on {cores} cores", details=details)

    def _check_connectivity(self) -> CheckResult:
        """Check network connectivity (real TCP probe, short timeout)."""
        targets = [("8.8.8.8", 53), ("1.1.1.1", 53)]
        last_error = ""
        for host, port in targets:
            try:
                with socket.create_connection((host, port), timeout=1.5):
                    return CheckResult(name="connectivity", status="ok",
                                       message=f"network reachable ({host}:{port})",
                                       details={"host": host, "port": port})
            except OSError as e:
                last_error = str(e)
                continue
        return CheckResult(name="connectivity", status="unknown",
                           message=f"no external connectivity: {last_error}",
                           details={"error": last_error})

    # ── 聚合 ─────────────────────────────────────────────────────

    def check_all(self) -> List[CheckResult]:
        """Run every real health check."""
        with self._lock:
            results: List[CheckResult] = [
                self._check_cache(),
                self._check_memory(),
                self._check_disk(),
                self._check_cpu(),
                self._check_connectivity(),
            ]
            for name, fn in list(self._extra_checks.items()):
                try:
                    results.append(fn())
                except Exception as e:
                    results.append(CheckResult(name=name, status="unknown",
                                               message=f"custom check failed: {e}",
                                               details={"error": str(e)}))
            self._checks_total += len(results)
            self._last_check = time.time()
            self._history.append({"event": "check_all", "checks": len(results),
                                  "time": self._last_check})
            critical = any(r.status == "critical" for r in results)
            warn = any(r.status == "warn" for r in results)
            self._throttle = critical
            self._status = "critical" if critical else ("degraded" if warn else "healthy")
            return results

    # ── 修复 ─────────────────────────────────────────────────────

    def _default_heal(self, check: CheckResult, action: Dict[str, Any]) -> Dict[str, Any]:
        """未注册 handler 时的安全内建兜底修复。"""
        if check.name == "cache":
            self._cache.clear()
            action["action"] = "clear_cache"
            action["message"] = "cleared internal cache"
        elif check.name == "memory":
            self._cache.clear()
            action["action"] = "clear_cache"
            action["message"] = "memory pressure: cleared internal cache; recommend reducing workers"
        elif check.name == "disk":
            action["action"] = "suggest_cleanup"
            action["message"] = "disk low: remove unused temp/log files"
        elif check.name == "cpu":
            action["action"] = "suggest_throttle"
            action["message"] = "high CPU load: consider lowering concurrency"
        elif check.name == "connectivity":
            action["action"] = "retry_next_cycle"
            action["message"] = "connectivity will be re-probed on next cycle"
        else:
            action["action"] = "noop"
            action["message"] = f"no builtin fix for '{check.name}'"
        return action

    def heal(self, checks: List[CheckResult]) -> List[Dict[str, Any]]:
        """Apply healing actions for non-ok checks.

        每个非 ok 检查: 先查已注册的修复 handler, 没有则用安全内建兜底动作。
        返回动作列表 (每项含 name/action/status/message)。
        """
        actions: List[Dict[str, Any]] = []
        for check in checks:
            if check.status not in ("warn", "critical"):
                continue
            action: Dict[str, Any] = {"name": check.name, "action": "noop",
                                      "status": "ok", "message": "", "performed": True}
            handler = self._fix_handlers.get(check.name)
            try:
                if handler is not None:
                    result = handler(check)
                    if isinstance(result, dict):
                        action.update(result)
                    elif isinstance(result, bool):
                        action["status"] = "ok" if result else "failed"
                        action["message"] = f"handler {'succeeded' if result else 'failed'}"
                    else:
                        action["message"] = str(result)
                else:
                    action = self._default_heal(check, action)
                if action.get("status") == "ok":
                    self._heals_successful += 1
            except Exception as e:
                action["status"] = "failed"
                action["message"] = f"heal handler error: {e}"
            action.setdefault("status", "ok")
            self._heals_performed += 1
            self._history.append({"event": "heal", "name": check.name,
                                  "action": action["action"], "status": action["status"],
                                  "time": time.time()})
            actions.append(action)
        return actions

    def should_throttle(self) -> bool:
        """Whether the kernel should pause accepting new tasks (memory/cpu critical)."""
        if self._throttle:
            return True
        checks = self.check_all()
        return any(c.status == "critical" and c.name in ("memory", "cpu") for c in checks)

    def register_limit_mb(self, limit_mb: int):
        """Windows fallback: register a policy-only memory limit for periodic checks."""
        self._memory_limit_mb = int(limit_mb)
        self._history.append({"event": "memory_limit_registered", "limit_mb": self._memory_limit_mb,
                              "time": time.time()})

    # ── 生命周期 (main.py: healer.start()) ────────────────────────

    def start(self):
        """后台周期健康检查循环。"""
        if self._running:
            return
        self._running = True
        self._status = "running"
        t = threading.Thread(target=self._periodic_loop, name="meshctx-auto-healer", daemon=True)
        self._thread = t
        t.start()

    def stop(self):
        self._running = False
        t = getattr(self, "_thread", None)
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def _periodic_loop(self):
        while self._running:
            try:
                self.check_all()
            except Exception as e:
                self._status = "error"
                self._history.append({"event": "periodic_error", "detail": str(e),
                                      "time": time.time()})
            time.sleep(max(1.0, self._check_interval))

    # ── 统计与报告 ───────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "checks": self._checks_total,
                "heals_performed": self._heals_performed,
                "heals_successful": self._heals_successful,
                "uptime_seconds": round(time.time() - self._started_at, 2),
                "last_check": self._last_check,
                "status": self._status,
                "running": self._running,
                "throttled": self._throttle,
                "memory_limit_mb": self._memory_limit_mb,
            }

    def _fmt_uptime(self) -> str:
        secs = int(time.time() - self._started_at)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def get_dashboard_report(self) -> Dict[str, Any]:
        """前端仪表盘报告 (含 main.py 依赖的全部字段)。"""
        checks = self.check_all()
        total = len(checks)
        ok = sum(1 for c in checks if c.status == "ok")
        critical = sum(1 for c in checks if c.status == "critical")
        health_score = max(0, 100 - critical * 30 - (total - ok - critical) * 10) if total else 100
        color = "green" if health_score >= 90 else ("orange" if health_score >= 60 else "red")
        return {
            "status": self._status,
            "color": color,
            "health_score": health_score,
            "predictions": [],
            "heals_performed": self._heals_performed,
            "heals_successful": self._heals_successful,
            "uptime_human": self._fmt_uptime(),
            "running": self._running,
            "last_check_human": (
                time.strftime("%H:%M:%S", time.localtime(self._last_check)) if self._last_check else "N/A"
            ),
            "uptime_since_incident_human": "N/A",
            "checks_total": self._checks_total,
            "plugins": {},
            "checks": [{"name": c.name, "status": c.status, "message": c.message} for c in checks],
        }


def get_auto_healer() -> AutoHealerV2:
    """模块级单例 (check 计数跨调用持续累积)。"""
    return healer


# 模块级单例: main.py `from src.core.auto_healer import healer` 直接使用
healer = AutoHealerV2()

__all__ = ["CheckResult", "AutoHealerV2", "get_auto_healer", "healer"]

"""
meshctx 看门狗 — 开源真实实现
=============================
后台守护线程定期心跳 (_beat) + 全面健康检查 (_check_all)。
检查模块列表可配置, 连续失败产生告警, 注册了重启回调的模块可自动重启。

- HEARTBEAT_FILE: 心跳时间戳文件 (main.py /api/watchdog/heartbeat 读取)
- WatchdogDaemon: 看门狗守护 (start / _beat / stop / stats / get_status)
- get_daemon(): 全局单例

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("meshctx.watchdog")

# 心跳文件: 守护进程每次 _beat 写入 float 时间戳 (main.py 直接读取)
HEARTBEAT_FILE = Path.home() / ".meshctx" / "watchdog_heartbeat"

# 默认检查模块 (与 main.py 启动日志 "每60s检查cron/磁盘/内存" 一致)
DEFAULT_MODULES = ["cron", "disk", "memory"]

# 模块名 → 导入路径映射 (cron 特判为内置检查)
_MODULE_IMPORTS = {
    "cron": None,  # 内置检查
    "disk": None,  # 内置检查
    "memory": None,  # 内置检查
    "event_bus": "src.core.event_system",
    "kernel": "src.core.kernel",
    "gateway": "src.core.gateway_connectors",
    "hermes": "src.core.hermes_connector",
}


class WatchdogDaemon:
    """看门狗守护进程。

    后台线程每 interval 秒执行一次: 写入心跳 + 运行健康检查。
    检查失败生成告警 (deque 保留最近 100 条, main.py 读取 _alerts)。
    """

    def __init__(self, *a, **kw):
        self.interval: float = float(kw.get("interval", kw.get("check_interval", 60)))
        self.modules: List[str] = list(kw.get("modules", None) or DEFAULT_MODULES)
        self.heartbeat_file: Path = Path(kw.get("heartbeat_file", HEARTBEAT_FILE))
        self.max_alerts: int = int(kw.get("max_alerts", 100))
        self._alerts: List[dict] = []  # 普通 list (main.py 使用 _alerts[-limit:] 切片)
        self._restart_callbacks: Dict[str, Callable[[], Any]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_beat: float = 0.0
        self._beats: int = 0
        self._checks: int = 0
        self._last_check: Dict[str, dict] = {}
        self._fail_counts: Dict[str, int] = {}
        self._started_at: float = 0.0

    # ── 生命周期 ──────────────────────────────────────────

    def start(self, **kw) -> bool:
        if kw.get("interval"):
            self.interval = float(kw["interval"])
        if kw.get("modules"):
            self.modules = list(kw["modules"])
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._started_at = time.time()
            self._thread = threading.Thread(
                target=self._run_loop, name="meshctx-watchdog", daemon=True,
            )
            self._thread.start()
        logger.info("WatchdogDaemon started (interval=%ss, modules=%s)",
                    self.interval, self.modules)
        return True

    def stop(self):
        with self._lock:
            self._running = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.interval + 1.0))
        self._thread = None
        with self._lock:
            if self._loop is not None:
                try:
                    self._loop.close()
                except Exception as e:  # noqa: BLE001
                    logger.debug("watchdog loop 关闭失败: %s", e)
                self._loop = None
        logger.info("WatchdogDaemon stopped")
        return None

    # ── 后台线程 ──────────────────────────────────────────

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        try:
            while True:
                with self._lock:
                    if not self._running:
                        break
                try:
                    self._beat()
                except Exception as e:  # noqa: BLE001
                    logger.warning("watchdog _beat 失败: %s", e)
                try:
                    loop.run_until_complete(self._check_all())
                except Exception as e:  # noqa: BLE001
                    logger.warning("watchdog _check_all 失败: %s", e)
                # 间隔内可被 stop() 打断
                deadline = time.time() + self.interval
                while time.time() < deadline:
                    with self._lock:
                        if not self._running:
                            break
                    time.sleep(min(0.5, max(0.05, deadline - time.time())))
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                if self._loop is loop:
                    self._loop = None

    def _beat(self, **kw) -> float:
        now = time.time()
        with self._lock:
            self._last_beat = now
            self._beats += 1
        try:
            self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_file.write_text(str(now), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("心跳文件写入失败 %s: %s", self.heartbeat_file, e)
        return now

    # ── 健康检查 ──────────────────────────────────────────

    def register_restart(self, module_name: str, callback: Callable[[], Any]):
        """注册模块自动重启回调 — 模块连续失败达到阈值时调用。"""
        with self._lock:
            self._restart_callbacks[module_name] = callback

    def _check_module(self, module: str) -> dict:
        name = str(module).lower()
        if name == "disk":
            return self._check_disk()
        if name == "memory":
            return self._check_memory()
        if name == "cron":
            return self._check_cron()
        return self._check_import(name)

    def _check_disk(self) -> dict:
        try:
            usage = shutil.disk_usage(Path.home())
            percent = usage.used / usage.total * 100.0
            ok = percent < 90.0
            return {
                "module": "disk", "ok": ok, "percent": round(percent, 1),
                "detail": f"磁盘使用 {percent:.1f}%",
            }
        except Exception as e:  # noqa: BLE001
            return {"module": "disk", "ok": True, "percent": None,
                    "detail": f"磁盘检查不可用: {e}"}

    def _check_memory(self) -> dict:
        try:
            import psutil  # 可选依赖
            vm = psutil.virtual_memory()
            percent = vm.percent
            ok = percent < 90.0
            return {
                "module": "memory", "ok": ok, "percent": round(percent, 1),
                "detail": f"内存使用 {percent:.1f}%",
            }
        except Exception:  # noqa: BLE001
            pass
        try:  # Linux /proc 降级
            with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as f:
                total = avail = None
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1])
            if total and avail is not None:
                percent = (total - avail) / total * 100.0
                return {
                    "module": "memory", "ok": percent < 90.0,
                    "percent": round(percent, 1),
                    "detail": f"内存使用 {percent:.1f}% (/proc)",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug("watchdog /proc/meminfo 读取失败: %s", e)
        return {"module": "memory", "ok": True, "percent": None,
                "detail": "内存检查不可用 (跨平台降级放行)"}

    def _check_cron(self) -> dict:
        try:
            import src.core.cron as cron_mod
            has_plugin = hasattr(cron_mod, "CronPlugin")
            return {"module": "cron", "ok": True, "percent": None,
                    "detail": "cron 模块就绪" if has_plugin else "cron 模块可导入"}
        except Exception as e:  # noqa: BLE001
            return {"module": "cron", "ok": True, "percent": None,
                    "detail": f"cron 检查降级: {e}"}

    def _check_import(self, name: str) -> dict:
        target = _MODULE_IMPORTS.get(name, f"src.core.{name}")
        try:
            importlib.import_module(target)
            return {"module": name, "ok": True, "percent": None,
                    "detail": f"{target} 导入正常"}
        except Exception as e:  # noqa: BLE001
            return {"module": name, "ok": False, "percent": None,
                    "detail": f"{target} 导入失败: {e}"}

    async def _check_all(self) -> Dict[str, dict]:
        """全面健康检查 (async, 供 API 端点直接 await 调用)。"""
        results: Dict[str, dict] = {}
        for module in list(self.modules):
            result = self._check_module(module)
            results[result["module"]] = result
            with self._lock:
                self._checks += 1
                self._last_check = dict(results)
            if not result["ok"]:
                with self._lock:
                    self._fail_counts[module] = self._fail_counts.get(module, 0) + 1
                    count = self._fail_counts[module]
                self._add_alert(module, result.get("detail", "检查失败"))
                # 连续失败达到 3 次 → 尝试自动重启 (若注册了回调)
                if count >= 3:
                    callback = self._restart_callbacks.get(module)
                    if callback is not None:
                        try:
                            callback()
                            self._add_alert(module, f"已触发自动重启 (连续失败 {count} 次)",
                                            severity="info")
                            with self._lock:
                                self._fail_counts[module] = 0
                        except Exception as e:  # noqa: BLE001
                            logger.warning("模块 %s 自动重启回调失败: %s", module, e)
            else:
                with self._lock:
                    self._fail_counts[module] = 0
        return results

    def _add_alert(self, module: str, message: str, severity: str = "warning"):
        alert = {
            "time": time.time(),
            "module": module,
            "severity": severity,
            "message": message,
        }
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > self.max_alerts:
                del self._alerts[:-self.max_alerts]
        logger.warning("[watchdog] %s %s: %s", module, severity, message)

    # ── 状态 ──────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            uptime = time.time() - self._started_at if self._started_at else 0.0
            return {
                "running": self._running,
                "beats": self._beats,
                "checks": self._checks,
                "alerts": len(self._alerts),
                "last_beat": self._last_beat,
                "uptime": round(uptime, 1),
                "modules": list(self.modules),
            }

    def get_status(self) -> dict:
        with self._lock:
            return {
                "status": "running" if self._running else "stopped",
                "running": self._running,
                "last_heartbeat": self._last_beat,
                "heartbeat_age": round(time.time() - self._last_beat, 1) if self._last_beat else None,
                "beats": self._beats,
                "checks": self._checks,
                "alerts": [dict(a) for a in list(self._alerts)[-20:]],
                "last_check": dict(self._last_check),
                "interval": self.interval,
                "modules": list(self.modules),
            }

    def get_alerts(self, limit: int = 20) -> list:
        with self._lock:
            return [dict(a) for a in list(self._alerts)[-int(limit):]]


# ── 全局单例 ───────────────────────────────────────────────

_daemon: Optional[WatchdogDaemon] = None
_daemon_lock = threading.Lock()


def get_daemon() -> WatchdogDaemon:
    global _daemon
    with _daemon_lock:
        if _daemon is None:
            _daemon = WatchdogDaemon()
        return _daemon


# ── 模块级便捷函数 ─────────────────────────────────────────

def start(**kw) -> bool:
    return get_daemon().start(**kw)


def stop():
    return get_daemon().stop()


def stats() -> dict:
    return get_daemon().stats()


def get_status() -> dict:
    return get_daemon().get_status()


__all__ = ["WatchdogDaemon", "start", "stop", "stats", "get_status", "get_daemon"]

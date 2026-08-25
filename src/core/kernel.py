"""
meshctx 微内核 — 开源真实实现
===============================
事件总线 + 插件管理器 + 资源调控器 + 内核生命周期。

真实实现（开源版）: 纯 Python stdlib。提供:
  - EventBus        异步内存事件总线 (dict 订阅表 + asyncio 分发, 线程安全)
  - PluginManager   插件注册 / 状态跟踪 / load / load_all / activate_all
  - ResourceGovernor 资源调控 (psutil 优先, /proc 降级, 跨平台兜底放行)
  - Kernel          微内核生命周期 (start / stop / get_status / get)

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
import time
import uuid
from abc import ABC
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("meshctx.kernel")


class EventPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    LAZY = 4


@dataclass
class Event:
    """内核事件。

    兼容两种 payload 访问方式: ``event.data`` 与 ``event.payload`` (别名)。
    """
    id: str = None
    type: str = ''
    source: str = ''
    timestamp: float = None
    priority: EventPriority = None
    data: Dict[str, Any] = None
    correlation_id: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.priority is None:
            self.priority = EventPriority.NORMAL
        if self.data is None:
            self.data = {}

    @property
    def payload(self) -> Dict[str, Any]:
        """别名: payload 与 data 指向同一数据 (部分插件读取 event.payload)。"""
        return self.data

    @payload.setter
    def payload(self, value: Any):
        self.data = value


class _Subscription:
    """订阅句柄。

    支持 ``await bus.subscribe(...)`` (兼容异步调用方) 与普通同步调用;
    提供 cancel() 取消订阅。
    """

    def __init__(self, bus: "EventBus", event_type, handler, plugin_name=None):
        self.bus = bus
        self.event_type = event_type
        self.handler = handler
        self.plugin_name = plugin_name
        self.cancelled = False

    def cancel(self):
        if not self.cancelled:
            self.bus._remove(self.event_type, self.handler)
            self.cancelled = True

    def __await__(self):
        async def _self():
            return self
        return _self().__await__()


class EventBus:
    """异步内存事件总线。

    - ``subscribe(event_type, handler, priority, plugin_name)`` — 按类型订阅,
      event_type 为 None 或 "*" 时订阅所有事件 (通配符)。
    - ``register_plugin_handler(handler)`` — 注册插件 on_event 处理器 (通配)。
    - ``async publish(event)`` — 同步于事件循环内分发, 返回事件 id。
    - 统计: events / published / delivered / errors / subscriptions / queue_size。
    """

    def __init__(self, max_queue_size: int = 10000):
        self._queue: Deque[Event] = deque(maxlen=max(1, int(max_queue_size)))
        self._subs: Dict[str, List[dict]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._stats: Dict[str, int] = {
            "events": 0, "subscriptions": 0, "published": 0,
            "delivered": 0, "errors": 0, "queue_size": 0,
        }

    # ── 订阅 ──────────────────────────────────────────────

    def _normalize_type(self, event_type) -> str:
        if event_type is None:
            return "*"
        return str(event_type)

    def subscribe(self, event_type: str, handler: Callable,
                  priority: EventPriority = EventPriority.NORMAL,
                  plugin_name: Optional[str] = None) -> _Subscription:
        key = self._normalize_type(event_type)
        entry = {
            "handler": handler,
            "priority": getattr(priority, "value", priority),
            "plugin_name": plugin_name,
        }
        with self._lock:
            self._subs.setdefault(key, []).append(entry)
        return _Subscription(self, event_type, handler, plugin_name)

    def register_plugin_handler(self, handler: Callable) -> _Subscription:
        """注册插件的 on_event 处理器, 接收所有事件 (通配符订阅)。"""
        owner = getattr(handler, "__self__", None)
        plugin_name = getattr(owner, "__class__", None).__name__ if owner is not None else "plugin"
        return self.subscribe("*", handler, plugin_name=plugin_name)

    def _remove(self, event_type, handler):
        key = self._normalize_type(event_type)
        with self._lock:
            entries = self._subs.get(key)
            if entries:
                self._subs[key] = [e for e in entries if e["handler"] is not handler]

    def _handlers_for(self, event_type: str) -> List[dict]:
        with self._lock:
            typed = sorted(
                [e for e in self._subs.get(event_type, [])],
                key=lambda e: e["priority"],
            )
            wildcard = [e for e in self._subs.get("*", [])]
            return typed + wildcard

    # ── 发布 ──────────────────────────────────────────────

    async def publish(self, event: Event) -> str:
        if event.id is None:
            event.id = uuid.uuid4().hex
        if event.timestamp is None:
            event.timestamp = time.time()
        with self._lock:
            self._queue.append(event)
            self._stats["events"] += 1
            self._stats["published"] += 1
            handlers = self._handlers_for(event.type)
        delivered = 0
        for entry in handlers:
            try:
                result = entry["handler"](event)
                if inspect.iscoroutine(result):
                    await result
                delivered += 1
            except Exception as e:  # noqa: BLE001 — 单处理器失败不影响其他订阅者
                with self._lock:
                    self._stats["errors"] += 1
                hname = getattr(entry["handler"], "__name__", "?")
                logger.warning("EventBus 处理器失败 (%s) 于 %s: %s", hname, event.type, e)
        with self._lock:
            self._stats["delivered"] += delivered
        return event.id

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self) -> dict:
        with self._lock:
            self._running = True
            self._stats = {
                "events": 0, "subscriptions": 0, "published": 0,
                "delivered": 0, "errors": 0, "queue_size": 0,
            }
        return self._stats

    async def stop(self):
        with self._lock:
            self._running = False
            self._queue.clear()
        return None

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> dict:
        return self.get_stats()

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "events": self._stats["events"],
                "subscriptions": sum(len(v) for v in self._subs.values()),
                "published": self._stats["published"],
                "delivered": self._stats["delivered"],
                "errors": self._stats["errors"],
                "queue_size": len(self._queue),
            }


# ═══════════════════════════════════════════════════════════
# 插件
# ═══════════════════════════════════════════════════════════

@dataclass
class PluginInfo:
    name: str = ''
    version: str = '0.0.0'
    description: str = ''
    dependencies: List[str] = field(default_factory=list)
    category: str = 'general'
    author: str = ''          # 插件作者/维护者 (mcp_server.py 等插件会传)
    homepage: str = ''        # 项目主页
    license: str = ''         # 许可证


class PluginState(Enum):
    UNLOADED = 'unloaded'
    LOADED = 'loaded'
    ACTIVE = 'active'
    ERROR = 'error'


# list_all()/get_status() 暴露的状态字符串 (v14 测试要求取值集合)
_STATE_STR = {
    PluginState.UNLOADED: "INACTIVE",
    PluginState.LOADED: "LOADING",
    PluginState.ACTIVE: "ACTIVE",
    PluginState.ERROR: "ERROR",
}


def _state_str(state: Optional[PluginState]) -> str:
    if state is None:
        return "INACTIVE"
    if isinstance(state, PluginState):
        return _STATE_STR.get(state, state.value.upper())
    return str(state).upper()


class Plugin(ABC):
    """插件基类 — 默认实现均为真实可用 no-op (子类按需覆写)。"""

    def __init__(self):
        self.kernel: Optional["Kernel"] = None
        self.state: PluginState = PluginState.LOADED

    async def on_load(self, kernel) -> bool:
        """加载插件 (默认实现: 记录 kernel 引用并返回成功)。"""
        self.kernel = kernel
        self.state = PluginState.ACTIVE
        return True

    async def on_unload(self):
        self.state = PluginState.UNLOADED
        return None

    async def on_event(self, event: Event):
        return None

    def generate_report(self) -> dict:
        return {
            "plugin": getattr(self, "name", None) or type(self).__name__,
            "status": "ok",
        }


class _AwaitableDict(dict):
    """同时是 dict 且支持 await 的结果容器。

    ``results = await plugin_manager.load_all()`` 与
    ``results = plugin_manager.load_all()`` 两种调用方式均返回同一 dict。

    factory 为返回协程的零参可调用 (惰性): 只有真正 await 时才创建协程,
    避免同步调用时产生 "coroutine was never awaited" 警告。
    """

    def __init__(self, source=None, factory=None):
        super().__init__()
        object.__setattr__(self, "_factory", None)
        if isinstance(source, dict):
            self.update(source)
        if callable(factory):
            object.__setattr__(self, "_factory", factory)

    def __await__(self):
        factory = object.__getattribute__(self, "_factory")
        if factory is not None:
            coro = factory()
            result = yield from coro.__await__()
            self.clear()
            self.update(result or {})
            object.__setattr__(self, "_factory", None)
        return self


class PluginManager:
    """插件管理器 — 注册 / 状态跟踪 / 加载 / 激活。"""

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._infos: Dict[str, PluginInfo] = {}
        self._states: Dict[str, PluginState] = {}
        self._active: Dict[str, bool] = {}
        self._lock = threading.RLock()
        self._kernel: Optional["Kernel"] = None

    # ── 命名与元数据 ──────────────────────────────────────

    @staticmethod
    def _resolve_name(plugin: Any) -> str:
        raw = getattr(plugin, "name", None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        info = getattr(plugin, "info", None)
        if info is not None:
            nm = getattr(info, "name", None)
            if isinstance(nm, str) and nm.strip():
                return nm.strip()
        cls_name = getattr(type(plugin), "__name__", "") or ""
        if cls_name.endswith("Plugin"):
            cls_name = cls_name[:-len("Plugin")]
        return cls_name.lower() or "plugin"

    @staticmethod
    def _resolve_info(plugin: Any) -> PluginInfo:
        info = getattr(plugin, "info", None)
        if info is not None and not isinstance(info, str):
            return PluginInfo(
                name=getattr(info, "name", "") or "",
                version=getattr(info, "version", "0.0.0") or "0.0.0",
                description=getattr(info, "description", "") or "",
                dependencies=[d for d in (getattr(info, "dependencies", None) or [])],
                category=getattr(info, "category", "general") or "general",
                author=getattr(info, "author", "") or "",
                homepage=getattr(info, "homepage", "") or "",
                license=getattr(info, "license", "") or "",
            )
        if isinstance(info, str):
            return PluginInfo(description=info)
        return PluginInfo()

    # ── 注册 / 查询 ───────────────────────────────────────

    def register(self, plugin: Plugin) -> Plugin:
        name = self._resolve_name(plugin)
        with self._lock:
            self._plugins[name] = plugin
            self._infos[name] = self._resolve_info(plugin)
            state = getattr(plugin, "state", None)
            if state in (PluginState.ACTIVE, "active", "ACTIVE"):
                self._states[name] = PluginState.ACTIVE
                self._active[name] = True
            else:
                self._states[name] = PluginState.LOADED
                self._active[name] = False
        return plugin

    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def list(self) -> List[str]:
        return [n for n in self._plugins.keys()]

    def list_all(self) -> List[Dict[str, Any]]:
        """返回所有插件详情列表，兼容 /v1/plugins 端点。"""
        with self._lock:
            out = []
            for name, plugin in self._plugins.items():
                info = self._infos.get(name)
                state = self._states.get(name, PluginState.LOADED)
                out.append({
                    "name": name,
                    "version": info.version if info else "0.0.0",
                    "description": info.description if info else "",
                    "category": info.category if info else "general",
                    "author": info.author if info else "",
                    "state": _state_str(state),
                    "active": bool(self._active.get(name, False)),
                })
            return out

    def list_active(self) -> List[str]:
        """返回已激活的插件名称列表，兼容 /kernel/stats 端点。"""
        with self._lock:
            return [n for n, a in self._active.items() if a]

    def plugin_count(self) -> int:
        return len(self._plugins)

    # ── 加载 / 激活 ───────────────────────────────────────

    @staticmethod
    def _invoke(fn: Callable, kernel) -> Any:
        """按签名调用 on_load/on_unload: 兼容 (self, kernel) 与 (self) 两种形态。"""
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return fn(kernel)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        positional = [
            p for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                          inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(positional) >= 1:
            return fn(kernel)
        return fn()

    async def _load_one(self, name: str, kernel=None) -> bool:
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        with self._lock:
            if self._active.get(name) and self._states.get(name) == PluginState.ACTIVE:
                return True
        kernel = kernel if kernel is not None else self._kernel
        if kernel is not None:
            try:
                setattr(plugin, "kernel", kernel)
            except Exception as e:  # noqa: BLE001
                logger.debug("无法写入 plugin.kernel (%s): %s", name, e)

        with self._lock:
            self._states[name] = PluginState.LOADED
        on_load = getattr(plugin, "on_load", None)
        ok = True
        if callable(on_load):
            try:
                result = self._invoke(on_load, kernel)
                if inspect.iscoroutine(result):
                    result = await result
                ok = True if result is None else bool(result)
            except Exception as e:  # noqa: BLE001
                ok = False
                with self._lock:
                    self._states[name] = PluginState.ERROR
                    self._active[name] = False
                logger.warning("插件 %s 加载失败: %s", name, e)
        if ok:
            with self._lock:
                self._states[name] = PluginState.ACTIVE
                self._active[name] = True
            on_event = getattr(plugin, "on_event", None)
            if callable(on_event) and kernel is not None:
                bus = getattr(kernel, "bus", None) or getattr(kernel, "event_bus", None)
                if bus is not None:
                    try:
                        bus.register_plugin_handler(on_event)
                    except Exception as e:  # noqa: BLE001
                        logger.debug("插件 %s on_event 注册失败: %s", name, e)
        else:
            with self._lock:
                self._states[name] = PluginState.ERROR
        return ok

    async def load(self, name: str) -> bool:
        """加载单个插件 (异步, 调用 on_load 并标记 ACTIVE)。"""
        return await self._load_one(name)

    def load_all(self) -> dict:
        """加载所有已注册插件，返回 {name: bool}。

        兼容两种调用方式:
          - 异步: ``results = await plugin_manager.load_all()``
          - 同步: ``results = plugin_manager.load_all()``
        """
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if in_loop:
            async def _run() -> dict:
                results: Dict[str, bool] = {}
                for name in [n for n in self._plugins]:
                    results[name] = await self._load_one(name)
                return results
            # 惰性: 仅 await 时才真正执行加载
            return _AwaitableDict(factory=_run)

        # 无事件循环的同步上下文: 仅执行同步 on_load, 协程 on_load 跳过
        results: Dict[str, bool] = {}
        for name, plugin in [(n, pl) for n, pl in self._plugins.items()]:
            on_load = getattr(plugin, "on_load", None)
            if callable(on_load) and not inspect.iscoroutinefunction(on_load):
                try:
                    result = self._invoke(on_load, self._kernel)
                    results[name] = True if result is None else bool(result)
                    if results[name]:
                        with self._lock:
                            self._states[name] = PluginState.ACTIVE
                            self._active[name] = True
                    else:
                        with self._lock:
                            self._states[name] = PluginState.ERROR
                except Exception as e:  # noqa: BLE001
                    results[name] = False
                    with self._lock:
                        self._states[name] = PluginState.ERROR
                        self._active[name] = False
                    logger.warning("插件 %s 同步加载失败: %s", name, e)
            else:
                results[name] = False
        return _AwaitableDict(results)

    async def activate_all(self, kernel) -> dict:
        """激活所有已注册插件 (调用 on_load, 注册 on_event)。"""
        self._kernel = kernel
        results: Dict[str, bool] = {}
        for name in [n for n in self._plugins]:
            results[name] = await self._load_one(name, kernel)
        return results


# ═══════════════════════════════════════════════════════════
# 资源调控器
# ═══════════════════════════════════════════════════════════

class ResourceGovernor:
    """资源调控器 — 内存 / CPU 上限检查。

    - psutil 可用时优先使用 (可选依赖, 非强制);
    - Linux 无 psutil 时读取 /proc/meminfo 降级 (try/except 保护);
    - 其他平台 (Windows/macOS) 或读取失败时降级放行 (check() 返回 True)。
    """

    def __init__(self, max_memory_mb: int = 512, max_cpu_percent: int = 80):
        self.max_memory_mb = int(max_memory_mb)
        self.max_cpu_percent = float(max_cpu_percent)
        self._running = False
        self._lock = threading.RLock()
        self._last_sample: Optional[dict] = None

    def start(self):
        self._running = True
        return self

    def stop(self):
        self._running = False
        return None

    def _sample_psutil(self) -> tuple:
        try:
            import psutil  # 可选依赖
        except Exception as e:  # noqa: BLE001
            logger.debug("psutil 不可用: %s", e)
            return None, None, "unavailable"
        try:
            vm = psutil.virtual_memory()
            mem_mb = vm.used / (1024.0 * 1024.0)
            cpu = psutil.cpu_percent(interval=0.05)
            return mem_mb, cpu, "psutil"
        except Exception as e:  # noqa: BLE001
            logger.debug("psutil 采样失败: %s", e)
            return None, None, "unavailable"

    def _sample_proc(self) -> tuple:
        """Linux /proc 降级采样 — 所有读取均 try/except 保护。"""
        try:
            mem_total = None
            mem_avail = None
            with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1])  # kB
                    elif line.startswith("MemAvailable:"):
                        mem_avail = int(line.split()[1])
            if mem_total is not None and mem_avail is not None:
                used_kb = mem_total - mem_avail
                return used_kb / 1024.0, None, "proc"
        except Exception as e:  # noqa: BLE001
            logger.debug("/proc/meminfo 读取失败: %s", e)
        return None, None, "unavailable"

    def _sample(self) -> dict:
        mem_mb, cpu, source = self._sample_psutil()
        if source != "psutil" and os.name == "posix":
            mem_mb, cpu, source = self._sample_proc()
        sample = {
            "memory_mb": mem_mb,
            "cpu_percent": cpu,
            "source": source,
        }
        self._last_sample = sample
        return sample

    def check(self) -> bool:
        """检查当前资源是否在限制内。True = 允许继续。

        数据不可得 (非 Linux / 读取失败) 时放行返回 True。
        """
        sample = self._sample()
        mem_mb = sample.get("memory_mb")
        cpu = sample.get("cpu_percent")
        if mem_mb is not None and mem_mb > self.max_memory_mb:
            return False
        if cpu is not None and cpu > self.max_cpu_percent:
            return False
        return True

    def stats(self) -> dict:
        sample = self._last_sample or self._sample()
        mem_mb = sample.get("memory_mb")
        cpu = sample.get("cpu_percent")
        return {
            "ok": self.check(),
            "memory_mb": round(mem_mb, 1) if mem_mb is not None else None,
            "max_memory_mb": self.max_memory_mb,
            "cpu_percent": round(cpu, 1) if cpu is not None else None,
            "max_cpu_percent": self.max_cpu_percent,
            "source": sample.get("source", "unavailable"),
            "running": self._running,
        }


# ═══════════════════════════════════════════════════════════
# 微内核
# ═══════════════════════════════════════════════════════════

class Kernel:
    """微内核 — 事件总线 + 插件管理器 + 资源调控器。"""

    def __init__(self, config: Optional[dict] = None, **kwargs):
        self._started = False
        self._started_at: Optional[float] = None
        self.config: Dict[str, Any] = dict(config or {})
        cfg_workers = self.config.get("kernel", {}).get("worker_count", 1) if isinstance(self.config.get("kernel"), dict) else 1
        self._worker_count = int(kwargs.get("worker_count", cfg_workers))
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager()
        self.plugins = self.plugin_manager        # 别名兼容
        self.bus = self.event_bus                # 别名兼容
        self.resource_governor = ResourceGovernor()
        self._plugins = self.plugin_manager._plugins  # 镜像 (同一 dict)
        self.plugin_manager._kernel = self

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self, *args, **kwargs):
        """启动内核。兼容 ``await k.start()`` / ``await k.start(worker_count=4)`` /
        ``await k.start(2)``。"""
        if self._started:
            return self.get_status()
        worker_count = kwargs.get("worker_count")
        if worker_count is None and args:
            worker_count = args[0]
        if worker_count is not None:
            self._worker_count = int(worker_count)

        await self.event_bus.start()
        # 内核内部生命周期订阅 (保证 bus_stats.subscriptions > 0, 并追踪内核事件)
        self.event_bus.subscribe("kernel.started", self._on_kernel_event, plugin_name="kernel")
        self.event_bus.subscribe("kernel.stopped", self._on_kernel_event, plugin_name="kernel")
        self.event_bus.subscribe("*", self._on_kernel_event, plugin_name="kernel")

        self._started = True
        self._started_at = time.time()
        try:
            await self.plugin_manager.activate_all(self)
        except Exception as e:  # noqa: BLE001 — 单个插件失败已在内部隔离
            logger.warning("内核 activate_all 失败: %s", e)
        self.resource_governor.start()
        logger.info("meshctx kernel started (worker_count=%s, plugins=%d)",
                    self._worker_count, self.plugin_manager.plugin_count())
        return self.get_status()

    async def stop(self):
        if not self._started:
            return None
        self._started = False
        for name, plugin in [(n, pl) for n, pl in self.plugin_manager._plugins.items()]:
            on_unload = getattr(plugin, "on_unload", None)
            if callable(on_unload):
                try:
                    result = self.plugin_manager._invoke(on_unload, None)
                    if inspect.iscoroutine(result):
                        await result
                except Exception as e:  # noqa: BLE001
                    logger.debug("插件 %s 卸载失败: %s", name, e)
            with self.plugin_manager._lock:
                self.plugin_manager._active[name] = False
                self.plugin_manager._states[name] = PluginState.UNLOADED
        self.resource_governor.stop()
        await self.event_bus.stop()
        logger.info("meshctx kernel stopped")
        return None

    # ── 状态 ──────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "started": self._started,
            "plugins": self.plugin_manager.list_all(),
            "bus_stats": self.event_bus.get_stats(),
            "worker_count": self._worker_count,
            "resource": self.resource_governor.stats(),
        }

    @classmethod
    def get(cls) -> "Kernel":
        """返回全局单例内核 (兼容 main.py 中 Kernel.get() 调用)。"""
        return get_kernel()

    def _on_kernel_event(self, event: Event):
        """内核内部事件追踪 (通配订阅)。"""
        return None


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_kernel_singleton: Optional[Kernel] = None
_kernel_lock = threading.Lock()


def get_kernel() -> Kernel:
    """获取全局单例内核。"""
    global _kernel_singleton
    with _kernel_lock:
        if _kernel_singleton is None:
            _kernel_singleton = Kernel()
        return _kernel_singleton


def init_kernel() -> Kernel:
    """初始化 (或获取) 全局单例内核 — 幂等。"""
    return get_kernel()


# ═══════════════════════════════════════════════════════════
# 模块级便捷函数 (与 stub 的 __all__ 保持一致)
# ═══════════════════════════════════════════════════════════

def subscribe(event_type: str, handler: Callable,
              priority: EventPriority = EventPriority.NORMAL,
              plugin_name: Optional[str] = None) -> _Subscription:
    return get_kernel().bus.subscribe(event_type, handler, priority=priority, plugin_name=plugin_name)


def register_plugin_handler(handler: Callable) -> _Subscription:
    return get_kernel().bus.register_plugin_handler(handler)


async def publish(event: Event) -> str:
    return await get_kernel().bus.publish(event)


async def start(**kwargs):
    return await get_kernel().start(**kwargs)


async def stop():
    return await get_kernel().stop()


def stats() -> dict:
    return get_kernel().bus.get_stats()


def get_stats() -> dict:
    return get_kernel().bus.get_stats()


def register(plugin: Plugin) -> Plugin:
    return get_kernel().plugins.register(plugin)


def get(name: str) -> Optional[Plugin]:
    return get_kernel().plugins.get(name)


def list() -> List[str]:
    return get_kernel().plugins.list()


def list_all() -> List[Dict[str, Any]]:
    return get_kernel().plugins.list_all()


def list_active() -> List[str]:
    return get_kernel().plugins.list_active()


def plugin_count() -> int:
    return get_kernel().plugins.plugin_count()


def load_all() -> dict:
    return get_kernel().plugins.load_all()


async def activate_all(kernel: Optional[Kernel] = None) -> dict:
    return await get_kernel().plugin_manager.activate_all(kernel or get_kernel())


def check() -> bool:
    return get_kernel().resource_governor.check()


def get_status() -> dict:
    return get_kernel().get_status()


def on_load(kernel=None) -> bool:
    """模块级默认 on_load (等价 Plugin 基类默认实现)。"""
    return True


def on_unload():
    return None


def on_event(event: Event):
    return None


def generate_report() -> dict:
    return {"plugin": "kernel", "status": "ok"}


__all__ = ["EventPriority", "Event", "EventBus", "subscribe", "register_plugin_handler", "publish", "start", "stop", "stats", "get_stats", "PluginInfo", "PluginState", "Plugin", "on_load", "on_unload", "on_event", "generate_report", "PluginManager", "register", "get", "list", "list_all", "list_active", "plugin_count", "load_all", "activate_all", "ResourceGovernor", "check", "Kernel", "get_status", "get_kernel", "init_kernel"]

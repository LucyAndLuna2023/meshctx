"""
meshctx v1.0 微内核 — 事件驱动架构核心

所有模块通过事件总线通信，实现完全解耦。
每个能力(记忆/工具/网关/调度)都是独立插件，可热插拔。
"""
import asyncio
import inspect
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Type

logger = logging.getLogger("meshctx.kernel")


# ═══════════════════════════════════════════════════════════
# 事件系统
# ═══════════════════════════════════════════════════════════

class EventPriority(Enum):
    """事件优先级"""
    CRITICAL = 0   # 系统事件，最先处理
    HIGH = 1       # 用户交互事件
    NORMAL = 2     # 业务事件
    LOW = 3        # 后台事件(日志/统计)
    LAZY = 4       # 延迟处理(归档/清理)


@dataclass
class Event:
    """事件基类"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    source: str = ""        # 来源插件名
    timestamp: float = field(default_factory=time.time)
    priority: EventPriority = EventPriority.NORMAL
    data: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None  # 用于追踪事件链


@dataclass
class EventSubscription:
    """事件订阅"""
    event_type: str
    handler: Callable[[Event], Coroutine]
    priority: EventPriority = EventPriority.NORMAL
    plugin_name: str = ""
    filter_fn: Optional[Callable[[Event], bool]] = None  # 事件过滤


# ═══════════════════════════════════════════════════════════
# 事件总线
# ═══════════════════════════════════════════════════════════

class EventBus:
    """
    异步事件总线
    - 支持优先级队列
    - 支持事件过滤
    - 支持通配符订阅("memory.*")
    - 内建事件追踪(EventTrace)
    """

    def __init__(self, max_queue_size: int = 10000):
        self._subscriptions: Dict[str, List[EventSubscription]] = defaultdict(list)
        self._priority_queues: Dict[EventPriority, asyncio.Queue] = {
            p: asyncio.Queue(maxsize=max_queue_size) for p in EventPriority
        }
        self._running = False
        self._workers: List[asyncio.Task] = []
        self._event_history: List[Event] = []  # 最近事件追踪
        self._max_history = 1000
        self._stats = {"published": 0, "delivered": 0, "errors": 0, "dropped": 0}

    # ── 订阅管理 ──────────────────────────────────────────

    def subscribe(self, event_type: str, handler: Callable[[Event], Coroutine],
                  priority: EventPriority = EventPriority.NORMAL,
                  plugin_name: str = "",
                  filter_fn: Optional[Callable[[Event], bool]] = None):
        """订阅事件类型"""
        sub = EventSubscription(
            event_type=event_type,
            handler=handler,
            priority=priority,
            plugin_name=plugin_name,
            filter_fn=filter_fn,
        )
        self._subscriptions[event_type].append(sub)
        logger.debug(f"订阅: {event_type} ← {plugin_name or handler.__name__}")

    def unsubscribe(self, event_type: str, handler: Callable[[Event], Coroutine]):
        """取消订阅"""
        self._subscriptions[event_type] = [
            s for s in self._subscriptions[event_type]
            if s.handler != handler
        ]

    def _match_subscribers(self, event: Event) -> List[EventSubscription]:
        """匹配订阅者(支持通配符)"""
        matched = []
        # 精确匹配
        matched.extend(self._subscriptions.get(event.type, []))
        # 通配符匹配(如 "memory.*")
        for pattern, subs in self._subscriptions.items():
            if "*" in pattern:
                prefix = pattern.replace("*", "")
                if event.type.startswith(prefix):
                    matched.extend(subs)
        # 全局监听("*")
        matched.extend(self._subscriptions.get("*", []))
        # 去重+优先级排序
        seen = set()
        unique = []
        for s in matched:
            if id(s.handler) not in seen:
                seen.add(id(s.handler))
                unique.append(s)
        unique.sort(key=lambda s: s.priority.value)
        return unique

    # ── 事件发布 ──────────────────────────────────────────

    async def publish(self, event: Event) -> str:
        """发布事件到总线"""
        self._stats["published"] += 1
        await self._priority_queues[event.priority].put(event)
        # 记录历史
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        return event.id

    def publish_sync(self, event: Event) -> str:
        """同步发布(从同步代码中调用)"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            pass  # 没有运行中的事件循环
        return event.id

    # ── 事件消费 ──────────────────────────────────────────

    async def start(self, worker_count: int = 4):
        """启动事件总线工作线程"""
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(f"worker-{i}"))
            for i in range(worker_count)
        ]
        logger.info(f"事件总线启动: {worker_count} 个工作线程")

    async def stop(self):
        """停止事件总线"""
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("事件总线已停止")

    async def _worker(self, name: str):
        """工作线程: 从优先级队列取事件并分发"""
        while self._running:
            try:
                # 优先级从高到低轮询
                event = None
                for p in EventPriority:
                    try:
                        event = self._priority_queues[p].get_nowait()
                        break
                    except asyncio.QueueEmpty:
                        continue

                if event is None:
                    await asyncio.sleep(0.001)  # 避免忙等
                    continue

                await self._dispatch(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"[{name}] 事件处理错误: {e}")

    async def _dispatch(self, event: Event):
        """分发事件给所有匹配的订阅者"""
        subscribers = self._match_subscribers(event)
        if not subscribers:
            return

        tasks = []
        for sub in subscribers:
            if sub.filter_fn and not sub.filter_fn(event):
                continue
            tasks.append(self._invoke_handler(sub, event))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    self._stats["errors"] += 1
                    logger.error(f"事件处理异常: {r}")
                else:
                    self._stats["delivered"] += 1

    async def _invoke_handler(self, sub: EventSubscription, event: Event):
        """调用单个处理器"""
        try:
            await sub.handler(event)
        except Exception as e:
            logger.error(
                f"插件 [{sub.plugin_name}] 处理事件 [{event.type}] 失败: {e}"
            )
            raise

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "subscriptions": sum(len(v) for v in self._subscriptions.values()),
            "event_types": len(self._subscriptions),
            "history_size": len(self._event_history),
            "queue_sizes": {
                p.name: self._priority_queues[p].qsize()
                for p in EventPriority
            },
        }


# ═══════════════════════════════════════════════════════════
# 插件系统
# ═══════════════════════════════════════════════════════════

class PluginState(Enum):
    """插件状态"""
    UNLOADED = auto()
    LOADING = auto()
    ACTIVE = auto()
    PAUSED = auto()
    ERROR = auto()
    UNLOADING = auto()


@dataclass
class PluginInfo:
    """插件元信息"""
    name: str
    version: str
    description: str
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)


class Plugin(ABC):
    """插件基类"""

    info: PluginInfo
    state: PluginState = PluginState.UNLOADED
    _kernel = None  # 回引用，由PluginManager注入
    _config: Dict[str, Any] = {}

    @abstractmethod
    async def on_load(self) -> None:
        """插件加载时调用"""

    @abstractmethod
    async def on_unload(self) -> None:
        """插件卸载时调用"""

    async def on_pause(self) -> None:
        """暂停(可选)"""

    async def on_resume(self) -> None:
        """恢复(可选)"""

    async def on_config_update(self, config: Dict[str, Any]) -> None:
        """配置更新(可选)"""
        self._config = config

    @property
    def kernel(self):
        """获取内核引用"""
        return self._kernel

    @property
    def bus(self) -> EventBus:
        """快捷访问事件总线"""
        return self._kernel.bus


class PluginManager:
    """
    插件管理器
    - 插件生命周期管理
    - 依赖解析
    - 热插拔支持
    - 插件隔离(可选: 独立进程)
    """

    def __init__(self, kernel):
        self.kernel = kernel
        self._plugins: Dict[str, Plugin] = {}
        self._load_order: List[str] = []

    # ── 注册与发现 ────────────────────────────────────────

    def register(self, plugin: Plugin) -> None:
        """注册插件"""
        if plugin.info.name in self._plugins:
            raise ValueError(f"插件 [{plugin.info.name}] 已注册")
        plugin._kernel = self.kernel
        self._plugins[plugin.info.name] = plugin
        logger.info(f"插件已注册: {plugin.info.name} v{plugin.info.version}")

    def discover(self, paths: List[str]) -> List[str]:
        """
        从路径发现插件
        支持: Python包、本地目录、GitHub仓库
        """
        discovered = []
        import importlib
        import pkgutil
        from pathlib import Path

        for path in paths:
            p = Path(path)
            if p.is_dir():
                # 扫描目录中的Python模块
                for init_file in p.rglob("plugin.py"):
                    discovered.append(str(init_file.parent))

        logger.info(f"发现 {len(discovered)} 个插件")
        return discovered

    # ── 生命周期 ──────────────────────────────────────────

    async def load(self, name: str) -> bool:
        """加载单个插件"""
        plugin = self._plugins.get(name)
        if not plugin:
            logger.error(f"插件不存在: {name}")
            return False

        if plugin.state == PluginState.ACTIVE:
            return True

        # 依赖检查
        for dep in plugin.info.dependencies:
            if dep not in self._plugins:
                logger.error(f"插件 [{name}] 缺少依赖: {dep}")
                return False
            if self._plugins[dep].state != PluginState.ACTIVE:
                await self.load(dep)

        # 加载
        plugin.state = PluginState.LOADING
        try:
            await plugin.on_load()
            plugin.state = PluginState.ACTIVE
            self._load_order.append(name)
            # 发布事件
            await self.kernel.bus.publish(Event(
                type="plugin.loaded",
                source="kernel",
                data={"plugin": name, "version": plugin.info.version},
            ))
            logger.info(f"插件已加载: {name}")
            return True
        except Exception as e:
            plugin.state = PluginState.ERROR
            logger.error(f"插件 [{name}] 加载失败: {e}")
            raise

    async def unload(self, name: str) -> bool:
        """卸载插件"""
        plugin = self._plugins.get(name)
        if not plugin or plugin.state != PluginState.ACTIVE:
            return False

        # 检查是否有其他插件依赖此插件
        for other_name, other in self._plugins.items():
            if name in other.info.dependencies and other.state == PluginState.ACTIVE:
                logger.warning(f"无法卸载 [{name}]: 被 [{other_name}] 依赖")
                return False

        plugin.state = PluginState.UNLOADING
        try:
            await plugin.on_unload()
            plugin.state = PluginState.UNLOADED
            if name in self._load_order:
                self._load_order.remove(name)
            await self.kernel.bus.publish(Event(
                type="plugin.unloaded",
                source="kernel",
                data={"plugin": name},
            ))
            logger.info(f"插件已卸载: {name}")
            return True
        except Exception as e:
            plugin.state = PluginState.ERROR
            logger.error(f"插件 [{name}] 卸载失败: {e}")
            raise

    async def load_all(self) -> Dict[str, bool]:
        """加载所有已注册插件(拓扑排序)"""
        results = {}
        # 拓扑排序: 无依赖的插件先加载
        loaded = set()
        remaining = set(self._plugins.keys())

        while remaining:
            progress = False
            for name in list(remaining):
                plugin = self._plugins[name]
                deps_loaded = all(
                    d in loaded for d in plugin.info.dependencies
                )
                if deps_loaded:
                    try:
                        results[name] = await self.load(name)
                        loaded.add(name)
                        remaining.discard(name)
                        progress = True
                    except Exception:
                        results[name] = False
                        remaining.discard(name)
                        progress = True
            if not progress:
                # 循环依赖或缺失依赖
                for name in remaining:
                    logger.error(f"插件 [{name}] 无法加载: 依赖未满足")
                    results[name] = False
                break

        return results

    # ── 查询 ──────────────────────────────────────────────

    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def list_active(self) -> List[str]:
        return [
            name for name, p in self._plugins.items()
            if p.state == PluginState.ACTIVE
        ]

    def list_all(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.info.name,
                "version": p.info.version,
                "state": p.state.name,
                "dependencies": p.info.dependencies,
            }
            for p in self._plugins.values()
        ]


# ═══════════════════════════════════════════════════════════
# 资源调控器
# ═══════════════════════════════════════════════════════════

class ResourceGovernor:
    """
    资源调控器
    - 防止单个插件耗尽系统资源
    - 支持CPU/内存/文件句柄配额
    - 自动限流+熔断
    """

    def __init__(self,
                 max_memory_mb: int = 2048,
                 max_cpu_percent: int = 80,
                 max_open_files: int = 1000):
        self._quotas: Dict[str, Dict[str, Any]] = {}
        self._usage: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"memory_mb": 0, "cpu_percent": 0, "open_files": 0}
        )
        self.max_memory_mb = max_memory_mb
        self.max_cpu_percent = max_cpu_percent
        self.max_open_files = max_open_files

        # 熔断器状态
        self._circuit_breakers: Dict[str, int] = defaultdict(int)  # 连续失败次数
        self._breaker_threshold = 5  # 连续失败5次熔断

    def set_quota(self, plugin_name: str, **quotas):
        """设置插件资源配额"""
        self._quotas[plugin_name] = quotas

    def check(self, plugin_name: str, resource_type: str, amount: float) -> bool:
        """检查资源是否可以分配"""
        # 熔断检查
        if self._circuit_breakers[plugin_name] >= self._breaker_threshold:
            logger.warning(f"插件 [{plugin_name}] 已熔断")
            return False

        # 配额检查
        quota = self._quotas.get(plugin_name, {})
        limit = quota.get(resource_type)
        if limit is not None:
            current = self._usage[plugin_name][resource_type]
            if current + amount > limit:
                logger.warning(
                    f"插件 [{plugin_name}] {resource_type} 超配额: "
                    f"{current + amount:.1f} > {limit}"
                )
                return False

        # 全局限制检查
        total_memory = sum(u["memory_mb"] for u in self._usage.values())
        if resource_type == "memory_mb" and total_memory + amount > self.max_memory_mb:
            logger.warning("全局内存超限")
            return False

        return True

    def allocate(self, plugin_name: str, resource_type: str, amount: float):
        """分配资源"""
        self._usage[plugin_name][resource_type] += amount

    def release(self, plugin_name: str, resource_type: str, amount: float):
        """释放资源"""
        self._usage[plugin_name][resource_type] = max(
            0, self._usage[plugin_name][resource_type] - amount
        )

    def record_error(self, plugin_name: str):
        """记录错误(用于熔断)"""
        self._circuit_breakers[plugin_name] += 1

    def record_success(self, plugin_name: str):
        """记录成功(重置熔断)"""
        self._circuit_breakers[plugin_name] = 0

    def get_usage_report(self) -> Dict[str, Any]:
        return {
            "quotas": dict(self._quotas),
            "usage": dict(self._usage),
            "circuit_breakers": dict(self._circuit_breakers),
            "total_memory_mb": sum(u["memory_mb"] for u in self._usage.values()),
        }


# ═══════════════════════════════════════════════════════════
# 微内核
# ═══════════════════════════════════════════════════════════

class Kernel:
    """
    meshctx 微内核

    职责:
    - 管理事件总线
    - 管理插件生命周期
    - 资源调控
    - 配置管理
    - 生命周期(start/stop)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.bus = EventBus()
        self.plugins = PluginManager(self)
        self.governor = ResourceGovernor()

        # 内核状态
        self._started = False
        self._start_time: Optional[float] = None

        # 内建事件处理器
        self._register_kernel_handlers()

    def _register_kernel_handlers(self):
        """注册内核级别的事件处理器"""

        async def on_plugin_error(event: Event):
            source = event.data.get("plugin", "unknown")
            self.governor.record_error(source)

        async def on_health_check(event: Event):
            """健康检查响应"""
            pass

        async def on_shutdown(event: Event):
            """优雅关闭"""
            logger.info("收到关闭信号...")
            await self.stop()

        self.bus.subscribe("plugin.error", on_plugin_error, plugin_name="kernel")
        self.bus.subscribe("system.health_check", on_health_check, plugin_name="kernel")
        self.bus.subscribe("system.shutdown", on_shutdown, plugin_name="kernel",
                           priority=EventPriority.CRITICAL)

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self, worker_count: int = 4) -> None:
        """启动内核"""
        if self._started:
            return

        logger.info("══════════════════════════════════════")
        logger.info("  meshctx v1.0 Kernel 启动中...")
        logger.info("══════════════════════════════════════")

        # 启动事件总线
        await self.bus.start(worker_count)

        # 加载所有插件
        results = await self.plugins.load_all()
        active = [k for k, v in results.items() if v]
        logger.info(f"已加载 {len(active)}/{len(results)} 个插件: {active}")

        self._started = True
        self._start_time = time.time()

        # 发布启动完成事件
        await self.bus.publish(Event(
            type="system.started",
            source="kernel",
            priority=EventPriority.CRITICAL,
            data={
                "version": "1.0.0",
                "plugins": active,
                "workers": worker_count,
            },
        ))

        logger.info("meshctx 内核启动完成 ✓")

    async def stop(self) -> None:
        """停止内核"""
        if not self._started:
            return

        logger.info("meshctx 内核关闭中...")

        # 卸载所有插件(逆序)
        for name in reversed(self.plugins._load_order):
            await self.plugins.unload(name)

        # 停止事件总线
        await self.bus.stop()

        self._started = False
        logger.info("meshctx 内核已关闭")

    # ── 统计 ──────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """获取内核状态"""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "started": self._started,
            "uptime_seconds": round(uptime, 1),
            "plugins": self.plugins.list_all(),
            "bus_stats": self.bus.get_stats(),
            "governor": self.governor.get_usage_report(),
        }


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_kernel: Optional[Kernel] = None


def get_kernel() -> Kernel:
    """获取全局内核实例"""
    global _kernel
    if _kernel is None:
        _kernel = Kernel()
    return _kernel


async def init_kernel(config: Dict = None, worker_count: int = 4) -> Kernel:
    """初始化并启动内核"""
    kernel = get_kernel()
    if config:
        kernel.config.update(config)
    await kernel.start(worker_count)
    return kernel

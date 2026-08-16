"""
meshctx 微内核 — 开源版 (简化实现)
事件总线 + 插件管理器，基础功能可用。
完整版见 meshctx-core (私有仓库)。
"""
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field

class _MeshCtxStubProxy:
    """未导出符号的优雅降级代理: 导入成功, 调用/属性访问时提示需 meshctx-core。"""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, attr):
        return _MeshCtxStubProxy(f"{self._name}.{attr}")
    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"meshctx-core required (private repo): {self._name}")
    def __repr__(self):
        return f"<meshctx stub {self._name}>"

def __getattr__(name):
    return _MeshCtxStubProxy(name)

logger = "logger"
class EventPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    LAZY = 4

@dataclass
class Event:
    id: str = None
    type: str = ''
    source: str = ''
    timestamp: float = None
    priority: EventPriority = None
    data: Dict[str, Any] = None
    correlation_id: Optional[str] = None

class EventBus:
    """异步事件总线 — 开源版 (stub: 最小内存版, 核心功能需 meshctx-core)"""
    def __init__(self, max_queue_size: int = 10000):
        from collections import deque
        self._queue: deque = deque(maxlen=max_queue_size)
        self._subs: Dict[str, list] = {}
        self._stats = {"events": 0, "subscriptions": 0}

    def subscribe(self, event_type: str, handler, priority = EventPriority.NORMAL, plugin_name = None):
        raise NotImplementedError("meshctx-core required (private repo): EventBus.subscribe()")

    def register_plugin_handler(self, handler):
        """Register a plugin's on_event handler to receive all events."""
        raise NotImplementedError("meshctx-core required (private repo): EventBus.register_plugin_handler()")

    async def publish(self, event: Event):
        raise NotImplementedError("meshctx-core required (private repo): EventBus.publish()")

    async def start(self):
        self._stats = {"events": 0, "subscriptions": len(self._subs)}
        return self._stats

    async def stop(self):
        return None

    def stats(self) -> dict:
        return {"events": self._stats.get("events", 0), "subscriptions": self._stats.get("subscriptions", 0)}

    def get_stats(self) -> dict:
        return {"events": self._stats.get("events", 0), "subscriptions": self._stats.get("subscriptions", 0)}


@dataclass
class PluginInfo:
    name: str = ''
    version: str = '0.0.0'
    description: str = ''
    dependencies: List[str] = None
    category: str = 'general'
    author: str = ''          # 插件作者/维护者 (mcp_server.py 等插件会传)
    homepage: str = ''        # 项目主页
    license: str = ''         # 许可证

class PluginState(Enum):
    UNLOADED = 'unloaded'
    LOADED = 'loaded'
    ACTIVE = 'active'
    ERROR = 'error'

class Plugin(ABC):
    """插件基类 — 开源版"""
    async def on_load(self, kernel) -> bool:
        """加载插件"""
        raise NotImplementedError("meshctx-core required (private repo)")

    async def on_unload(self):
        raise NotImplementedError("meshctx-core required (private repo)")

    async def on_event(self, event: Event):
        raise NotImplementedError("meshctx-core required (private repo)")

    def generate_report(self) -> dict:
        raise NotImplementedError("meshctx-core required (private repo)")


class PluginManager:
    """插件管理器 — 开源版 (stub: 最小内存版, 注册/查询可用; 激活需 meshctx-core)"""
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._active: Dict[str, bool] = {}

    def register(self, plugin: Plugin):
        name = getattr(plugin, "name", None) or getattr(plugin, "__class__", None).__name__
        self._plugins[name] = plugin
        return plugin

    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def list(self) -> List[str]:
        return list(self._plugins.keys())

    def list_all(self) -> List[Dict[str, Any]]:
        """返回所有插件详情列表，兼容 /v1/plugins 端点"""
        return [{"name": n, "active": self._active.get(n, False)} for n in self._plugins]

    def list_active(self) -> List[str]:
        """返回已激活的插件名称列表，兼容 /kernel/stats 端点"""
        return [n for n, a in self._active.items() if a]

    def plugin_count(self) -> int:
        return len(self._plugins)

    def load_all(self) -> dict:
        raise NotImplementedError("meshctx-core required (private repo): PluginManager.load_all()")

    async def activate_all(self, kernel):
        raise NotImplementedError("meshctx-core required (private repo): PluginManager.activate_all()")


class ResourceGovernor:
    """资源调控器 — 开源版"""
    def __init__(self, max_memory_mb = 512, max_cpu_percent = 80):
        raise NotImplementedError("meshctx-core required (private repo)")

    def check(self) -> bool:
        raise NotImplementedError("meshctx-core required (private repo)")

    def stats(self) -> dict:
        raise NotImplementedError("meshctx-core required (private repo)")


class Kernel:
    """微内核 — 开源版 (stub: 最小内存版, 核心功能需 meshctx-core)"""
    def __init__(self):
        # stub 模式: 构造成功, 基础属性可用; 核心方法调用时显式抛错
        from .kernel import EventBus, PluginManager
        self._started = False
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager()
        self.plugins = self.plugin_manager  # 别名兼容
        self.bus = self.event_bus  # 别名兼容
        self._plugins = {}

    def get_status(self):
        return {"started": self._started, "plugins": len(self._plugins), "bus_stats": {"events": 0, "subscriptions": 3}}

    async def start(self, **kwargs):
        # P0 修复 (codex 审计): stub 模式禁止静默假运行 — 核心启动显式失败
        raise NotImplementedError("meshctx-core required (private repo): kernel.start()")

    async def stop(self):
        raise NotImplementedError("meshctx-core required (private repo): kernel.stop()")


def get_kernel() -> Kernel:
    raise NotImplementedError("meshctx-core required (private repo)")

def init_kernel() -> Kernel:
    raise NotImplementedError("meshctx-core required (private repo)")


__all__ = ["EventPriority", "Event", "EventBus", "subscribe", "register_plugin_handler", "publish", "start", "stop", "stats", "get_stats", "PluginInfo", "PluginState", "Plugin", "on_load", "on_unload", "on_event", "generate_report", "PluginManager", "register", "get", "list", "list_all", "list_active", "plugin_count", "load_all", "activate_all", "ResourceGovernor", "check", "Kernel", "get_status", "get_kernel", "init_kernel"]

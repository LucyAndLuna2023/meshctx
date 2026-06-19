"""
meshctx 微内核 — 开源版 (简化实现)
事件总线 + 插件管理器，基础功能可用。
完整版见 meshctx-core (私有仓库)。
"""
import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger("meshctx.kernel")

class EventPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    LAZY = 4

@dataclass
class Event:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    priority: EventPriority = EventPriority.NORMAL
    data: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None

class EventBus:
    """异步事件总线 — 开源版"""
    def __init__(self, max_queue_size: int = 10000):
        self._subscriptions: Dict[str, list] = defaultdict(list)
        self._running = False
        self._stats = {"published": 0, "delivered": 0, "errors": 0}
    
    def subscribe(self, event_type: str, handler, priority=EventPriority.NORMAL):
        self._subscriptions[event_type].append(handler)
    
    async def publish(self, event: Event):
        self._stats["published"] += 1
        handlers = self._subscriptions.get(event.type, [])
        for h in handlers:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h(event)
                else:
                    h(event)
                self._stats["delivered"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"Event handler error: {e}")
    
    def get_stats(self): return {"subscriptions": sum(len(v) for v in self._subscriptions.values()), **self._stats}

    async def start(self, **kwargs): self._running = True
    async def stop(self): self._running = False
    def stats(self): return dict(self._stats)

@dataclass
class PluginInfo:
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    category: str = "general"

class PluginState(Enum):
    UNLOADED = "unloaded"
    LOADED = "loaded"
    ACTIVE = "active"
    ERROR = "error"

class Plugin(ABC):
    """插件基类 — 开源版"""
    info: PluginInfo = PluginInfo()
    state: PluginState = PluginState.UNLOADED
    
    @abstractmethod
    async def on_load(self, kernel) -> bool:
        """加载插件"""
        ...
    
    async def on_unload(self): pass
    async def on_event(self, event: Event): pass
    
    def generate_report(self) -> dict:
        return {"name": self.info.name, "state": self.state.value}

class PluginManager:
    """插件管理器"""
    def __init__(self):
        self._running = False
        self._plugins: Dict[str, Plugin] = {}
    
    def register(self, plugin: Plugin):
        name = getattr(plugin, "info", None)
        name = name.name if name else type(plugin).__name__
        self._plugins[name] = plugin
        try: plugin.state = PluginState.LOADED
        except: pass
    
    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)
    
    def list(self) -> List[str]:
        return list(self._plugins.keys())
    
    async def load_all(self) -> dict:
        return {name: True for name in self._plugins}

    async def activate_all(self, kernel):
        for name, p in self._plugins.items():
            try:
                await p.on_load(kernel)
                p.state = PluginState.ACTIVE
            except Exception as e:
                p.state = PluginState.ERROR
                logger.error(f"Plugin {name} failed: {e}")

class ResourceGovernor:
    """资源调控器 — 开源版"""
    def __init__(self, max_memory_mb=512, max_cpu_percent=80):
        self.max_memory_mb = max_memory_mb
        self.max_cpu_percent = max_cpu_percent
        self._usage = {"memory_mb": 0, "cpu_percent": 0}
    
    def check(self) -> bool:
        return self._usage["memory_mb"] < self.max_memory_mb
    
    def stats(self) -> dict:
        return dict(self._usage)

class Kernel:
    """微内核 — 开源版"""
    def __init__(self):
        self._running = False
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager()
        self.governor = ResourceGovernor()
        self.bus = self.event_bus
        self.plugins = self.plugin_manager  # 别名兼容
    
    async def start(self, **kwargs):
        self._running = True
        await self.event_bus.start()
        await self.plugin_manager.activate_all(self)
        logger.info("Kernel started (open-source stub mode)")
    
    async def stop(self):
        self._running = False
        await self.event_bus.stop()

# 全局单例
_kernel: Optional[Kernel] = None

def get_kernel() -> Kernel:
    global _kernel
    if _kernel is None:
        _kernel = Kernel()
    return _kernel

def init_kernel() -> Kernel:
    global _kernel
    _kernel = Kernel()
    return _kernel

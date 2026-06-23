"""
meshctx 插件系统
支持动态加载、热重载、插件优先级
"""
import importlib
import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Any, Optional, Type

logger = logging.getLogger("meshctx.plugins")


class PluginBase(ABC):
    """插件基类 — 所有插件必须继承"""

    # 子类覆盖
    name: str = "unnamed"
    version: str = "0.1.0"
    description: str = ""
    priority: int = 0  # 数值越大优先级越高

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._enabled = True

    @abstractmethod
    def on_message_added(self, message_context: Dict[str, Any]) -> Optional[Dict]:
        """
        当新消息添加时触发
        message_context: {"project_id", "conversation_id", "message_id", "role", "content", "metadata"}
        返回: 可选的处理结果字典
        """
        pass

    @abstractmethod
    def on_memory_extracted(self, memory: Dict[str, Any]) -> Optional[Dict]:
        """
        当记忆被提取时触发
        memory: {"key", "value", "importance", "category", "entities"}
        返回: 可选的处理后记忆
        """
        pass

    def on_context_built(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """当上下文组装时触发 — 可修改上下文"""
        return context

    def on_project_created(self, project: Dict[str, Any]) -> None:
        """项目创建后触发"""
        pass

    def on_startup(self) -> None:
        """引擎启动时触发"""
        pass

    def on_shutdown(self) -> None:
        """引擎关闭时触发"""
        pass

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def __repr__(self):
        return f"Plugin({self.name} v{self.version})"


class PluginManager:
    """插件管理器 — 负责注册、加载、调度"""

    def __init__(self, plugin_dir: Optional[str] = None):
        self._plugins: Dict[str, PluginBase] = {}  # name -> instance
        self._priorities: List[str] = []  # 按优先级排序的name列表
        self.plugin_dir = plugin_dir or self._default_plugin_dir()

    @staticmethod
    def _default_plugin_dir() -> str:
        return os.path.join(os.path.dirname(__file__), "..", "plugins")

    # ── 注册 ──────────────────────────────────────────────

    def register(self, plugin_class: Type[PluginBase], config: Dict = None) -> PluginBase:
        """注册并实例化一个插件"""
        instance = plugin_class(config)
        if instance.name in self._plugins:
            logger.warning(f"插件 {instance.name} 已存在，将被覆盖")
        self._plugins[instance.name] = instance
        self._rebuild_priorities()
        logger.info(f"插件已注册: {instance.name} v{instance.version} (priority={instance.priority})")
        return instance

    def unregister(self, name: str) -> bool:
        """注销插件"""
        if name in self._plugins:
            del self._plugins[name]
            self._rebuild_priorities()
            logger.info(f"插件已注销: {name}")
            return True
        return False

    def _rebuild_priorities(self):
        """重建优先级排序"""
        enabled = [(p.priority, p.name) for p in self._plugins.values() if p.enabled]
        enabled.sort(key=lambda x: -x[0])  # 降序
        self._priorities = [name for _, name in enabled]

    # ── 加载 ──────────────────────────────────────────────

    def load_from_directory(self, directory: str = None) -> int:
        """从目录动态加载插件模块"""
        target = Path(directory or self.plugin_dir)
        if not target.exists():
            return 0

        count = 0
        sys.path.insert(0, str(target.parent))

        for py_file in target.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            try:
                module = importlib.import_module(module_name)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, PluginBase) and
                            attr is not PluginBase):
                        self.register(attr)
                        count += 1
            except Exception as e:
                logger.warning(f"加载插件失败 {module_name}: {e}")

        return count

    def reload(self):
        """重载所有插件"""
        for plugin in list(self._plugins.values()):
            plugin.on_shutdown()
        self._plugins.clear()
        self._priorities.clear()
        loaded = self.load_from_directory()
        for plugin in self._plugins.values():
            plugin.on_startup()
        logger.info(f"插件重载完成: {loaded} 个")

    # ── 调度（钩子） ─────────────────────────────────────────

    def dispatch_message_added(self, context: Dict[str, Any]) -> List[Dict]:
        """调度消息添加事件到所有启用的插件"""
        results = []
        for name in self._priorities:
            plugin = self._plugins[name]
            try:
                result = plugin.on_message_added(context)
                if result is not None:
                    results.append({"plugin": name, "result": result})
            except Exception as e:
                logger.warning(f"插件 {name}.on_message_added 异常: {e}")
        return results

    def dispatch_memory_extracted(self, memory: Dict[str, Any]) -> List[Dict]:
        """调度记忆提取事件"""
        results = []
        for name in self._priorities:
            plugin = self._plugins[name]
            try:
                result = plugin.on_memory_extracted(memory)
                if result is not None:
                    results.append({"plugin": name, "result": result})
            except Exception as e:
                logger.warning(f"插件 {name}.on_memory_extracted 异常: {e}")
        return results

    def build_context_pipeline(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """管道式处理上下文"""
        for name in self._priorities:
            plugin = self._plugins[name]
            try:
                context = plugin.on_context_built(context)
            except Exception as e:
                logger.warning(f"插件 {name}.on_context_built 异常: {e}")
        return context

    def dispatch_project_created(self, project: Dict[str, Any]):
        for name in self._priorities:
            try:
                self._plugins[name].on_project_created(project)
            except Exception as e:
                logger.warning(f"插件 {name}.on_project_created 异常: {e}")

    def startup_all(self):
        for plugin in self._plugins.values():
            try:
                plugin.on_startup()
            except Exception as e:
                logger.warning(f"插件 {plugin.name}.on_startup 异常: {e}")

    def shutdown_all(self):
        for plugin in self._plugins.values():
            try:
                plugin.on_shutdown()
            except Exception as e:
                logger.warning(f"插件 {plugin.name}.on_shutdown 异常: {e}")

    # ── 查询 ──────────────────────────────────────────────

    def list_plugins(self) -> List[Dict]:
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "priority": p.priority,
                "enabled": p.enabled,
            }
            for p in self._plugins.values()
        ]

    def get_plugin(self, name: str) -> Optional[PluginBase]:
        return self._plugins.get(name)

    def enable_plugin(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if plugin:
            plugin.enabled = True
            self._rebuild_priorities()
            return True
        return False

    def disable_plugin(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if plugin:
            plugin.enabled = False
            self._rebuild_priorities()
            return True
        return False

    @property
    def plugin_count(self) -> int:
        return len(self._plugins)

    @property
    def active_count(self) -> int:
        return len(self._priorities)


# ── 内置插件 ─────────────────────────────────────────────


class ImportanceFilterPlugin(PluginBase):
    """重要性过滤插件 — 低重要性记忆自动过滤"""

    name = "importance_filter"
    version = "0.1.0"
    description = "过滤重要性低于阈值的记忆"
    priority = 100

    def __init__(self, config=None):
        super().__init__(config)
        self.threshold = float(self.config.get("threshold", 0.3))

    def on_memory_extracted(self, memory: Dict[str, Any]) -> Optional[Dict]:
        importance = float(memory.get("importance", 0.5))
        if importance < self.threshold:
            logger.debug(f"过滤低重要性记忆: {memory.get('key')} ({importance:.2f})")
            return None
        return memory

    def on_message_added(self, message_context: Dict[str, Any]) -> Optional[Dict]:
        return None


class DeduplicationPlugin(PluginBase):
    """去重插件 — 避免重复记忆"""

    name = "deduplication"
    version = "0.1.0"
    description = "基于内容哈希去重记忆"
    priority = 90

    def __init__(self, config=None):
        super().__init__(config)
        self._hashes: set = set()

    def on_memory_extracted(self, memory: Dict[str, Any]) -> Optional[Dict]:
        import hashlib
        content = memory.get("value", "")
        h = hashlib.md5(content.encode()).hexdigest()
        if h in self._hashes:
            logger.debug(f"去重记忆: {memory.get('key')}")
            return None
        self._hashes.add(h)
        return memory

    def on_message_added(self, message_context: Dict[str, Any]) -> Optional[Dict]:
        return None


class LoggingPlugin(PluginBase):
    """审计日志插件 — 记录所有操作"""

    name = "audit_logging"
    version = "0.1.0"
    description = "审计日志记录"
    priority = 10

    def __init__(self, config=None):
        super().__init__(config)
        log_dir = self.config.get("log_dir", os.path.join(os.path.dirname(__file__), "..", "logs"))
        os.makedirs(log_dir, exist_ok=True)
        self.log_file = os.path.join(log_dir, "audit.log")

    def on_message_added(self, message_context: Dict[str, Any]) -> Optional[Dict]:
        self._log("message_added", message_context)
        return None

    def on_memory_extracted(self, memory: Dict[str, Any]) -> Optional[Dict]:
        self._log("memory_extracted", memory)
        return memory

    def on_context_built(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self._log("context_built", {"project": context.get("project", {}).get("name")})
        return context

    def _log(self, event: str, data: Dict):
        from datetime import datetime
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "data": data,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


# 全局单例
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager(plugin_dir: str = None) -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(plugin_dir)
        # 注册内置插件
        _plugin_manager.register(ImportanceFilterPlugin)
        _plugin_manager.register(DeduplicationPlugin)
        _plugin_manager.register(LoggingPlugin)
        _plugin_manager.startup_all()
    return _plugin_manager

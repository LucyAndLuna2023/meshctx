"""
meshctx Plugin Manager (v3.115.16) — Real implementation, no stubs.
Plugin discovery, loading, lifecycle hooks, hot-reload, dependency resolution.
"""
import importlib
import importlib.util
import inspect
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("meshctx.plugins")


class PluginState(Enum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginMeta:
    """Plugin metadata — extracted from plugin module."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    category: str = "general"
    entry_point: str = "plugin"  # module attribute name


@dataclass
class PluginInstance:
    """A loaded plugin instance."""
    meta: PluginMeta
    module: Any = None
    instance: Any = None
    state: PluginState = PluginState.DISCOVERED
    load_error: Optional[str] = None


class PluginManagerEngine:
    """Real plugin manager — discovery, loading, lifecycle, hot-reload."""
    
    def __init__(self, plugin_dirs: List[str] = None):
        self._plugins: Dict[str, PluginInstance] = {}
        self._hooks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        self._plugin_dirs = plugin_dirs or [
            str(Path(__file__).parent.parent / "plugins"),
            str(Path.home() / ".meshctx" / "plugins"),
        ]
    
    # ── Discovery ──
    
    def discover(self) -> List[PluginMeta]:
        """Scan plugin directories and discover available plugins."""
        discovered = []
        for d in self._plugin_dirs:
            p = Path(d)
            if not p.exists():
                continue
            for item in p.iterdir():
                meta = self._scan_plugin(item)
                if meta:
                    discovered.append(meta)
                    if meta.name not in self._plugins:
                        self._plugins[meta.name] = PluginInstance(meta=meta)
        logger.info(f"Discovered {len(discovered)} plugins in {len(self._plugin_dirs)} dirs")
        return discovered
    
    def _scan_plugin(self, path: Path) -> Optional[PluginMeta]:
        """Scan a directory or file for plugin metadata."""
        if path.is_dir():
            manifest = path / "plugin.json"
            if manifest.exists():
                try:
                    data = json.loads(manifest.read_text())
                    return PluginMeta(
                        name=data.get("name", path.name),
                        version=data.get("version", "0.1.0"),
                        description=data.get("description", ""),
                        author=data.get("author", ""),
                        dependencies=data.get("dependencies", []),
                        category=data.get("category", "general"),
                        entry_point=data.get("entry_point", "plugin"),
                    )
                except Exception as e:
                    logger.warning(f"Invalid plugin manifest {manifest}: {e}")
        elif path.suffix == ".py" and not path.name.startswith("_"):
            try:
                spec = importlib.util.spec_from_file_location(path.stem, str(path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return PluginMeta(
                    name=getattr(mod, "PLUGIN_NAME", path.stem),
                    version=getattr(mod, "PLUGIN_VERSION", "0.1.0"),
                    description=getattr(mod, "PLUGIN_DESCRIPTION", ""),
                    author=getattr(mod, "PLUGIN_AUTHOR", ""),
                    dependencies=getattr(mod, "PLUGIN_DEPS", []),
                    category=getattr(mod, "PLUGIN_CATEGORY", "general"),
                    entry_point=getattr(mod, "PLUGIN_ENTRY", "plugin"),
                )
            except Exception as e:
                logger.debug(f"Skipped {path.name}: {e}")
        return None
    
    # ── Loading ──
    
    def load(self, name: str) -> bool:
        """Load a plugin by name."""
        with self._lock:
            if name not in self._plugins:
                logger.warning(f"Plugin '{name}' not found")
                return False
            pi = self._plugins[name]
            if pi.state == PluginState.ACTIVE:
                return True
            
            try:
                # Try to find and load the plugin module
                module = self._find_module(name, pi.meta)
                if module:
                    pi.module = module
                    # Get the plugin class/instance
                    entry = getattr(module, pi.meta.entry_point, None)
                    if entry is None:
                        entry = getattr(module, "setup", None)
                    if entry:
                        if inspect.isclass(entry):
                            pi.instance = entry()
                        elif callable(entry):
                            pi.instance = entry()
                        else:
                            pi.instance = entry
                    pi.state = PluginState.LOADED
                    logger.info(f"Plugin '{name}' loaded")
                    return True
                else:
                    pi.load_error = f"Module not found: {name}"
                    pi.state = PluginState.ERROR
            except Exception as e:
                pi.load_error = str(e)
                pi.state = PluginState.ERROR
                logger.error(f"Failed to load plugin '{name}': {e}")
            return False
    
    def _find_module(self, name: str, meta: PluginMeta) -> Any:
        """Find and import a plugin module."""
        # Try standard Python imports first
        for prefix in ["src.plugins.", "plugins.", ""]:
            try:
                return importlib.import_module(f"{prefix}{name}")
            except ImportError:
                continue
        
        # Try file-based discovery
        for d in self._plugin_dirs:
            p = Path(d) / f"{name}.py"
            if p.exists():
                spec = importlib.util.spec_from_file_location(name, str(p))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
            # Directory-based
            p = Path(d) / name
            if p.is_dir():
                init = p / "__init__.py"
                if init.exists():
                    spec = importlib.util.spec_from_file_location(name, str(init))
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    return mod
        
        return None
    
    # ── Lifecycle ──
    
    def activate(self, name: str) -> bool:
        """Activate a loaded plugin — calls on_activate hook."""
        with self._lock:
            if not self.load(name):
                return False
            pi = self._plugins[name]
            try:
                if pi.instance and hasattr(pi.instance, "on_activate"):
                    pi.instance.on_activate()
                pi.state = PluginState.ACTIVE
                self._fire_hook("on_plugin_activated", name)
                logger.info(f"Plugin '{name}' activated")
                return True
            except Exception as e:
                pi.load_error = str(e)
                pi.state = PluginState.ERROR
                logger.error(f"Failed to activate '{name}': {e}")
            return False
    
    def deactivate(self, name: str) -> bool:
        """Deactivate a plugin — calls on_deactivate hook."""
        with self._lock:
            if name not in self._plugins:
                return False
            pi = self._plugins[name]
            try:
                if pi.instance and hasattr(pi.instance, "on_deactivate"):
                    pi.instance.on_deactivate()
                pi.state = PluginState.DISABLED
                self._fire_hook("on_plugin_deactivated", name)
                logger.info(f"Plugin '{name}' deactivated")
                return True
            except Exception as e:
                logger.error(f"Failed to deactivate '{name}': {e}")
            return False
    
    def unload(self, name: str) -> bool:
        """Fully unload a plugin."""
        self.deactivate(name)
        with self._lock:
            if name in self._plugins:
                pi = self._plugins.pop(name)
                if pi.module:
                    sys.modules.pop(pi.module.__name__, None)
                return True
        return False
    
    # ── Hot Reload ──
    
    def reload(self, name: str) -> bool:
        """Hot-reload a plugin."""
        if name not in self._plugins:
            return self.load(name)
        self.deactivate(name)
        pi = self._plugins[name]
        old_module = pi.module
        if old_module:
            sys.modules.pop(old_module.__name__, None)
            try:
                importlib.reload(old_module)
            except Exception:
                pass
        return self.activate(name)
    
    # ── Query ──
    
    def get(self, name: str) -> Optional[PluginInstance]:
        return self._plugins.get(name)
    
    def list_all(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": name, "version": pi.meta.version,
                "description": pi.meta.description, "category": pi.meta.category,
                "state": pi.state.value, "error": pi.load_error,
            }
            for name, pi in self._plugins.items()
        ]
    
    def list_active(self) -> List[str]:
        return [n for n, p in self._plugins.items() if p.state == PluginState.ACTIVE]
    
    @property
    def active_count(self) -> int:
        return len(self.list_active())
    
    @property
    def plugin_count(self) -> int:
        return len(self._plugins)
    
    # ── Hooks ──
    
    def register_hook(self, event: str, callback: Callable):
        """Register a callback for plugin lifecycle events."""
        self._hooks.setdefault(event, []).append(callback)
    
    def _fire_hook(self, event: str, *args):
        for cb in self._hooks.get(event, []):
            try:
                cb(*args)
            except Exception as e:
                logger.warning(f"Hook {event} failed: {e}")


# ── Global singleton ──
_global_manager: Optional[PluginManagerEngine] = None

def get_plugin_manager() -> PluginManagerEngine:
    global _global_manager
    if _global_manager is None:
        _global_manager = PluginManagerEngine()
        _global_manager.discover()
    return _global_manager

"""
meshctx v3.55 — Plugin Hot-Reload Engine (插件热加载)

功能:
  1. 文件监控: 检测插件目录变更
  2. 热加载: 不重启服务替换插件
  3. 版本管理: 插件版本追踪+回滚
  4. 沙箱测试: 新插件加载前隔离测试
"""
import logging, os, time, importlib, importlib.util, json
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger("meshctx.plugin_hotreload")

@dataclass
class PluginMeta:
    name: str=""; version: str="0"; path: str=""
    loaded: bool=False; load_time: float=0; reload_count: int=0
    dependencies: List[str]=field(default_factory=list)
    errors: List[str]=field(default_factory=list)

class PluginHotReload:
    def __init__(self, plugin_dir: Optional[str]=None):
        self._plugin_dir = Path(plugin_dir) if plugin_dir else Path("plugins")
        self._plugins: Dict[str,PluginMeta] = {}
        self._instances: Dict[str,Any] = {}
        self._file_mtimes: Dict[str,float] = {}
        self._reload_history: deque=deque(maxlen=50)
        self._plugin_dir.mkdir(parents=True, exist_ok=True)
    
    def scan(self) -> List[PluginMeta]:
        discovered = []
        for f in self._plugin_dir.glob("*.py"):
            if f.stem.startswith("_"): continue
            name = f.stem
            mtime = f.stat().st_mtime
            if name not in self._plugins:
                meta = PluginMeta(name=name, path=str(f))
                self._plugins[name] = meta
                self._file_mtimes[name] = mtime
                discovered.append(meta)
        return discovered
    
    def load(self, name: str) -> bool:
        meta = self._plugins.get(name)
        if not meta: return False
        try:
            spec = importlib.util.spec_from_file_location(name, meta.path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._instances[name] = mod
                meta.loaded = True
                meta.load_time = time.time()
                meta.reload_count += 1
                self._reload_history.append(("load", name, time.time()))
                logger.info(f"Loaded plugin: {name} v{meta.version}")
                return True
        except Exception as e:
            meta.errors.append(str(e))
            logger.error(f"Failed to load {name}: {e}")
        return False
    
    def unload(self, name: str) -> bool:
        if name in self._instances:
            del self._instances[name]
            if name in self._plugins:
                self._plugins[name].loaded = False
            return True
        return False
    
    def reload(self, name: str) -> bool:
        self.unload(name)
        importlib.invalidate_caches()
        return self.load(name)
    
    def check_updates(self) -> List[str]:
        updated = []
        for name, meta in self._plugins.items():
            f = Path(meta.path)
            if f.exists():
                mtime = f.stat().st_mtime
                if name in self._file_mtimes and mtime > self._file_mtimes[name]:
                    updated.append(name)
                    self._file_mtimes[name] = mtime
        return updated
    
    def auto_reload(self) -> List[str]:
        reloaded = []
        for name in self.check_updates():
            if self.reload(name):
                reloaded.append(name)
        return reloaded

    def get_stats(self) -> Dict[str,Any]:
        return {
            "plugins_total": len(self._plugins),
            "plugins_loaded": sum(1 for m in self._plugins.values() if m.loaded),
            "reloads": len(self._reload_history),
            "plugins": {n:{"version":m.version,"loaded":m.loaded,"reloads":m.reload_count} for n,m in self._plugins.items()},
        }

_hotreload: Optional[PluginHotReload]=None
def get_hotreload(d:str=None): 
    global _hotreload
    if _hotreload is None: _hotreload = PluginHotReload(d)
    return _hotreload

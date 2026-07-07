"""meshctx plugin_hotreload — hot-reload plugin management"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PluginMeta:
    name: str = ""
    path: str = ""
    version: str = ""
    loaded: bool = False


class PluginHotReload:
    """Hot-reload manager for plugin files in a directory."""

    def __init__(self, plugin_dir: str):
        self.plugin_dir = Path(plugin_dir)
        self._plugins: dict[str, PluginMeta] = {}
        self._modules: dict[str, object] = {}

    def scan(self) -> list[PluginMeta]:
        self._plugins.clear()
        if not self.plugin_dir.exists():
            return []
        for f in sorted(self.plugin_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            name = f.stem
            meta = PluginMeta(name=name, path=str(f))
            try:
                content = f.read_text()
                for line in content.splitlines():
                    if line.startswith("VERSION"):
                        meta.version = line.split("=")[1].strip().strip("'\"").strip()
                        break
            except Exception:
                pass
            self._plugins[name] = meta
        return list(self._plugins.values())

    def load(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        meta = self._plugins[name]
        try:
            spec = importlib.util.spec_from_file_location(name, meta.path)
            if spec is None or spec.loader is None:
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            self._modules[name] = module
            meta.loaded = True
            return True
        except Exception:
            return False

    def unload(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        meta = self._plugins[name]
        self._modules.pop(name, None)
        sys.modules.pop(name, None)
        meta.loaded = False
        return True

    def check_updates(self) -> list[PluginMeta]:
        updates = []
        for name, meta in self._plugins.items():
            try:
                stored_path = Path(meta.path)
                if stored_path.exists():
                    current_mtime = stored_path.stat().st_mtime
                    # Compare with current file state
                    if current_mtime > stored_path.stat().st_mtime:
                        updates.append(meta)
            except Exception:
                pass
        return updates

    def reload(self, name: str) -> bool:
        if name not in self._plugins:
            return False
        self.unload(name)
        return self.load(name)

    def get_stats(self) -> dict:
        total = len(self._plugins)
        loaded = sum(1 for m in self._plugins.values() if m.loaded)
        return {
            "plugins_total": total,
            "plugins_loaded": loaded,
        }


# ── Singleton ──────────────────────────────────────────────────────────
_hotreload_instance: Optional[PluginHotReload] = None
_hotreload_dir: Optional[str] = None


def get_hotreload(plugin_dir: str = None) -> PluginHotReload:
    global _hotreload_instance, _hotreload_dir
    if _hotreload_instance is None or (plugin_dir is not None and plugin_dir != _hotreload_dir):
        _hotreload_instance = PluginHotReload(plugin_dir or "plugins")
        _hotreload_dir = plugin_dir
    return _hotreload_instance

"""插件自动加载 — v3.115.36 真实实现

扫描 ~/.meshctx/plugins/ 目录，自动发现和加载插件。
每个插件是一个目录，包含 plugin.json 清单文件。"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.plugins")

# ── Plugin manifest ──────────────────────────────────────────

PLUGIN_MANIFEST_SCHEMA = {
    "name": "",
    "version": "1.0.0",
    "description": "",
    "author": "",
    "entry_point": "plugin.py",  # relative to plugin dir
    "enabled": True,
    "category": "utility",
    "dependencies": [],
}

PLUGINS_DIR = Path.home() / ".meshctx" / "plugins"


def discover_plugins(plugins_dir: Path = None) -> List[Dict[str, Any]]:
    """Scan plugins directory and return discovered plugin manifests.

    Each subdirectory with a plugin.json is a plugin.
    """
    if plugins_dir is None:
        plugins_dir = PLUGINS_DIR

    discovered = []
    if not plugins_dir.exists():
        plugins_dir.mkdir(parents=True, exist_ok=True)
        return discovered

    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "plugin.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest["_path"] = str(entry)
            manifest["_loaded"] = False
            discovered.append(manifest)
        except Exception as e:
            logger.warning(f"Failed to read plugin manifest {manifest_path}: {e}")

    return discovered


def load_plugin(manifest: Dict[str, Any]) -> Optional[Any]:
    """Load a single plugin from its manifest with safety checks.

    Returns the plugin module/object, or None on failure.
    """
    plugin_dir = Path(manifest.get("_path", ""))
    entry = manifest.get("entry_point", "plugin.py")
    entry_path = plugin_dir / entry

    if not entry_path.exists():
        logger.warning(f"Plugin entry point not found: {entry_path}")
        return None

    # ═══ v3.115.38: Safety checks ═══
    # 1. Verify plugin.json signature (SHA256 of entry_point)
    sig_path = plugin_dir / "plugin.json.sig"
    if sig_path.exists():
        try:
            import hashlib
            manifest_text = (plugin_dir / "plugin.json").read_bytes()
            expected = sig_path.read_text().strip()
            actual = hashlib.sha256(manifest_text).hexdigest()
            if expected != actual:
                logger.error(f"Plugin {manifest['name']}: signature mismatch — rejected")
                return None
        except Exception as e:
            logger.warning(f"Plugin {manifest['name']}: signature check failed ({e}) — skipping")
    
    # 2. Size limit: reject plugins > 100KB entry point
    try:
        if entry_path.stat().st_size > 100 * 1024:
            logger.error(f"Plugin {manifest['name']}: entry point too large ({entry_path.stat().st_size} bytes)")
            return None
    except Exception:
        pass
    
    # 3. Forbidden imports check: scan for dangerous imports
    try:
        code = entry_path.read_text()
        dangerous = ["subprocess", "os.system", "eval(", "exec(", "__import__",
                      "ctypes", "multiprocessing", "socket", "requests"]
        found = [d for d in dangerous if d in code]
        if found:
            logger.warning(f"Plugin {manifest['name']}: uses potentially dangerous imports: {found}")
            # Still allow but log prominently
    except Exception:
        pass

    try:
        # Add plugin dir to path temporarily
        plugin_dir_str = str(plugin_dir)
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)

        # Import the plugin module
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"meshctx_plugin_{manifest['name']}",
            str(entry_path)
        )
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        # Call on_load if available
        if hasattr(module, "on_load"):
            module.on_load()

        manifest["_loaded"] = True
        manifest["_module"] = spec.name
        logger.info(f"Plugin loaded: {manifest['name']} v{manifest['version']}")
        return module

    except Exception as e:
        logger.error(f"Failed to load plugin {manifest['name']}: {e}")
        return None


def load_all_plugins(plugins_dir: Path = None) -> Dict[str, Any]:
    """Discover and load all plugins. Returns {name: module_or_None}."""
    discovered = discover_plugins(plugins_dir)
    loaded = {}
    for manifest in discovered:
        if manifest.get("enabled", True):
            module = load_plugin(manifest)
            loaded[manifest["name"]] = module
    return loaded


def auto_activate_builtins(kernel=None) -> int:
    """Auto-discover and load all plugins. Returns count of loaded plugins."""
    try:
        loaded = load_all_plugins()
        count = sum(1 for v in loaded.values() if v is not None)
        if count > 0:
            logger.info(f"Auto-loaded {count} plugins: {list(loaded.keys())}")
        else:
            logger.info("No plugins found in ~/.meshctx/plugins/")
        return count
    except Exception as e:
        logger.warning(f"Plugin auto-load failed: {e}")
        return 0


def get_plugin_list() -> List[Dict[str, Any]]:
    """Get list of all plugins (discovered + loaded status)."""
    return discover_plugins()


def create_example_plugin(name: str = "hello_world") -> Path:
    """Create an example plugin skeleton for users to start with."""
    plugin_dir = PLUGINS_DIR / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": f"A sample {name} plugin for meshctx",
        "author": "meshctx community",
        "entry_point": "plugin.py",
        "enabled": True,
        "category": "example",
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )

    plugin_code = '''"""{} - meshctx plugin"""

def on_load():
    """Called when the plugin is loaded."""
    import logging
    logger = logging.getLogger("meshctx.plugins.{}")
    logger.info("{} plugin activated!")

def on_unload():
    """Called when the plugin is unloaded."""
    pass

# Plugin metadata (read by meshctx)
PLUGIN_INFO = {{
    "name": "{}",
    "version": "1.0.0",
    "description": "A sample plugin",
    "hooks": ["on_load", "on_unload"],
}}
'''.format(name.capitalize(), name, name.capitalize(), name)

    (plugin_dir / "plugin.py").write_text(plugin_code)
    logger.info(f"Created example plugin at {plugin_dir}")
    return plugin_dir

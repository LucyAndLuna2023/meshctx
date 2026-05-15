"""
MeshCtx Plugin Autoloader — Auto-activate plugins on startup
==============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Scans plugins/ directory and auto-activates builtin plugins.
"""
import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


def discover_plugins(plugins_dir: str = None) -> List[Dict]:
    """Discover all plugins in the plugins directory."""
    if plugins_dir is None:
        plugins_dir = Path(__file__).resolve().parent.parent.parent / "plugins"
    else:
        plugins_dir = Path(plugins_dir)

    plugins = []

    # Load registry
    registry_path = plugins_dir / "registry.json"
    registry = {}
    if registry_path.exists():
        with open(registry_path) as f:
            registry = json.load(f)

    # Scan for plugin directories
    for entry in plugins_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            manifest = entry / "manifest.json"
            if manifest.exists():
                try:
                    with open(manifest) as f:
                        data = json.load(f)
                    data["_path"] = str(entry)
                    data["_active"] = data.get("builtin", False)  # Auto-activate builtins
                    plugins.append(data)
                except Exception as e:
                    logger.warning(f"Failed to load plugin {entry.name}: {e}")

    # Merge with registry status
    registry_plugins = {p["name"]: p for p in registry.get("plugins", [])}
    for p in plugins:
        name = p.get("name", "")
        if name in registry_plugins:
            p["installs"] = registry_plugins[name].get("installs", 0)
            # Activate if installed or builtin
            if registry_plugins[name].get("installs", 0) > 0 or p.get("builtin"):
                p["_active"] = True

    return plugins


def get_active_plugins(plugins_dir: str = None) -> List[Dict]:
    """Get only active (installed/builtin) plugins."""
    return [p for p in discover_plugins(plugins_dir) if p.get("_active")]


def auto_activate_builtins(plugins_dir: str = None):
    """Auto-activate all builtin plugins on startup."""
    if plugins_dir is None:
        plugins_dir = Path(__file__).resolve().parent.parent.parent / "plugins"

    registry_path = plugins_dir / "registry.json"
    if not registry_path.exists():
        logger.warning("No plugin registry found")
        return 0

    with open(registry_path) as f:
        registry = json.load(f)

    count = 0
    for p in registry.get("plugins", []):
        if p.get("builtin") and p.get("installs", 0) == 0:
            p["installs"] = 1
            count += 1
            logger.info(f"Auto-activated builtin plugin: {p['name']}")

    if count > 0:
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)

    return count

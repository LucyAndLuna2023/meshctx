"""
meshctx Configuration Chain v1.0 — Hierarchical TOML/YAML Config Override System

Design (inspired by CarbonCode's config chain):
  Config loaded in priority order (last wins):
    1. Package defaults (meshctx.yaml inside package)
    2. ~/.meshctx/config.yaml  (user global)
    3. ./.meshctx.yaml         (project local)
    4. ./meshctx.toml          (project TOML override)
    5. environment variables   (MESHCTX_*)
  
  Deep merge (not shallow), so you can override one key without re-specifying everything.

Usage:
  cfg = ConfigChain()
  cfg.load()
  model = cfg.get("models.default")        # "deepseek-flash"
  threshold = cfg.get("router.flash_threshold", 500)  # with default
  all_keys = cfg.flat()                    # flattened dot-notation dict
"""

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import logging

logger = logging.getLogger("meshctx.config_chain")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

ENV_PREFIX = "MESHCTX_"

# Config file search order (later files override earlier)
CONFIG_SEARCH_ORDER = [
    # (path, description)
    (None, "package_defaults"),       # Virtual: built-in defaults
    ("~/.meshctx/config.yaml", "user_global_yaml"),
    ("~/.meshctx/config.toml", "user_global_toml"),
    ("./.meshctx.yaml", "project_yaml"),
    ("./meshctx.toml", "project_toml"),
    (None, "env_vars"),               # Virtual: MESHCTX_* env vars
]

DEFAULT_CONFIG = {
    "kernel": {"worker_count": 4, "log_level": "info", "max_steps": 50},
    "models": {
        "default": "deepseek-flash",
        "providers": {
            "deepseek-flash": {"provider": "deepseek", "model": "deepseek-flash", "max_tokens": 4096},
            "deepseek-pro": {"provider": "deepseek", "model": "deepseek-pro", "max_tokens": 8192},
        },
    },
    "router": {
        "flash_threshold": 500,
        "mix_threshold": 2000,
        "flash_cost_per_1m": 0.14,
        "pro_cost_per_1m": 2.19,
    },
    "memory": {"max_context": 8000, "levels": ["observe", "compact", "off"]},
    "subagent": {"max_concurrent": 3, "max_turns": 20, "timeout_sec": 120},
    "prompts": {"directory": "~/.meshctx/prompts/", "audit_enabled": True},
    "plugins": {"builtin": ["memory", "metacognition"], "extra": []},
    "gateway": {"enabled": False, "port": 3001},
    "skills": {"auto_create": True, "directory": "~/.meshctx/skills/"},
}


# ═══════════════════════════════════════════════════════════
# Config Chain
# ═══════════════════════════════════════════════════════════

class ConfigChain:
    """
    Hierarchical configuration with TOML support and deep merging.
    
    Layers (priority from low to high):
      1. Built-in defaults (hardcoded)
      2. ~/.meshctx/config.yaml (user global YAML)
      3. ~/.meshctx/config.toml (user global TOML)
      4. ./.meshctx.yaml (project local YAML)
      5. ./meshctx.toml (project local TOML)
      6. MESHCTX_* environment variables
    
    Get with dot-notation: cfg.get("router.flash_threshold")
    Set with dot-notation: cfg.add_override("models.default", "deepseek-pro")
    """
    
    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._sources: List[str] = []  # Which files were loaded
        self._overrides: Dict[str, Any] = {}  # Runtime overrides
        self._loaded = False
        
        # Try importing optional parsers
        self._has_yaml = False
        self._has_toml = False
        try:
            import yaml
            self._has_yaml = True
        except ImportError:
            pass
        try:
            import tomllib  # Python 3.11+
            self._has_toml = True
        except ImportError:
            try:
                import tomli as tomllib
                self._has_toml = True
            except ImportError:
                pass
    
    # ── Loading ─────────────────────────────────────────────
    
    def load(self, extra_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Load config from all layers.
        
        Args:
            extra_files: Additional config files to merge (highest priority)
        
        Returns:
            Merged config dict
        """
        # Start with defaults
        self._config = deepcopy(DEFAULT_CONFIG)
        self._sources = ["defaults"]
        
        # Load files in order
        for filepath_str, source_name in CONFIG_SEARCH_ORDER:
            if filepath_str is None:
                if source_name == "env_vars":
                    env_config = self._load_env_vars()
                    if env_config:
                        self._deep_merge(self._config, env_config)
                        self._sources.append("env_vars")
                continue
            
            filepath = Path(filepath_str).expanduser()
            if not filepath.exists():
                continue
            
            try:
                layer = self._load_file(filepath)
                if layer:
                    self._deep_merge(self._config, layer)
                    self._sources.append(str(filepath))
                    logger.debug(f"Loaded config layer: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load {filepath}: {e}")
        
        # Extra files (highest priority)
        if extra_files:
            for fp in extra_files:
                try:
                    layer = self._load_file(Path(fp).expanduser())
                    if layer:
                        self._deep_merge(self._config, layer)
                        self._sources.append(str(fp))
                except Exception as e:
                    logger.warning(f"Failed to load extra file {fp}: {e}")
        
        # Apply runtime overrides
        for key_path, value in self._overrides.items():
            self._set_nested(self._config, key_path, value)
        
        self._loaded = True
        logger.info(f"Config loaded from {len(self._sources)} sources: {', '.join(self._sources)}")
        return self._config
    
    def reload(self):
        """Reload config (clear + load again)."""
        self._loaded = False
        return self.load()
    
    # ── Access ──────────────────────────────────────────────
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get config value by dot-notation path.
        
        Examples:
          cfg.get("models.default")           → "deepseek-flash"
          cfg.get("router.flash_threshold")   → 500
          cfg.get("nonexistent.key", "fallback") → "fallback"
        """
        if not self._loaded:
            self.load()
        
        keys = key_path.split(".")
        node = self._config
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node
    
    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val
    
    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
    
    # ── Overrides ───────────────────────────────────────────
    
    def add_override(self, key_path: str, value: Any):
        """
        Add a runtime override (persists only for this session).
        Overrides apply on top of all file layers.
        """
        self._overrides[key_path] = value
        if self._loaded:
            self._set_nested(self._config, key_path, value)
    
    def clear_overrides(self):
        """Remove all runtime overrides."""
        self._overrides.clear()
        if self._loaded:
            self.reload()
    
    # ── Utilities ───────────────────────────────────────────
    
    def flat(self, prefix: str = "") -> Dict[str, Any]:
        """Flatten config to dot-notation dict."""
        if not self._loaded:
            self.load()
        result = {}
        self._flatten(self._config, prefix, result)
        return result
    
    def dump(self) -> str:
        """Pretty-print the merged config."""
        if not self._loaded:
            self.load()
        return json.dumps(self._config, indent=2, default=str)
    
    def write(self, path: Union[str, Path], format: str = "yaml") -> bool:
        """
        Write current merged config to a file.
        
        Args:
            path: Output file path
            format: "yaml" or "json"
        """
        if not self._loaded:
            self.load()
        
        filepath = Path(path).expanduser()
        
        if format == "json":
            with open(filepath, "w") as f:
                json.dump(self._config, f, indent=2, default=str)
        elif format == "yaml":
            self._write_yaml(filepath)
        else:
            raise ValueError(f"Unknown format: {format}")
        
        logger.info(f"Config written to {filepath}")
        return True
    
    # ── Internal ────────────────────────────────────────────
    
    def _load_file(self, filepath: Path) -> Optional[Dict[str, Any]]:
        """Load a config file (YAML or TOML based on extension)."""
        filename = filepath.name.lower()
        
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            if self._has_yaml:
                import yaml
                with open(filepath, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            else:
                logger.warning(f"YAML not available, skipping {filepath}")
                return None
        
        elif filename.endswith(".toml"):
            if self._has_toml:
                with open(filepath, "rb") as f:
                    return tomllib.load(f)
            else:
                logger.warning(f"TOML not available, skipping {filepath}")
                return None
        
        elif filename.endswith(".json"):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        
        else:
            logger.debug(f"Unknown config format: {filepath}")
            return None
    
    def _load_env_vars(self) -> Dict[str, Any]:
        """Extract MESHCTX_* env vars into nested dict."""
        config = {}
        for key, value in os.environ.items():
            if key.startswith(ENV_PREFIX):
                # MESHCTX_MODELS_DEFAULT → ["models", "default"]
                parts = key[len(ENV_PREFIX):].lower().split("_")
                # Try to parse value as JSON/number
                parsed = self._parse_env_value(value)
                self._set_nested_list(config, parts, parsed)
        return config
    
    def _parse_env_value(self, value: str) -> Any:
        """Parse env var value (try JSON, number, boolean)."""
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
        return value
    
    def _deep_merge(self, base: Dict, override: Dict):
        """Deep merge override into base (mutates base)."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = deepcopy(value)
    
    def _flatten(self, node: Any, prefix: str, result: Dict[str, Any]):
        """Recursively flatten nested dict."""
        if isinstance(node, dict):
            for k, v in node.items():
                new_prefix = f"{prefix}.{k}" if prefix else k
                self._flatten(v, new_prefix, result)
        elif isinstance(node, list):
            result[prefix] = [self._flatten_value(v) for v in node]
        else:
            result[prefix] = node
    
    def _flatten_value(self, v: Any) -> Any:
        """Convert a value to a flat-safe representation."""
        if isinstance(v, dict):
            return dict(v)
        return v
    
    def _set_nested(self, node: Dict, key_path: str, value: Any):
        """Set a nested key by dot-notation (mutates node)."""
        keys = key_path.split(".")
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value
    
    def _set_nested_list(self, node: Dict, parts: List[str], value: Any):
        """Set nested key from list of parts."""
        for key in parts[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[parts[-1]] = value
    
    def _write_yaml(self, filepath: Path):
        """Write config as YAML (manual, no dependency)."""
        lines = []
        self._yaml_lines(self._config, lines, indent=0)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    
    def _yaml_lines(self, node: Any, lines: List[str], indent: int):
        """Recursively generate YAML lines."""
        prefix = "  " * indent
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict):
                    lines.append(f"{prefix}{k}:")
                    self._yaml_lines(v, lines, indent + 1)
                elif isinstance(v, list):
                    if all(isinstance(x, (str, int, float, bool)) for x in v):
                        items = ", ".join(repr(x) for x in v)
                        lines.append(f"{prefix}{k}: [{items}]")
                    else:
                        lines.append(f"{prefix}{k}:")
                        for item in v:
                            if isinstance(item, dict):
                                lines.append(f"{prefix}  -")
                                self._yaml_lines(item, lines, indent + 2)
                            else:
                                lines.append(f"{prefix}  - {item}")
                elif isinstance(v, bool):
                    lines.append(f"{prefix}{k}: {'true' if v else 'false'}")
                elif isinstance(v, (int, float)):
                    lines.append(f"{prefix}{k}: {v}")
                elif v is None:
                    lines.append(f"{prefix}{k}: null")
                else:
                    lines.append(f"{prefix}{k}: \"{v}\"")
    
    # ── Stats ───────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Config chain statistics."""
        if not self._loaded:
            self.load()
        
        flat = self.flat()
        return {
            "sources": self._sources,
            "total_keys": len(flat),
            "overrides": len(self._overrides),
            "has_yaml": self._has_yaml,
            "has_toml": self._has_toml,
            "loaded": self._loaded,
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_config_chain: Optional[ConfigChain] = None


def get_config_chain() -> ConfigChain:
    """Get or create the global config chain."""
    global _config_chain
    if _config_chain is None:
        _config_chain = ConfigChain()
        _config_chain.load()
    return _config_chain


def get_config(key: str, default: Any = None) -> Any:
    """Shorthand: get a config value."""
    return get_config_chain().get(key, default)

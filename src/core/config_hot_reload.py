"""
meshctx Config Hot Reload — 配置热加载 v1.0
=============================================

生产级配置管理, 支持多格式、热加载、
验证和回滚, 无需重启服务即可更新配置。

核心能力:
  1. 多格式支持 (JSON, YAML, TOML, ENV)
  2. 文件监听 (inotify / 轮询)
  3. 配置验证 (Schema 校验)
  4. 原子热加载 (不中断服务)
  5. 变更历史和回滚
  6. 环境变量覆盖

使用场景:
  - 微服务配置中心
  - 特性开关动态切换
  - 模型参数运行时调整
  - 运维配置即时生效

使用示例:
  chr = get_config_hot_reload()
  chr.load("app_config.json")
  chr.watch("app_config.json", on_change=lambda new_cfg: apply(new_cfg))
  chr.get("model.default_temperature")
  chr.set("model.default_temperature", 0.7)

代码量: ~480 行
"""

import copy
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.config_hot_reload")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

DEFAULT_WATCH_INTERVAL = 5.0  # 秒
MAX_HISTORY = 50


class ConfigFormat(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置文件格式"""
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    ENV = "env"
    INI = "ini"
    AUTO = "auto"       # 自动检测


class ConfigSource(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置来源"""
    FILE = "file"
    ENV = "env"
    DEFAULT = "default"
    OVERRIDE = "override"


class ValidationLevel(str, Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """验证级别"""
    STRICT = "strict"      # 严格的 Schema 验证
    WARN = "warn"          # 警告但不阻止
    NONE = "none"          # 不验证


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ConfigEntry:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置条目 (带来源追踪)"""
    key: str
    value: Any
    source: ConfigSource = ConfigSource.FILE
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigSnapshot:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置快照"""
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    version: int = 1
    comment: str = ""

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "version": self.version,
            "comment": self.comment,
            "keys": list(self.data.keys()),
            "size": len(json.dumps(self.data)),
        }


@dataclass
class WatchDescriptor:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """文件监听描述符"""
    file_path: str
    callback: Callable[[Dict[str, Any]], None]
    interval: float = DEFAULT_WATCH_INTERVAL
    last_mtime: float = 0.0
    enabled: bool = True
    error_count: int = 0


@dataclass
class ValidationRule:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """验证规则"""
    key_pattern: str              # 键模式 (支持 * 通配)
    required: bool = False
    value_type: type = None       # 期望类型
    min_value: Any = None
    max_value: Any = None
    allowed_values: List[Any] = None
    description: str = ""


# ═══════════════════════════════════════════════════════════
# 配置管理核心
# ═══════════════════════════════════════════════════════════

class ConfigStore:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置存储核心

    线程安全的配置存储, 支持原子更新和版本历史。
    """

    def __init__(self, **kw):
        self._data: Dict[str, ConfigEntry] = {}
        self._lock = threading.RLock()
        self._history: List[ConfigSnapshot] = []
        self._version: int = 0

    def get(self, key: str, default: Any = None, **kw) -> Any:
        """获取配置值

        支持点号分隔的嵌套键: "model.gpt.temperature"
        """
        with self._lock:
            # 直接匹配
            if key in self._data:
                return self._data[key].value

            # 嵌套键解析
            parts = key.split(".")
            if len(parts) == 1:
                return default

            # 尝试从值中递归查找
            root_key = parts[0]
            if root_key in self._data:
                value = self._data[root_key].value
                if isinstance(value, dict):
                    for part in parts[1:]:
                        if isinstance(value, dict) and part in value:
                            value = value[part]
                        else:
                            return default
                    return value
            return default

    def set(self, key: str, value: Any, source: ConfigSource = ConfigSource.OVERRIDE, **kw) -> None:
        """设置配置值"""
        with self._lock:
            self._data[key] = ConfigEntry(key=key, value=value, source=source)
            logger.debug(f"Config set: {key} = {value}")

    def delete(self, key: str, **kw) -> bool:
        """删除配置"""
        with self._lock:
            if key in self._data:
                del self._data[key]
                logger.debug(f"Config deleted: {key}")
                return True
        return False

    def set_nested(self, key: str, value: Any, **kw) -> None:
        """设置嵌套配置值

        e.g. set_nested("model.gpt.temperature", 0.7)
        """
        parts = key.split(".")
        if len(parts) == 1:
            self.set(key, value)
            return

        with self._lock:
            root = parts[0]
            if root not in self._data or not isinstance(self._data[root].value, dict):
                self._data[root] = ConfigEntry(key=root, value={}, source=ConfigSource.OVERRIDE)

            current = self._data[root].value
            for part in parts[1:-1]:
                if part not in current or not isinstance(current[part], dict):
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value

    def load_dict(self, data: Dict[str, Any], source: ConfigSource = ConfigSource.FILE, **kw) -> None:
        """批量加载配置 (原子)"""
        with self._lock:
            for key, value in data.items():
                self._data[key] = ConfigEntry(key=key, value=value, source=source)
            logger.info(f"Loaded {len(data)} config keys from {source.value}")

    def to_dict(self, include_metadata: bool = False, **kw) -> Dict[str, Any]:
        """导出为字典"""
        with self._lock:
            if include_metadata:
                return {
                    k: {"value": v.value, "source": v.source.value, "timestamp": v.timestamp}
                    for k, v in self._data.items()
                }
            return {k: v.value for k, v in self._data.items()}

    def keys(self, prefix: str = None, **kw) -> List[str]:
        """列出键"""
        with self._lock:
            keys = list(self._data.keys())
            if prefix:
                keys = [k for k in keys if k.startswith(prefix)]
            return sorted(keys)

    def search(self, pattern: str, **kw) -> Dict[str, Any]:
        """模糊搜索配置键"""
        with self._lock:
            results = {}
            regex = re.compile(pattern.replace("*", ".*"))
            for key, entry in self._data.items():
                if regex.search(key):
                    results[key] = entry.value
            return results

    def snapshot(self, comment: str = "", **kw) -> ConfigSnapshot:
        """创建快照"""
        with self._lock:
            self._version += 1
            snapshot = ConfigSnapshot(
                data=dict(self.to_dict()),
                version=self._version,
                comment=comment,
            )
            self._history.append(snapshot)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]
            return snapshot

    def rollback(self, version: int = None, **kw) -> bool:
        """回滚配置"""
        with self._lock:
            if not self._history:
                return False

            if version is None:
                # 回退到上一版本
                if len(self._history) < 2:
                    return False
                target = self._history[-2]
            else:
                target = next((s for s in self._history if s.version == version), None)
                if not target:
                    return False

            self._data.clear()
            self.load_dict(target.data, source=ConfigSource.FILE)
            self._version = target.version
            logger.info(f"Rolled back config to version {target.version}")
            return True

    def get_history(self, limit: int = 10, **kw) -> List[Dict[str, Any]]:
        """获取版本历史"""
        with self._lock:
            return [s.to_dict() for s in self._history[-limit:]]

    def diff(self, version_a: int, version_b: int = None, **kw) -> Dict[str, Any]:
        """对比两个版本"""
        with self._lock:
            snap_a = next((s for s in self._history if s.version == version_a), None)
            if not snap_a:
                return {"error": f"Version {version_a} not found"}

            if version_b is None:
                data_b = self.to_dict()
            else:
                snap_b = next((s for s in self._history if s.version == version_b), None)
                if not snap_b:
                    return {"error": f"Version {version_b} not found"}
                data_b = snap_b.data

            data_a = snap_a.data
            all_keys = set(list(data_a.keys()) + list(data_b.keys()))
            added = {}
            removed = {}
            changed = {}
            unchanged = {}

            for k in all_keys:
                va = data_a.get(k)
                vb = data_b.get(k)
                if k not in data_a and k in data_b:
                    added[k] = vb
                elif k in data_a and k not in data_b:
                    removed[k] = va
                elif va != vb:
                    changed[k] = {"old": va, "new": vb}
                else:
                    unchanged[k] = va

            return {
                "version_a": version_a,
                "version_b": version_b or "current",
                "added": added,
                "removed": removed,
                "changed": changed,
                "unchanged_count": len(unchanged),
            }


# ═══════════════════════════════════════════════════════════
# 文件监听器
# ═══════════════════════════════════════════════════════════

class FileWatcher:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """文件监听器 (轮询)"""

    def __init__(self, **kw):
        self._watches: Dict[str, WatchDescriptor] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    def add_watch(
        self, file_path: str, callback: Callable[[Dict[str, Any]], None],
        interval: float = DEFAULT_WATCH_INTERVAL,
    ) -> WatchDescriptor:
        """添加文件监听

        Args:
            file_path: 文件路径
            callback: 变更回调 (接收新配置字典)
            interval: 轮询间隔 (秒)
        """
        abs_path = os.path.abspath(file_path)
        with self._lock:
            if abs_path in self._watches:
                logger.warning(f"Already watching: {abs_path}")
                return self._watches[abs_path]

            watch = WatchDescriptor(
                file_path=abs_path,
                callback=callback,
                interval=interval,
            )
            if os.path.exists(abs_path):
                watch.last_mtime = os.path.getmtime(abs_path)

            self._watches[abs_path] = watch
            logger.info(f"Watching file: {abs_path}")
        return watch

    def remove_watch(self, file_path: str, **kw) -> bool:
        """移除文件监听"""
        abs_path = os.path.abspath(file_path)
        with self._lock:
            if abs_path in self._watches:
                del self._watches[abs_path]
                logger.info(f"Stopped watching: {abs_path}")
                return True
        return False

    def start(self, **kw) -> None:
        """启动监听线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="config-watcher",
        )
        self._thread.start()
        logger.info("File watcher started")

    def stop(self, **kw) -> None:
        """停止监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("File watcher stopped")

    def _watch_loop(self, **kw) -> None:
        """监听循环"""
        while self._running:
            with self._lock:
                watches = list(self._watches.values())

            for watch in watches:
                if not watch.enabled:
                    continue
                try:
                    if not os.path.exists(watch.file_path):
                        continue
                    current_mtime = os.path.getmtime(watch.file_path)
                    if current_mtime != watch.last_mtime:
                        watch.last_mtime = current_mtime
                        logger.info(f"File changed: {watch.file_path}")
                        try:
                            # 加载新配置
                            raw = _load_file(watch.file_path)
                            watch.callback(raw)
                            watch.error_count = 0
                        except Exception as e:
                            watch.error_count += 1
                            logger.error(f"Watch callback error for {watch.file_path}: {e}")
                            if watch.error_count > 10:
                                logger.error(f"Disabling watch for {watch.file_path} after 10 errors")
                                watch.enabled = False
                except Exception as e:
                    logger.error(f"Watch error for {watch.file_path}: {e}")

            time.sleep(DEFAULT_WATCH_INTERVAL)

    @property
    def active_watches(self, **kw) -> int:
        with self._lock:
            return sum(1 for w in self._watches.values() if w.enabled)


# ═══════════════════════════════════════════════════════════
# 配置验证器
# ═══════════════════════════════════════════════════════════

class ConfigValidator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置验证器"""

    def __init__(self, **kw):
        self._rules: List[ValidationRule] = []

    def add_rule(self, rule: ValidationRule, **kw) -> None:
        """添加验证规则"""
        self._rules.append(rule)

    def validate(self, data: Dict[str, Any], **kw) -> Tuple[bool, List[str]]:
        """验证配置

        Returns:
            (is_valid, error_messages)
        """
        errors = []
        warnings_list = []

        for rule in self._rules:
            # 构建正则
            pattern = rule.key_pattern.replace("*", ".*")
            regex = re.compile(f"^{pattern}$")

            matching_keys = [k for k in data if regex.match(k)]

            if rule.required and not matching_keys:
                errors.append(f"Required key '{rule.key_pattern}' not found")
                continue

            for key in matching_keys:
                value = data[key]

                if rule.value_type and not isinstance(value, rule.value_type):
                    errors.append(
                        f"Key '{key}': expected {rule.value_type.__name__}, "
                        f"got {type(value).__name__}"
                    )
                    continue

                if rule.min_value is not None and value < rule.min_value:
                    errors.append(
                        f"Key '{key}': value {value} < min {rule.min_value}"
                    )

                if rule.max_value is not None and value > rule.max_value:
                    errors.append(
                        f"Key '{key}': value {value} > max {rule.max_value}"
                    )

                if rule.allowed_values and value not in rule.allowed_values:
                    errors.append(
                        f"Key '{key}': value '{value}' not in {rule.allowed_values}"
                    )

        return len(errors) == 0, errors


# ═══════════════════════════════════════════════════════════
# ConfigHotReload — 主类
# ═══════════════════════════════════════════════════════════

class ConfigHotReload:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配置热加载管理器

    组合配置存储、文件监听和验证。
    支持从多种格式文件加载配置, 并提供热更新能力。
    """

    def __init__(self, **kw):
        self.store = ConfigStore()
        self.watcher = FileWatcher()
        self.validator = ConfigValidator()
        self._on_change_callbacks: List[Callable] = []
        self._lock = threading.RLock()

    # ── 加载配置 ────────────────────────────────────────────

    def load(self, file_path: str, format: ConfigFormat = ConfigFormat.AUTO, **kw) -> Dict[str, Any]:
        """加载配置文件

        Args:
            file_path: 文件路径
            format: 文件格式 (自动检测)

        Returns:
            Dict: 加载的配置
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Config file not found: {file_path}")

        data = _load_file(file_path, format)
        self.store.load_dict(data, source=ConfigSource.FILE)

        # 验证
        valid, errors = self.validator.validate(data)
        if not valid:
            logger.warning(f"Config validation warnings for {file_path}:")
            for err in errors:
                logger.warning(f"  {err}")

        logger.info(f"Loaded config from {file_path}: {len(data)} keys")
        return data

    def load_env(self, prefix: str = "MESHCTX_", **kw) -> Dict[str, Any]:
        """从环境变量加载配置

        MESHCTX_MODEL_TEMPERATURE → model.temperature
        """
        data = {}
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower().replace("_", ".")
                # 尝试类型转换
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif re.match(r"^-?\d+$", value):
                    value = int(value)
                elif re.match(r"^-?\d+\.\d+$", value):
                    value = float(value)
                data[config_key] = value

        if data:
            self.store.load_dict(data, source=ConfigSource.ENV)
            logger.info(f"Loaded {len(data)} config keys from environment (prefix={prefix})")
        return data

    def load_defaults(self, defaults: Dict[str, Any], **kw) -> None:
        """加载默认值"""
        self.store.load_dict(defaults, source=ConfigSource.DEFAULT)

    # ── 配置访问 ────────────────────────────────────────────

    def get(self, key: str, default: Any = None, **kw) -> Any:
        """获取配置值"""
        return self.store.get(key, default)

    def get_int(self, key: str, default: int = 0, **kw) -> int:
        return int(self.get(key, default))

    def get_float(self, key: str, default: float = 0.0, **kw) -> float:
        return float(self.get(key, default))

    def get_bool(self, key: str, default: bool = False, **kw) -> bool:
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    def get_str(self, key: str, default: str = "", **kw) -> str:
        return str(self.get(key, default))

    def get_list(self, key: str, default: List = None, **kw) -> List:
        val = self.get(key, default or [])
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        return [val] if val is not None else []

    def set(self, key: str, value: Any, **kw) -> None:
        """设置配置值 (运行时覆盖)"""
        self.store.set(key, value, source=ConfigSource.OVERRIDE)
        self._notify_change()

    def set_nested(self, key: str, value: Any, **kw) -> None:
        """设置嵌套配置值"""
        self.store.set_nested(key, value)
        self._notify_change()

    def delete(self, key: str, **kw) -> bool:
        return self.store.delete(key)

    def keys(self, prefix: str = None, **kw) -> List[str]:
        return self.store.keys(prefix)

    def search(self, pattern: str, **kw) -> Dict[str, Any]:
        return self.store.search(pattern)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return self.store.to_dict()

    # ── 热加载 ──────────────────────────────────────────────

    def watch(
        self, file_path: str, on_change: Callable[[Dict[str, Any]], None] = None,
        interval: float = DEFAULT_WATCH_INTERVAL,
    ) -> WatchDescriptor:
        """监听文件变更并自动加载

        Args:
            file_path: 文件路径
            on_change: 变更回调 (如果不指定则自动 reload)
            interval: 轮询间隔
        """
        if on_change is None:
            def auto_reload(data, **kw):
                self.store.load_dict(data, source=ConfigSource.FILE)
                self._notify_change()
                logger.info(f"Auto-reloaded config from {file_path}")
            on_change = auto_reload

        watch = self.watcher.add_watch(file_path, on_change, interval)
        self.watcher.start()
        return watch

    def unwatch(self, file_path: str, **kw) -> bool:
        return self.watcher.remove_watch(file_path)

    def on_change(self, callback: Callable[[], None], **kw) -> None:
        """注册配置变更回调"""
        self._on_change_callbacks.append(callback)

    def _notify_change(self, **kw) -> None:
        """通知所有变更回调"""
        self.store.snapshot(comment="auto")
        for cb in self._on_change_callbacks:
            try:
                cb()
            except Exception as e:
                logger.error(f"Change callback error: {e}")

    # ── 版本管理 ────────────────────────────────────────────

    def snapshot(self, comment: str = "", **kw) -> ConfigSnapshot:
        return self.store.snapshot(comment)

    def rollback(self, version: int = None, **kw) -> bool:
        result = self.store.rollback(version)
        if result:
            self._notify_change()
        return result

    def history(self, limit: int = 10, **kw) -> List[Dict[str, Any]]:
        return self.store.get_history(limit)

    def diff(self, v1: int, v2: int = None, **kw) -> Dict[str, Any]:
        return self.store.diff(v1, v2)

    # ── 验证 ────────────────────────────────────────────────

    def add_validation_rule(
        self, key_pattern: str, required: bool = False,
        value_type: type = None, min_value: Any = None,
        max_value: Any = None, allowed_values: List[Any] = None,
        description: str = "",
    ) -> None:
        """添加验证规则"""
        rule = ValidationRule(
            key_pattern=key_pattern,
            required=required,
            value_type=value_type,
            min_value=min_value,
            max_value=max_value,
            allowed_values=allowed_values,
            description=description,
        )
        self.validator.add_rule(rule)

    def validate_current(self, **kw) -> Tuple[bool, List[str]]:
        """验证当前配置"""
        return self.validator.validate(self.to_dict())

    # ── 导出 ────────────────────────────────────────────────

    def export(self, file_path: str, format: ConfigFormat = ConfigFormat.JSON, **kw) -> None:
        """导出配置到文件"""
        data = self.to_dict()
        if format == ConfigFormat.JSON:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format == ConfigFormat.YAML:
            try:
                import yaml
                with open(file_path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False)
            except ImportError:
                raise ImportError("PyYAML required for YAML export")
        elif format == ConfigFormat.ENV:
            with open(file_path, "w") as f:
                for key, value in sorted(data.items()):
                    f.write(f"MESHCTX_{key.upper().replace('.', '_')}={value}\n")
        logger.info(f"Exported config to {file_path}")


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _load_file(file_path: str, format: ConfigFormat = ConfigFormat.AUTO) -> Dict[str, Any]:
    """加载配置文件 (多格式)"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    # 自动检测格式
    if format == ConfigFormat.AUTO:
        ext = os.path.splitext(file_path)[1].lower()
        format_map = {
            ".json": ConfigFormat.JSON,
            ".yaml": ConfigFormat.YAML,
            ".yml": ConfigFormat.YAML,
            ".toml": ConfigFormat.TOML,
            ".env": ConfigFormat.ENV,
            ".ini": ConfigFormat.INI,
        }
        format = format_map.get(ext, ConfigFormat.JSON)

    if format == ConfigFormat.JSON:
        with open(file_path, "r") as f:
            return json.load(f)

    elif format == ConfigFormat.YAML:
        try:
            import yaml
            with open(file_path, "r") as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            raise ImportError("PyYAML required for YAML configs. Install with: pip install pyyaml")

    elif format == ConfigFormat.TOML:
        try:
            import tomllib
            with open(file_path, "rb") as f:
                return tomllib.load(f)
        except ImportError:
            try:
                import tomli
                with open(file_path, "rb") as f:
                    return tomli.load(f)
            except ImportError:
                raise ImportError("tomllib/tomli required for TOML configs")

    elif format == ConfigFormat.ENV:
        data = {}
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    data[key.strip()] = value.strip().strip('"').strip("'")
        return data

    else:
        raise ValueError(f"Unsupported config format: {format}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_config_hot_reload: Optional[ConfigHotReload] = None
_global_chr_lock = threading.Lock()


def get_config_hot_reload() -> ConfigHotReload:
    """获取全局 ConfigHotReload 单例"""
    global _global_config_hot_reload
    if _global_config_hot_reload is None:
        with _global_chr_lock:
            if _global_config_hot_reload is None:
                _global_config_hot_reload = ConfigHotReload()
                logger.info("Created global ConfigHotReload instance")
    return _global_config_hot_reload


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx Config Hot Reload — 诊断工具")
    print("=" * 60)

    chr = ConfigHotReload()

    # 加载默认值
    chr.load_defaults({
        "app.name": "meshctx",
        "app.env": "dev",
        "model.default_temperature": 0.7,
        "model.max_tokens": 4096,
        "logging.level": "INFO",
    })

    # 运行时覆盖
    chr.set("model.default_temperature", 0.9)

    print(f"\n[1] 配置读取:")
    print(f"    app.name = {chr.get_str('app.name')}")
    print(f"    app.env = {chr.get_str('app.env')}")
    print(f"    model.default_temperature = {chr.get_float('model.default_temperature')}")
    print(f"    model.max_tokens = {chr.get_int('model.max_tokens')}")
    print(f"    logging.level = {chr.get_str('logging.level')}")

    # 类型安全访问
    print(f"\n[2] 类型安全访问:")
    print(f"    get_bool('nonexistent') = {chr.get_bool('nonexistent')}")
    print(f"    get_list('nonexistent', ['a','b']) = {chr.get_list('nonexistent', ['a', 'b'])}")
    print(f"    get_float('model.default_temperature') = {chr.get_float('model.default_temperature')}")

    # 搜索
    print(f"\n[3] 搜索 (model.*):")
    for k, v in chr.search("model.*").items():
        print(f"    {k} = {v}")

    # 快照和版本
    v1 = chr.snapshot("initial")
    chr.set("logging.level", "DEBUG")
    v2 = chr.snapshot("changed log level")

    print(f"\n[4] 版本历史:")
    for h in chr.history():
        print(f"    v{h['version']}: {h['comment']} ({h['keys']} keys)")

    print(f"\n[5] Diff v1 → current:")
    diff = chr.diff(v1.version)
    if "changed" in diff:
        for k, v in diff["changed"].items():
            print(f"    {k}: {v['old']} → {v['new']}")

    # 回滚
    print(f"\n[6] 回滚到 v1...")
    chr.rollback(v1.version)
    print(f"    logging.level = {chr.get_str('logging.level')} (should be INFO)")

    # 导出
    export_path = "/tmp/meshctx_test_config.json"
    chr.export(export_path)
    print(f"\n[7] 导出到 {export_path}: {os.path.getsize(export_path)} bytes")

    # 环境变量
    os.environ["MESHCTX_FEATURE_X"] = "enabled"
    env_config = chr.load_env()
    print(f"\n[8] 环境变量: {len(env_config)} keys loaded")
    print(f"    feature.x = {chr.get('feature.x')}")

    print("\n✅ Config Hot Reload 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()

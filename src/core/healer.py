"""Healer — 开源真实实现

健康检查 + 电路断路器 + 错误学习器 + 自愈引擎。

真实实现（开源版）: 纯 Python stdlib (threading / time / logging / enum /
dataclasses)。提供:
  - HealthStatus / CircuitState 状态常量
  - CircuitBreaker 电路断路器 (失败阈值 → OPEN, 冷却后 HALF_OPEN)
  - ErrorLearner 错误分类学习 (TRANSIENT / PERMANENT / UNKNOWN,
    自动恢复建议)
  - SelfHealingEngine 插件健康注册/心跳/故障/崩溃/聚合状态
  - MemoryCompactor 记忆压缩 (L2 → L3 迁移, 对接 memory_hierarchy)
  - HealerPlugin 内核插件 (on_load / generate_report)

不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.healer")


class HealthStatus:
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    FAILING = 'failing'


class CircuitState(Enum):
    CLOSED = 'closed'        # 正常: 请求放行
    OPEN = 'open'            # 熔断: 请求拒绝
    HALF_OPEN = 'half_open'  # 试探: 允许单个请求验证恢复


class ErrorClass(Enum):
    TRANSIENT = 'transient'
    PERMANENT = 'permanent'
    UNKNOWN = 'unknown'


# ═══════════════════════════════════════════════════════════
# CircuitBreaker
# ═══════════════════════════════════════════════════════════

class CircuitBreaker:
    """电路断路器。

    连续失败达到 failure_threshold 后进入 OPEN；OPEN 状态下 check()
    拒绝放行，直到 reset_timeout 冷却期满进入 HALF_OPEN 试探；
    record_success() 复位为 CLOSED，record_failure() 重新熔断。
    """

    def __init__(self, *a, **kw):
        self.failure_threshold: int = int(kw.get("failure_threshold", 5))
        self.reset_timeout: float = float(kw.get("reset_timeout", 30.0))
        self.state: CircuitState = CircuitState.CLOSED
        self.failures: int = 0
        self.last_failure_time: float = 0.0
        self._lock = threading.Lock()

    def check(self):
        """是否允许本次调用放行 (True = 放行)。"""
        now = time.time()
        with self._lock:
            if self.state == CircuitState.OPEN:
                if now - self.last_failure_time >= self.reset_timeout:
                    self.state = CircuitState.HALF_OPEN
                    return True
                return False
            return True

    def record_failure(self) -> CircuitState:
        with self._lock:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
            return self.state

    def record_success(self) -> CircuitState:
        with self._lock:
            self.failures = 0
            self.state = CircuitState.CLOSED
            return self.state

    def stats(self) -> dict:
        with self._lock:
            return {
                "state": self.state.value,
                "failures": self.failures,
                "failure_threshold": self.failure_threshold,
                "reset_timeout": self.reset_timeout,
                "last_failure_time": self.last_failure_time,
            }


# ═══════════════════════════════════════════════════════════
# ErrorLearner — 错误分类 + 自动恢复建议
# ═══════════════════════════════════════════════════════════

_TRANSIENT_KEYWORDS = (
    "timeout", "timed out", "rate_limit", "rate limit", "connection refused",
    "connection reset", "temporar", "retry", "overload", "busy", "eagain",
    "ecolnreset", "too many requests", "network", "超时", "暂时",
)
_PERMANENT_KEYWORDS = (
    "permission denied", "access denied", "not found", "does not exist",
    "no such", "missing", "forbidden", "invalid config", "syntax error",
    "cannot access", "unable to access", "不存在", "语法错误", "无权限",
)


class ErrorLearner:
    """错误模式学习器。

    按关键词把错误消息分为 TRANSIENT / PERMANENT / UNKNOWN，
    并按 (plugin, signature) 聚合统计，给出自动恢复建议。
    """

    # 连续/累计失败达到该次数且无一成功 → 不再建议自动恢复
    AUTO_RECOVER_MAX_FAILURES = 5

    def __init__(self, max_history: int = 2000):
        self._patterns: Dict[tuple, dict] = {}
        self._history: List[dict] = []
        self._max_history = int(max_history)
        self._lock = threading.Lock()

    def classify(self, error: str) -> ErrorClass:
        text = (error or "").lower()
        if not text:
            return ErrorClass.UNKNOWN
        if any(kw in text for kw in _TRANSIENT_KEYWORDS):
            return ErrorClass.TRANSIENT
        if any(kw in text for kw in _PERMANENT_KEYWORDS):
            return ErrorClass.PERMANENT
        return ErrorClass.UNKNOWN

    def record(self, plugin: str, error: str,
               auto_recover_success: Optional[bool] = None) -> ErrorClass:
        """记录一次错误; 返回其分类。"""
        cls = self.classify(error)
        key = (str(plugin), str(error))
        with self._lock:
            pattern = self._patterns.get(key)
            now = time.time()
            if pattern is None:
                pattern = {
                    "plugin": str(plugin),
                    "signature": str(error),
                    "class": cls.value,
                    "count": 0,
                    "auto_recover_attempts": 0,
                    "auto_recover_successes": 0,
                    "first_seen": now,
                    "last_seen": now,
                }
                self._patterns[key] = pattern
            pattern["count"] += 1
            pattern["last_seen"] = now
            if auto_recover_success is not None:
                pattern["auto_recover_attempts"] += 1
                if auto_recover_success:
                    pattern["auto_recover_successes"] += 1
            self._history.append({
                "plugin": str(plugin),
                "error": str(error),
                "class": cls.value,
                "timestamp": now,
            })
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        return cls

    def should_auto_recover(self, error: str) -> bool:
        """是否建议对该错误自动恢复。

        - PERMANENT / UNKNOWN → 不自动恢复
        - TRANSIENT 但累计失败 ≥5 且无一成功 → 停止自动恢复
        - 其余 TRANSIENT → 允许
        """
        cls = self.classify(error)
        if cls is not ErrorClass.TRANSIENT:
            return False
        with self._lock:
            for pattern in self._patterns.values():
                if pattern["signature"] != str(error):
                    continue
                if (pattern["auto_recover_attempts"] >= self.AUTO_RECOVER_MAX_FAILURES
                        and pattern["auto_recover_successes"] == 0):
                    return False
        return True

    def get_known_patterns(self) -> List[dict]:
        """已知错误模式, 按出现次数降序。"""
        with self._lock:
            out = []
            for p in self._patterns.values():
                item = dict(p)
                attempts = p["auto_recover_attempts"]
                item["auto_recover_rate"] = (
                    round(p["auto_recover_successes"] / attempts, 4) if attempts else 0.0
                )
                out.append(item)
            out.sort(key=lambda x: -x["count"])
            return out

    def get_stats(self) -> dict:
        with self._lock:
            transient = sum(1 for p in self._patterns.values() if p["class"] == "transient")
            permanent = sum(1 for p in self._patterns.values() if p["class"] == "permanent")
            unknown = sum(1 for p in self._patterns.values() if p["class"] == "unknown")
            attempts = sum(p["auto_recover_attempts"] for p in self._patterns.values())
            successes = sum(p["auto_recover_successes"] for p in self._patterns.values())
            return {
                "total_patterns": len(self._patterns),
                "transient": transient,
                "permanent": permanent,
                "unknown": unknown,
                "history_size": len(self._history),
                "auto_recover_rate": round(successes / attempts, 4) if attempts else 0.0,
            }


# ═══════════════════════════════════════════════════════════
# SelfHealingEngine — 插件健康注册 / 心跳 / 故障 / 崩溃
# ═══════════════════════════════════════════════════════════

@dataclass
class PluginHealth:
    """单个插件的健康状态。"""
    name: str = ''
    crash_count: int = 0
    consecutive_failures: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    last_crash_time: float = 0.0
    last_failure_time: float = 0.0
    ping_failures: int = 0
    periodic_ping_ok: bool = True
    circuit_state: CircuitState = CircuitState.CLOSED
    last_error: str = ''

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "crashes": self.crash_count,
            "consecutive_failures": self.consecutive_failures,
            "ping_ok": self.periodic_ping_ok,
            "ping_failures": self.ping_failures,
            "circuit": self.circuit_state.value,
            "last_heartbeat": self.last_heartbeat,
            "last_crash_time": self.last_crash_time,
            "last_failure_time": self.last_failure_time,
            "last_error": self.last_error,
        }


class SelfHealingEngine:
    """自愈引擎: 健康检查 + 电路断路器 + 错误学习。

    默认配置（与历史版本一致）:
      restart_delay          = 1.0   秒（模拟重启耗时）
      max_crash_restarts     = 3     次（崩溃重启上限）
      heartbeat_interval     = 5.0   秒（心跳超时判定）
      failure_restart_threshold = 3   （连续失败 N 次建议重启）
      circuit_failure_threshold = 5   （连续失败 N 次熔断）
    """

    def __init__(self):
        self.restart_delay: float = 1.0
        self.max_crash_restarts: int = 3
        self.heartbeat_interval: float = 5.0
        self.failure_restart_threshold: int = 3
        self.circuit_failure_threshold: int = 5
        self._plugin_health: Dict[str, PluginHealth] = {}
        self._error_learner: ErrorLearner = ErrorLearner()
        self._heal_history: List[dict] = []
        self._lock = threading.RLock()
        self._started_at = time.time()

    # ── 注册 / 心跳 ───────────────────────────────────────
    def register_plugin(self, name: str) -> bool:
        with self._lock:
            if name not in self._plugin_health:
                self._plugin_health[name] = PluginHealth(name=str(name))
                return True
            return False

    def heartbeat(self, name: str) -> bool:
        with self._lock:
            health = self._plugin_health.setdefault(name, PluginHealth(name=str(name)))
            health.last_heartbeat = time.time()
            health.ping_failures = 0
            health.periodic_ping_ok = True
            return True

    # ── 故障 / 崩溃 ───────────────────────────────────────
    def report_failure(self, name: str, error: str = '') -> ErrorClass:
        """记录一次运行时故障; 返回错误分类。"""
        with self._lock:
            health = self._plugin_health.setdefault(name, PluginHealth(name=str(name)))
            health.consecutive_failures += 1
            health.last_failure_time = time.time()
            health.last_error = str(error)
            cls = self._error_learner.record(name, error or "unknown")
            if health.consecutive_failures >= self.circuit_failure_threshold:
                health.circuit_state = CircuitState.OPEN
                logger.warning("circuit OPEN for plugin %s (%d failures)",
                               name, health.consecutive_failures)
            return cls

    def report_crash(self, name: str, error: str = '') -> bool:
        """记录一次崩溃。返回是否允许重启（超过 max_crash_restarts 则拒绝）。"""
        with self._lock:
            health = self._plugin_health.setdefault(name, PluginHealth(name=str(name)))
            health.crash_count += 1
            health.consecutive_failures += 1
            health.last_crash_time = time.time()
            health.last_error = str(error)
            self._error_learner.record(name, f"crash: {error}")
            allowed = health.crash_count <= self.max_crash_restarts
            if not allowed:
                logger.error("plugin %s exceeded max_crash_restarts=%d",
                             name, self.max_crash_restarts)
            return allowed

    def should_restart(self, name: str) -> bool:
        with self._lock:
            health = self._plugin_health.get(name)
            if health is None:
                return False
            return health.consecutive_failures >= self.failure_restart_threshold

    def periodic_ping(self, name: str) -> bool:
        """周期性心跳检查; 超时返回 False 并累计 ping_failures。"""
        with self._lock:
            health = self._plugin_health.get(name)
            if health is None:
                return False
            if time.time() - health.last_heartbeat > self.heartbeat_interval:
                health.ping_failures += 1
                health.periodic_ping_ok = False
                return False
            return True

    # ── 聚合 / 报表 ───────────────────────────────────────
    def get_status_aggregation(self) -> dict:
        with self._lock:
            total = len(self._plugin_health)
            healthy = 0
            degraded = 0
            critical = 0
            for h in self._plugin_health.values():
                if h.circuit_state == CircuitState.OPEN or h.crash_count > 0:
                    critical += 1
                elif h.circuit_state == CircuitState.HALF_OPEN or not h.periodic_ping_ok:
                    degraded += 1
                else:
                    healthy += 1
            health_pct = round(healthy / total * 100.0, 1) if total else 100.0
            return {
                "total": total,
                "healthy": healthy,
                "degraded": degraded,
                "critical": critical,
                "health_pct": health_pct,
            }

    def get_system_health(self) -> dict:
        with self._lock:
            agg = self.get_status_aggregation()
            status = HealthStatus.HEALTHY
            if agg["critical"] > 0:
                status = HealthStatus.FAILING
            elif agg["degraded"] > 0:
                status = HealthStatus.DEGRADED
            return {
                "status": status,
                "aggregation": agg,
                "error_learner": self._error_learner.get_stats(),
                "plugins": {name: h.to_dict() for name, h in self._plugin_health.items()},
                "uptime": time.time() - self._started_at,
                "timestamp": time.time(),
            }

    # ── 自愈动作 ──────────────────────────────────────────
    def heal(self) -> dict:
        """执行一轮自愈: 对故障/熔断插件执行"重启"复位。

        不真实等待 restart_delay（避免阻塞），仅在历史中记录计划耗时。
        """
        with self._lock:
            healed = []
            checked = 0
            for name, h in list(self._plugin_health.items()):
                if h.circuit_state == CircuitState.OPEN or h.consecutive_failures > 0 \
                        or not h.periodic_ping_ok:
                    checked += 1
                    h.consecutive_failures = 0
                    h.ping_failures = 0
                    h.periodic_ping_ok = True
                    h.circuit_state = CircuitState.CLOSED
                    h.last_error = ''
                    healed.append(name)
                    self._heal_history.append({
                        "plugin": name,
                        "action": "restart",
                        "scheduled_delay": self.restart_delay,
                        "timestamp": time.time(),
                    })
            return {
                "checked": checked,
                "healed": healed,
                "critical_remaining": sum(
                    1 for h in self._plugin_health.values()
                    if h.circuit_state == CircuitState.OPEN or h.crash_count > 0
                ),
            }

    def get_heal_history(self, limit: int = 20) -> List[dict]:
        with self._lock:
            return list(self._heal_history[-limit:])

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "plugins": len(self._plugin_health),
                "heal_actions": len(self._heal_history),
                "restart_delay": self.restart_delay,
                "max_crash_restarts": self.max_crash_restarts,
                "heartbeat_interval": self.heartbeat_interval,
            }


# ═══════════════════════════════════════════════════════════
# MemoryCompactor — L2 → L3 记忆迁移
# ═══════════════════════════════════════════════════════════

class MemoryCompactor:
    """记忆压缩器: 将长时间未访问/陈旧的 SHORT_TERM(L2) 记忆提升为
    LONG_TERM(L3)，减少工作记忆压力。对接 memory_hierarchy 存储。
    """

    # 默认: 创建超过 7 天且 importance >= 0.3 的 L2 记忆被提升到 L3
    RETENTION_THRESHOLD_SECONDS = 86400 * 7
    MIN_IMPORTANCE = 0.3

    def __init__(self, retention_seconds: float | None = None,
                 min_importance: float | None = None):
        self.retention_seconds = (
            float(retention_seconds) if retention_seconds is not None
            else self.RETENTION_THRESHOLD_SECONDS
        )
        self.min_importance = (
            float(min_importance) if min_importance is not None else self.MIN_IMPORTANCE
        )
        self._promotion_history: List[dict] = []

    async def compact(self, store) -> dict:
        """对 HierarchicalMemoryStore 执行一次压缩。

        返回: {"l2_to_l3": int, "total_scanned": int, "promoted": [ids]}
        """
        try:
            from .memory_hierarchy import MemoryLevel, MemoryItem  # noqa: F401
        except ImportError as e:  # 可选集成: 无 memory_hierarchy 时显式降级
            logger.warning("memory_hierarchy unavailable, compaction skipped: %s", e)
            return {"l2_to_l3": 0, "total_scanned": 0, "promoted": [], "error": str(e)}

        items = getattr(store, "_items", None)
        if items is None:
            return {"l2_to_l3": 0, "total_scanned": 0, "promoted": []}

        now = time.time()
        l2_to_l3 = 0
        promoted: List[str] = []

        def _is_short_term(item) -> bool:
            level = getattr(item, "level", None)
            try:
                if isinstance(level, MemoryLevel):
                    return level in (MemoryLevel.SHORT_TERM, MemoryLevel.WORKING, MemoryLevel.L2)
                return int(level) in (1, 2)
            except (TypeError, ValueError):
                return False

        for item in list(items.values()):
            if not _is_short_term(item):
                continue
            age = now - getattr(item, "created_at", now)
            importance = float(getattr(item, "importance", 0.5) or 0.0)
            access_count = int(getattr(item, "access_count", 0) or 0)
            # 升级条件: 陈旧(≥retention) 且有一定重要度; 或高频访问
            if (age >= self.retention_seconds and importance >= self.min_importance) \
                    or access_count >= 3:
                item.level = MemoryLevel.LONG_TERM
                l2_to_l3 += 1
                promoted.append(getattr(item, "id", "") or getattr(item, "key", ""))

        if promoted:
            self._promotion_history.append({
                "timestamp": now,
                "promoted": list(promoted),
            })
            logger.info("compaction: %d L2 -> L3 memories", l2_to_l3)
        return {
            "l2_to_l3": l2_to_l3,
            "total_scanned": len(items),
            "promoted": promoted,
        }

    def get_history(self, limit: int = 20) -> List[dict]:
        return list(self._promotion_history[-limit:])


# ═══════════════════════════════════════════════════════════
# HealerPlugin — 内核插件
# ═══════════════════════════════════════════════════════════

class HealerPlugin:
    """自愈插件: 注册进 Kernel 后通过 on_load 激活引擎。"""

    name = "healer"
    info = "meshctx healer plugin (open-source real impl)"
    state = 'active'
    version = '1.0.0'

    def __init__(self, **kw):
        self.engine = SelfHealingEngine()
        self.kernel = None
        self._config = dict(kw)

    async def on_load(self, kernel):
        self.kernel = kernel
        # 可选集成: 订阅 healer.heal 事件; 事件总线不可用时插件仍可独立运行
        bus = getattr(kernel, "bus", None) or getattr(kernel, "event_bus", None)
        if bus is not None and hasattr(bus, "subscribe"):
            try:
                bus.subscribe("healer.heal", self.on_event, plugin_name=self.name)
            except NotImplementedError:
                logger.info("event bus is a stub — healer runs standalone")
        return True

    async def on_event(self, event):
        event_type = getattr(event, "type", None)
        if event_type == "healer.heal":
            return self.engine.heal()
        return None

    def generate_report(self):
        return {
            "plugin": self.name,
            "info": self.info,
            "status": self.state,
            "health": self.engine.get_system_health(),
            "stats": self.engine.get_stats(),
            "timestamp": time.time(),
        }


# ═══════════════════════════════════════════════════════════
# AUTO_HEALER — 测试/外部访问的全局句柄
# ═══════════════════════════════════════════════════════════

class _AutoHealerRegistry:
    """持有单例 SelfHealingEngine 的注册表（兼容 conftest 重置）。"""

    _instance: Optional[SelfHealingEngine] = None

    @classmethod
    def get(cls) -> SelfHealingEngine:
        if cls._instance is None:
            cls._instance = SelfHealingEngine()
        return cls._instance


AUTO_HEALER = _AutoHealerRegistry


def get_auto_healer() -> SelfHealingEngine:
    """返回全局自愈引擎单例。"""
    return AUTO_HEALER.get()


__all__ = [
    "HealthStatus", "CircuitState", "CircuitBreaker",
    "ErrorClass", "ErrorLearner",
    "PluginHealth", "SelfHealingEngine", "MemoryCompactor",
    "HealerPlugin", "AUTO_HEALER", "get_auto_healer",
]

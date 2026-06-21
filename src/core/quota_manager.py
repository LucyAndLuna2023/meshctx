"""
meshctx Quota Manager — 多层级配额管控
======================================

用户/组织/全局多层级配额管理, 支持弹性配额与告警。

核心功能:
  1. 多层级配额 — 用户 (user) / 组织 (org) / 全局 (global)
  2. 时间窗口 — 每分钟 (minute) / 小时 (hour) / 天 (day) / 月 (month)
  3. 配额弹性 — 硬限制 (hard) / 软限制 (soft) / 突发额度 (burst)
  4. 配额使用追踪 — 实时使用量, 历史趋势
  5. 配额告警 — 使用率阈值通知
  6. 配额恢复策略 — 窗口重置, 手动补充, 自动扩展

使用示例:
  qm = get_quota_manager()
  qm.set_quota("user:alice", max_tokens=100000, window="day")
  used, remaining, allowed = qm.check("user:alice", tokens=500)
  if not allowed:
      print(f"Quota exceeded: {used}/{used + remaining}")
  qm.consume("user:alice", tokens=500)
"""

import bisect
import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.quota_manager")


# ═══════════════════════════════════════════════════════════
# 枚举与数据结构
# ═══════════════════════════════════════════════════════════

class QuotaLevel(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配额层级。"""
    GLOBAL = "global"     # 全局配额
    ORG = "org"           # 组织配额
    USER = "user"         # 用户配额


class QuotaWindow(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """时间窗口。"""
    MINUTE = "minute"     # 60 秒
    HOUR = "hour"         # 3600 秒
    DAY = "day"           # 86400 秒
    MONTH = "month"       # 2592000 秒 (30 天)
    FOREVER = "forever"   # 永不重置


WINDOW_SECONDS = {
    QuotaWindow.MINUTE: 60,
    QuotaWindow.HOUR: 3600,
    QuotaWindow.DAY: 86400,
    QuotaWindow.MONTH: 2592000,
    QuotaWindow.FOREVER: float("inf"),
}


class QuotaLimitType(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """限制类型。"""
    HARD = "hard"         # 硬限制 — 达到后拒绝
    SOFT = "soft"         # 软限制 — 达到后告警但不拒绝
    BURST = "burst"       # 突发 — 短期超额


@dataclass
class QuotaConfig:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配额配置 — 定义一条配额规则。"""
    key: str                              # 配额标识 (e.g. "user:alice", "org:acme")
    level: QuotaLevel = QuotaLevel.USER
    max_units: int = 0                    # 窗口内最大配额单位
    window: QuotaWindow = QuotaWindow.DAY
    limit_type: QuotaLimitType = QuotaLimitType.HARD
    burst_units: int = 0                  # 突发额度 (额外)
    soft_limit_pct: float = 0.8           # 软限制阈值 (80% 开始告警)
    enabled: bool = True
    auto_refill: bool = True              # 窗口重置时是否自动恢复
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuotaUsage:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配额使用记录。"""
    key: str
    used: int = 0                        # 已使用量
    window_start: float = 0.0            # 当前窗口开始时间
    window_end: float = 0.0              # 当前窗口结束时间
    last_updated: float = 0.0            # 最后更新时间
    burst_used: int = 0                  # 已使用突发额度
    history: List[Tuple[float, int]] = field(default_factory=list)  # (timestamp, cumulative)


@dataclass
class QuotaResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配额检查结果。"""
    allowed: bool
    key: str
    used: int
    remaining: int                       # 剩余配额 (含 burst)
    limit: int                           # 总限额
    burst_available: int                 # 剩余突发额度
    window_remaining_seconds: float      # 窗口剩余时间
    level: QuotaLevel
    window: QuotaWindow
    limit_type: QuotaLimitType
    near_soft_limit: bool = False        # 是否接近软限制
    message: str = ""


@dataclass
class QuotaAlert:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配额告警。"""
    key: str
    level: QuotaLevel
    usage_pct: float                     # 使用率 (0.0 - 1.0+)
    used: int
    limit: int
    window: QuotaWindow
    limit_type: QuotaLimitType
    timestamp: float
    severity: str = "warning"            # info | warning | critical
    message: str = ""


@dataclass
class QuotaStats:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """配额管理器统计。"""
    total_checks: int = 0
    total_allowed: int = 0
    total_blocked: int = 0
    total_alerts: int = 0
    active_configs: int = 0
    active_usages: int = 0
    last_updated: float = 0.0


# ═══════════════════════════════════════════════════════════
# QuotaManager 主类
# ═══════════════════════════════════════════════════════════

class QuotaManager:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """
    多层级配额管理器 — 用户/组织/全局 + 弹性配额。

    层级优先级 (检查顺序):
      1. 用户级 (User)      — 最细粒度
      2. 组织级 (Org)       — 中间粒度
      3. 全局级 (Global)    — 最粗粒度

    时间窗口管理:
      - 每个 window 独立计算窗口起止时间
      - 窗口到期自动重置使用量
      - minute: 按分钟对齐, hour: 按小时对齐, day: 按天对齐, month: 按月对齐

    配额弹性:
      - hard: 硬限制, 达到后拒绝
      - soft: 软限制, 达到后告警但允许继续
      - burst: 额外突发额度, 超出主配额时消耗 burst
    """

    def __init__(self, persist_path: Optional[str] = None, **kw):
        # 配置存储
        self._configs: Dict[str, QuotaConfig] = {}
        self._config_lock = threading.Lock()

        # 使用量存储
        self._usages: Dict[str, QuotaUsage] = {}
        self._usage_lock = threading.Lock()

        # 告警回调
        self._alert_callbacks: List[Callable[[QuotaAlert], None]] = []
        self._alerts: List[QuotaAlert] = []

        # 统计
        self._stats = QuotaStats()

        # 持久化
        self._persist_path = Path(
            persist_path or os.environ.get(
                "MESHCTX_QUOTA_PERSIST",
                str(Path.home() / ".meshctx" / "quota_manager.json"),
            )
        )
        self._load()

        # 清理线程
        self._cleanup_interval = 300  # 5 分钟
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="quota-cleanup"
        )
        self._cleanup_thread.start()

        logger.info(f"QuotaManager initialized: {len(self._configs)} configs")

    # ── 配额配置 ──────────────────────────────────────

    def set_quota(
        self,
        key: str,
        max_units: int,
        window: Union[str, QuotaWindow] = "day",
        level: Union[str, QuotaLevel] = "user",
        limit_type: Union[str, QuotaLimitType] = "hard",
        burst_units: int = 0,
        soft_limit_pct: float = 0.8,
        enabled: bool = True,
        auto_refill: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> QuotaConfig:
        """
        设置配额规则。

        Args:
            key: 配额标识
            max_units: 窗口内最大配额单位 (0 = 无限)
            window: 时间窗口 ("minute"|"hour"|"day"|"month"|"forever")
            level: 层级 ("global"|"org"|"user")
            limit_type: 限制类型 ("hard"|"soft"|"burst")
            burst_units: 突发额度
            soft_limit_pct: 软限制触发百分比
            enabled: 启用
            auto_refill: 窗口到期是否自动恢复

        Returns:
            QuotaConfig
        """
        # 转换字符串枚举
        if isinstance(window, str):
            window = QuotaWindow(window)
        if isinstance(level, str):
            level = QuotaLevel(level)
        if isinstance(limit_type, str):
            limit_type = QuotaLimitType(limit_type)

        config = QuotaConfig(
            key=key,
            level=level,
            max_units=max_units,
            window=window,
            limit_type=limit_type,
            burst_units=burst_units,
            soft_limit_pct=soft_limit_pct,
            enabled=enabled,
            auto_refill=auto_refill,
            metadata=metadata or {},
        )

        with self._config_lock:
            self._configs[key] = config

        # 初始化使用记录
        now = time.time()
        ws, we = self._compute_window(window, now)
        with self._usage_lock:
            if key not in self._usages:
                self._usages[key] = QuotaUsage(
                    key=key,
                    window_start=ws,
                    window_end=we,
                    last_updated=now,
                )

        self._save()
        logger.info(f"Quota set: {key} ({level.value}, {max_units}/{window.value}, {limit_type.value})")
        return config

    def get_quota_config(self, key: str, **kw) -> Optional[QuotaConfig]:
        """获取配额配置。"""
        with self._config_lock:
            return self._configs.get(key)

    def list_quota_configs(self, **kw) -> List[QuotaConfig]:
        """列出所有配额配置。"""
        with self._config_lock:
            return list(self._configs.values())

    def remove_quota(self, key: str, **kw) -> bool:
        """移除配额配置。"""
        with self._config_lock:
            if key in self._configs:
                del self._configs[key]
                self._save()
                with self._usage_lock:
                    self._usages.pop(key, None)
                logger.info(f"Quota removed: {key}")
                return True
        return False

    # ── 配额检查 + 消费 ───────────────────────────────

    def check(
        self,
        key: str,
        units: int = 1,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Tuple[int, int, bool]:
        """
        检查配额是否足够。

        按层级检查: user → org → global

        Args:
            key: 配额标识
            units: 请求消耗的配额单位
            user_id: 用户 ID (自动检查用户级配额)
            org_id: 组织 ID (自动检查组织级配额)

        Returns:
            (used, remaining, allowed)
        """
        self._stats.total_checks += 1
        self._stats.last_updated = time.time()

        # 检查指定 key 的配额
        config = self.get_quota_config(key)
        if config is None:
            # 自动创建: 无限制 (无限配额)
            config = self.set_quota(key=key, max_units=0, window="day", limit_type="soft")
            logger.info(f"Auto-created unlimited quota for: {key}")

        result = self._check_single(config, units)
        if not result.allowed:
            self._stats.total_blocked += 1
            return result.used, result.remaining, False

        # 检查用户级 (如果提供了 user_id)
        if user_id:
            user_key = f"user:{user_id}:{key}"
            user_config = self.get_quota_config(user_key)
            if user_config is None:
                user_config = self.get_quota_config(f"user:{user_id}")
            if user_config:
                user_result = self._check_single(user_config, units)
                if not user_result.allowed:
                    self._stats.total_blocked += 1
                    return user_result.used, user_result.remaining, False

        # 检查组级 (如果提供了 org_id)
        if org_id:
            org_key = f"org:{org_id}:{key}"
            org_config = self.get_quota_config(org_key)
            if org_config is None:
                org_config = self.get_quota_config(f"org:{org_id}")
            if org_config:
                org_result = self._check_single(org_config, units)
                if not org_result.allowed:
                    self._stats.total_blocked += 1
                    return org_result.used, org_result.remaining, False

        self._stats.total_allowed += 1
        return result.used, result.remaining, True

    def _check_single(self, config: QuotaConfig, units: int, **kw) -> QuotaResult:
        """检查单条配额规则。"""
        if not config.enabled or config.max_units == 0:
            return QuotaResult(
                allowed=True,
                key=config.key,
                used=0,
                remaining=0,
                limit=0,
                burst_available=0,
                window_remaining_seconds=float("inf"),
                level=config.level,
                window=config.window,
                limit_type=QuotaLimitType.SOFT,
                message="Unlimited",
            )

        usage = self._get_or_create_usage(config)
        self._refresh_window(config, usage)

        total_limit = config.max_units + config.burst_units
        available = total_limit - usage.used

        if units <= available:
            near_soft = (usage.used + units) >= (config.max_units * config.soft_limit_pct)
            return QuotaResult(
                allowed=True,
                key=config.key,
                used=usage.used,
                remaining=available,
                limit=total_limit,
                burst_available=config.burst_units - usage.burst_used,
                window_remaining_seconds=max(0, usage.window_end - time.time()),
                level=config.level,
                window=config.window,
                limit_type=config.limit_type,
                near_soft_limit=near_soft,
            )

        # 超出限额
        if config.limit_type == QuotaLimitType.HARD:
            return QuotaResult(
                allowed=False,
                key=config.key,
                used=usage.used,
                remaining=0,
                limit=total_limit,
                burst_available=0,
                window_remaining_seconds=max(0, usage.window_end - time.time()),
                level=config.level,
                window=config.window,
                limit_type=config.limit_type,
                message=f"Hard limit exceeded: {usage.used}/{total_limit}",
            )

        # 软限制: 发出告警但允许
        self._maybe_alert(config, usage, units)
        return QuotaResult(
            allowed=True,
            key=config.key,
            used=usage.used,
            remaining=0,
            limit=total_limit,
            burst_available=0,
            window_remaining_seconds=max(0, usage.window_end - time.time()),
            level=config.level,
            window=config.window,
            limit_type=config.limit_type,
            near_soft_limit=True,
            message=f"Soft limit exceeded: {usage.used}/{total_limit}",
        )

    def consume(
        self,
        key: str,
        units: int = 1,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Tuple[int, int, bool]:
        """
        检查并消费配额。

        Args:
            key: 配额标识
            units: 消耗的配额单位
            user_id: 用户 ID
            org_id: 组织 ID

        Returns:
            (used, remaining, allowed)
        """
        used, remaining, allowed = self.check(key, units, user_id=user_id, org_id=org_id)
        if not allowed:
            return used, remaining, False

        # 消费主 key
        self._consume_single(key, units)

        # 消费用户级
        if user_id:
            user_key = f"user:{user_id}:{key}"
            if user_key in self._get_config_keys():
                self._consume_single(user_key, units)
            else:
                user_generic = f"user:{user_id}"
                if user_generic in self._get_config_keys():
                    self._consume_single(user_generic, units)

        # 消费组织级
        if org_id:
            org_key = f"org:{org_id}:{key}"
            if org_key in self._get_config_keys():
                self._consume_single(org_key, units)
            else:
                org_generic = f"org:{org_id}"
                if org_generic in self._get_config_keys():
                    self._consume_single(org_generic, units)

        return used, remaining, allowed

    def _consume_single(self, key: str, units: int, **kw):
        """消费单条配额。"""
        config = self.get_quota_config(key)
        if config is None or not config.enabled or config.max_units == 0:
            return

        with self._usage_lock:
            usage = self._usages.get(key)
            if usage is None:
                return
            self._refresh_window(config, usage)
            usage.used += units
            usage.last_updated = time.time()
            # 记录历史
            usage.history.append((time.time(), usage.used))
            # 只保留最近 1000 条
            if len(usage.history) > 1000:
                usage.history = usage.history[-1000:]

            # 追踪突发消耗
            if usage.used > config.max_units:
                usage.burst_used = usage.used - config.max_units

    # ── 配额查询 ──────────────────────────────────────

    def get_usage(self, key: str, **kw) -> Optional[QuotaUsage]:
        """获取配额使用量。"""
        with self._usage_lock:
            return self._usages.get(key)

    def get_remaining(self, key: str, **kw) -> int:
        """获取剩余配额。"""
        config = self.get_quota_config(key)
        if config is None or config.max_units == 0:
            return float("inf")  # type: ignore
        usage = self._get_or_create_usage(config)
        self._refresh_window(config, usage)
        return max(0, config.max_units + config.burst_units - usage.used)

    def get_usage_pct(self, key: str, **kw) -> float:
        """获取使用率百分比 (0.0 - 1.0+)。"""
        config = self.get_quota_config(key)
        if config is None or config.max_units == 0:
            return 0.0
        usage = self._get_or_create_usage(config)
        self._refresh_window(config, usage)
        return usage.used / config.max_units

    # ── 弹性配额 ──────────────────────────────────────

    def set_burst(self, key: str, burst_units: int, **kw) -> bool:
        """设置突发额度。"""
        config = self.get_quota_config(key)
        if config is None:
            return False
        with self._config_lock:
            config.burst_units = max(0, burst_units)
        self._save()
        logger.info(f"Burst set: {key} +{burst_units}")
        return True

    def set_soft_limit(self, key: str, pct: float, **kw) -> bool:
        """设置软限制百分比。"""
        config = self.get_quota_config(key)
        if config is None:
            return False
        with self._config_lock:
            config.soft_limit_pct = max(0.0, min(1.0, pct))
            config.limit_type = QuotaLimitType.SOFT
        self._save()
        logger.info(f"Soft limit set: {key} at {pct*100}%")
        return True

    def set_hard_limit(self, key: str, **kw) -> bool:
        """将配额设为硬限制。"""
        config = self.get_quota_config(key)
        if config is None:
            return False
        with self._config_lock:
            config.limit_type = QuotaLimitType.HARD
        self._save()
        return True

    # ── 告警 ──────────────────────────────────────────

    def _maybe_alert(self, config: QuotaConfig, usage: QuotaUsage, units: int, **kw):
        """检查是否需要发出告警。"""
        if config.max_units == 0:
            return

        usage_pct = (usage.used + units) / config.max_units
        severity = "info"
        if usage_pct >= 1.0:
            severity = "critical"
        elif usage_pct >= config.soft_limit_pct:
            severity = "warning"

        if usage_pct >= config.soft_limit_pct or usage_pct >= 1.0:
            alert = QuotaAlert(
                key=config.key,
                level=config.level,
                usage_pct=usage_pct,
                used=usage.used + units,
                limit=config.max_units,
                window=config.window,
                limit_type=config.limit_type,
                timestamp=time.time(),
                severity=severity,
                message=f"Quota {severity}: {config.key} at {usage_pct*100:.0f}% ({usage.used}/{config.max_units})",
            )
            self._alerts.append(alert)
            self._stats.total_alerts += 1

            # 触发回调
            for cb in self._alert_callbacks:
                try:
                    cb(alert)
                except Exception as e:
                    logger.error(f"Alert callback error: {e}")

            logger.warning(alert.message)

    def on_alert(self, callback: Callable[[QuotaAlert], None], **kw):
        """注册告警回调。"""
        self._alert_callbacks.append(callback)

    def get_alerts(self, limit: int = 50, **kw) -> List[QuotaAlert]:
        """获取最近告警。"""
        return self._alerts[-limit:]

    def clear_alerts(self, **kw):
        """清除告警历史。"""
        self._alerts.clear()

    # ── 配额恢复 ──────────────────────────────────────

    def reset_usage(self, key: str, **kw) -> bool:
        """手动重置配额使用量。"""
        with self._usage_lock:
            if key in self._usages:
                now = time.time()
                usage = self._usages[key]
                ws, we = self._compute_window(
                    self._configs[key].window if key in self._configs else QuotaWindow.DAY,
                    now,
                )
                usage.used = 0
                usage.burst_used = 0
                usage.window_start = ws
                usage.window_end = we
                usage.last_updated = now
                usage.history.append((now, 0))
                logger.info(f"Quota usage reset: {key}")
                return True
        return False

    def reset_all_usages(self, **kw):
        """重置所有配额使用量。"""
        count = 0
        for key in list(self._configs.keys()):
            if self.reset_usage(key):
                count += 1
        logger.info(f"Reset {count} quota usages")

    def add_units(self, key: str, units: int, **kw) -> bool:
        """手动补充配额 (减少已使用量)。"""
        with self._usage_lock:
            if key in self._usages:
                usage = self._usages[key]
                usage.used = max(0, usage.used - units)
                usage.burst_used = max(0, usage.burst_used - units)
                usage.last_updated = time.time()
                usage.history.append((time.time(), usage.used))
                logger.info(f"Quota refund: {key} +{units} (now {usage.used})")
                return True
        return False

    def set_usage(self, key: str, used: int, **kw) -> bool:
        """手动设置已使用量。"""
        with self._usage_lock:
            if key in self._usages:
                self._usages[key].used = max(0, used)
                self._usages[key].last_updated = time.time()
                return True
        return False

    # ── 窗口管理 ──────────────────────────────────────

    @staticmethod
    def _compute_window(window: QuotaWindow, now: float, **kw) -> Tuple[float, float]:
        """计算窗口起止时间 (按自然周期对齐)。"""
        import datetime

        dt = datetime.datetime.fromtimestamp(now)
        if window == QuotaWindow.MINUTE:
            start = dt.replace(second=0, microsecond=0)
            end = start + datetime.timedelta(minutes=1)
        elif window == QuotaWindow.HOUR:
            start = dt.replace(minute=0, second=0, microsecond=0)
            end = start + datetime.timedelta(hours=1)
        elif window == QuotaWindow.DAY:
            start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + datetime.timedelta(days=1)
        elif window == QuotaWindow.MONTH:
            start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if dt.month == 12:
                end = start.replace(year=dt.year + 1, month=1)
            else:
                end = start.replace(month=dt.month + 1)
        else:  # FOREVER
            start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + datetime.timedelta(days=365 * 100)

        return start.timestamp(), end.timestamp()

    def _refresh_window(self, config: QuotaConfig, usage: QuotaUsage, **kw):
        """检查窗口是否过期, 必要时重置使用量。"""
        now = time.time()
        if now >= usage.window_end:
            if config.auto_refill:
                usage.used = 0
                usage.burst_used = 0
                usage.history.append((now, 0))
            ws, we = self._compute_window(config.window, now)
            usage.window_start = ws
            usage.window_end = we
            usage.last_updated = now
            logger.debug(f"Quota window reset: {config.key} ({config.window.value})")

    def _get_or_create_usage(self, config: QuotaConfig, **kw) -> QuotaUsage:
        """获取或创建使用记录。"""
        with self._usage_lock:
            if config.key not in self._usages:
                now = time.time()
                ws, we = self._compute_window(config.window, now)
                self._usages[config.key] = QuotaUsage(
                    key=config.key,
                    window_start=ws,
                    window_end=we,
                    last_updated=now,
                )
            return self._usages[config.key]

    def _get_config_keys(self, **kw) -> Set[str]:
        """获取所有配置 key。"""
        with self._config_lock:
            return set(self._configs.keys())

    # ── 统计 ──────────────────────────────────────────

    def get_stats(self, **kw) -> QuotaStats:
        """获取配额管理器统计。"""
        with self._config_lock:
            self._stats.active_configs = len(self._configs)
        with self._usage_lock:
            self._stats.active_usages = len(self._usages)
        self._stats.last_updated = time.time()
        return self._stats

    def get_status(self, **kw) -> Dict[str, Any]:
        """
        获取配额管理器完整状态 — 用于监控端点。

        Returns:
            包含所有配额规则的使用率、剩余量、告警统计
        """
        stats = self.get_stats()
        result: Dict[str, Any] = {
            "summary": {
                "total_checks": stats.total_checks,
                "total_allowed": stats.total_allowed,
                "total_blocked": stats.total_blocked,
                "total_alerts": stats.total_alerts,
                "active_configs": stats.active_configs,
                "active_usages": stats.active_usages,
                "last_updated": stats.last_updated,
            },
            "quotas": {},
            "recent_alerts": [],
        }

        for config in self.list_quota_configs():
            usage = self.get_usage(config.key)
            usage_data = {
                "level": config.level.value,
                "window": config.window.value,
                "limit_type": config.limit_type.value,
                "max_units": config.max_units,
                "burst_units": config.burst_units,
                "soft_limit_pct": config.soft_limit_pct,
                "enabled": config.enabled,
                "auto_refill": config.auto_refill,
            }
            if usage:
                usage_data["used"] = usage.used
                usage_data["remaining"] = max(0, config.max_units + config.burst_units - usage.used)
                usage_data["usage_pct"] = round(
                    (usage.used / config.max_units * 100) if config.max_units > 0 else 0, 1
                )
                usage_data["burst_used"] = usage.burst_used
                usage_data["window_remaining"] = round(max(0, usage.window_end - time.time()), 1)
            else:
                usage_data["used"] = 0
                usage_data["remaining"] = config.max_units + config.burst_units
                usage_data["usage_pct"] = 0.0
                usage_data["burst_used"] = 0
                usage_data["window_remaining"] = 0
            result["quotas"][config.key] = usage_data

        for alert in self.get_alerts(10):
            result["recent_alerts"].append({
                "key": alert.key,
                "severity": alert.severity,
                "usage_pct": round(alert.usage_pct * 100, 1),
                "message": alert.message,
                "timestamp": alert.timestamp,
            })

        return result

    # ── 持久化 ────────────────────────────────────────

    def _save(self, **kw):
        """持久化配额配置。"""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_lock:
                data = {
                    "configs": [
                        {
                            "key": c.key,
                            "level": c.level.value,
                            "max_units": c.max_units,
                            "window": c.window.value,
                            "limit_type": c.limit_type.value,
                            "burst_units": c.burst_units,
                            "soft_limit_pct": c.soft_limit_pct,
                            "enabled": c.enabled,
                            "auto_refill": c.auto_refill,
                            "metadata": c.metadata,
                        }
                        for c in self._configs.values()
                    ],
                }
            self._persist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save quota configs: {e}")

    def _load(self, **kw):
        """从磁盘加载配置。"""
        try:
            if self._persist_path.exists():
                data = json.loads(self._persist_path.read_text())
                with self._config_lock:
                    for item in data.get("configs", []):
                        cfg = QuotaConfig(
                            key=item["key"],
                            level=QuotaLevel(item["level"]),
                            max_units=item["max_units"],
                            window=QuotaWindow(item["window"]),
                            limit_type=QuotaLimitType(item["limit_type"]),
                            burst_units=item.get("burst_units", 0),
                            soft_limit_pct=item.get("soft_limit_pct", 0.8),
                            enabled=item.get("enabled", True),
                            auto_refill=item.get("auto_refill", True),
                            metadata=item.get("metadata", {}),
                        )
                        self._configs[cfg.key] = cfg
                # 初始化使用记录
                now = time.time()
                with self._usage_lock:
                    for cfg in self._configs.values():
                        if cfg.key not in self._usages:
                            ws, we = self._compute_window(cfg.window, now)
                            self._usages[cfg.key] = QuotaUsage(
                                key=cfg.key,
                                window_start=ws,
                                window_end=we,
                                last_updated=now,
                            )
                logger.info(f"Loaded {len(self._configs)} quota configs from {self._persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load quota configs: {e}")

    def _cleanup_loop(self, **kw):
        """后台清理 — 清理过期使用记录和旧历史。"""
        while True:
            time.sleep(self._cleanup_interval)
            try:
                now = time.time()
                max_age = 86400 * 7  # 7 天
                with self._usage_lock:
                    stale = []
                    for key, usage in self._usages.items():
                        if usage.used == 0 and now - usage.last_updated > max_age:
                            stale.append(key)
                    for key in stale:
                        del self._usages[key]
                if stale:
                    logger.debug(f"Cleaned up {len(stale)} stale quota usages")
            except Exception as e:
                logger.error(f"Quota cleanup error: {e}")


# ═══════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════

_quota_manager_instance: Optional[QuotaManager] = None
_quota_manager_lock = threading.Lock()


def get_quota_manager(persist_path: Optional[str] = None) -> QuotaManager:
    """
    获取全局 QuotaManager 单例 (auto-create)。

    Args:
        persist_path: 持久化路径

    Returns:
        QuotaManager 实例
    """
    global _quota_manager_instance
    if _quota_manager_instance is None:
        with _quota_manager_lock:
            if _quota_manager_instance is None:
                _quota_manager_instance = QuotaManager(persist_path=persist_path)
    return _quota_manager_instance

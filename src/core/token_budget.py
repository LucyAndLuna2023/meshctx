"""
meshctx Token Budget — Token 预算分配与配额管理
===============================================

多维度 Token 预算管理系统。支持总预算/模型/用户/Session 四级预算分配,
consume/reserve/release 操作、配额跟踪、超额告警与窗口重置。

核心功能:
  1. 预算分配 — 多层级: total / model / user / session
  2. 预算操作 — consume / reserve / release / check
  3. 配额跟踪 — 实时使用量追踪, 历史记录
  4. 超额告警 — 使用率阈值 (80%/95%) 触发告警回调
  5. 预算重置 — 周期性重置 (minute/hour/day/month)
  6. 使用统计 — 按维度聚合统计, 趋势分析

预算维度 (从粗到细):
  total → model → user → session (层级递进, 下层受限上层)

使用示例:
  tb = get_token_budget()
  tb.set_budget("total", max_tokens=1_000_000, window="day")
  tb.set_budget("model:gpt-4", max_tokens=500_000, window="day")
  tb.set_budget("user:alice", max_tokens=100_000, window="day")

  ok, info = tb.consume("user:alice", tokens=500, model="gpt-4")
  if not ok:
      print(f"Budget exceeded: {info}")

设计原则:
  - 零外部依赖: 纯 Python 标准库
  - 线程安全: 读写锁保护
  - 层级级联: 下层消耗自动计入上层
  - 可扩展: 支持自定义告警回调

代码量: ~480 行
"""

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.token_budget")


# ═══════════════════════════════════════════════════════════
# 枚举与常量
# ═══════════════════════════════════════════════════════════

class BudgetLevel(str, Enum):
    """预算层级"""
    TOTAL = "total"       # 全局总预算
    MODEL = "model"       # 按模型 (e.g. "model:gpt-4")
    USER = "user"         # 按用户 (e.g. "user:alice")
    SESSION = "session"   # 按会话 (e.g. "session:abc123")


class BudgetWindow(str, Enum):
    """预算重置窗口"""
    MINUTE = "minute"     # 每分钟重置
    HOUR = "hour"         # 每小时重置
    DAY = "day"           # 每天重置
    MONTH = "month"       # 每月重置
    FOREVER = "forever"   # 永不重置


WINDOW_SECONDS = {
    BudgetWindow.MINUTE: 60,
    BudgetWindow.HOUR: 3600,
    BudgetWindow.DAY: 86400,
    BudgetWindow.MONTH: 2592000,  # 30 天
    BudgetWindow.FOREVER: float("inf"),
}


class BudgetStatus(str, Enum):
    """预算检查结果"""
    OK = "ok"                   # 预算充足
    WARNING = "warning"         # 接近上限 (>80%)
    CRITICAL = "critical"       # 严重不足 (>95%)
    EXCEEDED = "exceeded"       # 已耗尽
    RESERVED = "reserved"       # 已预留
    NOT_CONFIGURED = "not_configured"  # 未配置预算


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class BudgetConfig:
    """预算配置"""
    key: str                                    # 预算标识 (e.g. "user:alice")
    level: BudgetLevel
    max_tokens: int
    window: BudgetWindow = BudgetWindow.DAY
    warning_threshold: float = 0.8              # 告警阈值 (80%)
    critical_threshold: float = 0.95            # 严重阈值 (95%)
    enabled: bool = True
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level.value,
            "max_tokens": self.max_tokens,
            "window": self.window.value,
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold,
            "enabled": self.enabled,
            "description": self.description,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], **kw) -> "BudgetConfig":
        return cls(
            key=d["key"],
            level=BudgetLevel(d["level"]),
            max_tokens=d["max_tokens"],
            window=BudgetWindow(d.get("window", "day")),
            warning_threshold=d.get("warning_threshold", 0.8),
            critical_threshold=d.get("critical_threshold", 0.95),
            enabled=d.get("enabled", True),
            description=d.get("description", ""),
            metadata=d.get("metadata", {}),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class BudgetUsage:
    """预算使用追踪"""
    key: str
    used_tokens: int = 0
    reserved_tokens: int = 0
    window_start: float = field(default_factory=time.time)
    last_consumed: float = 0.0
    consume_count: int = 0
    history: List[Tuple[float, int]] = field(default_factory=list)  # (timestamp, cumulative)

    @property
    def total_committed(self, **kw) -> int:
        """总共已承诺的 Token (已消费 + 已预留)"""
        return self.used_tokens + self.reserved_tokens

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "key": self.key,
            "used_tokens": self.used_tokens,
            "reserved_tokens": self.reserved_tokens,
            "window_start": self.window_start,
            "last_consumed": self.last_consumed,
            "consume_count": self.consume_count,
        }


@dataclass
class BudgetCheckResult:
    """预算检查结果"""
    status: BudgetStatus
    key: str
    max_tokens: int
    used_tokens: int
    remaining: int
    usage_ratio: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "key": self.key,
            "max_tokens": self.max_tokens,
            "used_tokens": self.used_tokens,
            "remaining": self.remaining,
            "usage_ratio": round(self.usage_ratio, 4),
            "message": self.message,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════
# Token 预算管理器
# ═══════════════════════════════════════════════════════════

class TokenBudget:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """多维度 Token 预算管理器

    管理全局/模型/用户/Session 四级预算, 支持 consume/reserve/release、
    窗口重置、告警回调和使用统计。
    """

    def __init__(self, persist_path: Optional[str] = None, **kw):
        self.persist_path = persist_path
        self._configs: Dict[str, BudgetConfig] = {}
        self._usages: Dict[str, BudgetUsage] = {}
        self._reservations: Dict[str, Dict[str, int]] = defaultdict(dict)  # reservation_id -> {budget_key: tokens}
        self._lock = threading.RLock()
        self._alert_callbacks: List[Callable[[BudgetCheckResult], None]] = []

    # ── 预算配置 ──────────────────────────────────────────

    def set_budget(self, key: str, max_tokens: int,
                   level: Optional[BudgetLevel] = None,
                   window: Union[BudgetWindow, str] = BudgetWindow.DAY,
                   warning_threshold: float = 0.8,
                   critical_threshold: float = 0.95,
                   **kwargs) -> BudgetConfig:
        """设置或更新预算配置

        Args:
            key: 预算标识 (e.g. "total", "user:alice", "model:gpt-4")
            max_tokens: 窗口内最大 Token 数
            level: 预算层级 (自动推断: 包含 ":" 则为对应层级)
            window: 重置窗口
            warning_threshold: 告警阈值
            critical_threshold: 严重阈值

        Returns:
            BudgetConfig
        """
        if level is None:
            level = self._infer_level(key)

        # Normalize window to enum
        if isinstance(window, str):
            window = BudgetWindow(window)

        config = BudgetConfig(
            key=key,
            level=level,
            max_tokens=max_tokens,
            window=window,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            **kwargs,
        )

        with self._lock:
            self._configs[key] = config
            if key not in self._usages:
                self._usages[key] = BudgetUsage(key=key)
            logger.info(f"Budget set: {key} = {max_tokens:,} tokens / {window.value}")
        return config

    def _infer_level(self, key: str, **kw) -> BudgetLevel:
        """从 key 推断层级"""
        if key == "total":
            return BudgetLevel.TOTAL
        if key.startswith("model:"):
            return BudgetLevel.MODEL
        if key.startswith("user:"):
            return BudgetLevel.USER
        if key.startswith("session:"):
            return BudgetLevel.SESSION
        return BudgetLevel.USER  # 默认

    def get_budget(self, key: str, **kw) -> Optional[BudgetConfig]:
        """获取预算配置"""
        with self._lock:
            return self._configs.get(key)

    def remove_budget(self, key: str, **kw) -> bool:
        """删除预算配置"""
        with self._lock:
            removed = self._configs.pop(key, None) is not None
            self._usages.pop(key, None)
            if removed:
                logger.info(f"Budget removed: {key}")
            return removed

    # ── 预算检查 ──────────────────────────────────────────

    def check(self, key: str, tokens: int = 0, **kw) -> BudgetCheckResult:
        """检查预算是否允许消费

        Args:
            key: 预算标识
            tokens: 预期消费 Token 数 (0 表示仅查询状态)

        Returns:
            BudgetCheckResult
        """
        with self._lock:
            config = self._configs.get(key)
            if not config or not config.enabled:
                return BudgetCheckResult(
                    status=BudgetStatus.NOT_CONFIGURED,
                    key=key,
                    max_tokens=0,
                    used_tokens=0,
                    remaining=0,
                    usage_ratio=0.0,
                    message=f"No budget configured for {key}",
                )

            self._maybe_reset_window(key)
            usage = self._usages.get(key, BudgetUsage(key=key))
            committed = usage.total_committed + tokens
            remaining = config.max_tokens - usage.total_committed
            ratio = committed / config.max_tokens if config.max_tokens > 0 else 1.0

            if ratio >= 1.0:
                status = BudgetStatus.EXCEEDED
                message = f"Budget exceeded: {committed}/{config.max_tokens} tokens"
            elif ratio >= config.critical_threshold:
                status = BudgetStatus.CRITICAL
                message = f"Budget critical: {ratio:.1%} used"
            elif ratio >= config.warning_threshold:
                status = BudgetStatus.WARNING
                message = f"Budget warning: {ratio:.1%} used"
            else:
                status = BudgetStatus.OK
                message = "Budget OK"

            result = BudgetCheckResult(
                status=status,
                key=key,
                max_tokens=config.max_tokens,
                used_tokens=usage.used_tokens,
                remaining=max(0, remaining - tokens),
                usage_ratio=ratio,
                message=message,
                details={
                    "reserved": usage.reserved_tokens,
                    "window": config.window.value,
                    "level": config.level.value,
                },
            )

            # 触发告警
            if status in (BudgetStatus.WARNING, BudgetStatus.CRITICAL, BudgetStatus.EXCEEDED):
                self._fire_alerts(result)

            return result

    def check_multi(self, keys: List[str], tokens: int = 0, **kw) -> Dict[str, BudgetCheckResult]:
        """检查多个预算维度

        Args:
            keys: 预算标识列表
            tokens: 预期消费 Token 数

        Returns:
            {key: BudgetCheckResult}
        """
        return {key: self.check(key, tokens) for key in keys}

    def check_hierarchical(self, user_key: str, model: str = "",
                           tokens: int = 0) -> Dict[str, BudgetCheckResult]:
        """层级预算检查: total → model → user

        Args:
            user_key: 用户预算 key (e.g. "user:alice")
            model: 模型名 (e.g. "gpt-4")
            tokens: 预期消费 Token 数

        Returns:
            各级检查结果
        """
        keys = ["total"]
        if model:
            keys.append(f"model:{model}")
        if user_key:
            keys.append(user_key)
        return self.check_multi(keys, tokens)

    # ── 消费/预留/释放 ────────────────────────────────────

    def consume(self, key: str, tokens: int,
                model: str = "",
                session_id: str = "") -> Tuple[bool, BudgetCheckResult]:
        """消费 Token 预算

        自动计入上级预算 (total, model, user)

        Args:
            key: 预算标识 (通常是 "user:xxx" 或 "session:xxx")
            tokens: 消费 Token 数
            model: 模型名 (计入对应 model 预算)
            session_id: Session ID (计入对应 session 预算)

        Returns:
            (是否成功, 检查结果)
        """
        with self._lock:
            # 构建检查链: total → model → user → session
            check_keys = ["total"]
            if model:
                check_keys.append(f"model:{model}")
            check_keys.append(key)
            if session_id:
                check_keys.append(f"session:{session_id}")

            # 确保相关预算配置存在
            for ck in check_keys:
                if ck not in self._configs:
                    self._ensure_default_budget(ck)

            # 检查所有层级
            results = {}
            for ck in check_keys:
                result = self.check(ck, tokens)
                results[ck] = result
                if result.status == BudgetStatus.EXCEEDED:
                    return False, result

            # 全部通过, 执行消费
            now = time.time()
            for ck in check_keys:
                usage = self._usages[ck]
                usage.used_tokens += tokens
                usage.last_consumed = now
                usage.consume_count += 1
                usage.history.append((now, usage.used_tokens))

            logger.debug(f"Consumed {tokens} tokens from {key} "
                         f"(model={model}, session={session_id})")
            return True, results[key]

    def reserve(self, reservation_id: str, key: str, tokens: int, **kw) -> BudgetCheckResult:
        """预留 Token 预算 (不实际消费, 但占用配额)

        用于异步操作前的预算锁定。

        Args:
            reservation_id: 预留 ID (用于后续 release)
            key: 预算标识
            tokens: 预留 Token 数

        Returns:
            BudgetCheckResult
        """
        with self._lock:
            result = self.check(key, tokens)
            if result.status == BudgetStatus.EXCEEDED:
                return result

            usage = self._usages.get(key)
            if not usage:
                usage = BudgetUsage(key=key)
                self._usages[key] = usage

            usage.reserved_tokens += tokens
            self._reservations[reservation_id][key] = \
                self._reservations[reservation_id].get(key, 0) + tokens

            logger.debug(f"Reserved {tokens} tokens for {reservation_id} on {key}")
            return result

    def release(self, reservation_id: str, **kw):
        """释放预留的 Token 预算

        Args:
            reservation_id: 预留 ID
        """
        with self._lock:
            if reservation_id not in self._reservations:
                return

            for key, tokens in self._reservations[reservation_id].items():
                if key in self._usages:
                    self._usages[key].reserved_tokens = max(
                        0, self._usages[key].reserved_tokens - tokens
                    )
            del self._reservations[reservation_id]
            logger.debug(f"Released reservation: {reservation_id}")

    def commit_reservation(self, reservation_id: str, **kw):
        """将预留转为实际消费

        Args:
            reservation_id: 预留 ID
        """
        with self._lock:
            if reservation_id not in self._reservations:
                return

            now = time.time()
            for key, tokens in self._reservations[reservation_id].items():
                if key in self._usages:
                    usage = self._usages[key]
                    usage.reserved_tokens = max(0, usage.reserved_tokens - tokens)
                    usage.used_tokens += tokens
                    usage.last_consumed = now
                    usage.consume_count += 1
                    usage.history.append((now, usage.used_tokens))

            del self._reservations[reservation_id]
            logger.debug(f"Committed reservation: {reservation_id}")

    # ── 预算重置 ──────────────────────────────────────────

    def _maybe_reset_window(self, key: str, **kw):
        """检查并执行窗口重置"""
        config = self._configs.get(key)
        if not config:
            return
        usage = self._usages.get(key)
        if not usage:
            return

        window_secs = WINDOW_SECONDS.get(config.window, float("inf"))
        if window_secs == float("inf"):
            return

        elapsed = time.time() - usage.window_start
        if elapsed >= window_secs:
            # 重置窗口
            usage.used_tokens = 0
            usage.reserved_tokens = 0
            usage.window_start = time.time()
            usage.history = []
            logger.info(f"Budget window reset: {key} ({config.window.value})")

    def reset_budget(self, key: str, **kw):
        """手动重置指定预算的窗口"""
        with self._lock:
            if key in self._usages:
                usage = self._usages[key]
                usage.used_tokens = 0
                usage.reserved_tokens = 0
                usage.window_start = time.time()
                usage.history.clear()
                logger.info(f"Budget manually reset: {key}")

    def reset_all(self, **kw):
        """重置所有预算窗口"""
        with self._lock:
            now = time.time()
            for usage in self._usages.values():
                usage.used_tokens = 0
                usage.reserved_tokens = 0
                usage.window_start = now
                usage.history.clear()
            self._reservations.clear()
            logger.info("All budgets reset")

    # ── 告警回调 ──────────────────────────────────────────

    def on_alert(self, callback: Callable[[BudgetCheckResult], None], **kw):
        """注册告警回调

        Args:
            callback: 接收 BudgetCheckResult 的回调函数
        """
        self._alert_callbacks.append(callback)

    def _fire_alerts(self, result: BudgetCheckResult, **kw):
        """触发所有告警回调"""
        for cb in self._alert_callbacks:
            try:
                cb(result)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    # ── 辅助 ──────────────────────────────────────────────

    def _ensure_default_budget(self, key: str, **kw):
        """为未配置的预算 key 创建默认配置"""
        if key == "total":
            self.set_budget(key, max_tokens=1_000_000, level=BudgetLevel.TOTAL)
        elif key.startswith("model:"):
            self.set_budget(key, max_tokens=500_000, level=BudgetLevel.MODEL)
        elif key.startswith("session:"):
            self.set_budget(key, max_tokens=100_000, level=BudgetLevel.SESSION)
        else:
            self.set_budget(key, max_tokens=100_000, level=BudgetLevel.USER)

    # ── 统计 ──────────────────────────────────────────────

    def get_usage(self, key: str, **kw) -> Optional[BudgetUsage]:
        """获取使用记录"""
        with self._lock:
            return self._usages.get(key)

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取全局统计"""
        with self._lock:
            total_configured = len(self._configs)
            total_used = sum(u.used_tokens for u in self._usages.values())
            total_reserved = sum(u.reserved_tokens for u in self._usages.values())
            budget_summary = {}
            for key, config in self._configs.items():
                usage = self._usages.get(key, BudgetUsage(key=key))
                budget_summary[key] = {
                    "max_tokens": config.max_tokens,
                    "used": usage.used_tokens,
                    "reserved": usage.reserved_tokens,
                    "remaining": max(0, config.max_tokens - usage.total_committed),
                    "usage_ratio": round(
                        usage.total_committed / config.max_tokens, 4
                    ) if config.max_tokens > 0 else 0.0,
                    "window": config.window.value,
                    "level": config.level.value,
                    "enabled": config.enabled,
                }

            return {
                "budgets_configured": total_configured,
                "total_used": total_used,
                "total_reserved": total_reserved,
                "active_reservations": len(self._reservations),
                "budget_summary": budget_summary,
            }

    def get_usage_history(self, key: str, limit: int = 100, **kw) -> List[Tuple[float, int]]:
        """获取预算使用历史

        Returns:
            [(timestamp, cumulative_tokens), ...]
        """
        with self._lock:
            usage = self._usages.get(key)
            if not usage:
                return []
            return usage.history[-limit:]

    # ── JSON 持久化 ───────────────────────────────────────

    def to_dict(self, **kw) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "configs": [c.to_dict() for c in self._configs.values()],
                "usages": {k: v.to_dict() for k, v in self._usages.items()},
                "version": "1.0",
                "exported_at": time.time(),
            }

    def save(self, path: Optional[str] = None, **kw):
        """持久化到 JSON 文件"""
        target = path or self.persist_path
        if not target:
            raise ValueError("No persist path specified")

        data = self.to_dict()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Token budget saved to {target}")

    def load(self, path: Optional[str] = None, **kw):
        """从 JSON 文件加载"""
        target = path or self.persist_path
        if not target:
            raise ValueError("No persist path specified")

        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)

        with self._lock:
            self._configs.clear()
            for cfg_data in data.get("configs", []):
                config = BudgetConfig.from_dict(cfg_data)
                self._configs[config.key] = config

            for key, usage_data in data.get("usages", {}).items():
                usage = BudgetUsage(
                    key=usage_data["key"],
                    used_tokens=usage_data.get("used_tokens", 0),
                    reserved_tokens=usage_data.get("reserved_tokens", 0),
                    window_start=usage_data.get("window_start", time.time()),
                    last_consumed=usage_data.get("last_consumed", 0.0),
                    consume_count=usage_data.get("consume_count", 0),
                )
                self._usages[key] = usage

        logger.info(f"Token budget loaded: {len(self._configs)} configs")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_tb_instance: Optional[TokenBudget] = None
_tb_lock = threading.Lock()


def get_token_budget(persist_path: Optional[str] = None) -> TokenBudget:
    """获取 TokenBudget 全局单例 (auto-create)

    Args:
        persist_path: 持久化路径 (仅首次创建时生效)

    Returns:
        TokenBudget 实例
    """
    global _tb_instance
    if _tb_instance is None:
        with _tb_lock:
            if _tb_instance is None:
                _tb_instance = TokenBudget(persist_path=persist_path)
    return _tb_instance


def reset_token_budget():
    """重置全局实例 (用于测试)"""
    global _tb_instance
    with _tb_lock:
        _tb_instance = None

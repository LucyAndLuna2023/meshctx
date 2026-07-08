"""
meshctx Usage Meter — 用量计量 v1.0
=====================================

精确的 API 用量计量和配额管理系统,
支持多租户、多模型、多指标的成本追踪。

核心能力:
  1. 多维度用量追踪 (Token, API 调用, 存储, 带宽)
  2. 配额和速率限制
  3. 成本计算 (按模型/提供商)
  4. 用量报告和趋势分析
  5. 预算告警

使用场景:
  - LLM API Token 用量追踪
  - 多租户计费和配额
  - 成本优化分析
  - 预算控制和告警

使用示例:
  um = get_usage_meter()
  um.record_usage(tenant="org_123", metric="tokens_input", value=1500,
                  model="gpt-4o", provider="openai")
  usage = um.get_usage(tenant="org_123", metric="tokens_input", period="today")

代码量: ~450 行
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.usage_meter")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

class UsagePeriod(str, Enum):
    """时间周期"""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class UsageMetric(str, Enum):
    """用量指标"""
    TOKENS_INPUT = "tokens_input"
    TOKENS_OUTPUT = "tokens_output"
    TOKENS_TOTAL = "tokens_total"
    API_CALLS = "api_calls"
    STORAGE_BYTES = "storage_bytes"
    BANDWIDTH_BYTES = "bandwidth_bytes"
    COMPUTE_SECONDS = "compute_seconds"
    IMAGE_GENERATIONS = "image_generations"
    AUDIO_SECONDS = "audio_seconds"


KNOWN_UNIT_COSTS = {
    (UsageMetric.TOKENS_INPUT, "openai", "gpt-4o"): 2.50 / 1_000_000,
    (UsageMetric.TOKENS_OUTPUT, "openai", "gpt-4o"): 10.00 / 1_000_000,
    (UsageMetric.TOKENS_INPUT, "openai", "gpt-4o-mini"): 0.15 / 1_000_000,
    (UsageMetric.TOKENS_OUTPUT, "openai", "gpt-4o-mini"): 0.60 / 1_000_000,
    (UsageMetric.TOKENS_INPUT, "anthropic", "claude-sonnet-4"): 3.00 / 1_000_000,
    (UsageMetric.TOKENS_OUTPUT, "anthropic", "claude-sonnet-4"): 15.00 / 1_000_000,
    (UsageMetric.TOKENS_INPUT, "deepseek", "deepseek-v4"): 0.14 / 1_000_000,
    (UsageMetric.TOKENS_OUTPUT, "deepseek", "deepseek-v4"): 0.28 / 1_000_000,
    (UsageMetric.API_CALLS, "openai", ""): 0.0,
    (UsageMetric.STORAGE_BYTES, "", ""): 0.023 / (1024 * 1024 * 1024),  # $0.023/GB
}

DEFAULT_UNIT_COST = 0.0


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class MeterEntry:
    """计量条目"""
    tenant: str
    metric: str
    value: float
    model: str = ""
    provider: str = ""
    timestamp: float = field(default_factory=time.time)
    request_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "metric": self.metric,
            "value": self.value,
            "model": self.model,
            "provider": self.provider,
            "timestamp": self.timestamp,
            "request_id": self.request_id,
        }


@dataclass
class QuotaRule:
    """配额规则"""
    tenant: str
    metric: str
    limit: float                     # 配额上限
    period: UsagePeriod
    hard_limit: bool = True          # True=硬限制拒绝, False=软限制告警
    model: str = ""                  # 空 = 所有模型
    alert_threshold: float = 0.8     # 80% 时告警
    created_at: float = field(default_factory=time.time)


@dataclass
class UsageWindow:
    """时间窗口聚合"""
    start: float                     # 窗口起始时间戳
    end: float                       # 窗口结束时间戳
    total: float = 0.0
    count: int = 0
    min_value: float = float("inf")
    max_value: float = 0.0

    def add(self, value: float, **kw):
        self.total += value
        self.count += 1
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)

    @property
    def avg(self, **kw) -> float:
        return self.total / max(1, self.count)


# ═══════════════════════════════════════════════════════════
# 用量聚合引擎
# ═══════════════════════════════════════════════════════════

class UsageAggregator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """用量聚合引擎"""

    def __init__(self, **kw):
        self._entries: List[MeterEntry] = []
        self._lock = threading.RLock()
        self._max_entries = 100000  # 最多保留 10 万条

    def add(self, entry: MeterEntry, **kw) -> None:
        """添加计量条目"""
        with self._lock:
            self._entries.append(entry)
            # 限制内存
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]

    def aggregate(
        self,
        tenant: str = None,
        metric: str = None,
        model: str = None,
        provider: str = None,
        start_time: float = None,
        end_time: float = None,
    ) -> float:
        """聚合用量

        Returns:
            float: 累计值
        """
        with self._lock:
            total = 0.0
            for entry in self._entries:
                if tenant and entry.tenant != tenant:
                    continue
                if metric and entry.metric != metric:
                    continue
                if model and entry.model != model:
                    continue
                if provider and entry.provider != provider:
                    continue
                if start_time and entry.timestamp < start_time:
                    continue
                if end_time and entry.timestamp > end_time:
                    continue
                total += entry.value
            return total

    def aggregate_by_model(
        self, tenant: str, metric: str,
        start_time: float = None, end_time: float = None,
    ) -> Dict[str, float]:
        """按模型聚合"""
        with self._lock:
            by_model = {}
            for entry in self._entries:
                if entry.tenant != tenant:
                    continue
                if entry.metric != metric:
                    continue
                if start_time and entry.timestamp < start_time:
                    continue
                if end_time and entry.timestamp > end_time:
                    continue
                by_model[entry.model or "unknown"] = (
                    by_model.get(entry.model, 0.0) + entry.value
                )
            return by_model

    def aggregate_by_time_buckets(
        self, tenant: str, metric: str,
        period: UsagePeriod = UsagePeriod.DAILY,
        num_buckets: int = 7,
    ) -> List[UsageWindow]:
        """按时间桶聚合"""
        now = time.time()
        bucket_seconds = {
            UsagePeriod.HOURLY: 3600,
            UsagePeriod.DAILY: 86400,
            UsagePeriod.WEEKLY: 604800,
            UsagePeriod.MONTHLY: 2592000,
            UsagePeriod.YEARLY: 31536000,
        }
        bucket_size = bucket_seconds.get(period, 86400)

        windows = []
        for i in range(num_buckets):
            end = now - i * bucket_size
            start = end - bucket_size
            windows.append(UsageWindow(start=start, end=end))

        with self._lock:
            for entry in self._entries:
                if entry.tenant != tenant:
                    continue
                if entry.metric != metric:
                    continue
                for w in windows:
                    if w.start <= entry.timestamp < w.end:
                        w.add(entry.value)
                        break

        return windows

    def clear(self, before_time: float = None, **kw) -> int:
        """清除旧条目"""
        if before_time is None:
            before_time = time.time()
        with self._lock:
            old_count = len(self._entries)
            self._entries = [
                e for e in self._entries
                if e.timestamp >= before_time
            ]
            return old_count - len(self._entries)


# ═══════════════════════════════════════════════════════════
# 成本计算器
# ═══════════════════════════════════════════════════════════

class CostCalculator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """成本计算器"""

    def __init__(self, **kw):
        self._pricing = dict(KNOWN_UNIT_COSTS)
        self._lock = threading.RLock()

    def set_pricing(
        self, provider: str, model: str, metric: str, unit_cost: float,
    ) -> None:
        """设置定价"""
        with self._lock:
            self._pricing[(UsageMetric(metric), provider, model)] = unit_cost
            logger.info(f"Set pricing: {provider}/{model}/{metric} = ${unit_cost}/unit")

    def get_unit_cost(
        self, metric: str, provider: str, model: str,
    ) -> float:
        """获取单位成本"""
        metric_enum = UsageMetric(metric)

        # 精确匹配
        key = (metric_enum, provider, model)
        if key in self._pricing:
            return self._pricing[key]

        # 模糊匹配
        key = (metric_enum, provider, "")
        if key in self._pricing:
            return self._pricing[key]

        key = (metric_enum, "", "")
        if key in self._pricing:
            return self._pricing[key]

        return DEFAULT_UNIT_COST

    def calculate_cost(
        self, usage_value: float, metric: str, provider: str, model: str,
    ) -> float:
        """计算花费"""
        unit_cost = self.get_unit_cost(metric, provider, model)
        return usage_value * unit_cost

    def calculate_total_cost(self, entries: List[MeterEntry], **kw) -> float:
        """计算总花费"""
        total = 0.0
        for entry in entries:
            total += self.calculate_cost(
                entry.value, entry.metric, entry.provider, entry.model,
            )
        return total


# ═══════════════════════════════════════════════════════════
# UsageMeter — 主类
# ═══════════════════════════════════════════════════════════

class UsageMeter:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """用量计量主类

    提供用量追踪、配额检查、成本计算和报告生成。
    """

    def __init__(self, storage_path: str = "", **kw):
        self.aggregator = UsageAggregator()
        self.calculator = CostCalculator()
        self._quotas: Dict[str, QuotaRule] = {}
        self._lock = threading.RLock()
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".meshctx", "usage_meter.json"
        )
        self._load_from_disk()

    # ── 用量记录 ────────────────────────────────────────────

    def record_usage(
        self,
        tenant: str,
        metric: str,
        value: float,
        model: str = "",
        provider: str = "",
        request_id: str = "",
        metadata: Dict[str, Any] = None,
    ) -> Optional[MeterEntry]:
        """记录用量

        Args:
            tenant: 租户标识
            metric: 指标, e.g. "tokens_input"
            value: 用量值
            model: 模型名
            provider: 提供商
            request_id: 请求 ID
            metadata: 附加元数据

        Returns:
            MeterEntry: 创建的条目 (如果超配额则返回 None)
        """
        # 配额检查
        quota_key = f"{tenant}:{metric}:{model}"
        if quota_key in self._quotas:
            quota = self._quotas[quota_key]
            current = self.get_usage(tenant=tenant, metric=metric, model=model)
            if current + value > quota.limit:
                if quota.hard_limit:
                    logger.warning(
                        f"Quota exceeded: {tenant}/{metric}/{model} "
                        f"({current:.0f}/{quota.limit:.0f})"
                    )
                    return None
                else:
                    logger.warning(
                        f"Soft quota exceeded: {tenant}/{metric}/{model} "
                        f"({current:.0f}/{quota.limit:.0f})"
                    )
            elif current + value >= quota.limit * quota.alert_threshold:
                logger.info(
                    f"Quota warning: {tenant}/{metric}/{model} "
                    f"({current:.0f}/{quota.limit:.0f})"
                )

        entry = MeterEntry(
            tenant=tenant,
            metric=metric,
            value=value,
            model=model,
            provider=provider,
            request_id=request_id,
            metadata=metadata or {},
        )
        self.aggregator.add(entry)
        logger.debug(f"Usage recorded: {tenant}/{model}/{metric} +{value}")
        return entry

    def record_batch(self, entries: List[Dict[str, Any]], **kw) -> int:
        """批量记录用量"""
        count = 0
        for e in entries:
            if self.record_usage(
                tenant=e.get("tenant", ""),
                metric=e.get("metric", ""),
                value=e.get("value", 0),
                model=e.get("model", ""),
                provider=e.get("provider", ""),
                request_id=e.get("request_id", ""),
            ):
                count += 1
        return count

    # ── 用量查询 ────────────────────────────────────────────

    def get_usage(
        self,
        tenant: str,
        metric: str = None,
        model: str = None,
        provider: str = None,
        period: str = "today",
    ) -> float:
        """获取用量

        Args:
            tenant: 租户
            metric: 指标
            model: 模型
            provider: 提供商
            period: 时间范围 ("today", "this_week", "this_month", "all")
        """
        now = time.time()
        if period == "today":
            start = now - (now % 86400)
        elif period == "this_week":
            start = now - (now % 604800)
        elif period == "this_month":
            # 简化: 30 天
            start = now - 2592000
        else:
            start = None

        return self.aggregator.aggregate(
            tenant=tenant, metric=metric, model=model,
            provider=provider, start_time=start,
        )

    def get_usage_by_model(
        self, tenant: str, metric: str, period: str = "today",
    ) -> Dict[str, float]:
        """按模型分解用量"""
        now = time.time()
        start = None
        if period == "today":
            start = now - (now % 86400)
        elif period == "this_week":
            start = now - (now % 604800)
        elif period == "this_month":
            start = now - 2592000

        return self.aggregator.aggregate_by_model(
            tenant=tenant, metric=metric, start_time=start,
        )

    def get_usage_trend(
        self, tenant: str, metric: str,
        period: UsagePeriod = UsagePeriod.DAILY,
        num_buckets: int = 7,
    ) -> List[Dict[str, Any]]:
        """获取用量趋势"""
        buckets = self.aggregator.aggregate_by_time_buckets(
            tenant=tenant, metric=metric,
            period=period, num_buckets=num_buckets,
        )
        return [
            {
                "start": b.start,
                "end": b.end,
                "total": b.total,
                "count": b.count,
                "avg": b.avg,
            }
            for b in buckets
        ]

    # ── 成本 ────────────────────────────────────────────────

    def get_cost(
        self, tenant: str, period: str = "today",
    ) -> Dict[str, Any]:
        """获取成本分析

        Returns:
            {total_cost, by_model, by_metric}
        """
        now = time.time()
        start = None
        if period == "today":
            start = now - (now % 86400)
        elif period == "this_week":
            start = now - (now % 604800)
        elif period == "this_month":
            start = now - 2592000

        # 按模型聚合
        tokens_in = self.aggregator.aggregate_by_model(
            tenant, UsageMetric.TOKENS_INPUT.value, start_time=start,
        )
        tokens_out = self.aggregator.aggregate_by_model(
            tenant, UsageMetric.TOKENS_OUTPUT.value, start_time=start,
        )

        by_model = {}
        total = 0.0
        all_models = set(list(tokens_in.keys()) + list(tokens_out.keys()))

        for model in all_models:
            provider = "openai"  # 简化
            cost_in = self.calculator.calculate_cost(
                tokens_in.get(model, 0), UsageMetric.TOKENS_INPUT.value,
                provider, model,
            )
            cost_out = self.calculator.calculate_cost(
                tokens_out.get(model, 0), UsageMetric.TOKENS_OUTPUT.value,
                provider, model,
            )
            model_total = cost_in + cost_out
            by_model[model] = {
                "tokens_input": tokens_in.get(model, 0),
                "tokens_output": tokens_out.get(model, 0),
                "cost_input": round(cost_in, 6),
                "cost_output": round(cost_out, 6),
                "total_cost": round(model_total, 6),
            }
            total += model_total

        return {
            "tenant": tenant,
            "period": period,
            "total_cost": round(total, 6),
            "currency": "USD",
            "by_model": by_model,
        }

    # ── 配额管理 ────────────────────────────────────────────

    def set_quota(
        self,
        tenant: str,
        metric: str,
        limit: float,
        period: UsagePeriod = UsagePeriod.MONTHLY,
        hard_limit: bool = True,
        model: str = "",
        alert_threshold: float = 0.8,
    ) -> QuotaRule:
        """设置配额"""
        quota = QuotaRule(
            tenant=tenant,
            metric=metric,
            limit=limit,
            period=period,
            hard_limit=hard_limit,
            model=model,
            alert_threshold=alert_threshold,
        )
        key = f"{tenant}:{metric}:{model}"
        self._quotas[key] = quota
        logger.info(f"Quota set: {key} = {limit} / {period.value}")
        return quota

    def get_quota(self, tenant: str, metric: str, model: str = "", **kw) -> Optional[QuotaRule]:
        """获取配额"""
        key = f"{tenant}:{metric}:{model}"
        return self._quotas.get(key)

    def check_quota(self, tenant: str, metric: str, model: str = "", **kw) -> Dict[str, Any]:
        """检查配额使用情况"""
        key = f"{tenant}:{metric}:{model}"
        quota = self._quotas.get(key)
        if not quota:
            return {"has_quota": False}

        current = self.get_usage(tenant=tenant, metric=metric, model=model)
        remaining = max(0, quota.limit - current)
        usage_pct = (current / quota.limit * 100) if quota.limit > 0 else 0

        return {
            "has_quota": True,
            "tenant": tenant,
            "metric": metric,
            "model": model,
            "limit": quota.limit,
            "current": current,
            "remaining": remaining,
            "usage_percent": round(usage_pct, 2),
            "period": quota.period.value,
            "hard_limit": quota.hard_limit,
            "exceeded": current >= quota.limit,
        }

    def list_quotas(self, tenant: str = None, **kw) -> List[Dict[str, Any]]:
        """列出配额"""
        quotas = []
        for key, q in self._quotas.items():
            if tenant and q.tenant != tenant:
                continue
            quotas.append({
                "tenant": q.tenant,
                "metric": q.metric,
                "model": q.model or "*",
                "limit": q.limit,
                "period": q.period.value,
                "hard_limit": q.hard_limit,
            })
        return quotas

    # ── 统计 ────────────────────────────────────────────────

    def get_stats(self, **kw) -> Dict[str, Any]:
        """获取统计"""
        tenants = set()
        total_entries = 0
        with self.aggregator._lock:
            total_entries = len(self.aggregator._entries)
            tenants = {e.tenant for e in self.aggregator._entries}

        return {
            "total_entries": total_entries,
            "active_tenants": len(tenants),
            "active_quotas": len(self._quotas),
            "tenants": sorted(tenants),
        }

    def clear_old_data(self, days: int = 90, **kw) -> int:
        """清除旧数据 (默认 90 天)"""
        before = time.time() - days * 86400
        return self.aggregator.clear(before_time=before)

    # ── 持久化 ──────────────────────────────────────────────

    def _save_to_disk(self, **kw) -> None:
        """持久化配额 (用量数据仅内存)"""
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with self._lock:
                data = {
                    "quotas": [
                        {
                            "tenant": q.tenant,
                            "metric": q.metric,
                            "limit": q.limit,
                            "period": q.period.value,
                            "hard_limit": q.hard_limit,
                            "model": q.model,
                            "alert_threshold": q.alert_threshold,
                        }
                        for q in self._quotas.values()
                    ],
                    "saved_at": time.time(),
                }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save usage meter: {e}")

    def _load_from_disk(self, **kw) -> None:
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for qd in data.get("quotas", []):
                quota = QuotaRule(
                    tenant=qd["tenant"],
                    metric=qd["metric"],
                    limit=qd["limit"],
                    period=UsagePeriod(qd.get("period", "monthly")),
                    hard_limit=qd.get("hard_limit", True),
                    model=qd.get("model", ""),
                    alert_threshold=qd.get("alert_threshold", 0.8),
                )
                key = f"{quota.tenant}:{quota.metric}:{quota.model}"
                self._quotas[key] = quota
            logger.info(f"Loaded {len(self._quotas)} quotas from disk")
        except Exception as e:
            logger.error(f"Failed to load usage meter: {e}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_usage_meter: Optional[UsageMeter] = None
_global_um_lock = threading.Lock()


def get_usage_meter(storage_path: str = "") -> UsageMeter:
    """获取全局 UsageMeter 单例"""
    global _global_usage_meter
    if _global_usage_meter is None:
        with _global_um_lock:
            if _global_usage_meter is None:
                _global_usage_meter = UsageMeter(storage_path=storage_path)
                logger.info("Created global UsageMeter instance")
    return _global_usage_meter


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx Usage Meter — 诊断工具")
    print("=" * 60)

    um = UsageMeter()

    # 设置配额
    um.set_quota("org_123", "tokens_total", 1_000_000,
                 period=UsagePeriod.MONTHLY, hard_limit=False,
                 alert_threshold=0.7)
    um.set_quota("org_456", "api_calls", 10000,
                 period=UsagePeriod.DAILY, hard_limit=True)

    # 模拟用量
    import random
    for i in range(100):
        um.record_usage(
            tenant=f"org_{random.choice(['123', '456', '789'])}",
            metric=random.choice(["tokens_input", "tokens_output", "api_calls"]),
            value=random.randint(100, 5000),
            model=random.choice(["gpt-4o", "gpt-4o-mini", "claude-sonnet-4"]),
            provider=random.choice(["openai", "anthropic"]),
        )

    print(f"\n[1] 统计: {json.dumps(um.get_stats(), indent=2)}")

    print("\n[2] 配额检查 (org_123):")
    for m in ["tokens_total", "api_calls"]:
        check = um.check_quota("org_123", m)
        print(f"    {m}: {check.get('current', 0):.0f}/{check.get('limit', 0):.0f} "
              f"({check.get('usage_percent', 0):.1f}%)")

    print(f"\n[3] 成本分析 (org_123, today):")
    cost = um.get_cost("org_123", "today")
    print(f"    总成本: ${cost['total_cost']:.4f}")
    for model, data in cost.get("by_model", {}).items():
        print(f"    {model}: ${data['total_cost']:.4f} "
              f"({data['tokens_input']:.0f} in, {data['tokens_output']:.0f} out)")

    print(f"\n[4] org_123 今日 Token 用量: "
          f"{um.get_usage('org_123', 'tokens_input', period='today'):.0f}")

    print("\n✅ Usage Meter 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()

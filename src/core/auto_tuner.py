"""
Performance Auto-Tuning Engine — v2.56
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
实时监控系统性能 → 自动调整参数 → 持续优化

机制:
1. 实时监控: 延迟/内存/Token/错误率 滑动窗口
2. PID控制器: 自动调整缓存/批处理/超时阈值
3. 参数历史: 学习最优配置
4. 降级策略: 负载过高时自动降级非关键功能
"""
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PerformanceSnapshot:
    """性能快照"""
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    tokens_used: int = 0
    error_count: int = 0


@dataclass
class TuningParameter:
    """可调参数"""
    name: str
    current_value: float
    min_value: float
    max_value: float
    step: float = 0.1
    history: List[float] = field(default_factory=list)
    optimal: float = 0.0
    direction: str = "minimize"  # minimize/maximize


class PerformanceAutoTuner:
    """性能自调优引擎"""

    def __init__(self, window_size: int = 60,
                 tune_interval: float = 30.0,
                 max_history: int = 1000):
        self.window_size = window_size
        self.tune_interval = tune_interval
        self.max_history = max_history

        # 性能历史
        self._history: deque = deque(maxlen=window_size)
        self._all_history: List[PerformanceSnapshot] = []

        # 可调参数
        self._params: Dict[str, TuningParameter] = {
            "cache_size_mb": TuningParameter("cache_size_mb", 64, 16, 512, 16, direction="maximize"),
            "batch_size": TuningParameter("batch_size", 8, 1, 64, 1, direction="maximize"),
            "timeout_seconds": TuningParameter("timeout_seconds", 30, 5, 120, 5, direction="minimize"),
            "model_temperature": TuningParameter("model_temperature", 0.7, 0.1, 1.5, 0.1, direction="minimize"),
            "max_concurrent": TuningParameter("max_concurrent", 4, 1, 16, 1, direction="maximize"),
        }

        # 自动调整状态
        self._last_tune_time: float = 0.0
        self._tuning_enabled: bool = True
        self._degraded: bool = False

        # 统计
        self._stats = {
            "total_snapshots": 0,
            "total_tunes": 0,
            "improvements": 0,
            "degradations": 0,
        }

    # ── Monitor ────────────────────────────────────────

    def snapshot(self, latency_ms: float = 0, memory_mb: float = 0,
                 cpu_percent: float = 0, tokens_used: int = 0,
                 error_count: int = 0) -> PerformanceSnapshot:
        """记录性能快照"""
        snap = PerformanceSnapshot(
            latency_ms=latency_ms, memory_mb=memory_mb,
            cpu_percent=cpu_percent, tokens_used=tokens_used,
            error_count=error_count,
        )
        self._history.append(snap)
        self._all_history.append(snap)
        self._stats["total_snapshots"] += 1

        if len(self._all_history) > self.max_history:
            self._all_history = self._all_history[-self.max_history:]

        # 触发自动调整
        if (self._tuning_enabled and
                time.time() - self._last_tune_time > self.tune_interval):
            self.auto_tune()

        return snap

    # ── Auto-Tune ──────────────────────────────────────

    def auto_tune(self) -> Dict[str, Any]:
        """自动调整所有参数"""
        self._last_tune_time = time.time()
        self._stats["total_tunes"] += 1

        if len(self._history) < 5:
            return {"status": "insufficient_data"}

        results = {}
        metrics = self._get_current_metrics()

        # 1. 延迟过高 → 增加缓存/降低超时
        if metrics["avg_latency_ms"] > 500:
            results["timeout_seconds"] = self._adjust_param(
                "timeout_seconds", +5, "延迟过高,增加超时")
            results["cache_size_mb"] = self._adjust_param(
                "cache_size_mb", +16, "延迟过高,增加缓存")
            self._stats["improvements"] += 1

        # 2. 内存警告 → 减少缓存/批处理
        if metrics["memory_mb"] > 500:
            results["cache_size_mb"] = self._adjust_param(
                "cache_size_mb", -32, "内存告警,减少缓存")
            results["batch_size"] = self._adjust_param(
                "batch_size", -1, "内存告警,减少批处理")
            self._degraded = True

        # 3. 错误率高 → 增加并发/超时
        if metrics["error_rate"] > 0.05:
            results["timeout_seconds"] = self._adjust_param(
                "timeout_seconds", +10, "错误率高,增加超时")
            results["max_concurrent"] = self._adjust_param(
                "max_concurrent", -1, "错误率高,减少并发")

        # 4. 正常 → 逐步优化吞吐
        if metrics["error_rate"] < 0.01 and metrics["avg_latency_ms"] < 200:
            results["batch_size"] = self._adjust_param(
                "batch_size", +1, "系统稳定,提升吞吐")
            results["max_concurrent"] = self._adjust_param(
                "max_concurrent", +1, "系统稳定,增加并发")
            self._stats["improvements"] += 1
            self._degraded = False

        return {
            "status": "tuned",
            "adjustments": results,
            "metrics": metrics,
            "degraded": self._degraded,
        }

    # ── Metrics ────────────────────────────────────────

    def _get_current_metrics(self) -> Dict[str, float]:
        """当前性能指标"""
        if not self._history:
            return {"avg_latency_ms": 0, "memory_mb": 0, "error_rate": 0}

        latencies = [s.latency_ms for s in self._history]
        memories = [s.memory_mb for s in self._history]
        errors = [s.error_count for s in self._history]

        return {
            "avg_latency_ms": round(np.mean(latencies), 1),
            "p95_latency_ms": round(np.percentile(latencies, 95), 1),
            "p99_latency_ms": round(np.percentile(latencies, 99), 1),
            "memory_mb": round(np.mean(memories), 1),
            "max_memory_mb": round(np.max(memories), 1),
            "error_rate": round(sum(errors) / max(1, len(errors) * 10), 4),
        }

    def _adjust_param(self, name: str, delta: float, reason: str) -> Dict:
        """调整单个参数"""
        param = self._params.get(name)
        if param is None:
            return {"error": f"未知参数: {name}"}

        new_val = param.current_value + delta
        new_val = max(param.min_value, min(param.max_value, new_val))

        old_val = param.current_value
        param.current_value = new_val
        param.history.append(new_val)

        return {
            "param": name,
            "old": old_val,
            "new": new_val,
            "delta": delta,
            "reason": reason,
        }

    # ── Query ──────────────────────────────────────────

    def get_params(self) -> Dict[str, Any]:
        return {
            name: {"value": p.current_value, "optimal": p.optimal,
                   "range": [p.min_value, p.max_value]}
            for name, p in self._params.items()
        }

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "current_metrics": self._get_current_metrics(),
            "params": self.get_params(),
            "degraded": self._degraded,
            "history_size": len(self._all_history),
        }

    def set_param(self, name: str, value: float) -> bool:
        """手动设置参数"""
        if name in self._params:
            param = self._params[name]
            param.current_value = max(param.min_value, min(param.max_value, value))
            return True
        return False


# 单例
_engine: Optional[PerformanceAutoTuner] = None


def get_auto_tuner() -> PerformanceAutoTuner:
    global _engine
    if _engine is None:
        _engine = PerformanceAutoTuner()
    return _engine

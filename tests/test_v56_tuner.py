"""v2.56 Performance Auto-Tuner — 测试套件"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.auto_tuner import PerformanceAutoTuner, get_auto_tuner


@pytest.fixture
def tuner():
    return PerformanceAutoTuner(window_size=20, tune_interval=1.0)


class TestMonitor:
    def test_snapshot(self, tuner):
        snap = tuner.snapshot(latency_ms=50, memory_mb=100)
        assert snap.latency_ms == 50
        assert tuner._stats["total_snapshots"] == 1

    def test_snapshot_multiple(self, tuner):
        for i in range(10):
            tuner.snapshot(latency_ms=10 * i)
        assert len(tuner._history) == 10

    def test_window_limit(self, tuner):
        for i in range(30):  # window=20
            tuner.snapshot(latency_ms=i)
        assert len(tuner._history) <= 20


class TestAutoTune:
    def test_auto_tune_insufficient_data(self, tuner):
        result = tuner.auto_tune()
        assert result["status"] == "insufficient_data"

    def test_auto_tune_high_latency(self, tuner):
        for _ in range(10):
            tuner.snapshot(latency_ms=600, memory_mb=200)
        result = tuner.auto_tune()
        assert result["status"] == "tuned"
        # 高延迟应调整
        assert any("timeout" in str(k).lower() for k in result.get("adjustments", {}))

    def test_auto_tune_high_error(self, tuner):
        for _ in range(10):
            tuner.snapshot(latency_ms=100, memory_mb=100, error_count=3)
        result = tuner.auto_tune()
        assert result["status"] == "tuned"

    def test_auto_tune_stable(self, tuner):
        for _ in range(10):
            tuner.snapshot(latency_ms=50, memory_mb=80)
        result = tuner.auto_tune()
        assert result["status"] == "tuned"


class TestParams:
    def test_get_params(self, tuner):
        params = tuner.get_params()
        assert "cache_size_mb" in params
        assert "batch_size" in params

    def test_set_param(self, tuner):
        assert tuner.set_param("batch_size", 16)
        assert tuner._params["batch_size"].current_value == 16

    def test_set_param_clamped(self, tuner):
        """参数被限制在范围内"""
        tuner.set_param("batch_size", 9999)
        assert tuner._params["batch_size"].current_value <= 64

    def test_set_unknown_param(self, tuner):
        assert not tuner.set_param("nonexistent", 10)


class TestMetrics:
    def test_metrics(self, tuner):
        for i in range(5):
            tuner.snapshot(latency_ms=100 + i * 10, memory_mb=200)
        metrics = tuner._get_current_metrics()
        assert metrics["avg_latency_ms"] > 0
        assert metrics["memory_mb"] > 0

    def test_metrics_empty(self, tuner):
        metrics = tuner._get_current_metrics()
        assert metrics["avg_latency_ms"] == 0


class TestStats:
    def test_stats(self, tuner):
        tuner.snapshot(latency_ms=50)
        stats = tuner.get_stats()
        assert stats["total_snapshots"] == 1
        assert "current_metrics" in stats
        assert "params" in stats


class TestSingleton:
    def test_singleton(self):
        from src.core import auto_tuner
        auto_tuner._engine = None
        t1 = get_auto_tuner()
        t2 = get_auto_tuner()
        assert t1 is t2

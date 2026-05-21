"""v2.59 Health Monitor — 测试"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.health_monitor import RealtimeHealthMonitor, get_health_monitor


@pytest.fixture
def monitor():
    return RealtimeHealthMonitor(check_interval=999, history_size=20)


class TestHealthChecks:
    @pytest.mark.asyncio
    async def test_check_single_module(self, monitor):
        check = await monitor.check_module("sdb")
        assert check.module == "sdb"
        assert check.status in ("ok", "error")
        assert check.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_all(self, monitor):
        result = await monitor.check_all()
        assert "modules" in result
        assert result["total"] >= 10
        assert "ok" in result

    @pytest.mark.asyncio
    async def test_check_unknown_module(self, monitor):
        check = await monitor.check_module("nonexistent")
        assert check.status == "ok"

    @pytest.mark.asyncio
    async def test_stats_tracked(self, monitor):
        await monitor.check_module("sdb")
        assert monitor._stats["total_checks"] >= 1

    @pytest.mark.asyncio
    async def test_consecutive_error_tracking(self, monitor):
        # 模拟错误
        monitor._stats["consecutive_errors"] = 3
        await monitor.check_module("sdb")  # 成功应重置
        assert monitor._stats["consecutive_errors"] == 0

    @pytest.mark.asyncio
    async def test_summary(self, monitor):
        await monitor.check_module("sdb")
        summary = monitor.get_summary()
        assert summary["healthy"] is True
        assert summary["checks_total"] >= 1


class TestWebSocket:
    @pytest.mark.asyncio
    async def test_subscribe(self, monitor):
        q = monitor.subscribe()
        assert q is not None


class TestSingleton:
    def test_singleton(self):
        from src.core import health_monitor
        health_monitor._monitor = None
        h1 = get_health_monitor()
        h2 = get_health_monitor()
        assert h1 is h2

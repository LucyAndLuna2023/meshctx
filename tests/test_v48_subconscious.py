"""
v3.48 Subconscious Observer — 测试
覆盖: 5通道观察 / 去重 / 优先级排序 / 过期清理 / 注入格式
"""
import pytest
import time
import json
from pathlib import Path
from src.core.subconscious import (
    SubconsciousObserver, Nudge, NudgePriority, NudgeSource,
    get_observer,
)


class TestNudge:
    """Nudge数据模型"""

    def test_nudge_creation(self):
        n = Nudge(title="test", detail="detail", action="do it")
        assert n.title == "test"
        assert n.priority == NudgePriority.MEDIUM
        assert not n.is_expired()

    def test_nudge_to_context(self):
        n = Nudge(
            priority=NudgePriority.CRITICAL,
            source=NudgeSource.SYSTEMIC,
            title="CRASH",
            detail="Server down",
            action="Restart now",
        )
        ctx = n.to_context()
        assert "🚨" in ctx
        assert "CRASH" in ctx
        assert "Server down" in ctx

    def test_nudge_expiry(self):
        n = Nudge(title="old", detail="gone", action="none",
                   expires_at=time.time() - 1)
        assert n.is_expired()

    def test_nudge_not_expired(self):
        n = Nudge(title="new", detail="here", action="ok",
                   expires_at=time.time() + 3600)
        assert not n.is_expired()

    def test_nudge_no_expiry(self):
        n = Nudge(title="forever", detail="stay", action="keep")
        assert not n.is_expired()


class TestSubconscious:
    """观察引擎核心"""

    def test_init(self):
        obs = SubconsciousObserver({"scan_interval": 60, "max_nudges": 3})
        assert obs._scan_interval == 60
        assert obs._max_nudges == 3
        assert obs._last_scan == 0

    def test_init_defaults(self):
        obs = SubconsciousObserver()
        assert obs._scan_interval == 300
        assert obs._max_nudges == 5
        assert obs._enabled_channels["internal"] is True
        assert obs._enabled_channels["external"] is True

    def test_inject_empty(self):
        obs = SubconsciousObserver()
        result = obs.inject([])
        assert result == ""

    def test_inject_formats_nudges(self):
        obs = SubconsciousObserver()
        n1 = Nudge(priority=NudgePriority.HIGH, title="Important",
                    detail="Something urgent", action="Fix it")
        n2 = Nudge(priority=NudgePriority.INSIGHT, title="Pattern",
                    detail="Something interesting", action="Note it")
        result = obs.inject([n1, n2])
        assert "Subconscious Observer" in result
        assert "Important" in result
        assert "Pattern" in result

    def test_analyze_dedup(self):
        obs = SubconsciousObserver()
        obs._nudges = [Nudge(title="Already seen")]
        # 同title的nudge应该被去重
        new = [Nudge(title="Already seen"), Nudge(title="New one")]
        result = obs.analyze(new)
        assert len(result) == 1
        assert result[0].title == "New one"

    def test_analyze_priority_sort(self):
        obs = SubconsciousObserver()
        nudges = [
            Nudge(priority=NudgePriority.LOW, title="low"),
            Nudge(priority=NudgePriority.CRITICAL, title="critical"),
            Nudge(priority=NudgePriority.MEDIUM, title="medium"),
        ]
        result = obs.analyze(nudges)
        assert result[0].priority == NudgePriority.CRITICAL
        assert result[-1].priority == NudgePriority.LOW

    def test_analyze_expiry_cleanup(self):
        obs = SubconsciousObserver()
        obs._nudges = [
            Nudge(title="expired", expires_at=time.time() - 3600),
            Nudge(title="active", expires_at=time.time() + 3600),
        ]
        result = obs.analyze([])
        # expired应该被清理，只保留active
        active_titles = [n.title for n in obs._nudges]
        assert "active" in active_titles
        assert "expired" not in active_titles

    def test_analyze_max_nudges(self):
        obs = SubconsciousObserver({"max_nudges": 2})
        nudges = [
            Nudge(title=f"nudge-{i}") for i in range(10)
        ]
        result = obs.analyze(nudges)
        assert len(result) <= 2

    def test_observe_internal_returns_list(self):
        obs = SubconsciousObserver()
        result = obs.observe_internal()
        assert isinstance(result, list)

    def test_observe_external_returns_list(self):
        obs = SubconsciousObserver()
        result = obs.observe_external()
        assert isinstance(result, list)

    def test_observe_systemic_returns_list(self):
        obs = SubconsciousObserver()
        result = obs.observe_systemic()
        assert isinstance(result, list)

    def test_observe_memory_returns_list(self):
        obs = SubconsciousObserver()
        result = obs.observe_memory()
        assert isinstance(result, list)

    def test_observe_predictive_returns_list(self):
        obs = SubconsciousObserver()
        result = obs.observe_predictive()
        assert isinstance(result, list)

    def test_get_stats(self):
        obs = SubconsciousObserver()
        obs._nudge_history.extend([
            Nudge(source=NudgeSource.INTERNAL, priority=NudgePriority.HIGH, title="a"),
            Nudge(source=NudgeSource.SYSTEMIC, priority=NudgePriority.MEDIUM, title="b"),
        ])
        stats = obs.get_stats()
        assert stats["total_nudges_generated"] == 2
        assert "history_by_source" in stats
        assert "history_by_priority" in stats
        assert stats["history_by_source"]["internal"] == 1
        assert stats["history_by_source"]["systemic"] == 1

    def test_enabled_channels_config(self):
        obs = SubconsciousObserver({
            "internal": False,
            "external": False,
            "systemic": True,
        })
        assert obs._enabled_channels["internal"] is False
        assert obs._enabled_channels["external"] is False
        assert obs._enabled_channels["systemic"] is True

    @pytest.mark.asyncio
    async def test_cycle_runs_all_channels(self):
        obs = SubconsciousObserver({"scan_interval": 1})
        nudges = await obs.cycle()
        assert isinstance(nudges, list)
        assert obs._last_scan > 0

    def test_singleton(self):
        o1 = get_observer()
        o2 = get_observer()
        assert o1 is o2

"""v3.68 Auto-Healer v2 — tests"""
import pytest
from src.core.auto_healer import AutoHealerV2, get_auto_healer

class TestHealer:
    def test_check_all(self):
        h = AutoHealerV2()
        checks = h.check_all()
        assert len(checks) >= 3
        for c in checks:
            assert c.status in ("ok","warn","critical","unknown")

    def test_heal(self):
        h = AutoHealerV2()
        actions = h.heal([h._check_cache()])
        assert isinstance(actions, list)

    def test_stats(self):
        h = AutoHealerV2()
        h.check_all()
        s = h.get_stats()
        assert s["checks"] >= 3

    def test_singleton(self):
        assert get_auto_healer() is get_auto_healer()

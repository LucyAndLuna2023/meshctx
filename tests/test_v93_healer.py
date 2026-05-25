"""v2.93 Self-Healing 2.0 — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def healer():
    from src.core.self_healing2 import SelfHealingEngine
    return SelfHealingEngine()


class TestHealthChecks:
    def test_check_all(self, healer):
        checks = healer.check_all()
        assert len(checks) >= 5
        for c in checks:
            assert c.module in ("system","tests","memory","security","backup","plugins")
            assert c.level is not None
            assert c.score is not None

    def test_system_check(self, healer):
        check = healer._check_system_resources()
        assert check.module == "system"

    def test_backup_check_warns(self, healer):
        check = healer._check_backup_status()
        assert check.module == "backup"

    def test_security_check(self, healer):
        check = healer._check_security_status()
        assert check.module == "security"


class TestAutoFix:
    def test_auto_fix_no_fix_needed(self, healer):
        from src.core.self_healing2 import HealthCheck, HealthLevel
        check = HealthCheck(module="tests", level=HealthLevel.OPTIMAL)
        result = healer.auto_fix(check)
        assert result["fixed"] is False

    def test_auto_fix_backup(self, healer):
        from src.core.self_healing2 import HealthCheck, HealthLevel
        check = HealthCheck(
            module="backup", level=HealthLevel.AT_RISK, score=0,
            auto_fix_available=True,
        )
        result = healer.auto_fix(check)
        assert "fixed" in result


class TestHealCycle:
    def test_heal_cycle(self, healer):
        result = healer.heal_cycle()
        assert "checked" in result
        assert result["checked"] >= 5
        assert "critical_remaining" in result

    def test_heal_cycle_produces_stats(self, healer):
        healer.heal_cycle()
        stats = healer.get_stats()
        assert stats["total_checks"] >= 5

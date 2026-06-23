"""v3.60 Alert Engine — tests"""
import pytest
from src.core.alert_engine import AlertEngine, AlertLevel, get_alert_engine

class TestAlert:
    def test_alert(self):
        e = AlertEngine()
        a = e.alert(AlertLevel.HIGH, "Test", "message")
        assert a is not None; assert a.level == AlertLevel.HIGH

    def test_suppression(self):
        e = AlertEngine()
        e.alert(AlertLevel.MEDIUM, "Dup", "msg1")
        a2 = e.alert(AlertLevel.MEDIUM, "Dup", "msg2")
        assert a2 is None  # Suppressed

    def test_acknowledge(self):
        e = AlertEngine()
        a = e.alert(AlertLevel.LOW, "Test", "msg")
        assert e.acknowledge(a.id)
        assert a.acknowledged

    def test_escalate(self):
        e = AlertEngine()
        a = e.alert(AlertLevel.MEDIUM, "Test", "msg")
        assert e.escalate(a.id)
        assert a.level == AlertLevel.HIGH

    def test_stats(self):
        e = AlertEngine()
        e.alert(AlertLevel.CRITICAL, "C", "c"); e.alert(AlertLevel.LOW, "L", "l")
        s = e.get_stats()
        assert s["total"] == 2

    def test_singleton(self):
        assert get_alert_engine() is get_alert_engine()

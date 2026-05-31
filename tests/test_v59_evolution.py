"""v3.59 Evolution Tracker — tests"""
import pytest
from src.core.evolution_tracker import EvolutionTracker, get_evolution_tracker

class TestEvolution:
    def test_snapshot(self):
        t = EvolutionTracker()
        s = t.snapshot("v1.0")
        assert s.version == "v1.0"; assert s.modules > 0

    def test_trend(self):
        t = EvolutionTracker()
        t.snapshot("v1.0"); t.snapshot("v2.0")
        trend = t.trend()
        assert "modules" in trend

    def test_latest(self):
        t = EvolutionTracker()
        t.snapshot("v1.0")
        assert t.latest().version == "v1.0"

    def test_singleton(self):
        assert get_evolution_tracker() is get_evolution_tracker()

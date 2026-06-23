"""v3.59 Evolution Tracker tests"""
import pytest, json
from pathlib import Path
from src.core.evolution_tracker import EvolutionSnapshot, EvolutionTracker


class TestEvolutionSnapshot:
    def test_snapshot_creation(self):
        snap = EvolutionSnapshot(version="3.40.0", modules=150, tests=1600)
        assert snap.version == "3.40.0"
        assert snap.modules == 150

    def test_default_values(self):
        snap = EvolutionSnapshot(version="1.0")
        assert snap.version == "1.0"
        assert snap.modules == 0


class TestEvolutionTracker:
    def test_snapshot_records(self):
        tracker = EvolutionTracker()
        tracker.snapshot("3.39.0")
        tracker.snapshot("3.40.0")
        latest = tracker.latest()
        assert latest is not None
        assert latest.version == "3.40.0"

    def test_trend(self):
        tracker = EvolutionTracker()
        # Add multiple snapshots for trend
        for v in ["3.0", "3.1", "3.2"]:
            tracker.snapshot(v)
        trend = tracker.trend()
        assert isinstance(trend, dict)

    def test_latest_none(self):
        tracker = EvolutionTracker()
        tracker._snapshots = []
        assert tracker.latest() is None


def test_singleton():
    from src.core.evolution_tracker import get_evolution_tracker
    t1 = get_evolution_tracker()
    t2 = get_evolution_tracker()
    assert t1 is t2

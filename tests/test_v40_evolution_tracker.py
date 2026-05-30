"""v3.40 Evolution Tracker tests"""
import pytest


class TestVersionSnapshot:
    def test_snapshot_creation(self):
        from src.core.evolution_tracker import VersionSnapshot
        snap = VersionSnapshot(version="3.40.0", modules_count=150, tests_count=1600, papers_landed=7)
        assert snap.version == "3.40.0"
        assert snap.modules_count == 150
    
    def test_default_scores(self):
        from src.core.evolution_tracker import VersionSnapshot
        snap = VersionSnapshot(version="1.0")
        assert snap.memory_score >= 0


class TestEvolutionTracker:
    def test_snapshot_records(self):
        from src.core.evolution_tracker import get_evolution_tracker
        tracker = get_evolution_tracker()
        before = len(tracker.history)
        tracker.snapshot("3.39.0", 150, 1590, 7)
        tracker.snapshot("3.40.0", 152, 1610, 7)
        assert len(tracker.history) == before + 2
    
    def test_get_trend(self):
        from src.core.evolution_tracker import get_evolution_tracker
        tracker = get_evolution_tracker()
        trend = tracker.get_trend("autonomy")
        assert "latest_score" in trend
        assert "growth_rate_pct" in trend
    
    def test_overall_health(self):
        from src.core.evolution_tracker import get_evolution_tracker
        tracker = get_evolution_tracker()
        health = tracker.get_overall_health()
        assert "version" in health
        assert "avg_capability_score" in health
        assert "evolution_rating" in health
    
    def test_compare_versions(self):
        from src.core.evolution_tracker import get_evolution_tracker
        tracker = get_evolution_tracker()
        tracker.snapshot("3.0.0", 100, 1000, 1)
        tracker.snapshot("3.40.0", 152, 1610, 7)
        comp = tracker.compare_versions("3.0.0", "3.40.0")
        if "error" not in comp:
            assert comp["modules_gained"] > 0
    
    def test_predict(self):
        from src.core.evolution_tracker import get_evolution_tracker
        tracker = get_evolution_tracker()
        pred = tracker.predict_next_version()
        if "error" not in pred:
            assert "predicted_version" in pred
            assert "predicted_scores" in pred
    
    def test_evolution_rating(self):
        from src.core.evolution_tracker import get_evolution_tracker, EvolutionTracker
        # Fresh tracker
        t = EvolutionTracker()
        t.history = []
        t.snapshot("1.0", 30, 100, 0)
        t.snapshot("2.0", 60, 500, 3)
        t.snapshot("3.0", 150, 1600, 7)
        rating = t._evolution_rating()
        assert rating in ["🚀 Hyper-Evolving", "📈 Rapidly Growing", "🌿 Steadily Improving", "🌱 Seedling"]
    
    def test_persistence(self):
        from src.core.evolution_tracker import EvolutionTracker, DATA_DIR
        t1 = EvolutionTracker()
        t1.history = []
        t1.snapshot("test-1.0", 50, 500, 2)
        # Reload
        t2 = EvolutionTracker()
        assert len(t2.history) >= 1

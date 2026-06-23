"""
跨会话身份连续性测试
"""
import pytest
import tempfile
import shutil
from pathlib import Path


class TestSessionIdentity:
    """会话身份持久化"""

    @pytest.fixture
    def tmp_dir(self):
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d, ignore_errors=True)

    def _new_si(self, tmp_dir):
        from src.core.session_identity import SessionIdentity
        return SessionIdentity(storage_dir=str(tmp_dir))

    def test_save_and_load_identity(self, tmp_dir):
        si = self._new_si(tmp_dir)
        si.set_strategy_belief("code_generation", {"exploit_best": 0.7, "balanced": 0.3})
        si.set_habit("deploy", "balanced", count=8)
        si.save()

        si2 = self._new_si(tmp_dir)
        assert si2.get_strategy_belief("code_generation") == {"exploit_best": 0.7, "balanced": 0.3}
        assert si2.get_habit("deploy")["strategy"] == "balanced"

    def test_multiple_strategies(self, tmp_dir):
        si = self._new_si(tmp_dir)
        si.set_strategy_belief("analyze", {"explore_random": 0.6, "balanced": 0.4})
        si.set_strategy_belief("deploy", {"balanced": 0.9, "safe_path": 0.1})
        si.set_habit("analyze", "explore_random", count=12)
        si.save()

        si2 = self._new_si(tmp_dir)
        assert si2.get_strategy_belief("analyze") == {"explore_random": 0.6, "balanced": 0.4}
        assert si2.is_habit_formed("analyze")

    def test_preferences_persist(self, tmp_dir):
        si = self._new_si(tmp_dir)
        si.set_preference("default_model", "deepseek:v4-pro")
        si.set_preference("theme", "dark")
        si.save()

        si2 = self._new_si(tmp_dir)
        assert si2.get_preference("default_model") == "deepseek:v4-pro"

    def test_touch_updates_timestamp(self, tmp_dir):
        import time
        si = self._new_si(tmp_dir)
        old_ts = si.last_active
        time.sleep(0.1)
        si.touch()
        assert si.last_active > old_ts

    def test_merge_with_learn_loop(self, tmp_dir):
        si = self._new_si(tmp_dir)
        si.set_strategy_belief("task1", {"a": 0.5, "b": 0.5})
        si.set_strategy_belief("task2", {"c": 0.8, "d": 0.2})
        si.set_habit("task2", "c", count=15)

        new_beliefs = {"task1": {"a": 0.6, "b": 0.4}, "task3": {"e": 1.0}}
        new_habits = {"task2": {"strategy": "c", "count": 20}}
        si.merge_from_learn_loop(new_beliefs, new_habits)
        si.save()

        si2 = self._new_si(tmp_dir)
        assert si2.get_strategy_belief("task1") == {"a": 0.6, "b": 0.4}
        assert si2.get_strategy_belief("task3") == {"e": 1.0}

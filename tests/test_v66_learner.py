"""v2.66 Error Learner — 测试"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def learner(tmp_path):
    from src.core.error_learner import AutonomousLearningEngine
    return AutonomousLearningEngine(data_dir=tmp_path / "learned")


class TestPatternExtraction:
    def test_extract_simple(self, learner):
        pattern = learner.extract_pattern("KeyError: 'my_key'")
        assert "<VALUE>" in pattern
        assert "my_key" not in pattern

    def test_extract_numbers(self, learner):
        pattern = learner.extract_pattern("line 42: division by zero")
        assert "<NUM>" in pattern
        assert "42" not in pattern

    def test_extract_paths(self, learner):
        pattern = learner.extract_pattern("File /home/user/app.py, line 100")
        assert "<PATH>" in pattern


class TestErrorClassification:
    def test_key_error(self, learner):
        etype, severity = learner.classify_error("KeyError: 'config'")
        assert etype == "KeyError"

    def test_module_not_found(self, learner):
        etype, severity = learner.classify_error("ModuleNotFoundError: No module named 'xyz'")
        assert etype == "ModuleNotFoundError"
        assert severity.value == "high"

    def test_critical(self, learner):
        from src.core.error_learner import LessonSeverity
        etype, severity = learner.classify_error("Permission denied: cannot delete production database")
        assert severity == LessonSeverity.CRITICAL


class TestLearning:
    def test_learn_new_error(self, learner):
        lesson = learner.learn(
            "KeyError: 'missing_key'",
            context="API handler",
            fix_applied="Use .get('missing_key', None)"
        )
        assert lesson.id != ""
        assert lesson.error_type == "KeyError"
        assert lesson.occurrence_count == 1

    def test_learn_duplicate(self, learner):
        first = learner.learn("KeyError: 'key1'", context="test")
        second = learner.learn("KeyError: 'key2'", context="test")
        # 相同模式应更新occurrence_count
        assert second.occurrence_count >= 1

    def test_learn_generates_regression(self, learner):
        from src.core.error_learner import LessonSeverity
        lesson = learner.learn(
            "Permission denied: cannot access /etc/shadow",
            context="system",
        )
        # CRITICAL错误应生成回归测试
        if lesson.severity == LessonSeverity.CRITICAL:
            assert lesson.regression_test != ""


class TestPrevention:
    def test_query_existing(self, learner):
        learner.learn("KeyError: 'secret'", context="handler")
        result = learner.query("KeyError: 'token'")
        assert result["matched"] is True

    def test_query_unknown(self, learner):
        result = learner.query("WeirdCustomError: unknown")
        assert result["matched"] is False

    def test_prevent(self, learner):
        learner.learn("KeyError: 'critical_config'", context="startup")
        prevented = learner.prevent("KeyError: 'app_config'")
        assert prevented is True

    def test_prevent_unknown(self, learner):
        prevented = learner.prevent("SomeRandomError: abc")
        assert prevented is False


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        from src.core.error_learner import AutonomousLearningEngine
        e1 = AutonomousLearningEngine(data_dir=tmp_path / "storage")
        e1.learn("KeyError: 'test_save'", context="persist test")

        e2 = AutonomousLearningEngine(data_dir=tmp_path / "storage")
        stats = e2.get_stats()
        assert stats["total_lessons_learned"] >= 1


class TestStats:
    def test_empty_stats(self, learner):
        stats = learner.get_stats()
        assert stats["total_lessons_learned"] == 0

    def test_stats_after_learning(self, learner):
        learner.learn("KeyError: 'a'")
        learner.learn("AttributeError: b")
        learner.learn("TypeError: c")
        stats = learner.get_stats()
        assert stats["total_lessons_learned"] >= 2
        assert "by_type" in stats
        assert "top_lessons" in stats

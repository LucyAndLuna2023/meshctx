"""v2.69 Version Guard — 测试"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def guard(tmp_path):
    from src.core.version_guard import VersionGuard
    # Copy project structure for testing
    core = tmp_path / "src" / "core"
    core.mkdir(parents=True)
    core_init = core / "__init__.py"
    core_init.write_text('__version__ = "2.69.0"\n')
    return VersionGuard(project_root=tmp_path, auto_backup=False)


class TestVersionDetection:
    def test_detect_version(self, guard):
        assert guard.detect_version() == "2.69.0"

    def test_is_new_version_first_time(self, guard):
        assert guard.is_new_version() is True

    def test_not_new_if_same(self, guard):
        guard._last_version = "2.69.0"
        assert guard.is_new_version() is False


class TestChangeDetection:
    def test_detect_changes(self, guard):
        changes = guard.detect_changes()
        assert changes["current_version"] == "2.69.0"
        assert changes["is_new_version"] is True

    def test_detect_changes_no_change(self, guard):
        guard._last_version = "2.69.0"
        changes = guard.detect_changes()
        assert changes["is_new_version"] is False


class TestVersionChange:
    def test_on_version_change_triggers(self, guard):
        result = guard.on_version_change()
        assert result["triggered"] is True
        assert result["to_version"] == "2.69.0"
        assert "版本历史已记录" in str(result["actions"])

    def test_no_trigger_if_same(self, guard):
        guard._last_version = "2.69.0"
        result = guard.on_version_change()
        assert result["triggered"] is False

    def test_history_recorded(self, guard):
        guard.on_version_change()
        history = guard.get_history()
        assert len(history) >= 1
        assert history[-1]["version"] == "2.69.0"


class TestHistory:
    def test_get_stats(self, guard):
        guard.on_version_change()
        stats = guard.get_stats()
        assert stats["current_version"] == "2.69.0"
        assert stats["total_versions_recorded"] >= 1


class TestPersistence:
    def test_history_persists(self, tmp_path):
        from src.core.version_guard import VersionGuard
        core = tmp_path / "src" / "core"
        core.mkdir(parents=True)
        (core / "__init__.py").write_text('__version__ = "2.69.0"\n')

        g1 = VersionGuard(project_root=tmp_path, auto_backup=False)
        g1.on_version_change()

        g2 = VersionGuard(project_root=tmp_path, auto_backup=False)
        assert g2._last_version == "2.69.0"
        assert len(g2.get_history()) >= 1

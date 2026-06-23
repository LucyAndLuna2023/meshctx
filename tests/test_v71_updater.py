"""v2.71 Self-Updater — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def updater(tmp_path):
    from src.core.self_updater import SelfUpdater
    # 不连远程，只测试本地逻辑
    return SelfUpdater(
        project_root=Path(__file__).parent.parent,
        auto_update=False
    )


class TestVersionDetection:
    def test_detect_version(self):
        from src.core.self_updater import SelfUpdater
        ver = SelfUpdater._detect_version(Path(__file__).parent.parent)
        assert ver != "0.0.0"
        assert "." in ver

    def test_detect_version_nonexistent(self, tmp_path):
        from src.core.self_updater import SelfUpdater
        ver = SelfUpdater._detect_version(tmp_path)
        assert ver == "0.0.0"


class TestCheck:
    def test_check_for_updates(self, updater):
        result = updater.check_for_updates()
        assert "update_available" in result
        assert "local_commit" in result


class TestStateless:
    """测试不需要网络的逻辑"""
    def test_init(self, updater):
        assert updater.auto_update is False
        assert updater.remote_host == "47.120.0.239"

    def test_get_stats_empty(self, updater):
        stats = updater.get_stats()
        assert "current_version" in stats
        assert "auto_update" in stats
        assert stats["total_updates"] == 0

    def test_pre_update_version(self, updater):
        ver = updater._detect_version(updater.project_root)
        assert ver != "0.0.0"


class TestUpdateResult:
    def test_create_result(self):
        from src.core.self_updater import UpdateResult, UpdateStatus
        r = UpdateResult(
            status=UpdateStatus.UP_TO_DATE,
            from_version="2.70.0",
            to_version="2.71.0",
            tests_passed=1400,
            verified=True,
        )
        assert r.status == UpdateStatus.UP_TO_DATE
        assert r.verified is True

    def test_all_statuses(self):
        from src.core.self_updater import UpdateStatus
        statuses = list(UpdateStatus)
        assert len(statuses) >= 8  # 至少8个状态


class TestSingleton:
    def test_singleton(self):
        from src.core.self_updater import get_self_updater
        u1 = get_self_updater()
        u2 = get_self_updater()
        assert u1 is u2

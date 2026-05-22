"""v2.67 Goal Decomposer — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def gd():
    from src.core.goal_decomposer import GoalDecomposer
    return GoalDecomposer()


class TestTypeDetection:
    def test_build_web(self, gd):
        assert gd._detect_type("构建一个网站") == "build_web_app"
        assert gd._detect_type("build web application") == "build_web_app"

    def test_fix_bug(self, gd):
        assert gd._detect_type("修复内存泄漏bug") == "fix_bug"
        assert gd._detect_type("fix the login bug") == "fix_bug"

    def test_add_feature(self, gd):
        assert gd._detect_type("添加搜索功能") == "add_feature"

    def test_deploy(self, gd):
        assert gd._detect_type("部署到生产环境") == "deploy"

    def test_generic(self, gd):
        assert gd._detect_type("做一些优化") == "generic"


class TestDecomposition:
    def test_decompose_build_web(self, gd):
        goal = gd.decompose("构建一个博客网站", "build_web_app")
        assert len(goal.subtasks) >= 4
        assert goal.progress == 0.0

    def test_decompose_fix_bug(self, gd):
        goal = gd.decompose("修复登录页面的bug", "fix_bug")
        assert len(goal.subtasks) >= 3
        # 第一个任务无依赖,应为READY
        first = goal.subtasks[0]
        assert first.status.value == "ready"

    def test_decompose_generic(self, gd):
        goal = gd.decompose("优化系统性能")
        assert len(goal.subtasks) == 5  # 分析→设计→实现→测试→部署

    def test_auto_detect_type(self, gd):
        goal = gd.decompose("创建一个电商网站")
        assert goal.id != ""

    def test_dependencies_set(self, gd):
        goal = gd.decompose("修复bug", "fix_bug")
        # 检查有依赖的任务
        has_deps = [st for st in goal.subtasks if st.dependencies]
        assert len(has_deps) > 0


class TestExecution:
    def test_get_ready_tasks(self, gd):
        goal = gd.decompose("修复bug", "fix_bug")
        ready = gd.get_ready_tasks(goal.id)
        assert len(ready) >= 1

    def test_start_and_complete(self, gd):
        goal = gd.decompose("修复bug", "fix_bug")
        ready = gd.get_ready_tasks(goal.id)
        task = ready[0]

        gd.start_task(goal.id, task.id)
        gd.complete_task(goal.id, task.id, "Done")

        # 刷新后应有新ready任务
        goal2 = gd._goals[goal.id]
        assert task.status.value == "completed"

    def test_fail_blocks_downstream(self, gd):
        goal = gd.decompose("修复bug", "fix_bug")
        ready = gd.get_ready_tasks(goal.id)
        task = ready[0]

        gd.fail_task(goal.id, task.id, "Network error")

        # 检查下游被阻塞
        goal2 = gd._goals[goal.id]
        blocked = [
            st for st in goal2.subtasks
            if st.status.value == "blocked"
        ]
        assert len(blocked) >= 1

    def test_progress_updates(self, gd):
        goal = gd.decompose("修复bug", "fix_bug")
        assert goal.progress == 0.0

        # 完成所有无依赖任务
        for st in goal.subtasks:
            if not st.dependencies:
                gd.start_task(goal.id, st.id)
                gd.complete_task(goal.id, st.id)

        # 刷新后检查下个就绪任务
        self._refresh_for_test(gd, goal)
        ready = gd.get_ready_tasks(goal.id)
        # 可能有新的ready任务

    @staticmethod
    def _refresh_for_test(gd, goal):
        gd._refresh_dependencies(goal)
        goal.progress = gd._calc_progress(goal)


class TestGoalStatus:
    def test_get_status(self, gd):
        goal = gd.decompose("修复bug", "fix_bug")
        status = gd.get_goal_status(goal.id)
        assert status["total_tasks"] >= 3
        assert "tasks" in status
        assert status["progress"] >= 0

    def test_unknown_goal(self, gd):
        status = gd.get_goal_status("nonexistent")
        assert status is None


class TestStats:
    def test_empty_stats(self, gd):
        stats = gd.get_stats()
        assert stats["total_goals"] == 0

    def test_stats_after_decompose(self, gd):
        gd.decompose("fix bug A")
        gd.decompose("build web app")
        stats = gd.get_stats()
        assert stats["total_goals"] == 2
        assert stats["active_goals"] == 2

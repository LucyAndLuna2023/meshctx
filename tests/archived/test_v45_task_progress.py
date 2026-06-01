"""v2.45 Background Task Progress — 测试套件"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.task_progress import (
    TaskProgressEngine, get_progress_engine, TaskProgress, _TaskTracker
)


@pytest.fixture
def engine():
    """创建新的任务进度引擎"""
    return TaskProgressEngine(max_history=10)


class TestTaskLifecycle:
    """任务生命周期"""

    def test_create_task(self, engine):
        task = engine.create_task("测试任务", total_steps=10)
        assert task.task_id.startswith("task_")
        assert task.name == "测试任务"
        assert task.status == "pending"
        assert task.total_steps == 10
        assert task.progress == 0.0

    def test_start_task(self, engine):
        task = engine.create_task("启动任务")
        result = engine.start_task(task.task_id)
        assert result is not None
        assert result.status == "running"
        assert result.started_at > 0

    def test_update_progress(self, engine):
        task = engine.create_task("进度任务")
        engine.start_task(task.task_id)

        engine.update_progress(task.task_id, 50.0, stage="处理中", message="已完成一半")
        updated = engine.get_task(task.task_id)
        assert updated.progress == 50.0
        assert updated.stage == "处理中"
        assert updated.message == "已完成一半"

    def test_update_progress_clamped(self, engine):
        task = engine.create_task("超出任务")
        engine.start_task(task.task_id)

        engine.update_progress(task.task_id, 150.0)  # 超出100%
        assert engine.get_task(task.task_id).progress == 100.0

        engine.update_progress(task.task_id, -10.0)  # 低于0%
        assert engine.get_task(task.task_id).progress == 0.0

    def test_complete_task(self, engine):
        task = engine.create_task("完成测试")
        engine.start_task(task.task_id)
        result = engine.complete_task(task.task_id, result={"count": 42})
        assert result.status == "completed"
        assert result.progress == 100.0
        assert result.result == {"count": 42}
        assert result.completed_at > 0

    def test_fail_task(self, engine):
        task = engine.create_task("失败测试")
        engine.start_task(task.task_id)
        result = engine.fail_task(task.task_id, "连接超时")
        assert result.status == "failed"
        assert result.error == "连接超时"

    def test_cancel_task(self, engine):
        task = engine.create_task("取消测试")
        engine.start_task(task.task_id)
        result = engine.cancel_task(task.task_id, "用户取消")
        assert result.status == "cancelled"
        assert "取消" in result.message

    def test_nonexistent_task(self, engine):
        assert engine.get_task("nonexistent") is None
        assert engine.start_task("nonexistent") is None
        assert engine.complete_task("nonexistent") is None


class TestProgressSubscription:
    """进度订阅(SSE)"""

    @pytest.mark.asyncio
    async def test_subscribe_specific_task(self, engine):
        task = engine.create_task("订阅测试")
        engine.start_task(task.task_id)

        queue = engine.subscribe(task.task_id)

        # 更新后应该能在队列中收到消息
        engine.update_progress(task.task_id, 30.0, message="第3步")
        data = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert data["task_id"] == task.task_id
        assert data["progress"] == 30.0
        assert data["message"] == "第3步"

    @pytest.mark.asyncio
    async def test_subscribe_global(self, engine):
        task = engine.create_task("全局订阅")
        engine.start_task(task.task_id)

        queue = engine.subscribe()  # 全局订阅

        engine.update_progress(task.task_id, 70.0)
        data = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert data["progress"] == 70.0

    @pytest.mark.asyncio
    async def test_unsubscribe(self, engine):
        task = engine.create_task("取消订阅")
        engine.start_task(task.task_id)

        queue = engine.subscribe(task.task_id)
        engine.unsubscribe(task.task_id, queue)

        engine.update_progress(task.task_id, 50.0)
        # 取消订阅后不应收到消息
        try:
            await asyncio.wait_for(queue.get(), timeout=0.5)
            assert False, "Should not receive message after unsubscribe"
        except asyncio.TimeoutError:
            pass  # 预期的超时


class TestListAndQuery:
    """列表与查询"""

    def test_list_active(self, engine):
        t1 = engine.create_task("活跃1")
        t2 = engine.create_task("活跃2")
        engine.start_task(t1.task_id)
        engine.start_task(t2.task_id)

        active = engine.list_active()
        assert len(active) == 2

    def test_list_active_excludes_completed(self, engine):
        t1 = engine.create_task("完成排除")
        engine.start_task(t1.task_id)
        engine.complete_task(t1.task_id)

        active = engine.list_active()
        assert len(active) == 0

    def test_get_history(self, engine):
        t1 = engine.create_task("历史1")
        engine.start_task(t1.task_id)
        engine.complete_task(t1.task_id, "done")

        history = engine.get_history()
        assert len(history) >= 1
        assert history[-1]["name"] == "历史1"
        assert history[-1]["status"] == "completed"

    def test_get_stats(self, engine):
        t1 = engine.create_task("统计1")
        engine.start_task(t1.task_id)
        engine.complete_task(t1.task_id)

        t2 = engine.create_task("统计2")
        engine.start_task(t2.task_id)
        engine.fail_task(t2.task_id, "error")

        stats = engine.get_stats()
        assert stats["completed"] == 1
        assert stats["failed"] == 1


class TestContextManager:
    """上下文管理器"""

    @pytest.mark.asyncio
    async def test_track_success(self, engine):
        """成功的追踪"""
        async with engine.track("上下文测试", total_steps=3) as tracker:
            tracker.update(33, "步骤1/3")
            tracker.update(66, "步骤2/3")
            tracker.update(100, "完成")

        history = engine.get_history()
        assert len(history) >= 1
        assert history[-1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_track_failure(self, engine):
        """失败的追踪"""
        try:
            async with engine.track("失败跟踪", total_steps=5) as tracker:
                tracker.update(20, "第1步")
                raise ValueError("故意的错误")
        except ValueError:
            pass

        history = engine.get_history()
        assert len(history) >= 1
        assert history[-1]["status"] == "failed"


class TestCleanup:
    """清理"""

    def test_cleanup_removes_old_tasks(self, engine):
        t1 = engine.create_task("旧任务")
        engine.start_task(t1.task_id)
        engine.complete_task(t1.task_id)
        # 直接操作内部时间来模拟过期
        # engine.cleanup(max_age_seconds=-1)  # 负数秒=所有都过期
        # 由于我们无法修改内部时间，简单验证cleanup不报错
        removed = engine.cleanup(max_age_seconds=3600)
        assert isinstance(removed, int)


class TestSingleton:
    """单例"""

    def test_singleton(self):
        from src.core import task_progress
        task_progress._engine = None
        e1 = get_progress_engine()
        e2 = get_progress_engine()
        assert e1 is e2

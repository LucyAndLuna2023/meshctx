"""v3.120.0: meshctx work 自主工作引擎测试（004 审计方案 v0.2 验收项）"""
import time
from pathlib import Path

import pytest


def _make_fake_client():
    """client: chat.completions.create 抛异常 → 总结降级拼接"""
    class _CC:
        def create(self, **kw):
            raise RuntimeError("no llm in test")
    class _Completions:
        create = _CC().create
    class _Chat:
        completions = _Completions()
    return type("FakeClient", (), {"_model": "test", "chat": _Chat()})()


class TestWorkPersistence:
    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        job = we.WorkJob(id="j1", goal="测试目标", target_hours=5,
                         deadline_ts=time.time() + 1000)
        job.plan = [we.WorkTask(id="t1", title="任务1", detail="做某事")]
        we.save_job(job)
        loaded = we.load_job("j1")
        assert loaded is not None
        assert loaded.id == "j1"
        assert loaded.plan[0].title == "任务1"
        assert loaded.plan[0].status == "pending"
        assert (tmp_path / "j1.json").exists()

    def test_atomic_write_no_tmp_leftover(self, tmp_path, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        we.save_job(we.WorkJob(id="j2", goal="g", target_hours=1,
                               deadline_ts=time.time() + 100))
        assert not list(tmp_path.glob("*.tmp"))


class TestTaskWallAdaptive:
    def test_clamp_formula(self, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", Path("/tmp/work-test"))
        # 004 公式: task_wall = clamp(hours*3600/len(plan)*2, 1200, 7200)
        # 5h / 20 任务 → 1800
        job = we.WorkJob(id="j", goal="g", target_hours=5, deadline_ts=0,
                         plan=[we.WorkTask(id=f"t{i}", title="", detail="") for i in range(20)])
        assert we.task_wall_seconds(job) == 1800
        # 24h / 100 任务 → 1728（区间内）
        job2 = we.WorkJob(id="j", goal="g", target_hours=24, deadline_ts=0,
                          plan=[we.WorkTask(id=f"t{i}", title="", detail="") for i in range(100)])
        assert we.task_wall_seconds(job2) == 1728
        # 0.5h / 1 任务 → 3600（公式直算，区间内）
        job3 = we.WorkJob(id="j", goal="g", target_hours=0.5, deadline_ts=0,
                          plan=[we.WorkTask(id="t1", title="", detail="")])
        assert we.task_wall_seconds(job3) == 3600
        # 0.1h / 10 任务 → 72 → 触底 1200
        job3b = we.WorkJob(id="j", goal="g", target_hours=0.1, deadline_ts=0,
                           plan=[we.WorkTask(id=f"t{i}", title="", detail="") for i in range(10)])
        assert we.task_wall_seconds(job3b) == 1200
        # 24h / 1 任务 → 上限 7200
        job4 = we.WorkJob(id="j", goal="g", target_hours=24, deadline_ts=0,
                          plan=[we.WorkTask(id="t1", title="", detail="")])
        assert we.task_wall_seconds(job4) == 7200


class TestRetryLayers:
    def test_classify_error(self):
        import src.work_engine as we
        assert we.classify_error("401 invalid api key") == "auth"
        assert we.classify_error("403 forbidden") == "auth"
        assert we.classify_error("429 rate limit exceeded") == "rate_limit"
        assert we.classify_error("timeout connecting to api") == "retry"
        assert we.classify_error("502 bad gateway") == "retry"
        assert we.classify_error("连接被拒绝") == "retry"
        assert we.classify_error("内容不正确") == "business"


class TestHeartbeatDeadDetection:
    def test_running_dead_process_becomes_pending(self, tmp_path, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        job = we.WorkJob(id="j3", goal="g", target_hours=1,
                         deadline_ts=time.time() + 100, status="running",
                         last_heartbeat=time.time() - we.HEARTBEAT_TIMEOUT - 10)
        job.plan = [we.WorkTask(id="t1", title="a", detail="a", status="running"),
                    we.WorkTask(id="t2", title="b", detail="b", status="pending")]
        we.save_job(job)
        rec = we.recoverable_jobs()
        assert len(rec) == 1
        assert rec[0].status == "pending"
        assert rec[0].plan[0].status == "pending"

    def test_recent_touch_not_recoverable(self, tmp_path, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        job = we.WorkJob(id="j3b", goal="g", target_hours=1,
                         deadline_ts=time.time() + 100, status="running",
                         last_heartbeat=time.time())
        we.save_job(job)
        assert we.recoverable_jobs() == []


class TestProcessLock:
    def test_exclusive_and_release(self, tmp_path, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        lock = we.acquire_lock("j9")
        assert lock.exists()
        with pytest.raises(RuntimeError):
            we.acquire_lock("j9")
        we.release_lock(lock)
        lock2 = we.acquire_lock("j9")  # 释放后可再获取
        we.release_lock(lock2)

    def test_dead_pid_reclaim(self, tmp_path, monkeypatch):
        import src.work_engine as we
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        (tmp_path / "j10.lock").write_text("999999")  # 不存在的 pid
        lock = we.acquire_lock("j10")
        assert lock.exists()
        we.release_lock(lock)


class TestRunJob:
    def _patch(self, tmp_path, monkeypatch):
        import src.work_engine as we
        import src.agent_loop as al
        import src.model_registry as mr
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        async def fake_loop(client, messages, **kw):
            yield {"type": "token", "text": "子任务完成"}
        monkeypatch.setattr(al, "run_agent_loop", fake_loop)
        monkeypatch.setattr(mr, "get_registry", lambda: type("R", (), {"get": lambda self: _make_fake_client()})())
        return we

    def test_run_all_tasks_and_summary_fallback(self, tmp_path, monkeypatch):
        we = self._patch(tmp_path, monkeypatch)
        job = we.WorkJob(id="j4", goal="目标", target_hours=1,
                         deadline_ts=time.time() + 3600, max_cost=0)
        job.plan = [we.WorkTask(id="t1", title="a", detail="a"),
                    we.WorkTask(id="t2", title="b", detail="b")]
        we.run_job(job)
        assert job.status == "done"
        assert all(t.status == "done" for t in job.plan)
        assert "目标" in job.summary          # LLM 失败 → 降级拼接
        assert "完成 2/2" in job.summary
        assert (tmp_path / "j4.json").exists()

    def test_deadline_does_not_start_new_tasks(self, tmp_path, monkeypatch):
        we = self._patch(tmp_path, monkeypatch)
        job = we.WorkJob(id="j5", goal="目标", target_hours=0.0001,
                         deadline_ts=time.time() - 10)  # 已到期
        job.plan = [we.WorkTask(id="t1", title="a", detail="a"),
                    we.WorkTask(id="t2", title="b", detail="b")]
        we.run_job(job)
        assert all(t.status == "skipped" for t in job.plan)

    def test_max_cost_stops_after_one(self, tmp_path, monkeypatch):
        we = self._patch(tmp_path, monkeypatch)
        job = we.WorkJob(id="j6", goal="目标", target_hours=1,
                         deadline_ts=time.time() + 3600,
                         max_cost=we.COST_PER_TASK_EST)  # 1 个任务后达上限
        job.plan = [we.WorkTask(id="t1", title="a", detail="a"),
                    we.WorkTask(id="t2", title="b", detail="b")]
        we.run_job(job)
        done = [t for t in job.plan if t.status == "done"]
        assert len(done) == 1
        assert job.cost_estimate >= job.max_cost

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


class TestApiErrorTextDetection:
    """004 审计 P1: run_agent_loop 把 API 错误当正常文本返回 → 假成功"""

    def test_401_text_marks_failed_not_done(self, tmp_path, monkeypatch):
        import src.work_engine as we
        import src.agent_loop as al
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        async def fake_loop(client, messages, **kw):
            yield {"type": "token",
                   "text": "Error code: 401 - Authentication Fails. Please check your API key."}
        monkeypatch.setattr(al, "run_agent_loop", fake_loop)
        task = we.WorkTask(id="t", title="a", detail="a")
        we._run_one_task(_make_fake_client(), task, wall_clock=1200)
        assert task.status == "failed"
        assert task.attempts == 1          # auth 不重试
        assert "API 错误文本" in task.error or "401" in task.error

    def test_500_text_retries_until_max(self, tmp_path, monkeypatch):
        import src.work_engine as we
        import src.agent_loop as al
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        monkeypatch.setattr(we, "backoff_seconds", lambda a: 0)  # 免等退避
        calls = {"n": 0}
        async def fake_loop(client, messages, **kw):
            calls["n"] += 1
            yield {"type": "token", "text": "Error code: 500 - internal server error"}
        monkeypatch.setattr(al, "run_agent_loop", fake_loop)
        task = we.WorkTask(id="t", title="a", detail="a", max_attempts=3)
        we._run_one_task(_make_fake_client(), task, wall_clock=1200)
        assert task.status == "failed"
        assert calls["n"] == 3             # 5xx 重试 3 次后失败


class TestClassifyNarrow:
    """004 审计 P2: 数字子串误报收窄"""

    def test_no_false_positive_on_digit_substrings(self):
        import src.work_engine as we
        assert we.classify_error("处理了 5 个文件后失败") == "business"
        assert we.classify_error("修改 50 行代码出错") == "business"
        assert we.classify_error("任务执行到第 5 步报错") == "business"
        assert we.classify_error("写了 504 行文档") == "business"

    def test_http_status_and_network_still_retry(self):
        import src.work_engine as we
        assert we.classify_error("Error code: 500 - server error") == "retry"
        assert we.classify_error("502 Bad Gateway") == "retry"
        assert we.classify_error("timeout connecting to api") == "retry"
        assert we.classify_error("连接被拒绝") == "retry"


class TestTaskTouchDuringRun:
    """004 审计 P2: 长任务执行期间心跳粒度（每 HEARTBEAT_INTERVAL 更新）"""

    def test_touch_callback_invoked_during_task(self, tmp_path, monkeypatch):
        import asyncio
        import src.work_engine as we
        import src.agent_loop as al
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        monkeypatch.setattr(we, "HEARTBEAT_INTERVAL", 0.01)
        hb = {"n": 0}
        async def fake_loop(client, messages, **kw):
            yield {"type": "token", "text": "开始"}
            await asyncio.sleep(0.03)
            yield {"type": "token", "text": "完成"}
        monkeypatch.setattr(al, "run_agent_loop", fake_loop)
        task = we.WorkTask(id="t", title="a", detail="a")
        we._run_one_task(_make_fake_client(), task, wall_clock=1200,
                         heartbeat_cb=lambda: hb.__setitem__("n", hb["n"] + 1))
        assert task.status == "done"
        assert hb["n"] >= 1


class TestDeadJobRecoverOnRun:
    """004 审计 P2: resume 判死接线 — run_job 对 running+心跳超时 job 判死重跑"""

    def test_running_dead_job_recovered(self, tmp_path, monkeypatch):
        import src.work_engine as we
        import src.agent_loop as al
        import src.model_registry as mr
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        async def fake_loop(client, messages, **kw):
            yield {"type": "token", "text": "done"}
        monkeypatch.setattr(al, "run_agent_loop", fake_loop)
        monkeypatch.setattr(mr, "get_registry",
                            lambda: type("R", (), {"get": lambda self: _make_fake_client()})())
        job = we.WorkJob(id="jd", goal="g", target_hours=1,
                         deadline_ts=time.time() + 3600, status="running",
                         last_heartbeat=time.time() - we.HEARTBEAT_TIMEOUT - 5)
        job.plan = [we.WorkTask(id="t1", title="a", detail="a", status="running")]
        we.save_job(job)
        we.run_job(job)
        assert job.plan[0].status == "done"   # 判死 → pending → 执行完成


class TestCliWorkSmoke:
    """004/002 审计 P0: meshctx work run 入口必崩（uuid 未导入）回归防护"""

    def test_cli_module_imports_uuid(self):
        import src.cli
        assert hasattr(src.cli, "uuid")

    def test_cmd_work_run_without_model_no_crash(self, tmp_path, monkeypatch):
        import src.cli
        import src.work_engine as we
        import src.model_registry as mr
        from types import SimpleNamespace
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        monkeypatch.setattr(mr, "get_registry",
                            lambda *a, **k: type("R", (), {"get": lambda self: None})())
        args = SimpleNamespace(work_cmd="run", config=None, goal="写一个5行说明",
                               hours=0.1, retry=3, max_cost=0, resume="")
        src.cli.cmd_work(args)  # 无模型 → 打印提示返回，不抛 NameError/其他异常


class TestModelCatalogReality:
    """v3.120.2: BUILTIN_MODELS 按厂商官方真实模型校准（用户反馈 + OpenRouter/官方文档交叉验证）"""

    def test_deepseek_official_v4_models(self):
        from src.model_registry import BUILTIN_MODELS
        ds = {k: v["model"] for k, v in BUILTIN_MODELS.items() if v["provider"] == "deepseek"}
        assert ds["deepseek:v4-flash"] == "deepseek-v4-flash"
        assert ds["deepseek:v4-pro"] == "deepseek-v4-pro"
        assert ds["deepseek:v4-flash-vision"] == "deepseek-v4-flash-vision-exp"
        # 官方已无 deepseek-chat/reasoner/coder（V3 时代名）；chat/reasoner 兼容映射到现役模型
        assert "deepseek-v4-flash" in ds.values()
        assert "deepseek-v4-pro" in ds.values()
        assert "deepseek-chat" not in ds.values()
        assert "deepseek-coder" not in ds.values()
        assert "deepseek-reasoner" not in ds.values()

    def test_openai_gpt5_replaces_retired_preview(self):
        from src.model_registry import BUILTIN_MODELS
        oai = {k: v["model"] for k, v in BUILTIN_MODELS.items() if v["provider"] == "openai"}
        assert "gpt-5" in oai.values()
        assert "gpt-5-mini" in oai.values()
        assert "gpt-4.5-preview" not in oai.values()

    def test_anthropic_xai_no_retired_models(self):
        from src.model_registry import BUILTIN_MODELS
        ant = [v["model"] for v in BUILTIN_MODELS.values() if v["provider"] == "anthropic"]
        xai = [v["model"] for v in BUILTIN_MODELS.values() if v["provider"] == "xai"]
        assert "claude-3.5-haiku" not in ant
        assert "claude-3.5-sonnet" not in ant
        assert any("latest" in m for m in ant)
        assert "grok-3-beta" not in xai
        assert "grok-4.6" in xai


class TestCliWorkNonInteractive:
    """004 审计 P1 (v3.120.2): 非交互 stdin（cron/后台/无人值守）必须默认开始而非卡 paused"""

    def test_eof_stdin_defaults_to_go(self, tmp_path, monkeypatch, capsys):
        import builtins
        import src.cli
        import src.work_engine as we
        import src.model_registry as mr
        from types import SimpleNamespace
        monkeypatch.setattr(we, "WORK_DIR", tmp_path)
        monkeypatch.setattr(we, "PLAN_CONFIRM_SECONDS", 0)  # 免等倒计时
        monkeypatch.setattr(mr, "get_registry",
                            lambda *a, **k: type("R", (), {"get": lambda self: None})())
        # 非交互 stdin → input() 立即 EOFError（cron/后台场景）
        def _eof(*a, **k):
            raise EOFError
        monkeypatch.setattr(builtins, "input", _eof)
        args = SimpleNamespace(work_cmd="run", config=None, goal="写一个5行说明",
                               hours=0.1, retry=3, max_cost=0, resume="")
        src.cli.cmd_work(args)  # 不应抛异常；不应卡在 paused 分支
        out = capsys.readouterr().out
        assert "未配置可用模型" in out   # EOF 默认 go → 走到执行路径（无模型提示）
        assert "已暂停" not in out       # 未卡在 print-plan-then-go 的 paused 分支

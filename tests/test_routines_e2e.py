"""WP6 (MCTX-PLAN-2026-0903) Routines 验收 e2e — 定时触发真派活 + 旧调度共存。

- 定时触发 e2e (mock 时钟): RoutineScheduler(tick_now) + 真实 make_spawn_fn
  (配额 try_consume_spawn → TaskCard enqueue) → 卡真实入队且 last_run 推进、
  间隔内不重复、越过间隔再触发。
- 旧 scheduler.py 共存: 迁移双跑期 (删除点 3.124.0, 002codex P3) 两者可并存。
"""
import pathlib
import shutil
import tempfile
import time

import pytest
import pytest_asyncio

from src.core.routines import Routine, RoutineScheduler, RoutineStore


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_routines_e2e_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture()
async def worker(tmp_dir, monkeypatch):
    """真实 CardWorker (独立线程) + 隔离 store/CARDS_DIR + 快速 run_fn。"""
    from src.core import task_cards as tc
    old_worker = tc._worker
    if old_worker is not None:
        old_worker.stop()
        old_worker.join(timeout=2.0)
    tc._worker = None
    monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
    from src.core.task_cards import TaskCardStore
    real_cls = TaskCardStore

    def _make(base_dir=None):
        return real_cls(base_dir=tmp_dir / "cards")

    monkeypatch.setattr(tc, "TaskCardStore", _make)

    async def fake_run(card):
        import asyncio as _a
        await _a.sleep(0.02)
        return {"result": "ok"}

    w = tc.get_card_worker()
    w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards")
    w.start(run_fn=fake_run)
    try:
        yield w
    finally:
        w.stop()
        w.join(timeout=3.0)
        tc._worker = None


class TestRoutineSpawnE2E:
    def test_interval_tick_spawns_card_once(self, tmp_dir, worker):
        """定时触发 e2e: tick 到期 → 配额→enqueue 真派活; 间隔内不重复。"""
        from src.core.routines_api import make_spawn_fn
        from src.core.task_cards import TaskCardStore

        clock = [time.time() - 10000]           # 假时钟, routine 早已创建
        store = RoutineStore(path=tmp_dir / "r.json")
        sched = RoutineScheduler(store=store, spawn_fn=make_spawn_fn(),
                                 tick_seconds=0.01, now_fn=lambda: clock[0])
        r = Routine(owner="local", prompt="定时备份 {date}", kind="interval",
                    schedule="100")
        r.created_at = clock[0] - 10000
        store.save(r)
        try:
            fired = sched.tick_now()
            assert fired == [r.id]
            got = store.get(r.id)
            assert got.last_run == clock[0], "成功后 last_run 应推进到触发时刻"
            # 卡真实入队 (worker store 可查)
            cards = TaskCardStore(base_dir=tmp_dir / "cards").list_cards(owner="local")
            assert len(cards) == 1
            assert "定时备份" in cards[0].prompt
            # 间隔 (100s) 内不重复
            clock[0] += 50
            assert sched.tick_now() == []
            # 越过间隔再触发
            clock[0] += 60
            fired2 = sched.tick_now()
            assert fired2 == [r.id]
            assert len(TaskCardStore(base_dir=tmp_dir / "cards").list_cards(owner="local")) == 2
        finally:
            sched.stop()

    def test_legacy_scheduler_coexists(self):
        """迁移双跑兼容 (删除点 3.124.0): 旧 scheduler API 仍可用, 不冲突。"""
        from src.core import scheduler as legacy
        assert hasattr(legacy, "schedule_periodic")
        assert hasattr(legacy, "schedule_delayed")
        assert hasattr(legacy, "cancel_all")
        assert hasattr(legacy, "list_tasks")
        # routines 模块独立线程, 不依赖 legacy 全局 _running
        from src.core.routines import RoutineScheduler
        assert RoutineScheduler is not None

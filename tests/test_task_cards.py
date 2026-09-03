# -*- coding: utf-8 -*-
"""Task Cards (Agent 派活中心) — T1 单元测试"""
import json
import pathlib
import shutil
import tempfile
import time

import pytest


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_task_cards_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def store(tmp_dir):
    from src.core.task_cards import TaskCardStore
    return TaskCardStore(base_dir=tmp_dir / "cards")


class TestTaskCard:
    def test_roundtrip(self):
        from src.core.task_cards import TaskCard, CardStatus
        c = TaskCard(owner="local", plan="free", title="T", prompt="读 README",
                     model="deepseek:v4-flash")
        c.mark(CardStatus.RUNNING)
        c.log("deliver", text="hi")
        d = c.to_dict()
        c2 = TaskCard.from_dict(d)
        assert c2.id == c.id
        assert c2.owner == "local"
        assert c2.status == CardStatus.RUNNING
        assert len(c2.timeline) == 1
        assert c2.timeline[0]["kind"] == "deliver"

    def test_status_transitions(self):
        from src.core.task_cards import TaskCard, CardStatus
        c = TaskCard()
        assert c.status == CardStatus.QUEUED
        c.mark(CardStatus.COMPLETED, result="ok")
        assert c.status == CardStatus.COMPLETED
        assert c.result == "ok"
        assert c.finished_at is not None

    def test_missing_fields_default(self):
        from src.core.task_cards import TaskCard, CardStatus
        c = TaskCard.from_dict({"id": "x1"})
        assert c.owner == "local"
        assert c.plan == "free"
        assert c.status == CardStatus.QUEUED


class TestTaskCardStore:
    def test_save_load_delete(self, store):
        from src.core.task_cards import TaskCard
        c = TaskCard(owner="local", prompt="do x")
        store.save(c)
        assert (store._dir / f"{c.id}.json").exists()
        got = store.load(c.id)
        assert got is not None and got.prompt == "do x"
        assert store.load("nope") is None
        assert store.delete(c.id) is True
        assert store.load(c.id) is None

    def test_file_perms_0600(self, store):
        from src.core.task_cards import TaskCard
        c = TaskCard(owner="local", prompt="secret")
        store.save(c)
        p = store._dir / f"{c.id}.json"
        mode = p.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0600 got {oct(mode)}"

    def test_list_filter(self, store):
        from src.core.task_cards import TaskCard, CardStatus
        a = TaskCard(owner="alice", prompt="a")
        b = TaskCard(owner="alice", prompt="b")
        c2 = TaskCard(owner="bob", prompt="c")
        for x in (a, b, c2):
            store.save(x)
        a.mark(CardStatus.COMPLETED)
        store.save(a)
        alice = store.list_cards(owner="alice")
        assert len(alice) == 2
        assert {x.id for x in alice} == {a.id, b.id}
        done = store.list_cards(owner="alice", status=CardStatus.COMPLETED)
        assert [x.id for x in done] == [a.id]

    def test_prune(self, store):
        from src.core.task_cards import TaskCard, CardStatus
        for i in range(12):
            c = TaskCard(owner="alice", prompt=f"t{i}")
            c.mark(CardStatus.COMPLETED, result=str(i))
            c.created_at = time.time() - (12 - i)  # 旧的先完成
            store.save(c)
        removed = store.prune("alice", keep=3)
        assert removed == 9
        assert len(store.list_cards(owner="alice")) == 3


class TestHubQuota:
    def test_limits_table(self):
        from src.core.task_cards import PLAN_LIMITS
        assert PLAN_LIMITS["free"]["spawns_per_day"] > 0
        assert PLAN_LIMITS["enterprise"]["spawns_per_day"] >= PLAN_LIMITS["team"]["spawns_per_day"]

    def test_consume_personal_never_hard_blocked(self):
        from src.core.task_cards import get_hub_quota
        hq = get_hub_quota()
        # 个人版永远 ok (soft), 不因 quota_manager 缺失崩溃
        res = hq.try_consume_spawn("test-user", plan="free")
        assert res["ok"] is True
        assert "remaining" in res

    def test_concurrent_soft_warn(self):
        from src.core.task_cards import get_hub_quota
        hq = get_hub_quota()
        lim = hq._limits("free")
        res = hq.try_consume_spawn("u", plan="free", concurrent_now=lim["max_concurrent"] + 5)
        assert res["ok"] is True
        assert res["warned"] is True


class TestCardWorker:
    def _make(self, tmp_dir, run_fn):
        from src.core.task_cards import CardWorker, TaskCardStore
        w = CardWorker()
        w._store = TaskCardStore(base_dir=tmp_dir / "w")
        w.start(run_fn=run_fn)
        return w

    def test_start_consume_end_to_end(self, tmp_dir):
        import asyncio, time
        from src.core.task_cards import TaskCard, CardStatus

        async def run_fn(card):
            await asyncio.sleep(0.01)
            return {"result": "done: " + card.prompt}

        w = self._make(tmp_dir, run_fn)
        try:
            c = TaskCard(owner="local", prompt="hello")
            assert w.enqueue(c) is True
            got = None
            for _ in range(200):
                time.sleep(0.02)
                got = w._store.load(c.id)
                if got and got.status in (CardStatus.COMPLETED, CardStatus.FAILED, CardStatus.CANCELLED):
                    break
            assert got is not None and got.status == CardStatus.COMPLETED, got.status if got else None
            assert got.result == "done: hello"
        finally:
            w.stop()
            w.join(timeout=3.0)

    def test_failure_sets_failed(self, tmp_dir):
        import time
        from src.core.task_cards import TaskCard, CardStatus

        async def run_fn(card):
            raise RuntimeError("boom")

        w = self._make(tmp_dir, run_fn)
        try:
            c = TaskCard(owner="local", prompt="x")
            assert w.enqueue(c) is True
            got = None
            for _ in range(200):
                time.sleep(0.02)
                got = w._store.load(c.id)
                if got and got.status in (CardStatus.COMPLETED, CardStatus.FAILED, CardStatus.CANCELLED):
                    break
            assert got is not None and got.status == CardStatus.FAILED
            assert "boom" in (got.error or "")
        finally:
            w.stop()
            w.join(timeout=3.0)

    def test_cancel_queued(self, tmp_dir):
        import time
        from src.core.task_cards import TaskCard, CardStatus

        async def run_fn(card):
            import asyncio
            await asyncio.sleep(2)
            return {"result": "slow"}

        w = self._make(tmp_dir, run_fn)
        try:
            c = TaskCard(owner="local", prompt="job")
            assert w.enqueue(c) is True
            assert w.cancel(c.id) is True
            # 排队取消是异步投递, 轮询直到状态确认
            got = None
            for _ in range(200):
                time.sleep(0.02)
                got = w._store.load(c.id)
                if got and got.status == CardStatus.CANCELLED:
                    break
            assert got is not None and got.status == CardStatus.CANCELLED
        finally:
            w.stop()
            w.join(timeout=3.0)

    def test_running_cancel(self, tmp_dir):
        import time
        from src.core.task_cards import TaskCard, CardStatus

        async def run_fn(card):
            import asyncio
            await asyncio.sleep(3)  # 足够久以便先看到 running 再 cancel
            return {"result": "done"}

        w = self._make(tmp_dir, run_fn)
        try:
            c = TaskCard(owner="local", prompt="slow-job")
            assert w.enqueue(c) is True
            got = None
            for _ in range(200):
                time.sleep(0.02)
                got = w._store.load(c.id)
                if got and got.status == CardStatus.RUNNING:
                    break
            assert got is not None and got.status == CardStatus.RUNNING
            w.cancel(c.id)
            cancelled = False
            for _ in range(200):
                time.sleep(0.02)
                got2 = w._store.load(c.id)
                if got2 and got2.status in (CardStatus.CANCELLED, CardStatus.FAILED):
                    cancelled = True
                    break
            assert cancelled, "running 卡取消后应进入终止态"
        finally:
            w.stop()
            w.join(timeout=3.0)

    def test_approval_register_decide(self, tmp_dir):
        """审批协调: register (worker loop 外也可注册? 实际在 loop 内) — 直接验证 decide 幂等。"""
        import asyncio
        from src.core.task_cards import CardWorker, TaskCard, TaskCardStore, CardStatus
        # 用显式 loop 模式 (测试注入)
        w = CardWorker()
        w._store = TaskCardStore(base_dir=tmp_dir / "w5")
        loop = asyncio.new_event_loop()
        w.start(run_fn=lambda c: None, loop=loop)
        try:
            c = TaskCard(owner="local", prompt="x")
            # 在 loop 内注册 future
            asyncio.set_event_loop(loop)
            fut = loop.create_future()
            w._approval_futures["req-test"] = fut
            # 模拟 waiter 已挂起
            async def waiter():
                return await fut
            task = loop.create_task(waiter())
            assert w.decide_approval("req-test", "agree") is True
            loop.run_until_complete(asyncio.wait_for(task, timeout=2))
            assert task.result() == {"action": "agree", "text": ""}
            # 二次 decide 应 False (已弹出)
            assert w.decide_approval("req-test", "agree") is False
        finally:
            w.stop()
            w.join(timeout=2.0)
            loop.close()
    def test_recover_interrupted_after_restart(self, tmp_dir):
        """模拟进程重启: 预置 running/queued/waiting_approval 卡, start(recover=True)
        后 running→queued 重新执行、queued 直接排队、waiting_approval→failed。"""
        import time
        from src.core.task_cards import CardWorker, TaskCard, TaskCardStore, CardStatus

        async def run_fn(card):
            import asyncio
            await asyncio.sleep(0.05)
            return {"result": "recovered:" + card.prompt}

        store = TaskCardStore(base_dir=tmp_dir / "rec")

        # 预置三种状态卡 (模拟上次进程遗留)
        c_running = TaskCard(owner="local", prompt="r")
        c_running.mark(CardStatus.RUNNING)
        store.save(c_running)
        c_queued = TaskCard(owner="local", prompt="q")
        c_queued.mark(CardStatus.QUEUED)
        store.save(c_queued)
        c_wait = TaskCard(owner="local", prompt="w")
        c_wait.mark(CardStatus.WAITING_APPROVAL)
        c_wait.approval_pending = {"request_id": "x"}
        store.save(c_wait)

        w = CardWorker()
        w._store = store
        w.start(run_fn=run_fn, recover=True)
        try:
            # waiting_approval 应立即转 failed
            gw = store.load(c_wait.id)
            assert gw.status == CardStatus.FAILED, gw.status
            # running/queued 应被恢复并最终完成
            done = set()
            for _ in range(200):
                time.sleep(0.05)
                for cid in (c_running.id, c_queued.id):
                    g = store.load(cid)
                    if g and g.status == CardStatus.COMPLETED:
                        done.add(cid)
                if len(done) == 2:
                    break
            assert c_running.id in done, "running 卡未恢复完成"
            assert c_queued.id in done, "queued 卡未恢复完成"
            gr = store.load(c_running.id)
            assert gr.result == "recovered:r"
        finally:
            w.stop()
            w.join(timeout=3.0)

    def test_recover_skips_stale_cards(self, tmp_dir):
        """超窗 (>6h) 的 running/queued 卡不重跑: running→failed, queued 丢弃。"""
        import time
        from src.core.task_cards import CardWorker, TaskCard, TaskCardStore, CardStatus

        async def run_fn(card):
            import asyncio
            await asyncio.sleep(0.05)
            return {"result": "ok"}

        store = TaskCardStore(base_dir=tmp_dir / "stale")
        old = time.time() - 7 * 3600  # 7h 前
        c_stale_run = TaskCard(owner="local", prompt="old")
        c_stale_run.created_at = old
        c_stale_run.mark(CardStatus.RUNNING)
        store.save(c_stale_run)
        c_stale_q = TaskCard(owner="local", prompt="oldq")
        c_stale_q.created_at = old
        c_stale_q.mark(CardStatus.QUEUED)
        store.save(c_stale_q)
        # 近期卡应恢复
        c_fresh = TaskCard(owner="local", prompt="new")
        c_fresh.mark(CardStatus.QUEUED)
        store.save(c_fresh)

        w = CardWorker()
        w._store = store
        w.start(run_fn=run_fn, recover=True)
        try:
            g1 = store.load(c_stale_run.id)
            assert g1.status == CardStatus.FAILED, g1.status
            assert "恢复窗口" in (g1.error or ""), g1.error
            # stale queued: 直接清理删除
            g2 = store.load(c_stale_q.id)
            assert g2 is None, "超窗排队卡应被清理"
            # fresh 卡应完成
            done = False
            for _ in range(100):
                time.sleep(0.05)
                gf = store.load(c_fresh.id)
                if gf and gf.status == CardStatus.COMPLETED:
                    done = True
                    break
            assert done, "近期卡未恢复完成"
        finally:
            w.stop()
            w.join(timeout=3.0)


    def test_cancel_running_is_timely(self, tmp_dir):
        """P2-1 (002meshctx): cancel() API → interrupt_check 及时中断 (worker 级集合)。"""
        import time
        from src.core.task_cards import CardWorker, TaskCard, TaskCardStore, CardStatus

        started = {"t": 0.0}

        async def run_fn(card):
            import asyncio
            started["t"] = time.time()
            # 模拟长循环: 每 0.1s 检查一次 interrupt_check
            from src.core.task_card_runner import make_interrupt_check
            from src.core.interruptible_runner import InterruptSignal
            check = make_interrupt_check(card, w)
            for _ in range(100):
                try:
                    check()
                except InterruptSignal:
                    return {"result": "interrupted"}
                await asyncio.sleep(0.1)
            return {"result": "finished"}

        w = CardWorker()
        w._store = TaskCardStore(base_dir=tmp_dir / "cancel")
        w.start(run_fn=run_fn)
        try:
            c = TaskCard(owner="local", prompt="job")
            assert w.enqueue(c) is True
            # 等 running
            for _ in range(100):
                time.sleep(0.05)
                g = w._store.load(c.id)
                if g and g.status == CardStatus.RUNNING:
                    break
            # cancel → 应在 ~0.2s 内中断 (集合查询)
            t0 = time.time()
            w.cancel(c.id)
            done = False
            for _ in range(100):
                time.sleep(0.05)
                g = w._store.load(c.id)
                if g and g.status in (CardStatus.CANCELLED, CardStatus.COMPLETED, CardStatus.FAILED):
                    done = True
                    break
            elapsed = time.time() - t0
            assert done, "cancel 后卡未及时终止"
            assert elapsed < 2.0, f"取消不及时: {elapsed:.1f}s"
        finally:
            w.stop()
            w.join(timeout=3.0)

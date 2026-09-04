"""WP4 (MCTX-PLAN-2026-0903 P1-1) swarm 派生任务卡编排测试。

验收 (方案 WP4): 同机 ≥2 worker 聚合 e2e + 失败重试一次 + 配额跳过 + 校验;
子卡 parent_card_id 链接; 不经 /api/swarm/* (个人版落地路径 = 任务卡化)。
"""
import asyncio
import json
import pathlib
import shutil
import tempfile
import time

import pytest
import pytest_asyncio


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_swarm_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture()
async def env(tmp_dir, monkeypatch):
    from src.core import task_cards as tc
    from src.core.task_card_runner import run_card
    old_worker = tc._worker
    if old_worker is not None:
        old_worker.stop(); old_worker.join(timeout=2.0)
    tc._worker = None
    monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
    from src.core.task_cards import TaskCardStore
    real_cls = TaskCardStore
    monkeypatch.setattr(tc, "TaskCardStore",
                        lambda base_dir=None: real_cls(base_dir=tmp_dir / "cards"))

    attempts = {"bad": 0}

    async def fake_loop(client, messages, **kw):
        text = " ".join(str(m.get("content", "")) for m in messages
                        if isinstance(m, dict))
        if "坏任务" in text and attempts["bad"] == 0:
            attempts["bad"] += 1
            yield {"type": "error", "text": "模拟失败"}; return
        marker = "A" if "任务A" in text else ("B" if "任务B" in text else "X")
        yield {"type": "final", "text": "完成-" + marker}

    monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)

    class FakeClient:  # run_agent_loop 只透传
        model_id = "fake"

    from src.core import task_card_runner as runner
    monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

    w = tc.get_card_worker()
    w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards")
    w.start(run_fn=run_card)
    yield {"worker": w, "attempts": attempts, "runner": runner}
    w.stop(); w.join(timeout=3.0); tc._worker = None


async def _wait_terminal(store, card_id, timeout=25.0):
    from src.core.task_cards import CardStatus
    end = time.time() + timeout
    while time.time() < end:
        c = store.load(card_id)
        if c and c.status in (CardStatus.COMPLETED, CardStatus.FAILED,
                              CardStatus.CANCELLED):
            return c
        await asyncio.sleep(0.1)
    return store.load(card_id)


class TestSwarmCards:
    async def test_two_worker_aggregation(self, tmp_dir, env):
        from src.core.task_cards import TaskCard, CardStatus
        w = env["worker"]
        parent = TaskCard(owner="local", plan="free", title="Swarm 汇总",
                          prompt="父任务")
        parent.extra["swarm_plan"] = {"subtasks": ["任务A：读文件", "任务B：写报告"],
                                      "retry": True}
        parent.extra["wall_clock"] = 30
        w._store.save(parent)
        assert w.enqueue(parent) is True
        got = await _wait_terminal(w._store, parent.id)
        assert got is not None and got.status == CardStatus.COMPLETED, (got.status, got.error)
        assert "完成-A" in (got.result or "") and "完成-B" in (got.result or "")
        kids = got.extra.get("swarm_children") or []
        assert len(kids) == 2 and all(k["status"] == "completed" for k in kids)
        # 子卡链接与落盘
        kids_cards = w._store.list_cards(owner="local")
        child_cards = [c for c in kids_cards
                       if (c.extra or {}).get("parent_card_id") == parent.id]
        assert len(child_cards) == 2
        assert all(c.status == CardStatus.COMPLETED for c in child_cards)

    async def test_child_failure_retry_once(self, tmp_dir, env):
        from src.core.task_cards import TaskCard, CardStatus
        w = env["worker"]
        parent = TaskCard(owner="local", plan="free", title="含失败",
                          prompt="父任务")
        parent.extra["swarm_plan"] = {"subtasks": ["任务A 正常", "坏任务 故意"],
                                      "retry": True}
        parent.extra["wall_clock"] = 40
        w._store.save(parent)
        w.enqueue(parent)
        got = await _wait_terminal(w._store, parent.id)
        assert got.status == CardStatus.COMPLETED, got.error
        kids = got.extra.get("swarm_children") or []
        assert len(kids) == 2
        retried = [k for k in kids if k.get("retries", 0) >= 1]
        assert retried and all(k["status"] == "completed" for k in retried), kids
        assert env["attempts"]["bad"] == 1  # 失败 1 次 → 重试成功

    async def test_quota_skip_records(self, tmp_dir, env, monkeypatch):
        from src.core import task_cards as tc
        from src.core.task_cards import TaskCard, CardStatus

        class FakeHQ:
            def try_consume_spawn(self, owner, plan="free", concurrent_now=0):
                return {"ok": False, "reason": "quota exceeded (test)"}
            def refund_spawn(self, owner): pass

        monkeypatch.setattr(tc, "get_hub_quota", lambda: FakeHQ())
        w = env["worker"]
        parent = TaskCard(owner="local", plan="free", prompt="父任务")
        parent.extra["swarm_plan"] = {"subtasks": ["任务A", "任务B"], "retry": False}
        parent.extra["wall_clock"] = 20
        w._store.save(parent)
        w.enqueue(parent)
        got = await _wait_terminal(w._store, parent.id)
        # worker 语义: out["error"] 记 card.error 但状态 COMPLETED — 断言 error 字段
        assert (got.error or "") and ("配额" in got.error or "无子任务" in got.error)

    async def test_validation_short_subtasks(self, tmp_dir, env):
        from src.core.task_cards import TaskCard, CardStatus
        w = env["worker"]
        parent = TaskCard(owner="local", plan="free", prompt="父任务")
        parent.extra["swarm_plan"] = {"subtasks": ["只有一条"], "retry": False}
        w._store.save(parent)
        w.enqueue(parent)
        got = await _wait_terminal(w._store, parent.id)
        assert (got.error or "") and "2-5" in got.error


class TestSwarmApprovalBoundary:
    """P3-1 (002codex): WAITING_APPROVAL 子卡在其余终态时不得孤儿 — 超时 cancel 收束。"""

    async def test_waiting_approval_child_not_orphaned(self, tmp_dir, monkeypatch):
        import time
        from src.core import task_cards as tc
        from src.core.task_card_runner import run_card
        monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards2")
        from src.core.task_cards import TaskCardStore, TaskCard, CardStatus
        real = TaskCardStore
        monkeypatch.setattr(tc, "TaskCardStore",
                            lambda base_dir=None: real(base_dir=tmp_dir / "cards2"))

        async def fake_loop(client, messages, **kw):
            text = " ".join(str(m.get("content", "")) for m in messages
                            if isinstance(m, dict))
            if "卡死" in text:
                yield {"type": "approval", "request_id": "req-x",
                       "name": "shell", "args": {"cmd": "x"}, "reason": "test"}
                res = await kw["approval_waiter"]("req-x")   # 阻塞至 decide/cancel
                yield {"type": "final", "text": "done-after:" + str(res.get("action"))}
                return
            yield {"type": "final", "text": "快完成"}

        monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)

        class FakeClient:
            model_id = "fake"

        from src.core import task_card_runner as runner
        monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

        w = tc.get_card_worker()
        w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards2")
        w.start(run_fn=run_card)
        try:
            parent = TaskCard(owner="local", plan="free", prompt="父任务")
            parent.extra["swarm_plan"] = {"subtasks": ["快任务", "卡死任务"],
                                          "retry": False, "timeout": 0.6}
            w._store.save(parent)
            w.enqueue(parent)
            end = time.time() + 12
            got = None
            while time.time() < end:
                c = w._store.load(parent.id)
                if c and c.status in (CardStatus.COMPLETED, CardStatus.FAILED,
                                      CardStatus.CANCELLED):
                    got = c; break
                await asyncio.sleep(0.1)
            assert got is not None, "父卡应在 deadline 后收束 (子卡不孤儿)"
            kids = got.extra.get("swarm_children") or []
            by_idx = {k["idx"]: k for k in kids}
            assert by_idx[0]["status"] == "completed"
            # idx1 卡死: 超时 cancel → 记 timeout (非孤儿静默)
            assert by_idx[1]["status"] in ("timeout", "cancelled", "failed"), kids
            # 子卡必达终态 (cancel 即时 reject 挂起审批, <~3s)
            c2 = w._store.load(by_idx[1].get("id", "zzz"))
            assert c2 is not None and c2.status in (CardStatus.CANCELLED,
                                                    CardStatus.FAILED,
                                                    CardStatus.COMPLETED), c2.status
        finally:
            w.stop(); w.join(timeout=3.0); tc._worker = None

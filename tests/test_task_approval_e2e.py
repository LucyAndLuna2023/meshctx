# -*- coding: utf-8 -*-
"""Task Cards 审批端到端 — T4: 危险动作 → waiting_approval → decide → 继续完成"""
import pathlib
import shutil
import tempfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_task_approval_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture()
async def env(tmp_dir, monkeypatch):
    """真实 runner (run_card) + 假 run_agent_loop (产出 approval 事件) + API app。"""
    from src.core import task_cards as tc
    from src.core import task_card_runner as runner_mod
    from src.core.task_cards import TaskCardStore

    monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
    old_worker = tc._worker
    tc._worker = None
    old_store_cls = tc.TaskCardStore
    tc.TaskCardStore = lambda base_dir=None: TaskCardStore(base_dir=tmp_dir / "cards")

    approval_flow = {"triggered": False}

    async def fake_loop(client, messages, **kw):
        """模拟 agent_loop: 先产 approval 事件, 待 decide 后完成。"""
        import asyncio
        needs = kw["needs_approval"]
        waiter = kw["approval_waiter"]
        reason = needs("terminal", {"cmd": "rm -rf /tmp/x"})
        assert reason is not None
        req_id = "approval-1"
        approval_flow["triggered"] = True
        yield {"type": "approval", "request_id": req_id,
               "name": "terminal", "args": {"cmd": "rm -rf /tmp/x"}, "reason": reason}
        dec = await waiter(req_id)
        yield {"type": "final", "text": f"decided={dec['action']}"}

    # patch runner 的依赖: run_agent_loop + client
    monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)
    monkeypatch.setattr(runner_mod, "_resolve_client",
                        lambda c: type("FakeC", (), {"model_id": "fake:v1"})())
    monkeypatch.setattr(runner_mod, "_resolve_tools", lambda: [])
    monkeypatch.setattr(runner_mod, "_resolve_exec_tool", lambda: (lambda *a, **k: "ok"))

    from src.core.task_card_runner import run_card
    w = tc.get_card_worker()
    w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards")
    w.start(run_fn=run_card)

    # API app (owner/plan 固定 local/free)
    from src.core.task_cards_api import router
    import src.core.task_cards_api as apimod
    a = FastAPI()
    a.include_router(router)

    async def _owner(request):
        return "local"

    async def _plan(request):
        return "free"

    apimod._owner = _owner
    apimod._plan = _plan
    client = AsyncClient(transport=ASGITransport(app=a), base_url="http://t")
    try:
        yield client, approval_flow
    finally:
        await client.aclose()
        await w.stop()
        tc._worker = old_worker
        tc.TaskCardStore = old_store_cls


class TestApprovalEndToEnd:
    async def test_dangerous_tool_pauses_and_resumes(self, env):
        import asyncio
        client, flow = env
        r = await client.post("/api/tasks/cards", json={"prompt": "删掉临时目录"})
        assert r.status_code == 200
        cid = r.json()["card_id"]

        # 等待卡进入 waiting_approval
        paused = None
        for _ in range(80):
            await asyncio.sleep(0.05)
            rr = await client.get(f"/api/tasks/cards/{cid}")
            if rr.status_code == 200:
                d = rr.json()
                if d["status"] == "waiting_approval":
                    paused = d
                    break
        assert paused is not None, "卡未进入 waiting_approval"
        assert flow["triggered"] is True
        pending = paused["approval_pending"]
        assert pending is not None and pending["name"] == "terminal"
        # 卡详情里应能看到审批请求事件
        kinds = [e["kind"] for e in paused["timeline"]]
        assert "approval_requested" in kinds

        # decide: reject
        ra = await client.post(f"/api/tasks/cards/{cid}/approve",
                               json={"action": "reject", "text": "不要删"})
        assert ra.status_code == 200, ra.text

        # 等待完成, 结果应体现 reject
        final = None
        for _ in range(80):
            await asyncio.sleep(0.05)
            rr = await client.get(f"/api/tasks/cards/{cid}")
            if rr.status_code == 200 and rr.json()["status"] == "completed":
                final = rr.json()
                break
        assert final is not None, "decide 后卡未完成"
        assert "reject" in (final["result"] or "")
        assert final["approval_pending"] is None

    async def test_approve_continue(self, env):
        import asyncio
        client, flow = env
        r = await client.post("/api/tasks/cards", json={"prompt": "rm 临时文件"})
        cid = r.json()["card_id"]
        paused = None
        for _ in range(80):
            await asyncio.sleep(0.05)
            rr = await client.get(f"/api/tasks/cards/{cid}")
            if rr.status_code == 200 and rr.json()["status"] == "waiting_approval":
                paused = rr.json()
                break
        assert paused is not None
        ra = await client.post(f"/api/tasks/cards/{cid}/approve",
                               json={"action": "agree"})
        assert ra.status_code == 200
        final = None
        for _ in range(80):
            await asyncio.sleep(0.05)
            rr = await client.get(f"/api/tasks/cards/{cid}")
            if rr.status_code == 200 and rr.json()["status"] == "completed":
                final = rr.json()
                break
        assert final is not None
        assert "agree" in (final["result"] or "")

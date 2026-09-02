# -*- coding: utf-8 -*-
"""Task Cards API — T3 HTTP 层测试 (httpx ASGI, 不起真实端口)"""
import pathlib
import shutil
import tempfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_task_api_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture()
async def isolated(tmp_dir, monkeypatch):
    """隔离全局 store/worker (跑在测试同一事件循环) + 修 CARDS_DIR。"""
    from src.core import task_cards as tc
    monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
    old_worker = tc._worker
    tc._worker = None
    old_store_cls = tc.TaskCardStore
    from src.core.task_cards import TaskCardStore
    tc.TaskCardStore = lambda base_dir=None: TaskCardStore(base_dir=tmp_dir / "cards")

    async def fake_run(card):
        import asyncio as _a
        await _a.sleep(0.05)
        return {"result": "fake done: " + card.prompt}

    w = tc.get_card_worker()
    w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards")
    w.start(run_fn=fake_run)
    try:
        yield w
    finally:
        await w.stop()
        tc._worker = old_worker
        tc.TaskCardStore = old_store_cls


@pytest.fixture()
def app(isolated):
    from src.core.task_cards_api import router
    from fastapi import FastAPI
    a = FastAPI()
    a.include_router(router)

    # 本地回环鉴权: _owner 会 import src.main._current_user_id → 太重。
    # 这里 patch 端点依赖的 _owner/_plan 到固定 "local"/"free"
    import src.core.task_cards_api as mod

    async def _owner(request):
        return "local"

    async def _plan(request):
        return "free"

    mod._owner = _owner
    mod._plan = _plan
    return a


@pytest.fixture()
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


class TestCreateList:
    async def test_create_and_list(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "读一下 README"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["card_id"]
        assert data["status"] in ("queued", "running")

        r2 = await client.get("/api/tasks/cards")
        assert r2.status_code == 200
        body = r2.json()
        assert body["owner"] == "local"
        assert any(c["id"] == data["card_id"] for c in body["cards"])

    async def test_missing_prompt(self, client):
        r = await client.post("/api/tasks/cards", json={})
        assert r.status_code == 400

    async def test_empty_prompt(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "   "})
        assert r.status_code == 400

    async def test_wait_for_completion(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "完成任务"})
        cid = r.json()["card_id"]
        import asyncio
        final = None
        for _ in range(50):
            await asyncio.sleep(0.05)
            rr = await client.get(f"/api/tasks/cards/{cid}")
            if rr.status_code == 200 and rr.json()["status"] == "completed":
                final = rr.json()
                break
        assert final is not None, "卡未在时限内完成"
        assert "fake done" in (final["result"] or "")

    async def test_get_missing_404(self, client):
        r = await client.get("/api/tasks/cards/nope")
        assert r.status_code == 404

    async def test_cancel_queued(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "x"})
        cid = r.json()["card_id"]
        rc = await client.post(f"/api/tasks/cards/{cid}/cancel")
        assert rc.status_code == 200

    async def test_retry(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "job"})
        cid = r.json()["card_id"]
        rr = await client.post(f"/api/tasks/cards/{cid}/retry")
        assert rr.status_code == 200
        assert rr.json()["retry_of"] == cid

    async def test_quota_endpoint(self, client):
        r = await client.get("/api/tasks/quota")
        assert r.status_code == 200
        body = r.json()
        assert body["plan"] == "free"
        assert body["limits"]["max_concurrent"] > 0


class TestApprove:
    async def test_approve_no_pending(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "job"})
        cid = r.json()["card_id"]
        ra = await client.post(f"/api/tasks/cards/{cid}/approve",
                               json={"action": "agree"})
        assert ra.status_code in (400, 409)  # 无 pending 或已结束

    async def test_approve_bad_action(self, client):
        r = await client.post("/api/tasks/cards", json={"prompt": "job"})
        cid = r.json()["card_id"]
        ra = await client.post(f"/api/tasks/cards/{cid}/approve",
                               json={"action": "nuke"})
        assert ra.status_code == 400

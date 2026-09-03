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
    # 彻底停掉可能残留的全局 worker (跨测试隔离)
    old_worker = tc._worker
    if old_worker is not None:
        old_worker.stop()
        old_worker.join(timeout=2.0)
    tc._worker = None
    monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
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
        w.stop()
        w.join(timeout=3.0)
        tc._worker = None  # 不恢复旧实例, 下个 fixture 自建 (防残留)
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
        """仅终止态卡可重试 (P3 002meshctx): 运行中→409; 完成后→200。"""
        import asyncio
        r = await client.post("/api/tasks/cards", json={"prompt": "job"})
        cid = r.json()["card_id"]
        # 运行中 retry → 409
        rr = await client.post(f"/api/tasks/cards/{cid}/retry")
        assert rr.status_code == 409, rr.text
        # 等完成
        for _ in range(100):
            await asyncio.sleep(0.05)
            d = (await client.get(f"/api/tasks/cards/{cid}")).json()
            if d["status"] == "completed":
                break
        rr2 = await client.post(f"/api/tasks/cards/{cid}/retry")
        assert rr2.status_code == 200, rr2.text
        assert rr2.json()["retry_of"] == cid

    async def test_quota_endpoint(self, client):
        r = await client.get("/api/tasks/quota")
        assert r.status_code == 200
        body = r.json()
        assert body["plan"] == "free"
        assert body["limits"]["max_concurrent"] > 0

    async def test_stream_terminal_ends(self, client):
        """stream: 已完成卡立即回 final 并结束。"""
        r = await client.post("/api/tasks/cards", json={"prompt": "job"})
        cid = r.json()["card_id"]
        import asyncio
        # 等卡完成
        for _ in range(100):
            await asyncio.sleep(0.05)
            rr = await client.get(f"/api/tasks/cards/{cid}")
            if rr.status_code == 200 and rr.json()["status"] == "completed":
                break
        async with client.stream("GET", f"/api/tasks/cards/{cid}/stream") as resp:
            assert resp.status_code == 200
            chunks = []
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    chunks.append(line)
                if len(chunks) >= 1 and '"event":"final"' in chunks[-1]:
                    break
        assert any('"event": "final"' in c or '"event":"final"' in c for c in chunks), "final 事件未到达"

    async def test_stream_404(self, client):
        async with client.stream("GET", "/api/tasks/cards/nope/stream") as resp:
            assert resp.status_code == 404

    async def test_create_with_wall_clock(self, client):
        """create 接受 wall_clock/max_rounds 并存进卡 extra。"""
        r = await client.post("/api/tasks/cards", json={
            "prompt": "任务", "wall_clock": 120, "max_rounds": 3})
        assert r.status_code == 200
        cid = r.json()["card_id"]
        rr = await client.get(f"/api/tasks/cards/{cid}")
        assert rr.status_code == 200
        d = rr.json()
        assert d["extra"]["wall_clock"] == 120.0
        assert d["extra"]["max_rounds"] == 3

    async def test_wall_clock_clamped(self, client):
        """wall_clock 超范围被钳制 (30-7200)。"""
        r = await client.post("/api/tasks/cards", json={"prompt": "x", "wall_clock": 5})
        cid = r.json()["card_id"]
        d = (await client.get(f"/api/tasks/cards/{cid}")).json()
        assert d["extra"]["wall_clock"] == 30.0

    async def test_delete_terminal_card(self, client):
        """删除终止态卡。"""
        import asyncio
        r = await client.post("/api/tasks/cards", json={"prompt": "job"})
        cid = r.json()["card_id"]
        for _ in range(100):
            await asyncio.sleep(0.05)
            d = (await client.get(f"/api/tasks/cards/{cid}")).json()
            if d["status"] == "completed":
                break
        rd = await client.request("DELETE", f"/api/tasks/cards/{cid}")
        assert rd.status_code == 200, rd.text
        rr = await client.get(f"/api/tasks/cards/{cid}")
        assert rr.status_code == 404

    async def test_delete_running_rejected(self, client, isolated):
        """运行中卡不可删 (409)。"""
        from src.core.task_cards import TaskCard
        card = TaskCard(owner="local", prompt="x")
        card.mark("running")
        isolated._store.save(card)
        rd = await client.request("DELETE", f"/api/tasks/cards/{card.id}")
        assert rd.status_code == 409


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

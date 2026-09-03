"""WP6 (MCTX-PLAN-2026-0903) routines API 测试 (CRUD/校验/触发/owner)。"""
import pathlib
import shutil
import tempfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_routine_api_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture()
async def isolated(tmp_dir, monkeypatch):
    """隔离: routines 存储路径 + task_cards store/worker (run-now 真派活)。
    全部经 monkeypatch 自动恢复 (防污染后续套件)。"""
    from src.core import task_cards as tc
    from src.core import routines as rt
    old_worker = tc._worker
    if old_worker is not None:
        old_worker.stop()
        old_worker.join(timeout=2.0)
    tc._worker = None
    monkeypatch.setattr(rt, "ROUTINES_PATH", tmp_dir / "routines.json")
    monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")

    from src.core.task_cards import TaskCardStore
    real_cls = TaskCardStore

    def _make(base_dir=None):
        return real_cls(base_dir=tmp_dir / "cards")

    monkeypatch.setattr(tc, "TaskCardStore", _make)

    async def fake_run(card):
        import asyncio as _a
        await _a.sleep(0.02)
        return {"result": "routine done: " + card.prompt}

    w = tc.get_card_worker()
    w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards")
    w.start(run_fn=fake_run)
    try:
        yield w
    finally:
        w.stop()
        w.join(timeout=3.0)
        tc._worker = None


@pytest.fixture()
def app(isolated):
    from src.core.routines_api import router
    import src.core.routines_api as mod
    a = FastAPI()
    a.include_router(router)

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


class TestCRUD:
    async def test_create_list_get(self, client):
        r = await client.post("/api/routines", json={
            "prompt": "每天早上备份 {date}", "kind": "interval", "schedule": "3600"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] and data["owner"] == "local"
        assert data["kind"] == "interval" and data["schedule"] == "3600"

        lst = (await client.get("/api/routines")).json()
        assert len(lst) == 1 and lst[0]["id"] == data["id"]

        got = (await client.get(f"/api/routines/{data['id']}")).json()
        assert got["prompt"] == "每天早上备份 {date}"

    async def test_cron_create(self, client):
        r = await client.post("/api/routines", json={
            "prompt": "x", "kind": "cron", "schedule": "30 8 * * 1-5"})
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "cron"

    async def test_validation_errors(self, client):
        assert (await client.post("/api/routines", json={})).status_code == 400
        assert (await client.post("/api/routines",
                                  json={"prompt": "x", "kind": "cron",
                                        "schedule": "bad expr"})).status_code == 400
        assert (await client.post("/api/routines",
                                  json={"prompt": "x", "kind": "interval",
                                        "schedule": "1"})).status_code == 400  # <10s

    async def test_update_toggle_and_delete(self, client):
        rid = (await client.post("/api/routines", json={"prompt": "p",
                                                         "schedule": "3600"})).json()["id"]
        r = await client.patch(f"/api/routines/{rid}", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert (await client.delete(f"/api/routines/{rid}")).status_code == 200
        assert (await client.get("/api/routines")).json() == []

    async def test_cross_owner_404(self, client, tmp_dir):
        # 直写 store 造一条 owner=alice 的记录, local 访问应 404
        from src.core.routines import RoutineStore, Routine
        st = RoutineStore(path=tmp_dir / "routines.json")
        st.save(Routine(owner="alice", prompt="secret",
                        kind="interval", schedule="3600"))
        rid = st.list()[0].id
        assert (await client.get(f"/api/routines/{rid}")).status_code == 404
        assert (await client.delete(f"/api/routines/{rid}")).status_code == 404

    async def test_run_now_spawns_card(self, client, tmp_dir):
        from src.core.routines import RoutineStore
        rid = (await client.post("/api/routines", json={
            "prompt": "立即跑一次", "schedule": "3600"})).json()["id"]
        r = await client.post(f"/api/routines/{rid}/run")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        # last_run 已推进
        got = RoutineStore(path=tmp_dir / "routines.json").get(rid)
        assert got.last_run > 0

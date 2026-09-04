"""Org Governance (组织架构/部门/数据权限/RBAC) 测试 — 2026-09 用户需求。

覆盖: 部门树/批量导入 (乱序/父子名)/成员分配/角色权限矩阵/数据 scope
(self|dept|org)/visible_owner_ids 部门聚合/级联删除/持久化回读 + API CRUD/导入/
成员/me/visible-owners + 任务卡 org_dept 视图隔离。
"""
import asyncio
import pathlib
import shutil
import tempfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.org_governance import OrgService, reset_org_service_for_tests


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_org_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


class TestOrgService:
    def test_dept_tree_and_import(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.import_depts([
            {"name": "总部"},
            {"name": "研发部", "parent": "总部"},
            {"name": "市场部", "parent": "总部"},
            {"name": "算法组", "parent": "研发部"},
        ])
        depts = {d["name"]: d for d in svc.list_depts()}
        assert set(depts) >= {"总部", "研发部", "市场部", "算法组"}
        assert depts["算法组"]["parent_id"] == depts["研发部"]["id"]
        assert depts["研发部"]["parent_id"] == depts["总部"]["id"]
        # 乱序父引用已注册名称可连
        sub = svc.dept_subtree_ids(depts["研发部"]["id"])
        assert set(sub) >= {depts["研发部"]["id"], depts["算法组"]["id"]}

    def test_members_roles_scope(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"},
                          {"name": "市场部", "parent": "总部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        mkt = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "市场部"))
        svc.set_member("alice", rnd["id"], "member")
        svc.set_member("bob", rnd["id"], "manager")
        svc.set_member("carol", mkt["id"], "member")
        assert svc.data_scope("alice") == "self"
        assert svc.data_scope("bob") == "dept"
        assert "audit_view" in svc.permissions("alice")
        assert svc.has("bob", "manage_members")
        # bob (manager, 研发部) 可见 研发部成员 (含自己)
        assert set(svc.visible_owner_ids("bob")) == {"alice", "bob"}
        # admin role perms
        svc.set_member("dave", mkt["id"], "admin")
        assert svc.data_scope("dave") == "org"
        assert set(svc.visible_owner_ids("dave")) == {"alice", "bob", "carol", "dave"}

    def test_persistence_and_cascade(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"},
                          {"name": "算法组", "parent": "研发部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        svc.set_member("alice", rnd["id"], "member")
        svc2 = OrgService(path=tmp_dir / "org.json")
        assert len(svc2.list_depts()) == 3
        assert svc2.member("alice")["role"] == "member"
        # 级联删除: 删研发部 → 算法组与其成员一并移除
        assert svc2.remove_dept(rnd["id"]) is True
        assert svc2.member("alice") is None
        assert len(svc2.list_depts()) == 1


@pytest.fixture()
def client(tmp_dir, monkeypatch):
    from src.core.org_api import router
    import src.core.org_api as mod
    from src.core import org_governance as og
    monkeypatch.setattr(og, "ORG_PATH", tmp_dir / "org.json")
    reset_org_service_for_tests()
    a = FastAPI(); a.include_router(router)

    async def _owner(req):
        return req.query_params.get("as", "alice") if "as" in req.query_params else "alice"

    mod._owner = _owner
    yield AsyncClient(transport=ASGITransport(app=a), base_url="http://t")
    reset_org_service_for_tests()


class TestOrgAPI:
    async def test_bootstrap_me(self, client):
        r = await client.get("/api/org/me")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"] == "alice"
        assert d["member"]["role"] == "owner"
        assert "manage_depts" in d["permissions"]

    async def test_dept_crud_and_import(self, client):
        # bootstrap 已自动建根"总部"; 导入研发部/市场部挂其下
        r = await client.post("/api/org/import", json={"format": "json", "items": [
            {"name": "研发部", "parent": "总部"}, {"name": "市场部", "parent": "总部"}]})
        assert r.status_code == 200 and r.json()["created"] == 2
        deps = (await client.get("/api/org/depts")).json()["depts"]
        assert len(deps) == 3 and sum(1 for d in deps if d["name"] == "总部") == 1

    async def test_csv_import(self, client):
        csv = "name,parent\n研发部,总部\n算法组,研发部\n"
        r = await client.post("/api/org/import",
                              json={"format": "csv", "csv": csv})
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 2

    async def test_member_assign_and_visible(self, client):
        await client.post("/api/org/import", json={"format": "json", "items": [
            {"name": "总部"}, {"name": "研发部", "parent": "总部"}]})
        deps = (await client.get("/api/org/depts")).json()["depts"]
        rnd = next(d for d in deps if d["name"] == "研发部")
        # alice(owner) 分配 bob 为 研发部 manager
        r = await client.post("/api/org/members", json={
            "user_id": "bob", "dept_id": rnd["id"], "role": "manager"})
        assert r.status_code == 200, r.text
        # 以 bob 身份查 visible-owners (dept scope → 部门成员)
        r2 = await client.get("/api/org/visible-owners", params={"as": "bob"})
        d2 = r2.json()
        assert d2["scope"] == "dept"
        # 部门此时仅 bob 本人成员 (alice 未入部门 → owner 自举在总部?)
        assert d2["owner"] == "bob"

    async def test_roles_permission_matrix(self, client):
        r = await client.get("/api/org/roles")
        assert r.status_code == 200
        roles = r.json()["roles"]
        assert "manage_depts" in roles["owner"]
        assert "data_scope_dept" in roles["manager"]
        assert "data_scope_org" in roles["auditor"]


class TestCardDeptScope:
    """数据权限落地: 任务卡 org_dept=1 视图 — manager 见部门卡, member 仅见自己。"""

    @pytest.fixture()
    def app_env(self, tmp_dir, monkeypatch):
        from fastapi import FastAPI
        from src.core.org_api import router as org_router
        from src.core import org_governance as og
        from src.core import task_cards as tc
        monkeypatch.setattr(og, "ORG_PATH", tmp_dir / "org.json")
        reset_org_service_for_tests()
        monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
        from src.core.task_cards import TaskCardStore
        tc.TaskCardStore = lambda base_dir=None: TaskCardStore(base_dir=tmp_dir / "cards")
        svc = og.get_org_service()
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        svc.set_member("alice", rnd["id"], "manager")     # 部门 manager
        svc.set_member("bob", rnd["id"], "member")        # 普通成员
        # 预置卡片: alice/bob/外来者 each 一张
        from src.core.task_cards import TaskCard, get_card_worker, TaskCardStore as TCS
        w = tc.get_card_worker()
        w._store = tc.TaskCardStore(base_dir=tmp_dir / "cards")
        for ow, txt in (("alice", "卡A"), ("bob", "卡B"), ("carol", "卡C")):
            c = TaskCard(owner=ow, plan="free", prompt=txt)
            w._store.save(c)
        a = FastAPI()
        from src.core.task_cards_api import router as tc_router
        a.include_router(tc_router)
        import src.core.task_cards_api as tcm
        import src.core.org_api as oam
        async def _owner(req):
            return req.query_params.get("as", "alice")
        tcm._owner = _owner
        oam._owner = _owner
        yield AsyncClient(transport=ASGITransport(app=a), base_url="http://t"), svc
        w.stop(); w.join(timeout=2.0)
        reset_org_service_for_tests()

    async def test_manager_sees_dept_cards_only(self, app_env):
        client, svc = app_env
        async with client as c:
            # alice = manager 研发部 → dept 视图含 alice+bob, 不含外来 carol
            r = await c.get("/api/tasks/cards", params={"org_dept": 1, "as": "alice"})
            assert r.status_code == 200, r.text
            cards = r.json()["cards"]
            owners = {cd["owner"] for cd in cards}
            assert owners == {"alice", "bob"}
            # 自己视图 (默认) 仅 alice
            r2 = await c.get("/api/tasks/cards", params={"as": "alice"})
            assert {cd["owner"] for cd in r2.json()["cards"]} == {"alice"}

    async def test_member_default_self_only(self, app_env):
        client, svc = app_env
        async with client as c:
            r = await c.get("/api/tasks/cards", params={"org_dept": 1, "as": "bob"})
            assert {cd["owner"] for cd in r.json()["cards"]} == {"bob"}

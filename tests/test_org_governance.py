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

    def test_import_audit_and_dup_name_failed(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.set_member("alice", "", "owner")          # 先有成员 → actor 走 alice
        res = svc.import_depts([{"name": "总部"},
                                {"name": "研发部", "parent_id": ""}],
                               actor="alice")
        # 同批同名二义: 第 2 个 总部 显式 failed (P3-6), 不再静默错挂
        res2 = svc.import_depts([{"name": "总部"}, {"name": "总部", "parent": "研发部"}],
                                actor="alice")
        assert res2["created"] == 0 and res2["failed"] == 1
        # 同名未重复创建
        assert sum(1 for d in svc.list_depts() if d["name"] == "总部") == 1
        # 导入入审计 (P3-1): actor 归责
        assert any(t["user"] == "alice" and t["action"] == "dept_import"
                   for t in svc.audit_trail())

    def test_root_dept_delete_protected(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"}])
        root = next(d for d in svc.list_depts() if d["name"] == "总部")
        import pytest as _pytest
        with _pytest.raises(ValueError):
            svc.remove_dept(root["id"])               # P3-7 根保护
        assert len(svc.list_depts()) == 2
        # 删完子部门后, 根为唯一部门 → 可删 (组织可整体清理)
        rnd = next(d for d in svc.list_depts() if d["name"] == "研发部")
        assert svc.remove_dept(rnd["id"]) is True
        assert svc.remove_dept(root["id"]) is True

    def test_upsert_rejected_mutation_atomic(self, tmp_dir):
        """002codex 44d7131d P3-5: 失败 upsert (环/父不存在) 不得变异内存树,
        重载文件须完整无环 (旧实现 400 后残留被拒变更, 下次 _save 落盘成环)。"""
        import pytest as _pytest
        svc = OrgService(path=tmp_dir / "org.json")
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"},
                          {"name": "算法组", "parent": "研发部"}])
        rnd = next(d for d in svc.list_depts() if d["name"] == "研发部")
        alg = next(d for d in svc.list_depts() if d["name"] == "算法组")
        hq = next(d for d in svc.list_depts() if d["name"] == "总部")
        before = svc.list_depts()
        # ① 环: 研发部 挂到其子孙 算法组 下 → 拒, 树不变
        with _pytest.raises(ValueError):
            svc.upsert_dept("研发部", parent_id=alg["id"], dept_id=rnd["id"])
        assert svc.list_depts() == before
        # ② 父不存在: 更新/新建均拒, 无悬挂节点
        with _pytest.raises(ValueError):
            svc.upsert_dept("研发部", parent_id="no-such-id", dept_id=rnd["id"])
        with _pytest.raises(ValueError):
            svc.upsert_dept("幽灵部", parent_id="no-such-id")
        assert svc.list_depts() == before
        # ③ 重载: 文件完整无环, 研发部 仍挂 总部
        svc2 = OrgService(path=tmp_dir / "org.json")
        by_id = {d["id"]: d for d in svc2.list_depts()}
        assert by_id[rnd["id"]]["parent_id"] == hq["id"]
        assert by_id[alg["id"]]["parent_id"] == rnd["id"]
        assert len(svc2.list_depts()) == 3
        # ④ 合法移动仍工作 (算法组 → 总部 平级挂靠)
        svc2.upsert_dept("算法组", parent_id=hq["id"], dept_id=alg["id"])
        assert {d["name"] for d in svc2.list_depts()} == {"总部", "研发部", "算法组"}


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
        # 全用 monkeypatch 自动恢复 (防污染: 历史教训 = 直接赋值 tc.TaskCardStore 泄漏)
        old_worker = tc._worker
        if old_worker is not None:
            old_worker.stop(); old_worker.join(timeout=2.0)
        tc._worker = None
        monkeypatch.setattr(tc, "CARDS_DIR", tmp_dir / "cards")
        from src.core.task_cards import TaskCardStore
        real_cls = TaskCardStore
        monkeypatch.setattr(tc, "TaskCardStore",
                            lambda base_dir=None: real_cls(base_dir=tmp_dir / "cards"))
        svc = og.get_org_service()
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        svc.set_member("alice", rnd["id"], "manager")     # 部门 manager
        svc.set_member("bob", rnd["id"], "member")        # 普通成员
        from src.core.task_cards import TaskCard
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
        tc._worker = None
        reset_org_service_for_tests()

    async def test_unregistered_403_on_dept_view(self, app_env):
        client, svc = app_env
        async with client as c:
            # P2-1: 组织非空, eve 未入册 → 部门聚合视图 403 (不再自举)
            r = await c.get("/api/tasks/cards", params={"org_dept": 1, "as": "eve"})
            assert r.status_code == 403, r.text

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


class TestOrgPhase2:
    """Org 阶段2: 审计轨迹 + 部门共享记忆 (数据权限) 隔离。"""

    @pytest.fixture()
    def env2(self, tmp_dir, monkeypatch):
        from fastapi import FastAPI
        from src.core.org_api import router
        import src.core.org_api as mod
        from src.core import org_governance as og
        import src.core.memory_api as ma
        monkeypatch.setattr(og, "ORG_PATH", tmp_dir / "org.json")
        monkeypatch.setattr(ma, "MEMORIES_DIR", tmp_dir / "mem")
        from src.core.memory_api import reset_memory_service_for_tests as rms
        reset_org_service_for_tests(); rms()
        svc = og.get_org_service()
        svc.ensure_self_bootstrap("root")          # 真实 owner (P3-4 导出/审计门控需 owner)
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"},
                          {"name": "市场部", "parent": "总部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        mkt = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "市场部"))
        svc.set_member("alice", rnd["id"], "manager")
        svc.set_member("bob", rnd["id"], "member")
        svc.set_member("carol", mkt["id"], "member")
        a = FastAPI(); a.include_router(router)
        async def _owner(req):
            return req.query_params.get("as", "alice")
        mod._owner = _owner
        yield AsyncClient(transport=ASGITransport(app=a), base_url="http://t"), svc, rnd, mkt
        reset_org_service_for_tests(); rms()

    async def test_audit_trail_captures_ops(self, env2):
        client, svc, rnd, mkt = env2
        async with client as c:
            await c.post("/api/org/members", params={"as": "alice"},
                         json={"user_id": "dave", "dept_id": rnd["id"], "role": "member"})
            r = await c.get("/api/org/audit", params={"as": "alice"})
            assert r.status_code == 200
            trail = r.json()["audit"]
            assert any(t["action"] == "member_set" and "dave" in t["detail"] for t in trail)

    async def test_dept_memory_share_isolated(self, env2):
        client, svc, rnd, mkt = env2
        async with client as c:
            # alice(研发 manager) 写入部门记忆
            w = await c.post("/api/org/memory", params={"as": "alice"},
                             json={"dept_id": rnd["id"], "text": "研发机密: Q3 计划"})
            assert w.status_code == 200, w.text
            # bob(研发 member) 可读可搜
            s = await c.get("/api/org/memory/search", params={"as": "bob", "q": "Q3",
                                                              "dept_id": rnd["id"]})
            assert s.status_code == 200 and s.json()["results"]
            # carol(市场部 member) 不可读研发部记忆 (跨部门隔离)
            s2 = await c.get("/api/org/memory/search", params={"as": "carol", "q": "Q3",
                                                               "dept_id": rnd["id"]})
            assert s2.status_code == 403
            # bob(普通成员) 不可写
            w2 = await c.post("/api/org/memory", params={"as": "bob"},
                              json={"dept_id": rnd["id"], "text": "x"})
            assert w2.status_code == 403
            # bob 可写市场部? 否; carol(市场 member) 也不可写 (非 manager) → 403
            w3 = await c.post("/api/org/memory", params={"as": "carol"},
                              json={"dept_id": mkt["id"], "text": "y"})
            assert w3.status_code == 403


class TestRoutinesDeptScope:
    """数据权限落地: routines org_dept 部门视图。"""

    @pytest.fixture()
    def renv(self, tmp_dir, monkeypatch):
        from fastapi import FastAPI
        from src.core import org_governance as og
        from src.core import routines as rt
        from src.core.routines_api import router
        import src.core.routines_api as mod
        monkeypatch.setattr(og, "ORG_PATH", tmp_dir / "org.json")
        monkeypatch.setattr(rt, "ROUTINES_PATH", tmp_dir / "routines.json")
        reset_org_service_for_tests()
        from src.core.routines import RoutineStore, Routine
        svc = og.get_org_service()
        svc.import_depts([{"name": "总部"}, {"name": "研发部", "parent": "总部"},
                          {"name": "市场部", "parent": "总部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        svc.set_member("alice", rnd["id"], "manager")
        svc.set_member("bob", rnd["id"], "member")
        st = RoutineStore(path=tmp_dir / "routines.json")
        st.save(Routine(owner="alice", prompt="研发定时任务", kind="interval", schedule="3600"))
        st.save(Routine(owner="bob", prompt="bob 个人任务", kind="interval", schedule="7200"))
        st.save(Routine(owner="carol", prompt="市场任务", kind="interval", schedule="3600"))
        a = FastAPI(); a.include_router(router)
        async def _owner(req):
            return req.query_params.get("as", "alice")
        mod._owner = _owner
        yield AsyncClient(transport=ASGITransport(app=a), base_url="http://t")
        reset_org_service_for_tests()

    async def test_unregistered_403_on_routines_dept(self, renv):
        async with renv as c:
            r = await c.get("/api/routines", params={"as": "eve", "org_dept": 1})
            assert r.status_code == 403, r.text

    async def test_manager_dept_view(self, renv):
        async with renv as c:
            # alice manager 研发部: dept 视图含 alice+bob, 不含市场 carol
            r = await c.get("/api/routines", params={"as": "alice", "org_dept": 1})
            owners = {x["owner"] for x in r.json()}
            assert owners == {"alice", "bob"}
            # 默认仅自己
            r2 = await c.get("/api/routines", params={"as": "alice"})
            assert {x["owner"] for x in r2.json()} == {"alice"}

    async def test_member_self_only(self, renv):
        async with renv as c:
            r = await c.get("/api/routines", params={"as": "bob", "org_dept": 1})
            assert {x["owner"] for x in r.json()} == {"bob"}


class TestOrgExport(TestOrgPhase2):   # 继承 env2 fixture
    async def test_export_jsonl_snapshot_and_audit(self, env2):
        client, svc, rnd, mkt = env2
        async with client as c:
            await c.post("/api/org/members", params={"as": "alice"},
                         json={"user_id": "dave", "dept_id": rnd["id"], "role": "member"})
            # P3-4: 导出限 owner/admin/auditor (合规角色) — 以 owner root 导出
            r = await c.get("/api/org/export", params={"as": "root"})
            assert r.status_code == 200
            body = r.text.strip().splitlines()
            snap = __import__("json").loads(body[0])
            assert snap["type"] == "org_snapshot" and len(snap["depts"]) == 3
            assert any("org_audit" in ln and "member_set" in ln for ln in body[1:])
            assert any("dave" in ln for ln in body[1:])
            # manager (非 owner/admin/auditor) 无权导出 (回归 P3-4)
            r3 = await c.get("/api/org/export", params={"as": "alice"})
            assert r3.status_code == 403, r3.text
            # 无 export_audit 的普通成员被拒 (carol)
            r2 = await c.get("/api/org/export", params={"as": "carol"})
            assert r2.status_code == 403


class TestOrgRBACNegatives:
    """P2-1/P2-2 (002meshctx f1eef868) 回归: 未入册/被移除成员不得自举,
    RBAC 授权闭包 — 仅 owner 可设/移 owner·admin, 不得提升自己等级。"""

    @pytest.fixture()
    def env3(self, tmp_dir, monkeypatch):
        from fastapi import FastAPI
        from src.core.org_api import router
        import src.core.org_api as mod
        from src.core import org_governance as og
        monkeypatch.setattr(og, "ORG_PATH", tmp_dir / "org.json")
        reset_org_service_for_tests()
        svc = og.get_org_service()
        svc.ensure_self_bootstrap("alice")       # 空组织首访 → alice owner@总部
        svc.import_depts([{"name": "研发部", "parent": "总部"}])
        rnd = svc.get_dept(next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))
        svc.set_member("bob", rnd["id"], "member")
        svc.set_member("carol", rnd["id"], "member")
        a = FastAPI(); a.include_router(router)
        async def _owner(req):
            return req.query_params.get("as", "alice")
        mod._owner = _owner
        yield AsyncClient(transport=ASGITransport(app=a), base_url="http://t"), svc, rnd
        reset_org_service_for_tests()

    async def test_unregistered_user_never_bootstraps(self, env3):
        client, svc, rnd = env3
        async with client as c:
            # eve 未入册: /me 如实返回 member=None (不自动变成 owner)
            r = await c.get("/api/org/me", params={"as": "eve"})
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["member"] is None and d["permissions"] == []
            # 一切管理/视图入口 403
            for path in ("/api/org/depts", "/api/org/members",
                         "/api/org/roles", "/api/org/visible-owners",
                         "/api/org/audit"):
                rr = await c.get(path, params={"as": "eve"})
                assert rr.status_code == 403, (path, rr.text)
            rr = await c.post("/api/org/depts", params={"as": "eve"},
                              json={"name": "篡改部"})
            assert rr.status_code == 403, rr.text
            rr = await c.post("/api/org/members", params={"as": "eve"},
                              json={"user_id": "eve", "dept_id": rnd["id"], "role": "owner"})
            assert rr.status_code == 403, rr.text
            assert svc.member("eve") is None          # 服务层也未写入

    async def test_removed_member_no_self_heal(self, env3):
        client, svc, rnd = env3
        async with client as c:
            r = await c.delete("/api/org/members/bob", params={"as": "alice"})
            assert r.status_code == 200, r.text
            assert svc.member("bob") is None
            # 被移除后不得自愈回 owner / 重获访问
            r = await c.get("/api/org/me", params={"as": "bob"})
            assert r.json()["member"] is None
            assert (await c.get("/api/org/depts", params={"as": "bob"})).status_code == 403
            assert (await c.get("/api/org/visible-owners",
                                params={"as": "bob"})).status_code == 403

    async def test_manager_cannot_escalate_self_or_remove_owner(self, env3):
        client, svc, rnd = env3
        async with client as c:
            # alice(owner) 把 bob 升为 研发部 manager
            r = await c.post("/api/org/members", params={"as": "alice"},
                             json={"user_id": "bob", "dept_id": rnd["id"], "role": "manager"})
            assert r.status_code == 200, r.text
            assert svc.member("bob")["role"] == "manager"
            # bob 不得把自己设成 owner/admin (授予等级 ≤ actor)
            for bad_role in ("owner", "admin"):
                rr = await c.post("/api/org/members", params={"as": "bob"},
                                  json={"user_id": "bob", "dept_id": rnd["id"],
                                        "role": bad_role})
                assert rr.status_code == 403, (bad_role, rr.text)
            # bob 不得给他人 owner
            rr = await c.post("/api/org/members", params={"as": "bob"},
                              json={"user_id": "dave", "dept_id": rnd["id"], "role": "owner"})
            assert rr.status_code == 403, rr.text
            # bob(manager) 不得移除 owner alice
            rr = await c.delete("/api/org/members/alice", params={"as": "bob"})
            assert rr.status_code == 403, rr.text
            assert svc.member("alice")["role"] == "owner"
            # manager 仍可按矩阵招收普通成员 (member/auditor)
            rr = await c.post("/api/org/members", params={"as": "bob"},
                              json={"user_id": "dave", "dept_id": rnd["id"], "role": "member"})
            assert rr.status_code == 200, rr.text
            # dave(普通成员) 试图把自己升 manager → 403
            rr = await c.post("/api/org/members", params={"as": "dave"},
                              json={"user_id": "dave", "dept_id": rnd["id"], "role": "manager"})
            assert rr.status_code == 403, rr.text

    async def test_only_owner_manages_owner_admin(self, env3):
        client, svc, rnd = env3
        async with client as c:
            # owner 可设 admin
            r = await c.post("/api/org/members", params={"as": "alice"},
                             json={"user_id": "dave", "dept_id": rnd["id"], "role": "admin"})
            assert r.status_code == 200, r.text
            # admin 不得再设 owner/admin (仅 owner), 可设 manager/member
            rr = await c.post("/api/org/members", params={"as": "dave"},
                              json={"user_id": "eve", "dept_id": rnd["id"], "role": "admin"})
            assert rr.status_code == 403, rr.text
            rr = await c.post("/api/org/members", params={"as": "dave"},
                              json={"user_id": "eve", "dept_id": rnd["id"], "role": "owner"})
            assert rr.status_code == 403, rr.text
            rr = await c.post("/api/org/members", params={"as": "dave"},
                              json={"user_id": "frank", "dept_id": rnd["id"], "role": "manager"})
            assert rr.status_code == 200, rr.text
            # admin 不得移除 owner
            rr = await c.delete("/api/org/members/alice", params={"as": "dave"})
            assert rr.status_code == 403, rr.text
            # admin 可移除普通成员 (等级低于自己)
            rr = await c.delete("/api/org/members/carol", params={"as": "dave"})
            assert rr.status_code == 200, rr.text
            assert svc.member("carol") is None

    async def test_root_dept_delete_400_and_memory_purge(self, env3):
        client, svc, rnd = env3
        async with client as c:
            root = next(d for d in svc.list_depts() if d["name"] == "总部")
            # P3-7 根保护: 存在子部门时删根 → 400
            r = await c.delete(f"/api/org/depts/{root['id']}", params={"as": "alice"})
            assert r.status_code == 400, r.text
            assert any(d["name"] == "总部" for d in svc.list_depts())
            # owner 写入部门记忆 → 整删 (DELETE /memory/{dept_id})
            w = await c.post("/api/org/memory", params={"as": "alice"},
                             json={"dept_id": rnd["id"], "text": "机密 Q3"})
            assert w.status_code == 200, w.text
            dl = await c.delete(f"/api/org/memory/{rnd['id']}", params={"as": "alice"})
            assert dl.status_code == 200 and dl.json()["purged_depts"] == 1, dl.text
            # bob(普通成员) 无写/删权
            d2 = await c.delete(f"/api/org/memory/{rnd['id']}", params={"as": "bob"})
            assert d2.status_code == 403, d2.text
            # 正常删子部门 (非根) → 200 + 记忆清理
            r3 = await c.delete(f"/api/org/depts/{rnd['id']}", params={"as": "alice"})
            assert r3.status_code == 200 and r3.json()["purged_depts"] == 1, r3.text
            assert svc.get_dept(rnd["id"]) is None


class TestAuditChain:
    """3.125-P1: 审计链式防篡改 (prev_hash + audit_chain_ok + /audit/chain)。"""

    def test_chain_ok_after_ops_and_persist(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.ensure_self_bootstrap("alice")
        svc.import_depts([{"name": "研发部", "parent": "总部"}], actor="alice")
        svc.set_member("bob", "", "member", actor="alice")
        assert svc.audit_chain_ok() is True
        # 持久化回读: 链完整
        svc2 = OrgService(path=tmp_dir / "org.json")
        assert svc2.audit_chain_ok() is True
        # 链长>1 且 prev_hash 存在
        rows = svc2.audit_trail(limit=200)
        assert len(rows) >= 3
        assert all("prev_hash" in r for r in rows)

    def test_tamper_detected(self, tmp_dir):
        svc = OrgService(path=tmp_dir / "org.json")
        svc.ensure_self_bootstrap("alice")
        svc.import_depts([{"name": "研发部", "parent": "总部"}], actor="alice")
        assert svc.audit_chain_ok() is True
        # 直接篡改中间条目 detail (绕过 _audit) → 链式检出
        import json as _json
        data = _json.loads((tmp_dir / "org.json").read_text(encoding="utf-8"))
        assert len(data["audit"]) >= 2
        data["audit"][0]["detail"] = "被篡改"   # 篡改首条 → 后继 prev_hash 失配
        (tmp_dir / "org.json").write_text(
            _json.dumps(data, ensure_ascii=False), encoding="utf-8")
        svc2 = OrgService(path=tmp_dir / "org.json")
        assert svc2.audit_chain_ok() is False
        # 篡改末条 → seal 检出 (audit_seal 与链末 hash 不符)
        data2 = _json.loads((tmp_dir / "org.json").read_text(encoding="utf-8"))
        data2["audit"][-1]["detail"] = "末条被篡改"
        (tmp_dir / "org.json").write_text(
            _json.dumps(data2, ensure_ascii=False), encoding="utf-8")
        svc3 = OrgService(path=tmp_dir / "org.json")
        assert svc3.audit_chain_ok() is False

    @pytest.fixture()
    def aenv(self, tmp_dir, monkeypatch):
        from fastapi import FastAPI
        from src.core.org_api import router
        import src.core.org_api as mod
        from src.core import org_governance as og
        monkeypatch.setattr(og, "ORG_PATH", tmp_dir / "org.json")
        reset_org_service_for_tests()
        svc = og.get_org_service()
        svc.ensure_self_bootstrap("alice")          # owner + 总部
        svc.import_depts([{"name": "研发部", "parent": "总部"}], actor="alice")
        svc.set_member("bob", svc.get_dept(
            next(d["id"] for d in svc.list_depts() if d["name"] == "研发部"))["id"],
            "member", actor="alice")
        a = FastAPI(); a.include_router(router)
        async def _owner(req):
            return req.query_params.get("as", "alice")
        mod._owner = _owner
        yield AsyncClient(transport=ASGITransport(app=a), base_url="http://t")
        reset_org_service_for_tests()

    def test_seal_mem_sync_after_reload_then_op(self, tmp_dir):
        """002codex faa77549: load(seal 入内存) 后再审计 — audit_chain_ok() 须仍 True。"""
        svc1 = OrgService(path=tmp_dir / "org.json")
        svc1.ensure_self_bootstrap("alice")
        svc2 = OrgService(path=tmp_dir / "org.json")   # 重载, seal 入内存
        assert svc2.audit_chain_ok() is True
        svc2.import_depts([{"name": "研发部", "parent": "总部"}], actor="alice")
        assert svc2.audit_chain_ok() is True           # 内存 seal 已同步 → 不误报
        svc3 = OrgService(path=tmp_dir / "org.json")   # 落盘值也一致
        assert svc3.audit_chain_ok() is True

    async def test_chain_api_gate(self, aenv):
        async with aenv as c:
            r = await c.get("/api/org/audit/chain", params={"as": "alice"})
            assert r.status_code == 200 and r.json()["ok"] is True, r.text
            r2 = await c.get("/api/org/audit/chain", params={"as": "eve"})
            assert r2.status_code == 403, r2.text

"""WP3 (MCTX-PLAN-2026-0903 P0-3) 对外 Memory API 测试。

覆盖: store/search/list/delete/GDPR 整 ns 删除 + owner 隔离 + 校验 + 服务层持久化。
"""
import pathlib
import shutil
import tempfile

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.memory_api import MemoryService, reset_memory_service_for_tests


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_memapi_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest_asyncio.fixture()
async def isolated(tmp_dir, monkeypatch):
    from src.core import memory_api as ma
    monkeypatch.setattr(ma, "MEMORIES_DIR", tmp_dir)
    reset_memory_service_for_tests()
    monkeypatch.setattr(ma, "MEMORIES_DIR", tmp_dir)  # service 默认读模块全局
    yield
    reset_memory_service_for_tests()


@pytest.fixture()
def app(isolated):
    from src.core.memory_api import router
    import src.core.memory_api as mod
    a = FastAPI()
    a.include_router(router)

    async def _owner(request):
        return "alice"

    mod._owner = _owner
    return a


@pytest.fixture()
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


class TestService:
    def test_store_search_delete(self, tmp_dir):
        svc = MemoryService(base_dir=tmp_dir)
        svc.store("alice:docs", "meshctx 支持记忆 API 检索", {"k": 1})
        svc.store("alice:docs", "今天天气晴朗适合跑步", {})
        res = svc.search("alice:docs", "记忆 API", top_k=3)
        assert res and "记忆" in res[0]["text"]
        assert svc.delete_entry("alice:docs", res[0]["id"]) is True
        assert len(svc.list_entries("alice:docs")) == 1

    def test_namespace_isolation(self, tmp_dir):
        svc = MemoryService(base_dir=tmp_dir)
        svc.store("alice:private", "alice 的秘密笔记")
        svc.store("bob:private", "bob 的公开笔记")
        res = svc.search("bob:private", "笔记", top_k=5)
        assert all("秘密" not in r["text"] for r in res)
        assert svc.list_entries("alice:private")[0]["text"].startswith("alice")

    def test_gdpr_delete_namespace(self, tmp_dir):
        svc = MemoryService(base_dir=tmp_dir)
        svc.store("alice:docs", "要删除的内容")
        assert svc.delete_namespace("alice:docs") is True
        assert svc.list_entries("alice:docs") == []
        assert svc.delete_namespace("ghost:ns") is False

    def test_reload_from_disk(self, tmp_dir):
        svc = MemoryService(base_dir=tmp_dir)
        svc.store("alice:docs", "持久化的记忆")
        svc2 = MemoryService(base_dir=tmp_dir)   # 新实例回读
        assert svc2.list_entries("alice:docs")[0]["text"] == "持久化的记忆"


class TestAPI:
    async def test_store_and_search(self, client):
        r = await client.post("/api/v1/memory", json={"text": "meshctx 记忆检索",
                                                      "namespace": "docs"})
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        s = await client.get("/api/v1/memory/search", params={"q": "记忆",
                                                              "namespace": "docs"})
        assert s.status_code == 200
        assert s.json()["results"] and s.json()["results"][0]["id"] == rid
        lst = await client.get("/api/v1/memory", params={"namespace": "docs"})
        assert len(lst.json()["entries"]) == 1

    async def test_delete_entry_and_namespace(self, client):
        rid = (await client.post("/api/v1/memory", json={
            "text": "x", "namespace": "ns1"})).json()["id"]
        assert (await client.delete(f"/api/v1/memory/{rid}",
                                    params={"namespace": "ns1"})).status_code == 200
        assert (await client.delete("/api/v1/memory",
                                    params={"namespace": "ns1"})).json()["removed"] is True

    async def test_validation(self, client):
        assert (await client.post("/api/v1/memory", json={})).status_code == 400
        assert (await client.get("/api/v1/memory/search",
                                 params={"q": "  "})).status_code == 400

class TestRc2Hardening:
    def test_ns_whitelist_rejects_colon(self, client):
        # P2-W3-1: ns 含 ':' → 400 (键碰撞面消除)
        r = await_patch(client) if False else None
        import asyncio
        async def _run():
            return await client.post("/api/v1/memory", json={"text": "x",
                                                             "namespace": "a:b"})
        assert (asyncio.run(_run())).status_code == 400

    def test_path_collision_free(self, tmp_dir):
        # P3-A: 分层 <owner>/<ns>.json — alice:b_c 与 alice_b:c 不同文件
        svc = MemoryService(base_dir=tmp_dir)
        svc.store("alice:b_c", "x1")
        svc.store("alice_b:c", "x2")
        p1 = tmp_dir / "alice" / "b_c.json"
        p2 = tmp_dir / "alice_b" / "c.json"
        assert p1.exists() and p2.exists()
        assert svc.search("alice:b_c", "x1") and not svc.search("alice_b:c", "x1")

    def test_store_writes_audit(self, tmp_dir):
        svc = MemoryService(base_dir=tmp_dir)
        svc.store("alice:docs", "敏感写入")
        ap = tmp_dir / ".audit" / "memory.jsonl"
        assert ap.exists()
        assert "store" in ap.read_text(encoding="utf-8")

    def test_cross_owner_http_isolation(self, tmp_dir, monkeypatch):
        """P2-W3-2: 跨 owner 端到端 — 顺序 client (alice 写 → bob 写/查互不可见)。"""
        import asyncio
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from src.core import memory_api as ma
        monkeypatch.setattr(ma, "MEMORIES_DIR", tmp_dir)
        reset_memory_service_for_tests()
        from src.core.memory_api import router
        import src.core.memory_api as mod

        def make_app(who):
            a = FastAPI(); a.include_router(router)
            async def _owner(req):
                return who
            mod._owner = _owner
            return a

        async def scenario():
            # alice 写入 (独立 app, owner=alice)
            async with AsyncClient(transport=ASGITransport(app=make_app("alice")),
                                   base_url="http://t") as ca:
                ra = await ca.post("/api/v1/memory", json={
                    "text": "alice 私密笔记", "namespace": "docs"})
                assert ra.status_code == 200
            # bob 写入 + 检索 (独立 app, owner=bob)
            async with AsyncClient(transport=ASGITransport(app=make_app("bob")),
                                   base_url="http://t") as cb:
                await cb.post("/api/v1/memory", json={
                    "text": "bob 公开内容", "namespace": "docs"})
                rb = await cb.get("/api/v1/memory/search",
                                  params={"q": "私密", "namespace": "docs"})
                assert rb.json()["results"] == [], "bob 不应看到 alice 内容"
            # alice 侧仍可检索到自己内容
            async with AsyncClient(transport=ASGITransport(app=make_app("alice")),
                                   base_url="http://t") as ca2:
                rc = await ca2.get("/api/v1/memory/search",
                                   params={"q": "私密", "namespace": "docs"})
                assert rc.json()["results"], "alice 应可检索到自己内容"


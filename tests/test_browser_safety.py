"""
BrowserSafetyGate 单测 — 授权状态机 / 三级分级 / 黑名单 / confirm队列并发 / 审计
全部用 mock 工具, 不启动真实浏览器 (pytest-asyncio auto 模式)
"""
import time

import pytest

from src.core.browser_safety import (
    BrowserSafetyGate,
    DANGEROUS_URL_PATTERNS,
    LEVEL_AUTO,
    LEVEL_BLOCKED,
    LEVEL_CONFIRM,
    get_browser_gate,
    reset_browser_gate,
)


class MockTool:
    """模拟 BrowserTool, 记录调用"""
    def __init__(self):
        self.calls = []
        self.started = False

    async def _ensure_browser(self):
        self.started = True

    async def close(self):
        self.started = False

    async def navigate(self, url):
        self.calls.append(("navigate", url))
        return {"title": f"T:{url}"}

    async def snapshot(self, full=False):
        self.calls.append(("snapshot", full))
        return "SNAPSHOT_TEXT"

    async def click(self, ref):
        self.calls.append(("click", ref))
        return {"ok": True}

    async def type_text(self, ref, text):
        self.calls.append(("type", ref, text))
        return {"ok": True}

    async def press_key(self, key):
        self.calls.append(("press", key))
        return {"ok": True}

    async def evaluate(self, js):
        self.calls.append(("evaluate", js))
        return {"result": "EVAL"}

    async def screenshot(self):
        self.calls.append(("screenshot",))
        return b"PNG_BYTES"

    async def get_console(self):
        self.calls.append(("console",))
        return ["log1"]


@pytest.fixture
def gate():
    return BrowserSafetyGate(tool=MockTool())


@pytest.fixture
async def authed(gate):
    await gate.authorize()
    return gate


# ── 授权状态机 ──────────────────────────────────────────
class TestAuthStateMachine:
    async def test_default_denied(self, gate):
        assert gate.state == "idle"

    async def test_authorize(self, gate):
        r = await gate.authorize()
        assert r["ok"] is True
        assert gate.state == "authorized"
        assert gate._tool.started is True

    async def test_revoke(self, authed):
        r = await authed.revoke()
        assert r["ok"] is True
        assert authed.state != "authorized"
        assert authed._tool.started is False

    async def test_timeout_auto_reset(self, gate):
        gate._state = "authorized"
        gate._last_activity = time.time() - 9999
        assert gate.state == "idle"

    async def test_no_expiry_within_window(self, gate):
        gate._state = "authorized"
        gate._last_activity = time.time() - 60
        assert gate.state == "authorized"


# ── 三级分级 ────────────────────────────────────────────
class TestClassify:
    async def test_auto_read(self, authed):
        # 先完成首次操作(走 confirm), 之后只读 navigate 归 auto
        r = await authed.execute({"type": "navigate", "url": "https://a.com"})
        await authed.confirm(r["action_id"], True)
        assert authed._classify({"type": "navigate", "url": "https://a.com"})[0] == LEVEL_AUTO

    async def test_confirm_write(self, authed):
        for t in ("click", "type", "press_key", "evaluate", "screenshot"):
            assert authed._classify({"type": t})[0] == LEVEL_CONFIRM

    async def test_blocked_danger_url(self, authed):
        for u in ("https://bank.com/payment", "https://x.com/checkout", "https://w.com/wallet"):
            assert authed._classify({"type": "navigate", "url": u})[0] == LEVEL_BLOCKED

    async def test_first_action_confirm(self, gate):
        # 未做过任何操作 → 只读也 confirm
        gate._state = "authorized"
        assert gate._classify({"type": "navigate", "url": "https://a.com"})[0] == LEVEL_CONFIRM

    async def test_unknown_type_confirm(self, authed):
        assert authed._classify({"type": "hack"})[0] == LEVEL_CONFIRM


# ── 执行与 confirm 队列 ─────────────────────────────────
class TestExecute:
    async def test_unauthorized_blocked(self, gate):
        r = await gate.execute({"type": "navigate", "url": "https://a.com"})
        assert r["ok"] is False
        assert r["code"] == 403
        assert "未授权" in r["error"]

    async def test_danger_url_blocked_even_authed(self, authed):
        r = await authed.execute({"type": "navigate", "url": "https://bank.com/payment"})
        assert r["ok"] is False
        assert r["code"] == 403
        assert "拦截" in r["error"]

    async def test_confirm_queued_and_approved(self, authed):
        r = await authed.execute({"type": "click", "ref": "@e1"})
        assert r["need_confirm"] is True
        aid = r["action_id"]
        assert aid in authed._pending
        r2 = await authed.confirm(aid, True)
        assert r2["ok"] is True
        assert aid not in authed._pending
        assert ("click", "@e1") in authed._tool.calls

    async def test_confirm_denied(self, authed):
        r = await authed.execute({"type": "click", "ref": "@e1"})
        aid = r["action_id"]
        r2 = await authed.confirm(aid, False)
        assert r2["ok"] is False
        assert r2["code"] == 403
        assert ("click", "@e1") not in authed._tool.calls

    async def test_confirm_invalid_id(self, authed):
        r = await authed.confirm("no_such_id", True)
        assert r["ok"] is False

    async def test_auto_execute_after_first(self, authed):
        # 首次 navigate 需 confirm
        r = await authed.execute({"type": "navigate", "url": "https://a.com"})
        assert r["need_confirm"] is True
        await authed.confirm(r["action_id"], True)
        # 之后只读 navigate auto 直接执行
        r2 = await authed.execute({"type": "navigate", "url": "https://b.com"})
        assert r2["ok"] is True

    async def test_confirm_concurrent_safety(self, authed):
        """并发提交多个 confirm 项, action_id 互不冲突"""
        results = await asyncio_gather_auto(*[
            authed.execute({"type": "click", "ref": f"@e{i}"}) for i in range(20)
        ])
        ids = [r["action_id"] for r in results if r.get("need_confirm")]
        assert len(ids) == 20
        assert len(set(ids)) == 20  # 无重复
        await asyncio_gather_auto(*[authed.confirm(aid, True) for aid in ids])
        assert len(authed._pending) == 0
        assert len([c for c in authed._tool.calls if c[0] == "click"]) == 20

    async def test_snapshot_str_normalized(self, authed):
        """snapshot 返回 str 也要规范化, 不能崩"""
        r = await authed.execute({"type": "snapshot"})
        # 首次操作需 confirm
        if r.get("need_confirm"):
            r = await authed.confirm(r["action_id"], True)
        assert r["ok"] is True
        assert "result" in r or "snapshot" in r


# ── 审计 ────────────────────────────────────────────────
class TestAudit:
    async def test_audit_tracks(self, authed):
        await authed.execute({"type": "navigate", "url": "https://a.com"})
        assert len(authed.audit_log()) >= 1

    async def test_blocked_audited(self, authed):
        await authed.execute({"type": "navigate", "url": "https://bank.com/payment"})
        assert authed.audit_log()[-1]["decision"] == "denied"

    async def test_session_lists_pending(self, authed):
        await authed.execute({"type": "click", "ref": "@e1"})
        s = authed.session()
        assert s["state"] == "authorized"
        assert len(s["pending_confirm"]) == 1


# ── 单例 ────────────────────────────────────────────────
class TestSingleton:
    async def test_singleton_shared(self):
        reset_browser_gate()
        g1 = await get_browser_gate()
        g2 = await get_browser_gate()
        assert g1 is g2


# ── 黑名单完整性 ────────────────────────────────────────
class TestBlacklist:
    async def test_patterns_present(self):
        for p in ("payment", "checkout", "transfer", "delete_account", "wallet", "billing"):
            assert p in DANGEROUS_URL_PATTERNS


async def asyncio_gather_auto(*coros):
    """并发执行协程 (async 测试内直接 asyncio.gather)"""
    import asyncio
    return await asyncio.gather(*coros)

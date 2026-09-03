# -*- coding: utf-8 -*-
"""task_card_runner — T2 执行链测试 (fake client, 不依赖真实 LLM)"""
import json
import pathlib
import shutil
import tempfile

import pytest


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="meshctx_task_runner_")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


class FakeClient:
    """fake client — run_agent_loop 只把 client 当第一参数传递, 不发真实请求。
    这里通过 monkeypatch run_agent_loop 产事件。"""
    model_id = "fake:v1"


class TestNeedsApproval:
    def test_write_overwrite(self):
        from src.core.task_card_runner import _needs_approval
        assert _needs_approval("write_file", {"if_exists": "overwrite"}) is not None
        assert _needs_approval("write_file", {"if_exists": "rename"}) is None

    def test_remote(self):
        from src.core.task_card_runner import _needs_approval
        assert _needs_approval("remote_exec", {"cmd": "whoami"}) is not None
        assert _needs_approval("remote_write", {}) is not None

    def test_terminal_rm(self):
        from src.core.task_card_runner import _needs_approval
        assert _needs_approval("terminal", {"cmd": "rm -rf /tmp/x"}) is not None
        assert _needs_approval("terminal", {"cmd": "ls -la"}) is None

    def test_safe(self):
        from src.core.task_card_runner import _needs_approval
        assert _needs_approval("read_file", {"path": "/a"}) is None
        assert _needs_approval("web_search", {}) is None


class TestRunCard:
    def test_event_mapping(self, tmp_dir, monkeypatch):
        import asyncio
        from src.core.task_cards import TaskCard, TaskCardStore
        from src.core import task_card_runner as runner

        async def fake_loop(client, messages, **kw):
            yield {"type": "token", "text": "结果"}
            yield {"type": "reasoning", "text": "思考"}
            yield {"type": "tool_start", "name": "read_file", "args": {"path": "/x"}}
            yield {"type": "tool_result", "name": "read_file", "result": "file内容"}
            yield {"type": "final", "text": "完成"}
            yield {"type": "done"}

        monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)
        monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

        class FakeWorker:
            def __init__(self, store):
                self._store = store
                self._approval_futures = {}
                self._approval_by_card = {}
                self._approval_decided = set()
                self._cancel_lock = __import__("threading").Lock()
                self._approval_lock = __import__("threading").Lock()
            def register_approval(self, *a, **k):
                pass
            def save(self, c):
                self._store.save(c)

        async def scenario():
            store = TaskCardStore(base_dir=tmp_dir / "s")
            w = FakeWorker(store)
            card = TaskCard(owner="local", prompt="干点事")
            store.save(card)
            out = await runner.run_card(card, worker=w)
            assert out["result"] == "结果完成"
            got = store.load(card.id)
            kinds = [e["kind"] for e in got.timeline]
            assert "final" in kinds
            assert "tool_start" in kinds
            # token 聚合计数, 不落 timeline 全文 (P2 002codex)
            assert got.extra.get("token_count", 0) >= 1
            assert "token" not in kinds
            assert got.result == "结果完成"

        asyncio.run(scenario())

    def test_run_card_telemetry_spans(self, tmp_dir, monkeypatch):
        """WP1: run_card 包 span + 工具/错误事件带同一 trace 归因。"""
        import asyncio, json
        from src.core.task_cards import TaskCard, TaskCardStore
        from src.core import task_card_runner as runner
        from src.core import telemetry as tel

        store_tel = tel.reset_telemetry(str(tmp_dir / "tel.jsonl"))

        async def fake_loop(client, messages, **kw):
            yield {"type": "tool_start", "name": "read_file", "args": {"path": "/x"}}
            yield {"type": "tool_result", "name": "read_file", "result": "file内容"}
            yield {"type": "final", "text": "完成"}
            yield {"type": "done"}

        monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)
        monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

        class FakeWorker:
            def __init__(self, store):
                self._store = store
                self._approval_futures = {}
                self._approval_by_card = {}
                self._approval_decided = set()
                self._cancel_lock = __import__("threading").Lock()
                self._approval_lock = __import__("threading").Lock()
            def register_approval(self, *a, **k):
                pass
            def save(self, c):
                self._store.save(c)

        async def scenario():
            store = TaskCardStore(base_dir=tmp_dir / "s2")
            w = FakeWorker(store)
            card = TaskCard(owner="local", prompt="查文件")
            card.extra["trace_id"] = "aabbccddeeff0011"   # 卡级预置 trace (worker._run_one 语义)
            store.save(card)
            await runner.run_card(card, worker=w)
            evs = store_tel.events()
            spans = [e for e in evs if e["event_type"] == "span"]
            assert spans, "run_card 应产出 card.run span"
            assert all(e["trace_id"] == "aabbccddeeff0011" for e in spans)
            detail = json.loads(spans[-1]["detail"])
            assert detail.get("span") == "card.run"
            assert detail.get("status") == "ok"
            # 工具事件与 run_end 均归因同一卡 trace (Span 上下文自动继承)
            tools = [e for e in evs if e["event_type"] == "tool_call"]
            assert tools and all(e["trace_id"] == "aabbccddeeff0011" for e in tools)
            assert any(e["event_type"] == "run_end" and e["trace_id"] == "aabbccddeeff0011"
                       for e in evs)

        asyncio.run(scenario())

    def test_error_event(self, tmp_dir, monkeypatch):
        import asyncio
        from src.core.task_cards import TaskCard, TaskCardStore
        from src.core import task_card_runner as runner

        async def fake_loop(client, messages, **kw):
            yield {"type": "error", "text": "模型错误"}
            raise RuntimeError("连接断开")

        monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)
        monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

        class FakeWorker:
            def __init__(self, store):
                self._store = store
                self._approval_futures = {}
                self._approval_by_card = {}
                self._approval_decided = set()
                self._cancel_lock = __import__("threading").Lock()
                self._approval_lock = __import__("threading").Lock()
            def register_approval(self, *a, **k):
                pass
            def save(self, c):
                self._store.save(c)

        async def scenario():
            store = TaskCardStore(base_dir=tmp_dir / "s2")
            w = FakeWorker(store)
            card = TaskCard(owner="local", prompt="x")
            store.save(card)
            out = await runner.run_card(card, worker=w)
            assert out["error"] is not None
            got = store.load(card.id)
            assert got.error is not None

        asyncio.run(scenario())

    def test_cancel_via_interrupt(self, tmp_dir, monkeypatch):
        import asyncio
        from src.core.task_cards import TaskCard, TaskCardStore
        from src.core import task_card_runner as runner

        async def fake_loop(client, messages, **kw):
            # 模拟 worker cancel 置位后 interrupt_check 抛 InterruptSignal
            kw["interrupt_check"]()
            yield {"type": "interrupted", "note": "cancelled"}

        monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)
        monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

        class FakeWorker:
            def __init__(self, store):
                self._store = store
                self._approval_futures = {}
                self._approval_by_card = {}
                self._approval_decided = set()
                self._cancel_lock = __import__("threading").Lock()
                self._approval_lock = __import__("threading").Lock()
            def register_approval(self, *a, **k):
                pass
            def save(self, c):
                self._store.save(c)

        async def scenario():
            store = TaskCardStore(base_dir=tmp_dir / "s3")
            w = FakeWorker(store)
            card = TaskCard(owner="local", prompt="x")
            card.cancel_requested = True
            store.save(card)
            await runner.run_card(card, worker=w)
            got = store.load(card.id)
            kinds = [e["kind"] for e in got.timeline]
            assert "interrupted" in kinds

        asyncio.run(scenario())

    def test_approval_coordination(self, tmp_dir, monkeypatch):
        """危险动作 → register_approval 落盘 waiting_approval → decide → 继续。"""
        import asyncio
        from src.core.task_cards import TaskCard, TaskCardStore, CardStatus
        from src.core import task_card_runner as runner

        decided = {}

        async def fake_loop(client, messages, **kw):
            needs = kw["needs_approval"]
            waiter = kw["approval_waiter"]
            # 模拟 agent_loop: 命中危险规则 → 产 approval 事件
            req_id = "req1"
            yield {"type": "approval", "request_id": req_id,
                   "name": "terminal", "args": {"cmd": "rm -rf /tmp/x"}, "reason": "危险"}
            # run_card 处理事件时 register_approval; 等注册后 decide → waiter 恢复
            import asyncio
            from src.core.task_cards import get_card_worker
            w2 = get_card_worker()
            for _ in range(50):
                if req_id in w2._approval_futures:
                    break
                await asyncio.sleep(0.02)
            w2.decide_approval(req_id, "reject", "不要删")
            dec = await waiter(req_id)
            assert dec["action"] == "reject"
            decided["ok"] = True
            yield {"type": "final", "text": "已安全处理"}

        monkeypatch.setattr("src.agent_loop.run_agent_loop", fake_loop)
        monkeypatch.setattr(runner, "_resolve_client", lambda c: FakeClient())

        from src.core import task_cards as tc_mod
        # 隔离: 重建 worker 全局
        old = tc_mod._worker
        tc_mod._worker = None
        try:
            store = TaskCardStore(base_dir=tmp_dir / "s5")
            w = tc_mod.get_card_worker()
            w._store = store
            card = TaskCard(owner="local", prompt="del")
            store.save(card)
            asyncio.run(runner.run_card(card, worker=w))
            assert decided.get("ok")
        finally:
            tc_mod._worker = old

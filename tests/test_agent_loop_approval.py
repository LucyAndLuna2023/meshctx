"""agent_loop 删除/改动类工具审批测试 (2026-08-26 004meshctx)

用户要求: 内容的删除和改动要像 deepseek harness 一样征求用户意见 —
允许(agree) / 拒绝(reject) / 用户自定义处理(custom)。
本测试锁定 agent_loop 审批钩子行为。
"""
import asyncio
import pytest

from src.agent_loop import run_agent_loop


class _FakeClient:
    def __init__(self, script):
        self._script = script
        self.calls = 0

    def chat_stream(self, messages, **kw):
        fn = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return fn(messages)

    def chat(self, messages, **kw):
        return {"content": "兜底"}


def _tool_call(name, args):
    return [("__TOOLS__", [{"id": "1", "name": name, "arguments": args}], "")]


def _exec(name, args):
    return f"EXECUTED:{name}"


def _needs(name, args):
    """所有工具都需要审批 (测试用)"""
    return f"需要审批 {name}"


def _run(client, decisions=None, **kw):
    """decisions: {request_id: {"action":...}} 或单值; 按顺序消费"""
    queue = list(decisions or [])
    calls = []

    async def waiter(request_id):
        calls.append(request_id)
        if not queue:
            await asyncio.sleep(10)  # 超时场景
        return queue.pop(0) if queue else {"action": "reject"}

    async def go():
        evs = []
        async for ev in run_agent_loop(
            client, [{"role": "user", "content": "q"}],
            tools=[], exec_tool=_exec,
            max_rounds=0,
            needs_approval=_needs,
            approval_waiter=waiter,
            **kw,
        ):
            evs.append(ev)
        return evs, calls
    return asyncio.run(go())


def test_approval_agree_executes_tool():
    """允许(agree) → 工具正常执行, 有 tool_start 和真实 tool_result"""
    client = _FakeClient([
        lambda m: iter(_tool_call("write_file", {"path": "/tmp/a.txt",
                                                 "content": "x", "if_exists": "overwrite"})),
        lambda m: iter(["完成"]),
    ])
    evs, _ = _run(client, decisions=[{"action": "agree"}])
    approvals = [e for e in evs if e["type"] == "approval"]
    assert len(approvals) == 1 and approvals[0]["reason"] == "需要审批 write_file"
    starts = [e for e in evs if e["type"] == "tool_start"]
    assert len(starts) == 1 and starts[0]["name"] == "write_file"
    results = [e for e in evs if e["type"] == "tool_result"]
    assert any(r["result"] == "EXECUTED:write_file" for r in results)


def test_approval_reject_skips_tool():
    """拒绝(reject) → 工具不执行, 注入拒绝结果, 无 tool_start"""
    client = _FakeClient([
        lambda m: iter(_tool_call("write_file", {"path": "/tmp/a.txt", "content": "x",
                                                 "if_exists": "overwrite"})),
        lambda m: iter(["好，我不改"]),
    ])
    evs, _ = _run(client, decisions=[{"action": "reject"}])
    starts = [e for e in evs if e["type"] == "tool_start"]
    assert not starts, "拒绝后不应执行工具"
    results = [e for e in evs if e["type"] == "tool_result"]
    assert any("拒绝" in r["result"] for r in results)


def test_approval_custom_injects_user_text():
    """自定义处理(custom) → 工具不执行, 用户文本注入为结果"""
    client = _FakeClient([
        lambda m: iter(_tool_call("terminal", {"cmd": "rm -rf /tmp/x"})),
        lambda m: iter(["明白"]),
    ])
    evs, _ = _run(client, decisions=[{"action": "custom", "text": "只删除临时文件，保留目录"}])
    starts = [e for e in evs if e["type"] == "tool_start"]
    assert not starts, "自定义处理不应执行工具"
    results = [e for e in evs if e["type"] == "tool_result"]
    assert any("只删除临时文件" in r["result"] for r in results)


def test_approval_not_required_passes_through():
    """needs_approval 返回 None → 无审批事件, 直接执行"""
    client = _FakeClient([
        lambda m: iter(_tool_call("read_file", {"path": "/tmp/a.txt"})),
        lambda m: iter(["内容"]),
    ])
    async def go():
        evs = []
        async for ev in run_agent_loop(
            client, [{"role": "user", "content": "q"}],
            tools=[], exec_tool=_exec, max_rounds=0,
            needs_approval=lambda n, a: None,
            approval_waiter=lambda rid: {"action": "agree"},
        ):
            evs.append(ev)
        return evs
    evs = asyncio.run(go())
    assert not any(e["type"] == "approval" for e in evs)
    starts = [e for e in evs if e["type"] == "tool_start"]
    assert len(starts) == 1


def test_approval_timeout_rejects():
    """审批超时 → 自动拒绝, 工具不执行"""
    client = _FakeClient([
        lambda m: iter(_tool_call("write_file", {"path": "/tmp/a.txt", "content": "x",
                                                 "if_exists": "overwrite"})),
        lambda m: iter(["ok"]),
    ])
    evs, _ = _run(client, decisions=[], approval_timeout=0.2)
    starts = [e for e in evs if e["type"] == "tool_start"]
    assert not starts, "超时应拒绝执行"
    results = [e for e in evs if e["type"] == "tool_result"]
    assert any("审批超时" in r["result"] for r in results)

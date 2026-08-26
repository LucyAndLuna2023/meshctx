"""agent_loop 无固定轮次限制 + 推理流 (reasoning) 转发测试 (2026-08-26 004meshctx)

用户报告: 对话显示"第1/29轮搜索"总数不对 + 推理流显示内容不对。
修复: max_rounds=0 默认无限循环 (模型直接回复文本即结束, 墙钟兜底);
reasoning_content 独立 reasoning 事件 (不混入正文)。本测试锁定新行为。
"""
import asyncio
import pytest

from src.agent_loop import run_agent_loop


class _FakeClient:
    """按调用顺序回放脚本的假模型客户端。"""
    def __init__(self, script):
        self._script = script
        self.calls = 0

    def chat_stream(self, messages, **kw):
        fn = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return fn(messages)

    def chat(self, messages, **kw):
        return {"content": "兜底"}


def _exec(name, args):
    return "搜索结果: OK"


def _run(client, msgs, **kw):
    async def go():
        evs = []
        async for ev in run_agent_loop(client, msgs, tools=[], exec_tool=_exec, **kw):
            evs.append(ev)
        return evs
    return asyncio.run(go())


def test_no_round_limit_total_none():
    """默认 max_rounds=0: 无限循环, round 事件 total=None (不再显示假 /29)。"""
    client = _FakeClient([
        lambda m: iter([("__TOOLS__", [{"id": "1", "name": "web_search",
                                        "arguments": {"query": "x"}}], "")]),
        lambda m: iter(["你好！这是最终回答。"]),
    ])
    evs = _run(client, [{"role": "user", "content": "hi"}], max_rounds=0)
    rounds = [e for e in evs if e["type"] == "round"]
    assert len(rounds) == 2                       # 两轮: 工具轮 + 回复轮
    assert all(r["total"] is None for r in rounds)  # 无固定总数
    tokens = "".join(e["text"] for e in evs if e["type"] == "token")
    assert "最终回答" in tokens
    assert evs[-1]["type"] == "done"


def test_reasoning_event_forwarded():
    """reasoning_content 以独立 reasoning 事件产出, 不混入正文 token。"""
    client = _FakeClient([
        lambda m: iter([("__REASONING__", "先分析"), ("__REASONING__", "再回答"), "正文内容"]),
    ])
    evs = _run(client, [{"role": "user", "content": "q"}], max_rounds=0)
    reason = "".join(e["text"] for e in evs if e["type"] == "reasoning")
    assert reason == "先分析再回答"
    tokens = "".join(e["text"] for e in evs if e["type"] == "token")
    assert tokens == "正文内容"      # 推理不污染正文
    assert evs[-1]["type"] == "done"


def test_fixed_rounds_backward_compat():
    """max_rounds>0 固定模式保留: total=max_rounds-1, 最后一轮 deliver。"""
    client = _FakeClient([
        lambda m: iter([("__TOOLS__", [{"id": "1", "name": "web_search",
                                        "arguments": {"query": "x"}}], "")]),
        lambda m: iter(["最终"]),
    ])
    evs = _run(client, [{"role": "user", "content": "q"}], max_rounds=2)
    rounds = [e for e in evs if e["type"] == "round"]
    assert len(rounds) == 1               # 最后一轮 deliver 不 yield round (与旧行为一致)
    assert rounds[0]["total"] == 1        # 固定模式 total = max_rounds - 1
    assert any(e["type"] == "deliver" for e in evs)


def test_direct_reply_ends_immediately():
    """模型直接回复文本 → 立即结束, 无多余轮次。"""
    client = _FakeClient([
        lambda m: iter(["直接回答，不调用工具。"]),
    ])
    evs = _run(client, [{"role": "user", "content": "q"}], max_rounds=0)
    rounds = [e for e in evs if e["type"] == "round"]
    assert len(rounds) == 1               # 只 1 轮
    assert evs[-1]["type"] == "done"

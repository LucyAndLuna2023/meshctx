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


# ── v3.132.3: 搜索上限→禁工具强制闭环 (用户实测: 多轮搜索后无结论) ──

def test_search_cap_disables_tools_then_final_answer():
    """web_search 超 max_search_calls → 工具停用 → 模型纯文本总结收敛 (有结论)."""
    calls = {"n": 0}

    def script_factory(m):
        # 前 9 轮都调 web_search (超过上限 8), 之后给最终回答
        if calls["n"] < 9:
            calls["n"] += 1
            return iter([("__TOOLS__", [{"id": str(calls["n"]),
                                         "name": "web_search",
                                         "arguments": {"query": f"q{calls['n']}"}}], "")])
        return iter(["基于全部搜索结果的最终结论: 答案是 X。"])

    client = _FakeClient([script_factory(None) for _ in range(20)])
    client = _FakeClient([])
    calls2 = {"n": 0}
    class _LoopClient:
        def chat_stream(self, messages, **kw):
            calls2["n"] += 1
            if calls2["n"] <= 9:
                calls2["n"] += 0
                return iter([("__TOOLS__", [{"id": str(calls2["n"]),
                                             "name": "web_search",
                                             "arguments": {"query": f"q{calls2['n']}"}}], "")])
            return iter(["最终结论: 答案是 X。"])
    evs = _run(_LoopClient(), [{"role": "user", "content": "研究 q"}],
               max_rounds=0, max_search_calls=8)
    tokens = "".join(e["text"] for e in evs if e["type"] == "token")
    assert "最终结论" in tokens, "上限触发后必须收敛出结论"
    assert evs[-1]["type"] == "done"

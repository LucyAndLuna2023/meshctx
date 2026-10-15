# -*- coding: utf-8 -*-
"""CLI 审批行为级守门 — 004meshctx位 audit_v3136061 点名缺口 ("y→future resolve").

v3.136.0 语义层 PASS 未覆盖行为级 (worker 线程 input + future 桥接 + TOCTOU) 的教训:
本守门跑真异步 waiter + 真线程输入路径, 三场景:
  ① 正常流: waiter 先注册, 输入线程 y → future 经 call_soon_threadsafe resolve → agree
  ② 快输入: 输入线程在 waiter 注册前 y (future 不存在) → pending 缓冲 → waiter 检1 命中 → agree (不丢)
  ③ 拒绝: N → reject
"""
import asyncio
import threading

import pytest

from src.cli import make_cli_approval_bridge


def _answer_like_input_thread(approvals, pending, loop_ref, rid, ans_text):
    """复刻 cli.py _ask 的线程侧行为: input → future 在则 threadsafe resolve, 不在则 pending."""
    agree = ans_text.strip().lower() in ("y", "yes", "是")
    decision = {"action": "agree"} if agree else {"action": "reject"}
    fut = approvals.get(rid)
    if not fut or fut.done():
        pending[rid] = decision
        return
    loop = loop_ref[0]
    if loop:
        loop.call_soon_threadsafe(fut.set_result, decision)
    else:
        fut.set_result({"action": "reject"})


def test_behavior_normal_y_resolves_future():
    """① 正常流: y → future resolve → agree (裁定点名的行为断言)."""
    wait, (approvals, pending, loop_ref) = make_cli_approval_bridge()

    async def scenario():
        loop_ref[0] = asyncio.get_running_loop()
        t = threading.Timer(
            0.05, _answer_like_input_thread,
            args=(approvals, pending, loop_ref, "r1", "y"))
        t.start()
        return await wait("r1")

    result = asyncio.run(scenario())
    assert result == {"action": "agree"}, f"y 必须 resolve 为 agree: {result}"


def test_behavior_fast_input_not_lost():
    """② 快输入 (TOCTOU): y 在 waiter 注册前到达 — pending 缓冲, 检1 命中, 不丢."""
    wait, (approvals, pending, loop_ref) = make_cli_approval_bridge()

    async def scenario():
        loop_ref[0] = asyncio.get_running_loop()
        # 输入先到 (future 尚未注册) → pending
        _answer_like_input_thread(approvals, pending, loop_ref, "r2", "y")
        assert "r2" in pending, "快输入必须入 pending 缓冲"
        return await wait("r2")

    result = asyncio.run(scenario())
    assert result == {"action": "agree"}, f"快输入 y 不得丢失: {result}"


def test_behavior_reject_path():
    """③ 拒绝: N → reject."""
    wait, (approvals, pending, loop_ref) = make_cli_approval_bridge()

    async def scenario():
        loop_ref[0] = asyncio.get_running_loop()
        t = threading.Timer(
            0.05, _answer_like_input_thread,
            args=(approvals, pending, loop_ref, "r3", "N"))
        t.start()
        return await wait("r3")

    result = asyncio.run(scenario())
    assert result == {"action": "reject"}

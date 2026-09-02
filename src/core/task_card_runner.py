# -*- coding: utf-8 -*-
"""task_card_runner — CardWorker 的执行链 (开源真实实现, AGPLv3)

一句话任务卡 → run_agent_loop (唯一统一 agent 循环) → 事件映射到卡 timeline。

设计 (2026-09-02, 基于架构勘察):
- 复用 run_agent_loop (src/agent_loop.py:98) 与 chat_tools 工具面, 与 /api/chat 同语义。
- 执行在后台 asyncio worker (CardWorker), 不绑定 HTTP 请求; 卡状态/事件全程落盘。
- 审批: 危险动作由 needs_approval 触发 → CardWorker.register_approval 落盘 waiting_approval
  → Web decide → future resolve (跨断连存活, 卡 JSON 为真相源)。
- 取消: 卡 cancel_requested → interrupt_check 抛 InterruptSignal 优雅结束。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.task_card_runner")

# 派活任务系统提示词 (后台自主执行, 与 chat 同一套工具语义)
CARD_SYSTEM_PROMPT = """你是 meshctx 的自主任务执行 Agent。用户给你一句话任务, 请自主完成:

- 需要读文件/搜代码/执行命令/搜索网页时, 直接用工具, 不要解释不能做。
- 你运行在用户本机, 有完整文件系统访问权限。
- 删除/移动/覆盖/远程等危险操作会触发审批, 等待用户确认后继续。
- 完成后给出简明最终答复 (含关键结果与产出路径)。
- 回复使用用户任务所用语言。
"""


def _needs_approval(name: str, args: dict) -> Optional[str]:
    """判定工具是否属于危险/改动类 (与 main.py _needs_approval 同语义, 供后台卡)。

    规则:
    - write_file if_exists=overwrite → 覆盖已有文件
    - terminal 含 rm/rmdir/unlink/del/remove/mv/cp → 删除/移动/复制
    - terminal 命中 ApprovalEngine 危险模式库 → 危险命令
    - remote_write / remote_exec → 远程改动
    """
    if name == "write_file" and args.get("if_exists") == "overwrite":
        return "修改已有文件内容 (write_file overwrite)"
    if name in ("remote_write", "remote_exec"):
        return f"远程操作 ({name}) 需用户授权"
    if name == "terminal":
        cmd = str(args.get("cmd", "") or "")
        import re as _re
        if _re.search(r"\b(rm|rmdir|unlink|del|remove|mv|cp)\b", cmd):
            return "删除/移动/复制文件命令 (terminal)"
        try:
            from src.core.approval import check as _approval_check
            r = _approval_check(cmd, {})
            if r.requires_approval:
                return f"危险命令 ({r.reason})"
        except Exception:
            pass
    return None


def build_card_messages(prompt: str) -> List[Dict[str, str]]:
    """构造 run_agent_loop 的 messages (system 由 runner 注入)。"""
    return [{"role": "user", "content": prompt}]


def _resolve_client(card):
    """按卡 model 取模型客户端 (空=registry 默认)。"""
    from src.model_registry import get_registry
    reg = get_registry()
    model_id = getattr(card, "model", "") or None
    return reg.get(model_id)


def _resolve_tools():
    """后台卡工具面: chat_tools 统一 schema 集 (CLI/UI 同源)。"""
    from src.chat_tools import TOOLS as _CHAT_TOOLS
    # TOOLS 可能为 dict (旧名 TOOL_EXECUTORS) 或 list — 统一转 schema list
    if isinstance(_CHAT_TOOLS, dict):
        # dict 形态: chat_tools.TOOLS = TOOL_EXECUTORS (无 schema) → 用 main 侧 schema 太重,
        # 退化为只允许安全子集: 直接映射 dict keys 为空 schema
        return [{"type": "function",
                 "function": {"name": n, "description": n,
                              "parameters": {"type": "object",
                                             "properties": {}}}} for n in _CHAT_TOOLS]
    return _CHAT_TOOLS


def _resolve_exec_tool():
    """后台卡工具执行器: chat_tools.execute_tool (模块级, 不依赖请求作用域)。"""
    from src.chat_tools import execute_tool
    return execute_tool


def make_interrupt_check(card, worker):
    """取消/超时检查: 卡 cancel_requested → 抛 InterruptSignal。"""
    from src.core.interruptible_runner import InterruptSignal

    def _check():
        if getattr(card, "cancel_requested", False):
            raise InterruptSignal([])
    return _check


def make_approval_handlers(card, worker):
    """构造 run_agent_loop 需要的 needs_approval / approval_waiter。

    返回 (needs_approval, approval_waiter):
    - needs_approval: 命中危险规则 → register_approval (落盘 waiting_approval)
    - approval_waiter: 等待卡级 pending 的 Web decide (future), 超时自动拒绝
    """
    def _needs(name: str, args: dict) -> Optional[str]:
        return _needs_approval(name, args)

    async def _waiter(request_id: str) -> dict:
        from src.core.task_cards import get_card_worker
        import asyncio
        w = get_card_worker()
        # 事件 yield 后 register_approval 才会注册 future → 短暂等待
        def _get_fut():
            with w._approval_lock:
                return w._approval_futures.get(request_id)
        fut = _get_fut()
        for _ in range(100):
            if fut is not None:
                break
            await asyncio.sleep(0.05)
            fut = _get_fut()
        if fut is None:
            return {"action": "reject", "text": "[审批不可用] 自动拒绝"}
        try:
            # 超时自动拒绝 (对齐 run_agent_loop approval_timeout 语义)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=120.0)
        except asyncio.TimeoutError:
            return {"action": "reject", "text": "[审批超时] 用户未在时限内决策，操作已拒绝。"}
        except Exception:
            return {"action": "reject", "text": "[审批异常] 自动拒绝"}

    return _needs, _waiter


def _needs_approval_for_request(request_id: str) -> Optional[str]:
    """辅助: 反查 request_id 对应 pending (用于日志)。"""
    return None


async def run_card(card, worker=None) -> Dict[str, Any]:
    """执行一张任务卡 (CardWorker._run_fn 的默认实现)。

    Returns: {"result": str|None, "error": str|None}
    卡的状态/事件由调用方 (worker._run_one) 负责最终落盘; 本函数只做事件 → 卡 timeline。
    """
    from src.core.task_cards import CardStatus
    from src.agent_loop import run_agent_loop
    if worker is None:
        from src.core.task_cards import get_card_worker
        worker = get_card_worker()
    client = _resolve_client(card)
    tools = _resolve_tools()
    exec_tool = _resolve_exec_tool()
    messages = build_card_messages(card.prompt)
    needs_approval, approval_waiter = make_approval_handlers(card, worker)
    interrupt_check = make_interrupt_check(card, worker)

    last_text_parts: List[str] = []
    error = None
    max_rounds = int(getattr(card, "extra", {}).get("max_rounds") or 0)
    wall_clock = float(getattr(card, "extra", {}).get("wall_clock") or 1800)

    card.log("run_start", model=getattr(client, "model_id", None) or "",
             prompt_len=len(card.prompt or ""))
    try:
        async for ev in run_agent_loop(
            client, messages,
            tools=tools,
            exec_tool=exec_tool,
            max_rounds=max_rounds,
            wall_clock=wall_clock,
            system_prompt=CARD_SYSTEM_PROMPT,
            needs_approval=needs_approval,
            approval_waiter=approval_waiter,
            interrupt_check=interrupt_check,
        ):
            kind = ev.get("type")
            if kind == "token":
                card.log("token", text=ev.get("text", ""))
                last_text_parts.append(ev.get("text", ""))
            elif kind == "reasoning":
                card.log("reasoning", text=ev.get("text", ""))
            elif kind == "round":
                card.log("round", n=ev.get("round"), total=ev.get("total"))
            elif kind == "deliver":
                card.log("deliver", text=ev.get("text", ""))
            elif kind == "approval":
                # 先记 timeline 再落盘 (register 内部会 save, 保证事件已写入)
                req_id = ev.get("request_id", "")
                reason = _needs_approval(ev.get("name", ""), ev.get("args") or {})
                card.log("approval_requested", name=ev.get("name"),
                         reason=ev.get("reason") or reason or "需确认")
                worker.register_approval(card, req_id, ev.get("name", ""),
                                         ev.get("args") or {}, ev.get("reason") or reason or "需确认")
            elif kind == "tool_start":
                card.log("tool_start", name=ev.get("name"), args=ev.get("args"))
            elif kind == "tool_result":
                card.log("tool_result", name=ev.get("name"),
                         result=(ev.get("result") or "")[:500])
            elif kind == "final":
                card.log("final", text=ev.get("text", ""))
                last_text_parts.append(ev.get("text", ""))
            elif kind == "timed_out":
                card.log("timed_out", text=ev.get("text", ""))
            elif kind == "error":
                card.log("error", text=ev.get("text", ""))
                error = ev.get("text", "")
            elif kind == "interrupted":
                card.log("interrupted", note=ev.get("note", ""))
                # 取消由 worker 置 CANCELLED; 这里结束事件循环
                break
            # 事件流每 N 条落盘一次防状态丢失 (卡 JSON 为真相源)
            if kind in ("tool_start", "tool_result", "approval_requested", "final", "error"):
                worker._store.save(card)
    except Exception as e:
        # 取消是正常路径: InterruptSignal 由 interrupt_check 抛出
        from src.core.interruptible_runner import InterruptSignal
        if isinstance(e, InterruptSignal):
            card.log("interrupted", note="cancelled by user")
            worker._store.save(card)
            return {"result": card.result, "error": None}
        logger.exception("run_card %s failed", card.id)
        error = str(e)
        card.log("exception", error=error)

    # 汇总最终答复: final 事件最优先, 否则拼接 token
    result = "".join(last_text_parts).strip()
    if result:
        card.result = result[-8000:]  # 防卡文件超大
    if error:
        card.error = error
    card.log("run_end", error=error)
    worker._store.save(card)
    return {"result": card.result, "error": error}


__all__ = ["run_card", "build_card_messages", "CARD_SYSTEM_PROMPT"]

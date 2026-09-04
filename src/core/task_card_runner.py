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

# WP1 (MCTX-PLAN-2026-0903): runner 事件遥测 — 在 run_card Span 上下文中 record
# 自动带 trace_id/span_id 归因 (contextvar 继承); 失败静默不影响业务
try:
    from src.core import telemetry as _tel_mod
except Exception:                       # pragma: no cover — stub 环境兜底
    _tel_mod = None

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
    """取消/超时检查: worker 级取消集合 (外部 cancel 及时生效, P2-1) → 抛 InterruptSignal。

    cancel() 跨线程登记 _cancelled 集合; 卡线程内存对象 cancel_requested 不随
    外部 cancel 更新, 故查集合 (fallback 内存标志保底)。
    """
    from src.core.interruptible_runner import InterruptSignal

    def _check():
        cancelled = False
        try:
            if worker is not None and hasattr(worker, "is_cancelled"):
                cancelled = worker.is_cancelled(card.id)
        except Exception:
            cancelled = False
        if cancelled or getattr(card, "cancel_requested", False):
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
        # 卡已被取消 (P3 002codex): 挂起审批即时返回 reject, 不再等 future/超时
        if w.is_cancelled(card.id):
            return {"action": "reject", "text": "[取消] 用户取消任务，审批已拒绝。"}
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
        if w.is_cancelled(card.id):
            return {"action": "reject", "text": "[取消] 用户取消任务，审批已拒绝。"}
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

    WP1 (MCTX-PLAN-2026-0903): 整卡执行包在 telemetry Span 内 — 每张卡一条
    span (trace_id=自动生成), 内含审批/取消/异常状态, 供 JSONL/OTLP 全链路追踪。
    遥测失败绝不干扰业务 (Span.__exit__ 内吞异常)。

    Returns: {"result": str|None, "error": str|None}
    卡的状态/事件由调用方 (worker._run_one) 负责最终落盘; 本函数只做事件 → 卡 timeline。
    """
    from src.core import telemetry as _tel
    # WP1: 卡级 trace 由 worker._run_one 预置 (extra.trace_id) — span 归入同一 trace,
    # 使审批/取消等 API 线程事件与执行 span 全链路关联; 直调 run_card (测试) 自动生成
    _trace = (getattr(card, "extra", None) or {}).get("trace_id", "") or ""
    with _tel.Span("card.run", agent="task", trace_id=_trace,
                   tags={"card_id": getattr(card, "id", "") or "",
                         "prompt_len": len(getattr(card, "prompt", "") or "")}):
        # WP4 (MCTX-PLAN-2026-0903 P1-1): swarm 派生任务卡编排 — 父卡派生 N 子卡
        # 并行执行 → 聚合 (个人版落地路径: 不经 /api/swarm/*, 全部任务卡化, D2)
        if (getattr(card, "extra", None) or {}).get("swarm_plan"):
            return await _run_swarm_card(card, worker)
        return await _run_card_inner(card, worker)


async def _run_card_inner(card, worker=None) -> Dict[str, Any]:
    """run_card 实现体 (被 Span 包裹, 见上)。"""
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
    # 默认 300s (5分钟) — 一句话派活不宜长挂; 长任务可经 API 传 wall_clock
    wall_clock = float(getattr(card, "extra", {}).get("wall_clock") or 300)

    def _save_card(w, c):
        """合并外部状态后落盘 (save_card 存在时), 否则直存 (测试 FakeWorker)。"""
        if w is not None and hasattr(w, "save_card"):
            w.save_card(c)
        else:
            w._store.save(c)

    def _emit(event_type: str, **kw):
        """WP1: 遥测事件 (Span 上下文内 → 自动 trace/span 归因); 失败静默。"""
        if _tel_mod is None:
            return
        try:
            _tel_mod.get_telemetry().record("task", event_type, **kw)
        except Exception:
            pass

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
                # 聚合 token 计数, 不逐条落盘全文 (防卡文件膨胀, P2 002codex)
                card.extra.setdefault("token_count", 0)
                card.extra["token_count"] += 1
                last_text_parts.append(ev.get("text", ""))
            elif kind == "reasoning":
                # reasoning 同样聚合: 仅记录条数
                card.extra.setdefault("reasoning_chunks", 0)
                card.extra["reasoning_chunks"] += 1
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
                _emit("approval_requested", tool=ev.get("name", ""),
                      detail=(ev.get("reason") or reason or "需确认")[:200])
            elif kind == "tool_start":
                card.log("tool_start", name=ev.get("name"), args=ev.get("args"))
                _emit("tool_call", tool=ev.get("name", ""),
                      detail=str(ev.get("args"))[:200])
            elif kind == "tool_result":
                card.log("tool_result", name=ev.get("name"),
                         result=(ev.get("result") or "")[:500])
                _emit("tool_result", tool=ev.get("name", ""),
                      detail=(ev.get("result") or "")[:200])
            elif kind == "final":
                card.log("final", text=ev.get("text", ""))
                last_text_parts.append(ev.get("text", ""))
            elif kind == "timed_out":
                card.log("timed_out", text=ev.get("text", ""))
                _emit("timed_out", detail=(ev.get("text") or "")[:200])
            elif kind == "error":
                card.log("error", text=ev.get("text", ""))
                error = ev.get("text", "")
                _emit("error", detail=(ev.get("text") or "")[:300])
            elif kind == "interrupted":
                card.log("interrupted", note=ev.get("note", ""))
                _emit("interrupted", detail=(ev.get("note") or "")[:200])
                # 取消由 worker 置 CANCELLED; 这里结束事件循环
                break
            # 事件流按节流落盘 (非逐 token; 防状态丢失, 卡 JSON 为真相源)
            if kind in ("tool_start", "tool_result", "approval_requested", "final", "error"):
                # timeline 上限裁剪: 只保留最近 2000 条, 防长任务卡无限膨胀
                if len(card.timeline) > 2000:
                    card.timeline = card.timeline[-1500:]
                _save_card(worker, card)
    except Exception as e:
        # 取消是正常路径: InterruptSignal 由 interrupt_check 抛出
        from src.core.interruptible_runner import InterruptSignal
        if isinstance(e, InterruptSignal):
            card.log("interrupted", note="cancelled by user")
            _save_card(worker, card)
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
    _save_card(worker, card)
    # WP1: 整卡汇总事件 (token/工具数聚合, 全链路 trace 关联; P3-2 codex:
    # 携带卡内 token_count/reasoning_chunks, 供观测页用量)
    _tok = int(getattr(card, "extra", {}).get("token_count", 0) or 0)
    _rsn = int(getattr(card, "extra", {}).get("reasoning_chunks", 0) or 0)
    _emit("run_end", tokens_in=_tok, tokens_out=0,
          detail=("error" if error else "ok") + f" tokens={_tok} reasoning={_rsn}")
    return {"result": card.result, "error": error}


__all__ = ["run_card", "build_card_messages", "CARD_SYSTEM_PROMPT"]


async def _run_swarm_card(card, worker=None) -> Dict[str, Any]:
    """WP4 swarm 派生任务卡编排 (P1-1): 父卡派生 N 子卡 → 等待终态 → 聚合。

    plan = card.extra['swarm_plan'] = {"subtasks": [prompt,...](2-5 条), "retry": bool=True}
    子卡 = 普通 agent 卡 (extra.parent_card_id=父 id; 不继承 swarm_plan, 防递归);
    每子卡独立消耗配额 (try_consume_spawn → enqueue 失败 refund);
    失败子卡默认重试 1 次 (retry=True); 截止=wall_clock (默认 300s, 最低 10s);
    全部子卡失败 → 父卡 error; 部分/全部跳过 → 记录在 extra.swarm_children。
    """
    import asyncio
    import time as _time
    from src.core.task_cards import CardStatus, TaskCard, get_card_worker, get_hub_quota
    if worker is None:
        worker = get_card_worker()

    def _emit(event_type: str, **kw):
        try:
            _tel_mod.get_telemetry().record("task", event_type, **kw)
        except Exception:
            pass

    def _save_card(w, c):
        if w is not None and hasattr(w, "save_card"):
            w.save_card(c)
        else:
            w._store.save(c)

    plan = (getattr(card, "extra", None) or {}).get("swarm_plan") or {}
    subtasks = plan.get("subtasks") or []
    retry_on = bool(plan.get("retry", True))
    if not isinstance(subtasks, list) or not (2 <= len(subtasks) <= 5):
        return {"result": None, "error": "swarm_plan.subtasks 需 2-5 条"}

    hq = get_hub_quota()
    owner = getattr(card, "owner", "local")
    records = []
    card.log("swarm_spawn_start", workers=len(subtasks))
    for i, st in enumerate(subtasks):
        st = str(st or "").strip()
        if not st:
            records.append({"idx": i, "status": "skipped_empty"}); continue
        try:
            q = hq.try_consume_spawn(owner, plan=card.plan,
                                     concurrent_now=worker.running_count())
        except Exception as e:
            q = {"ok": False, "reason": str(e)}
        if not q.get("ok"):
            records.append({"idx": i, "status": "skipped_quota",
                            "reason": str(q.get("reason", ""))[:120]})
            _emit("swarm_child", tool="quota", detail=f"child#{i} skipped")
            continue
        child = TaskCard(owner=owner, plan=card.plan,
                         title=f"[swarm#{i + 1}] {(card.title or card.prompt)[:40]}",
                         prompt=st)
        child.extra["parent_card_id"] = card.id
        child.extra["quota"] = q
        if not worker.enqueue(child):
            try: hq.refund_spawn(owner)
            except Exception: pass
            records.append({"idx": i, "status": "skipped_enqueue"})
            continue
        records.append({"idx": i, "id": child.id, "status": "queued", "retries": 0})
        card.log("swarm_child_spawned", idx=i, card_id=child.id)
    _save_card(worker, card)
    spawned = [r for r in records if r.get("id")]

    wall = float((getattr(card, "extra", None) or {}).get("wall_clock") or 300)
    pto = plan.get("timeout")
    try:
        _to = float(pto) if pto else 0.0
    except (TypeError, ValueError):            # P3-8: 非法值钳制回默认
        _to = 0.0
    deadline = _time.time() + (_to if _to > 0 else max(10.0, min(wall, 7200.0)))
    while spawned:
        pending = [r for r in spawned
                   if r["status"] in ("queued", "running", "waiting_approval")]
        if not pending or _time.time() > deadline:
            for r in pending:
                # P3-1/P3-8 (002codex): 超时收束任一未终态子卡 (WAITING_APPROVAL/
                # RUNNING/QUEUED 一律 cancel → reject 审批/中断/出队), 防孤儿
                try:
                    worker.cancel(r["id"])
                except Exception:
                    pass
                r["status"] = "timeout"
            break
        await asyncio.sleep(0.25)
        for r in spawned:
            if r["status"] not in ("queued", "running", "waiting_approval"): continue
            c = worker._store.load(r["id"]) if worker is not None else None
            if c is None: continue
            r["status"] = c.status.value
            if c.status in (CardStatus.COMPLETED, CardStatus.FAILED,
                            CardStatus.CANCELLED):
                # 语义: worker 对 out["error"] 记 card.error 但状态 COMPLETED —
                # swarm 聚合把「带 error 的完成」视作失败 (可重试)
                failed_like = (c.status == CardStatus.FAILED
                               or bool((c.error or "").strip()))
                r["status"] = ("cancelled" if c.status == CardStatus.CANCELLED
                               else ("failed" if failed_like else "completed"))
                r["result"] = (c.result or "")[:400]
                r["error"] = (c.error or "")[:200]
                card.log("swarm_child", idx=r["idx"], card_id=r["id"],
                         status=r["status"])
                _emit("swarm_child", tool="orchestrator",
                      detail=f"idx={r['idx']} status={r['status']}")
                # 失败重试一次 (P4-8 验收: 失败重试场景)
                if (failed_like and c.status != CardStatus.CANCELLED
                        and retry_on and r.get("retries", 0) < 1):
                    try:
                        q = hq.try_consume_spawn(owner, plan=card.plan,
                                                 concurrent_now=worker.running_count())
                    except Exception as e:
                        q = {"ok": False, "reason": str(e)}
                    if q.get("ok"):
                        rc = TaskCard(owner=owner, plan=card.plan,
                                      title=f"[swarm#{r['idx'] + 1}-retry] {(card.title or card.prompt)[:36]}",
                                      prompt=c.prompt)
                        rc.extra["parent_card_id"] = card.id
                        rc.extra["retry_of"] = r["id"]
                        rc.extra["quota"] = q
                        if worker.enqueue(rc):
                            r["retries"] = 1
                            r["id"] = rc.id
                            r["status"] = "queued"
                            del r["result"]; del r["error"]
                            card.log("swarm_child_retry", idx=r["idx"], card_id=rc.id)
                            continue
                    try: hq.refund_spawn(owner)
                    except Exception: pass
        _save_card(worker, card)

    ok = sum(1 for r in spawned if r["status"] == "completed")
    fail = sum(1 for r in spawned if r["status"] == "failed")
    skip = len(records) - len(spawned)
    lines = []
    for r in records:
        if not r.get("id"):
            lines.append(f"#{r['idx'] + 1} [跳过·{r['status']}]")
            continue
        body = (r.get("result") or r.get("error") or "")[:300]
        tag = "完成" if r["status"] == "completed" else f"{r['status']}"
        if r.get("retries"): tag += f"·重试{r['retries']}"
        lines.append(f"#{r['idx'] + 1} [{tag}] {body}")
    header = f"Swarm 聚合: 成功 {ok} / 失败 {fail} / 跳过 {skip} (workers={len(subtasks)})"
    card.extra["swarm_children"] = records
    card.log("swarm_done", ok=ok, failed=fail, skipped=skip)
    _emit("run_end", tokens_in=0, tokens_out=0,
          detail=f"swarm ok={ok} fail={fail} skip={skip}")
    _save_card(worker, card)
    error = None
    if spawned and ok == 0 and fail + sum(1 for r in spawned if r["status"] == "timeout") > 0:
        error = "全部子任务失败/超时"
    elif not spawned:
        error = "无子任务派生 (配额/队列不可用)"
    return {"result": (header + "\n" + "\n".join(lines))[:8000], "error": error}

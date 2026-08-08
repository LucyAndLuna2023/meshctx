"""统一 Agent 循环 — CLI 与 UI 共用同一套「搜索→工具→交付」逻辑。

之前 CLI(cli._chat_loop) 与 UI(main.api_chat_stream) 各写一套循环，
提示词/工具集/轮次上限/过滤规则不同 → 同一任务输出必然不同。
本模块把循环抽成唯一实现，两个入口只做 I/O 适配。

事件协议:
  {"type":"round", "round":int, "total":int}          搜索轮提示
  {"type":"deliver"}                                  进入交付阶段
  {"type":"token", "text":str}                        模型输出 token
  {"type":"tool_start","name":str,"args":dict}        工具开始
  {"type":"tool_result","name":str,"result":str}      工具结果
  {"type":"final","text":str}                         轮次耗尽后的非流式兜底
  {"type":"timed_out","text":str}                     墙钟超时
  {"type":"timed_out_done"}                           超时消息已发
  {"type":"error","text":str}                         致命错误
  {"type":"done"}                                     正常结束
"""
import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional

from src.chat_tools import trim_messages

DEFAULT_WALL_CLOCK = 300.0      # 整轮处理墙钟上限(秒)
DEFAULT_TOOL_TIMEOUT = 120.0    # 单批工具执行超时(秒)
DEFAULT_MAX_SEARCH_CALLS = 8    # web_search 防循环上限
DEFAULT_MAX_TOKENS = 16384

# 最后一轮注入的完成指令：允许工具，强制收尾
FINAL_HINT = (
    "[系统提示] 这是最后一轮。如果任务要求生成文件（Word/报告/文档/脚本等）且尚未完成，"
    "必须立即完成文件生成：Word 报告用 save_docx 工具，其他文件用 write_file/terminal。"
    "然后直接输出最终交付总结（含保存路径）。"
)


async def run_agent_loop(
    client,
    messages: List[Dict],
    *,
    tools: List[Dict],
    exec_tool: Callable[[str, Dict], str],
    max_rounds: int = 4,
    wall_clock: float = DEFAULT_WALL_CLOCK,
    tool_timeout: float = DEFAULT_TOOL_TIMEOUT,
    max_search_calls: int = DEFAULT_MAX_SEARCH_CALLS,
    system_prompt: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
):
    """统一的 搜索→工具→交付 循环（async generator，产出事件 dict）。

    - 每一轮都允许工具调用（含最后一轮，便于“先搜索→最后写文件”）。
    - 模型直接回复文本 → 立即结束。
    - 轮次耗尽 / 最后一轮工具执行完 → 无工具兜底生成最终文本。
    - web_search 总数超 max_search_calls 后强制模型收尾。
    """
    # 确保 system 在首位（UI 传 system_prompt；CLI 自带 system 则不注入）
    if system_prompt is not None and (not messages or messages[0].get("role") != "system"):
        messages.insert(0, {"role": "system", "content": system_prompt})

    _tools_ok = True
    _start_ts = time.time()
    _total_search_calls = 0
    _timed_out = False

    for _round in range(max_rounds):
        if time.time() - _start_ts > wall_clock:
            yield {"type": "timed_out", "text": f"[已达到最大处理时间 {int(wall_clock)} 秒，已中止]"}
            _timed_out = True
            break

        # ── 最后一轮 = Deliver（仍带工具，注入完成指令）──
        is_last = (_round == max_rounds - 1)
        if is_last:
            yield {"type": "deliver"}
            # 用克隆列表注入提示，不污染真实 messages（避免 pop 误删工具结果）
            _stream_msgs = messages + [{"role": "user", "content": FINAL_HINT}]
        else:
            _stream_msgs = messages
            yield {"type": "round", "round": _round, "total": max_rounds - 1}

        try:
            if _tools_ok:
                stream = client.chat_stream(
                    _stream_msgs, temperature=0.7, max_tokens=max_tokens, tools=tools)
            else:
                stream = client.chat_stream(
                    _stream_msgs, temperature=0.7, max_tokens=max_tokens)
        except Exception as tool_err:
            err_msg = str(tool_err)
            if 'tool' in err_msg.lower() or 'not support' in err_msg.lower() or 'invalid' in err_msg.lower():
                _tools_ok = False
                stream = client.chat_stream(
                    messages, temperature=0.7, max_tokens=max_tokens)
            else:
                yield {"type": "error", "text": str(tool_err)}
                return

        tool_calls_raw = None
        msg_content = ""
        for item in stream:
            if isinstance(item, tuple) and item[0] == "__TOOLS__":
                if _tools_ok:
                    tool_calls_raw = item[1]
                msg_content = item[2]
            elif isinstance(item, str):
                yield {"type": "token", "text": item}
                msg_content += item

        # 组装伪消息（兼容 model_registry.chat_stream 的 ("__TOOLS__", ...) 协议）
        class _PM: pass
        msg = _PM()
        msg.content = msg_content or None
        msg.tool_calls = None
        if tool_calls_raw:
            msg.tool_calls = []
            for tc in tool_calls_raw:
                ptc = _PM()
                ptc.id = tc["id"]
                ptc.type = "function"
                ptc.function = _PM()
                ptc.function.name = tc["name"]
                ptc.function.arguments = json.dumps(tc["arguments"])
                msg.tool_calls.append(ptc)

        if msg.tool_calls:
            # 记录 assistant 消息（tool_calls 时 content 必须为 null，不能用 ""）
            messages.append({"role": "assistant", "content": msg.content or None, "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]})

            # 防循环: web_search 上限
            def _safe_exec(name, args):
                nonlocal _total_search_calls
                if name == "web_search":
                    _total_search_calls += 1
                    if _total_search_calls > max_search_calls:
                        return (f"[防循环] 搜索已达 {max_search_calls} 次上限，请立即基于已有信息输出最终结果，"
                                "不要再调用 web_search")
                return exec_tool(name, args)

            # 并发执行工具（run_in_executor + asyncio.wait，Python 3.12 兼容）
            loop = asyncio.get_running_loop()
            futures_map = {}
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                futures_map[loop.run_in_executor(None, _safe_exec, name, args)] = (tc, name, args)
                yield {"type": "tool_start", "name": name, "args": args}

            done_futures, pending_futures = await asyncio.wait(
                list(futures_map.keys()), timeout=tool_timeout)
            for pf in pending_futures:
                pf.cancel()
                tc, name, args = futures_map[pf]
                timeout_msg = f"[工具 {name} 执行超过{tool_timeout}秒，已超时中止]"
                yield {"type": "tool_result", "name": name, "result": timeout_msg}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": timeout_msg})
            for future in done_futures:
                tc, name, args = futures_map[future]
                try:
                    result = await future
                except Exception as e:
                    result = f"工具执行失败: {e}"
                yield {"type": "tool_result", "name": name, "result": result}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:16000]})

            # 防消息无限膨胀（CLI/UI 共用）
            if len(messages) > 40:
                messages[:] = trim_messages(messages, max_len=40, keep=30)

            if is_last:
                # ── 交付阶段：工具执行完后，最多再给 3 轮「带工具」机会收尾 ──
                # 模型可能在最后一轮还想再搜索/再写文件（尤其 deepseek 会把工具调用
                # 写成 DSML 文本块）；这里让最终交付也带工具，直到输出纯文本为止。
                from src.chat_tools import strip_dsml_tool_calls
                final_text = ""
                for _fi in range(3):
                    if time.time() - _start_ts > wall_clock:
                        break
                    _stream2 = client.chat_stream(
                        messages, temperature=0.7, max_tokens=max_tokens,
                        tools=tools if _tools_ok else None)
                    _tc2, _txt2 = None, ""
                    for _item in _stream2:
                        if isinstance(_item, tuple) and _item[0] == "__TOOLS__":
                            _tc2, _txt2 = _item[1], _item[2]
                        elif isinstance(_item, str):
                            _txt2 += _item
                    if not _tc2:
                        final_text = strip_dsml_tool_calls(_txt2).strip()
                        break
                    messages.append({"role": "assistant", "content": _txt2 or None, "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                        for tc in _tc2]})
                    _loop2 = asyncio.get_running_loop()
                    _futures = {}
                    for _tc in _tc2:
                        _nm = _tc["name"]
                        try:
                            _ar = json.loads(_tc["arguments"]) if isinstance(_tc["arguments"], str) else _tc["arguments"]
                        except Exception:
                            _ar = {}
                        _futures[_loop2.run_in_executor(None, _safe_exec, _nm, _ar)] = (_tc, _nm, _ar)
                        yield {"type": "tool_start", "name": _nm, "args": _ar}
                    _d2, _p2 = await asyncio.wait(list(_futures.keys()), timeout=tool_timeout)
                    for _pf in _p2:
                        _pf.cancel()
                        _tc, _nm, _ar = _futures[_pf]
                        _res = f"[工具 {_nm} 执行超过{tool_timeout}秒，已超时中止]"
                        yield {"type": "tool_result", "name": _nm, "result": _res}
                        messages.append({"role": "tool", "tool_call_id": _tc["id"], "content": _res})
                    for _fu in _d2:
                        _tc, _nm, _ar = _futures[_fu]
                        try:
                            _res = await _fu
                        except Exception as _e:
                            _res = f"工具执行失败: {_e}"
                        yield {"type": "tool_result", "name": _nm, "result": _res}
                        messages.append({"role": "tool", "tool_call_id": _tc["id"], "content": _res[:16000]})
                    if len(messages) > 40:
                        messages[:] = trim_messages(messages, max_len=40, keep=30)
                if len(final_text) < 30:
                    try:
                        _resp = await loop.run_in_executor(
                            None, lambda: client.chat(messages, temperature=0.7, max_tokens=max_tokens))
                        final_text = strip_dsml_tool_calls(_resp.get("content") or "").strip()
                    except Exception:
                        final_text = ""
                if not final_text:
                    final_text = "处理完成（文件已生成）"
                yield {"type": "token", "text": final_text}
                messages.append({"role": "assistant", "content": final_text})
                yield {"type": "done"}
                return

            continue  # 下一轮，让模型基于工具结果回复

        # 模型直接回复文本 → 结束
        messages.append({"role": "assistant", "content": msg_content})
        yield {"type": "done"}
        return

    # 轮次耗尽/超时兜底
    if _timed_out:
        yield {"type": "timed_out_done"}
        return
    try:
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: client.chat(messages, temperature=0.7, max_tokens=max_tokens))
        final_content = resp.get("content") or ""
    except Exception:
        final_content = ""
    if not final_content or final_content == "处理超时，请重试":
        final_content = "已达搜索轮次上限，先交付当前成果。你可以继续输入，我会在保留上下文的基础上追加轮次。"
    messages.append({"role": "assistant", "content": final_content})
    yield {"type": "final", "text": final_content}
    yield {"type": "done"}

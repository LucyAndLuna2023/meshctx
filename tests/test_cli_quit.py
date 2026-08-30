"""
Test v3.119.0 — CLI REPL /quit 退出 (004 F5) + v3.122 打断模式

复现 (旧): readline 多行分支下输入 /quit 只置 quit_requested=True, 未 append 进
lines → user='' 命中 "if not user: continue", 且外层循环把 quit_requested
重置为 False → 死循环无法退出 (Linux/macOS 均受影响, Windows 走 else 分支不受影响)。
验证: 退出判断先于空串判断, /quit 立即 break。

v3.122 (2026-08-29): 新增打断模式 (MESHCTX_INTERRUPT=1 默认) —
任务执行中可继续输入 + 新消息打断置顶。测试覆盖:
  1) 旧模式 (MESHCTX_INTERRUPT=0) /quit 退出 (原回归, 代码块切片执行)
  2) 打断模式主循环: 代码块语法完整 + runner 打断语义单测
"""
import builtins
import os
import textwrap

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLI_PATH = os.path.join(PROJECT_ROOT, "src", "cli.py")


def _extract_block(start_marker, end_marker):
    src = open(CLI_PATH, encoding="utf-8").read()
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return textwrap.dedent(src[start:end])


def _legacy_repl_body():
    """旧模式 REPL 代码块 (MESHCTX_INTERRUPT=0 分支内部)。

    实际结构: `if _interrupt_enabled: ... else: <旧REPL>`。
    从打断分支结束后的 else: 行开始提取, 只保留循环体。
    """
    src = open(CLI_PATH, encoding="utf-8").read()
    # 打断分支结尾是 `_reader.join(timeout=1.0)` + 空行 + `else:`
    anchor = "_reader.join(timeout=1.0)\n"
    pos = src.find(anchor)
    assert pos >= 0, "未找到打断分支结尾"
    else_pos = src.find("    else:\n", pos)
    assert else_pos >= 0, "未找到 else: 分支"
    body_start = else_pos + len("    else:\n")
    end_marker = "    # ── 对话结束：自动写入记忆体系"
    body_end = src.index(end_marker, body_start)
    return textwrap.dedent(src[body_start:body_end])


def _interrupt_repl_body():
    """打断模式 REPL 代码块 (MESHCTX_INTERRUPT=1 分支内部)。"""
    return _extract_block(
        "    if _interrupt_enabled:",
        "    # ── 旧 REPL (MESHCTX_INTERRUPT=0)",
    )


def _run_legacy_repl(feed, max_inputs=100):
    it = iter(feed)
    calls = {"n": 0}

    def fake_input(prompt):
        calls["n"] += 1
        if calls["n"] > max_inputs:
            raise RuntimeError(f"deadloop: exceeded {max_inputs} inputs")
        try:
            return next(it)
        except StopIteration:
            return ""

    old = builtins.input
    builtins.input = fake_input
    g = {
        "_HAS_READLINE": True,
        "profile_tag": "",
        "prompt": "You> ",
        "_handle_slash": lambda *a, **k: False,
        "reg": None, "client": None, "SESS": None, "session_id": None,
        "messages": [],
        "_build_system_msg": lambda *a, **k: ([],),
        "_chat_loop": lambda *a, **k: None,
        "TOOLS": [], "execute_tool": lambda *a, **k: None,
        "TOOL_ICONS": {}, "max_turns": 0, "wall_clock": None,
    }
    try:
        exec(_legacy_repl_body(), g)
        return "EXIT_OK", calls["n"]
    except RuntimeError as e:
        return "DEADLOOP", str(e)
    finally:
        builtins.input = old


def test_quit_directly_exits_legacy_mode():
    """旧模式 (MESHCTX_INTERRUPT=0): /quit 立即退出, 不死循环。"""
    result, calls = _run_legacy_repl(["/quit", "", ""])
    assert result == "EXIT_OK", f"legacy /quit 未退出: {result}"


def test_interrupt_mode_block_integrity():
    """打断模式 REPL 代码块: 语法完整, 包含打断语义关键调用。"""
    body = _interrupt_repl_body()
    # 语法可编译
    compile(body, "<repl-interrupt>", "exec")
    # 关键语义: runner + reader + interrupt_check + apply_interrupt + 清理
    assert "InterruptibleRunner()" in body
    assert "StdinReader(" in body
    assert "interrupt_check=_runner.interrupt_check" in body
    assert "apply_interrupt" in body
    assert "reader.stop()" in body or "_reader.stop()" in body


def test_interrupt_semantics_runner():
    """打断语义: 排队任务执行中, 新消息打断置顶优先执行 (核心需求)。"""
    from src.core.interruptible_runner import (
        InterruptibleRunner, InterruptSignal,
    )
    import threading, time

    r = InterruptibleRunner()
    results = []

    def feeder():
        time.sleep(0.2)
        r.enqueue([{"role": "user", "content": "任务1"}])
        time.sleep(0.4)  # 任务1执行中
        r.submit([{"role": "user", "content": "打断2"}])
        time.sleep(0.3)
        r.set_eof()

    t = threading.Thread(target=feeder)
    t.start()

    try:
        while True:
            msgs = r.next_task_blocking()
            if msgs is None:
                break
            results.append(msgs[-1]["content"])
            if msgs[-1]["content"] == "任务1":
                # 模拟任务执行: 轮询打断
                for _ in range(6):
                    time.sleep(0.1)
                    try:
                        r.interrupt_check()
                    except InterruptSignal as sig:
                        results.append(f"<打断:{sig.messages[-1]['content']}>")
                        r.apply_interrupt(sig.messages)
                        break
            else:
                time.sleep(0.1)
    finally:
        t.join(timeout=2)

    # 任务1 → 被打断 → 打断2 置顶执行
    assert "任务1" in results
    assert "<打断:打断2>" in results
    assert "打断2" in results
    assert results.index("打断2") < results.index("任务1") + 10  # 打断2在任务1之后很快执行


def test_stop_signal_interrupts_task():
    """P1 (002meshctx 审计): /stop 和 Ctrl+C (submit([])) 必须能停止进行中的任务。

    修复前: interrupt_check 条件 `_interrupt_requested and _pending_top`,
    空列表 falsy → 不抛异常 → /stop 无效。
    修复后: 只查 _interrupt_requested, InterruptSignal 允许空 messages。
    """
    from src.core.interruptible_runner import (
        InterruptibleRunner, InterruptSignal,
    )
    import threading, time

    r = InterruptibleRunner()
    results = []

    def feeder():
        time.sleep(0.2)
        r.enqueue([{"role": "user", "content": "长任务"}])
        time.sleep(0.5)   # 任务执行中
        r.submit([])      # /stop 或 Ctrl+C: 空消息停止信号
        time.sleep(0.3)
        r.set_eof()

    t = threading.Thread(target=feeder)
    t.start()

    stopped = False
    try:
        while True:
            msgs = r.next_task_blocking()
            if msgs is None:
                break
            results.append(msgs[-1]["content"])
            # 模拟任务执行: 轮询打断
            for _ in range(8):
                time.sleep(0.1)
                try:
                    r.interrupt_check()
                except InterruptSignal as sig:
                    if sig.messages:
                        results.append(f"<打断:{sig.messages[-1]['content']}>")
                        r.apply_interrupt(sig.messages)
                    else:
                        stopped = True          # 空消息 = 停止信号
                    break
            if stopped:
                break   # 停止后不执行任何新任务, 回到等待
    finally:
        t.join(timeout=2)

    assert "长任务" in results
    assert stopped, "/stop (空消息) 未能停止进行中的任务 (P1 回归)"


def test_web_anon_no_cross_tab_interrupt():
    """P2-2 (002meshctx 审计): 无 conversation_id (anon) 时多标签页互不打断。

    修复前: anon 分组按首条消息 → 相同首条消息的多标签页互相打断。
    修复后: anon 固定分组, 每次独立 manager, 绝不自打断/互打断。
    """
    from src.core.interruptible_runner import ConversationInterruptManager
    import threading, time

    mgr_a = ConversationInterruptManager()
    mgr_b = ConversationInterruptManager()   # 模拟另一标签页 (独立实例)

    rid_a = "req-a"
    rid_b = "req-b"
    mgr_a.register(rid_a)
    mgr_b.register(rid_b)

    # a 与 b 互不影响
    assert mgr_a.should_interrupt(rid_a) is False
    assert mgr_b.should_interrupt(rid_b) is False

    # 同会话内: 新请求取代旧请求
    mgr_a.register(rid_a + "-new")
    assert mgr_a.should_interrupt(rid_a) is True
    assert mgr_a.should_interrupt(rid_a + "-new") is False

    # 不同会话 (b) 不受 a 影响
    assert mgr_b.should_interrupt(rid_b) is False

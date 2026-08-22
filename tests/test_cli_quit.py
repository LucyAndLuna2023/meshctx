"""
Test v3.119.0 — CLI REPL /quit 退出 (004 F5)

复现: readline 多行分支下输入 /quit 只置 quit_requested=True, 未 append 进
lines → user='' 命中 "if not user: continue", 且外层循环把 quit_requested
重置为 False → 死循环无法退出 (Linux/macOS 均受影响, Windows 走 else 分支不受影响)。
验证: 退出判断先于空串判断, /quit 立即 break。
"""
import builtins
import os
import sys
import textwrap

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLI_PATH = os.path.join(PROJECT_ROOT, "src", "cli.py")


def _repl_body():
    src = open(CLI_PATH, encoding="utf-8").read()
    start = src.index("    # ── REPL ──")
    end = src.index('        messages.append({"role": "user", "content": user})')
    return textwrap.dedent(src[start:end])


_REPL_BODY = _repl_body()


def _run_repl(feed, max_inputs=100):
    """按真实 REPL 代码块执行; 输入耗尽后持续返回空串(模拟 prompt 重现)."""
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
        exec(_REPL_BODY, g)
        return "EXIT_OK", calls["n"]
    except RuntimeError as e:
        return "DEADLOOP", str(e)
    finally:
        builtins.input = old


def test_quit_directly_exits():
    result, calls = _run_repl(["/quit", "", ""])
    assert result == "EXIT_OK"
    assert calls == 1


def test_quit_after_message_exits():
    result, calls = _run_repl(["hello", "", "/quit", ""])
    assert result == "EXIT_OK"
    assert calls == 3


def test_empty_input_continues():
    result, calls = _run_repl(["", "/quit", ""])
    assert result == "EXIT_OK"
    assert calls == 2

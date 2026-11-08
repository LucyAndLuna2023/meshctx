# -*- coding: utf-8 -*-
"""settle window 回归测试 (002codex 放行条件 1: 补 settle 回归测试)."""
from __future__ import annotations
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _poller_src():
    s = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    m = re.search(r"python3 - <<'EOF'\n(.*?)\n          EOF", s, re.S)
    assert m, "ci.yml poller heredoc not found"
    return m.group(1)


def test_settle_uses_loop_variable():
    """002codex B1: settle 分支不得引用未定义变量 (旧 _loop 会 NameError)."""
    src = _poller_src()
    m = re.search(r"for (\w+) in range\(60\)", src)
    assert m, "poller loop not found"
    loop_var = m.group(1)
    assert "_loop" not in src, "settle 分支仍引用未定义的 _loop"
    assert "if " + loop_var + " < 50" in src, f"settle 分支应使用循环变量 {loop_var}"


def test_settle_waits_before_judging_missing():
    """002codex settle 语义: missing 时先等 (~25min), 超时才 fail-closed."""
    src = _poller_src()
    assert "if missing:" in src
    assert "continue" in src, "missing 分支应 continue 等待"
    assert "等待超时" in src, "超时后应 fail-closed"


def test_race_condition_completed_only():
    """002codex R4: 只对 completed run 判红 (in_progress conclusion=None 不入 bad)."""
    src = _poller_src()
    assert "not active and bad" in src, "bad 判定必须在 not active 之后 (时序竞态)"

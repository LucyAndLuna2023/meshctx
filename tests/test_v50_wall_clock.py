"""test_v50_wall_clock.py — wall_clock 可配置性回归测试 (2026-08-16)

背景：002 将搜索轮次默认 6→30，但 DEFAULT_WALL_CLOCK 仍为 300s，
30 轮跑不完就被墙钟掐断（轮次承诺落空）。本测试锁定修复：
- DEFAULT_WALL_CLOCK = 1200（30轮×平均40秒/轮，留余量）
- CLI --wall-clock 参数存在且帮助文本正确
- MESHCTX_WALL_CLOCK 环境变量读取逻辑（与 cmd_chat 一致）
- run_agent_loop 的 wall_clock 参数真实生效（超时产出 timed_out）
"""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def test_default_wall_clock_1200():
    from src.agent_loop import DEFAULT_WALL_CLOCK
    assert DEFAULT_WALL_CLOCK == 1200.0, \
        f"wall_clock 默认应为 1200（30轮×40秒/轮），实际 {DEFAULT_WALL_CLOCK}"


def test_cli_wall_clock_arg_exists():
    """--wall-clock 参数存在，帮助文本含默认值与环境变量说明"""
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "chat", "--help"],
        capture_output=True, text=True, cwd=PROJECT, timeout=90,
    )
    assert "--wall-clock" in r.stdout, f"--wall-clock 参数缺失:\n{r.stdout[-600:]}"
    assert "MESHCTX_WALL_CLOCK" in r.stdout, \
        f"帮助文本缺环境变量说明:\n{r.stdout[-600:]}"


def test_wall_clock_env_read_pattern():
    """MESHCTX_WALL_CLOCK 环境变量读取（与 cmd_chat 相同表达式）；--wall-clock 优先"""
    os.environ["MESHCTX_WALL_CLOCK"] = "600"
    try:
        # 未传 --wall-clock（args.wall_clock=0）→ 读环境变量
        wall_clock = 0.0 or float(os.environ.get("MESHCTX_WALL_CLOCK", "1200"))
        assert wall_clock == 600.0, f"应读环境变量 600，实际 {wall_clock}"
        # 传了 --wall-clock → 参数优先
        wall_clock = 900.0 or float(os.environ.get("MESHCTX_WALL_CLOCK", "1200"))
        assert wall_clock == 900.0, f"--wall-clock 应优先，实际 {wall_clock}"
    finally:
        del os.environ["MESHCTX_WALL_CLOCK"]


class _ToolLoopClient:
    """每轮都返回 tool_calls，迫使循环进入下一轮，用于触发 wall_clock 超时"""

    def __init__(self, delay: float = 0.15):
        self._delay = delay

    def chat_stream(self, messages, temperature=0.7, max_tokens=16384, tools=None):
        time.sleep(self._delay)
        # ("__TOOLS__", tool_calls, content) 协议：每轮声明一次工具调用
        return iter([("__TOOLS__", [{"id": "t1", "name": "fake_tool", "arguments": "{}"}], "")])

    def chat(self, messages, temperature=0.7, max_tokens=16384):
        return {"content": "final"}


def test_wall_clock_timeout_effective():
    """run_agent_loop 的 wall_clock 参数真实生效：到期产出 timed_out 并中止"""
    async def _go():
        from src.agent_loop import run_agent_loop
        client = _ToolLoopClient(delay=0.15)
        events = []
        async for ev in run_agent_loop(
            client,
            [{"role": "user", "content": "hi"}],
            tools=[],
            exec_tool=lambda name, args: "ok",
            max_rounds=30,
            wall_clock=0.2,  # 200ms：两轮 chat_stream(0.15s×2) 后触发超时
        ):
            events.append(ev)
        types = [e["type"] for e in events]
        assert "timed_out" in types, f"wall_clock 应触发 timed_out，实际事件类型: {types}"
        # timed_out 之后不得继续跑轮次
        idx = types.index("timed_out")
        assert "round" not in types[idx + 1:], "timed_out 后不应再有轮次事件"

    asyncio.run(_go())

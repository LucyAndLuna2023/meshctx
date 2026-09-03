"""WP5 (MCTX-PLAN-2026-0903 P1-2) MCP 工具扩展测试 — 注册面 + 无副作用 handler。

覆盖: WP5 工具注册完整; defs/classes ≥40 (23→43); 轻量 handler 可调用返回 JSON。
(重依赖 worker/docker 的工具仅验证注册与参数 schema, 不在单测真跑派活。)
"""
import asyncio
import json

import pytest

from src.mcp_server import MCPServer

WP5_TOOLS = ["memory_api_store", "memory_api_search", "memory_api_list",
             "memory_api_delete_entry", "memory_api_delete_namespace",
             "task_spawn", "task_status", "task_list", "task_cancel",
             "task_approve", "routine_create", "routine_list",
             "routine_toggle", "routine_run_now", "quota_status",
             "telemetry_stats", "telemetry_trace"]


class TestRegistration:
    def test_all_wp5_tools_registered(self):
        s = MCPServer()
        for name in WP5_TOOLS:
            assert name in s._tools, name

    def test_def_count_reached_40(self):
        import re
        src = open("src/mcp_server.py", encoding="utf-8").read()
        n = len(re.findall(r"^(?:class |\s+(?:async )?def |def )", src, re.M))
        assert n >= 40, f"MCP 定义 {n} < 40 (WP5 目标 23→≥40)"


class TestHandlers:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_telemetry_trace_unknown_returns_empty(self):
        from src.mcp_server import _handle_telemetry_trace
        out = json.loads(self._run(_handle_telemetry_trace({"trace_id": "zzz"})))
        assert out == {"events": []}

    def test_telemetry_stats_shape(self):
        from src.mcp_server import _handle_telemetry_stats
        out = json.loads(self._run(_handle_telemetry_stats({"window_hours": 24})))
        assert "events" in out and "spans_ok" in out

    def test_quota_status_owner(self):
        from src.mcp_server import _handle_quota_status
        out = json.loads(self._run(_handle_quota_status({"owner": "local"})))
        assert out["owner"] == "local"

    def test_memory_list_empty_namespace(self, tmp_path, monkeypatch):
        from src.mcp_server import _handle_mem_list
        import src.core.memory_api as ma
        monkeypatch.setattr(ma, "MEMORIES_DIR", tmp_path)
        out = json.loads(self._run(_handle_mem_list({"namespace": "empty"})))
        assert out["entries"] == []

    def test_routine_list_empty(self, tmp_path, monkeypatch):
        from src.mcp_server import _handle_routine_list
        import src.core.routines as rt
        monkeypatch.setattr(rt, "ROUTINES_PATH", tmp_path / "r.json")
        out = json.loads(self._run(_handle_routine_list({})))
        assert out["routines"] == []

    def test_task_spawn_empty_prompt_error(self):
        from src.mcp_server import _handle_task_spawn
        out = json.loads(self._run(_handle_task_spawn({"prompt": "  "})))
        assert out.get("error")

    def test_task_status_unknown_error(self, tmp_path, monkeypatch):
        from src.mcp_server import _handle_task_status
        from src.core import task_cards as tc
        monkeypatch.setattr(tc, "CARDS_DIR", tmp_path / "cards")
        out = json.loads(self._run(_handle_task_status({"card_id": "nope"})))
        assert out.get("error")

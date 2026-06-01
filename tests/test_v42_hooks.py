"""Tests for Hooks Engine — v2.42"""
import pytest, tempfile, time, os
from pathlib import Path
from src.core.hooks_engine import (
    HooksEngine, HookEvent, HookRule, HookContext, get_hooks,
)


class TestHooksEngine:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = HooksEngine(config_path=os.path.join(self.tmp, "hooks.json"))

    def test_init_empty(self):
        assert len(self.engine.rules) == 0

    def test_add_rule(self):
        r = self.engine.add_rule(HookEvent.PRE_TOOL, "Bash", "echo test")
        assert len(self.engine.rules) == 1
        assert r.event == HookEvent.PRE_TOOL

    def test_remove_rule(self):
        self.engine.add_rule(HookEvent.STOP, "*", "echo done")
        assert self.engine.remove_rule(0)
        assert len(self.engine.rules) == 0

    def test_fire_matching_rule(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "Bash", "echo 'tool used'")
        ctx = HookContext(event=HookEvent.PRE_TOOL, tool_name="Bash(git status)")
        result = self.engine.fire(HookEvent.PRE_TOOL, ctx)
        assert result["fired"] >= 1

    def test_fire_no_match(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "Write", "echo 'write'")
        ctx = HookContext(event=HookEvent.PRE_TOOL, tool_name="Bash(ls)")
        result = self.engine.fire(HookEvent.PRE_TOOL, ctx)
        assert result["fired"] == 0

    def test_block_command(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "Bash(*rm -rf *)",
                            'exit 2', "command", 100)
        ctx = HookContext(event=HookEvent.PRE_TOOL, tool_name="Bash(rm -rf /tmp/test)")
        result = self.engine.fire(HookEvent.PRE_TOOL, ctx)
        assert result["blocked"] >= 1

    def test_wildcard_match(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "Bash(git *)", "echo git")
        ctx = HookContext(event=HookEvent.PRE_TOOL, tool_name="Bash(git commit -m msg)")
        result = self.engine.fire(HookEvent.PRE_TOOL, ctx)
        assert result["fired"] >= 1

    def test_cooldown(self):
        r = self.engine.add_rule(HookEvent.POST_TOOL, "Write",
                                "echo done", cooldown_s=10)
        r.last_triggered = time.time()  # Just triggered
        ctx = HookContext(event=HookEvent.POST_TOOL, tool_name="Write(test.py)")
        result = self.engine.fire(HookEvent.POST_TOOL, ctx)
        assert result["fired"] == 0  # Cooldown active

    def test_security_defaults(self):
        self.engine.enable_security_defaults()
        assert len(self.engine.rules) >= 4

    def test_persistence(self):
        self.engine.add_rule(HookEvent.STOP, "test", "echo test")
        self.engine._save()

        e2 = HooksEngine(config_path=os.path.join(self.tmp, "hooks.json"))
        assert len(e2.rules) == 1
        assert e2.rules[0].matcher == "test"

    def test_get_stats(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "test", "echo")
        stats = self.engine.get_stats()
        assert stats["total_rules"] == 1
        assert "rules_by_event" in stats

    def test_multiple_events(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "Bash", "echo pre")
        self.engine.add_rule(HookEvent.POST_TOOL, "Bash", "echo post")
        self.engine.add_rule(HookEvent.STOP, "", "echo stop")

        # Fire PRE_TOOL
        ctx = HookContext(event=HookEvent.PRE_TOOL, tool_name="Bash(ls)")
        r1 = self.engine.fire(HookEvent.PRE_TOOL, ctx)
        assert r1["fired"] == 1  # Only PRE_TOOL matches

        # Fire STOP
        r2 = self.engine.fire(HookEvent.STOP, HookContext(event=HookEvent.STOP))
        assert r2["fired"] == 1  # Only STOP matches

    def test_list_rules(self):
        self.engine.add_rule(HookEvent.PRE_TOOL, "Bash", "echo")
        self.engine.add_rule(HookEvent.POST_TOOL, "Write", "echo")
        rules = self.engine.list_rules()
        assert len(rules) == 2
        assert rules[0]["index"] == 0


class TestHookContext:
    def test_defaults(self):
        ctx = HookContext(event=HookEvent.SESSION_START)
        assert ctx.tool_name == ""
        assert ctx.user_message == ""

    def test_with_data(self):
        ctx = HookContext(event=HookEvent.PRE_TOOL, tool_name="Write(test.py)",
                         tool_input={"code": "print(1)"}, session_id="s1")
        assert ctx.tool_name == "Write(test.py)"
        assert ctx.session_id == "s1"


class TestHookEvent:
    def test_all_events(self):
        events = list(HookEvent)
        assert len(events) >= 7  # 7 unique events (aliases don't add to iteration)
        assert HookEvent.USER_PROMPT in events
        assert HookEvent.SUBAGENT_STOP in events

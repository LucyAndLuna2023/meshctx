"""v3.64 Desktop Agent — tests"""
import pytest
from src.core.desktop_agent import DesktopAgent, get_desktop_agent

class TestDesktopAgent:
    def test_list_windows(self):
        da = DesktopAgent()
        wins = da.list_windows()
        assert isinstance(wins, list)

    def test_run_command(self):
        da = DesktopAgent()
        out = da.run_command("echo hello")
        assert "hello" in out

    def test_stats(self):
        da = DesktopAgent()
        s = da.get_stats()
        assert "platform" in s

    def test_singleton(self):
        assert get_desktop_agent() is get_desktop_agent()

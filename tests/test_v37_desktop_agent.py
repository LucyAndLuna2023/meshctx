"""v3.64 Desktop Agent tests — updated for v3.83 API"""
import pytest
from src.core.desktop_agent import DesktopAgent, DesktopAction, WindowInfo, get_desktop_agent


class TestWindowInfo:
    def test_creation(self):
        w = WindowInfo(title="Test", pid=1234, handle="0x123", visible=True)
        assert w.title == "Test"
        assert w.pid == 1234

    def test_defaults(self):
        w = WindowInfo()
        assert w.title == ""
        assert w.visible is True


class TestDesktopAction:
    def test_action_creation(self):
        a = DesktopAction(action="click", target="button", 
                         params={"x": 100, "y": 200})
        assert a.action == "click"
        assert a.target == "button"
        assert a.params["x"] == 100

    def test_default_values(self):
        a = DesktopAction()
        assert a.action == ""
        assert a.result is None
        assert a.error == ""


class TestDesktopAgent:
    def test_init(self):
        agent = DesktopAgent()
        assert agent is not None

    def test_list_windows(self):
        agent = DesktopAgent()
        windows = agent.list_windows()
        assert isinstance(windows, list)

    def test_get_stats(self):
        agent = DesktopAgent()
        stats = agent.get_stats()
        assert isinstance(stats, dict)
        assert "actions" in stats


def test_singleton():
    a1 = get_desktop_agent()
    a2 = get_desktop_agent()
    assert a1 is a2

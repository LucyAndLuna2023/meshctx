"""
MeshCtx v3.37 — Desktop Agent Tests
测试桌面自动化引擎 (mock WinRM session)
"""
import pytest
from unittest.mock import MagicMock, patch


class TestDesktopState:
    """桌面状态快照"""
    
    def test_state_creation(self):
        from src.core.desktop_agent import DesktopState
        state = DesktopState(
            screen_width=1920, screen_height=1080,
            mouse_x=100, mouse_y=200,
            active_window="Notepad",
            visible_windows=["Notepad", "Explorer"],
        )
        assert state.screen_width == 1920
        assert state.active_window == "Notepad"
        assert len(state.visible_windows) == 2


class TestDesktopAction:
    """桌面行动枚举"""
    
    def test_all_actions(self):
        from src.core.desktop_agent import DesktopAction
        assert DesktopAction.CLICK.value == "click"
        assert DesktopAction.TYPE.value == "type"
        assert DesktopAction.KEY_PRESS.value == "key_press"
        assert DesktopAction.LAUNCH_APP.value == "launch_app"


class TestDesktopPerceptionMock:
    """桌面感知器 (mock)"""
    
    def test_get_screen_info(self):
        from src.core.desktop_agent import DesktopPerception
        p = DesktopPerception(None)
        # Without session, returns defaults
        w, h = p.get_screen_info()
        assert w == 1024
        assert h == 768
    
    def test_get_state_vector(self):
        from src.core.desktop_agent import DesktopPerception
        p = DesktopPerception(None)
        vec = p.get_state_vector()
        assert len(vec) == 64
        assert all(0.0 <= v <= 1.0 for v in vec[:6])
    
    def test_perceive_without_session(self):
        from src.core.desktop_agent import DesktopPerception
        p = DesktopPerception(None)
        state = p.perceive()
        assert state.screen_width == 1024
        assert state.screen_height == 768
        assert state.mouse_x == 0
    
    def test_list_windows_empty(self):
        from src.core.desktop_agent import DesktopPerception
        p = DesktopPerception(None)
        windows = p.list_windows()
        assert isinstance(windows, list)
        assert windows == []  # No session = empty


class TestDesktopControllerMock:
    """桌面控制器 (mock)"""
    
    def test_click_without_session(self):
        from src.core.desktop_agent import DesktopController
        ctrl = DesktopController(None)
        result = ctrl.click(100, 200)
        assert result is False  # No session = can't click
    
    def test_type_without_session(self):
        from src.core.desktop_agent import DesktopController
        ctrl = DesktopController(None)
        result = ctrl.type_text("hello")
        assert result is False
    
    def test_press_key(self):
        from src.core.desktop_agent import DesktopController
        ctrl = DesktopController(None)
        r1 = ctrl.press_key("enter")
        r2 = ctrl.press_key("escape")
        assert r1 is False and r2 is False  # No session
    
    def test_launch_app(self):
        from src.core.desktop_agent import DesktopController
        ctrl = DesktopController(None)
        r = ctrl.launch_app("notepad.exe")
        assert r is False
    
    def test_kill_process(self):
        from src.core.desktop_agent import DesktopController
        ctrl = DesktopController(None)
        r = ctrl.kill_process("notepad")
        assert r is False
    
    def test_action_history(self):
        from src.core.desktop_agent import DesktopController
        ctrl = DesktopController(None)
        ctrl.click(10, 20)
        ctrl.type_text("test")
        assert len(ctrl.action_history) == 2
        assert ctrl.action_history[0]["action"] == "click"


class TestDesktopAgent:
    """桌面Agent完整流程"""
    
    def test_observe_without_session(self):
        from src.core.desktop_agent import DesktopAgent
        agent = DesktopAgent(None)
        state = agent.observe()
        assert state.screen_width > 0
        assert isinstance(state.visible_windows, list)
    
    def test_think_default(self):
        from src.core.desktop_agent import DesktopAgent
        agent = DesktopAgent(None)
        state = agent.observe()
        result = agent.think(state, "open notepad")
        assert "score" in result
        assert "recommendation" in result
    
    def test_act_without_session(self):
        from src.core.desktop_agent import DesktopAgent, DesktopAction
        agent = DesktopAgent(None)
        r1 = agent.act(DesktopAction.CLICK, x=100, y=200)
        r2 = agent.act(DesktopAction.TYPE, text="hello")
        r3 = agent.act(DesktopAction.LAUNCH_APP, app_path="notepad.exe")
        assert r1 is False  # No session
        assert r2 is False
        assert r3 is False
    
    def test_get_stats(self):
        from src.core.desktop_agent import DesktopAgent
        agent = DesktopAgent(None)
        stats = agent.get_stats()
        assert "screen" in stats
        assert "mouse" in stats
        assert "active_window" in stats
        assert "actions_taken" in stats


class TestDesktopIntegration:
    """集成: DesktopAgent + JEPA"""
    
    def test_desktop_state_to_vector(self):
        from src.core.desktop_agent import DesktopState, DesktopPerception
        state = DesktopState(
            screen_width=1920, screen_height=1080,
            mouse_x=500, mouse_y=300,
            active_window="VS Code",
        )
        # Verify state can be used for JEPA input
        assert 0 <= state.mouse_x <= state.screen_width
    
    def test_perceive_returns_valid_state(self):
        from src.core.desktop_agent import DesktopPerception
        p = DesktopPerception(None)
        state = p.perceive()
        assert isinstance(state.screen_width, int)
        assert isinstance(state.mouse_x, int)
        assert isinstance(state.active_window, str)

"""
MeshCtx v3.37 — Desktop Agent (Windows桌面自动化引擎)

基于WinRM的桌面操控，让AI Agent直接操作真实Windows桌面：
- 屏幕感知 + 窗口管理 + 鼠标键盘控制
- 进程管理 + 文件操作 + 应用启动
- 融合JEPA世界模型：桌面状态→潜空间→预测→行动

HN趋势: Agent-desktop (99↑) — 原生桌面自动化是当前最热方向
"""
import base64
import json
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DesktopAction(Enum):
    """桌面行动类型"""
    CLICK = "click"
    TYPE = "type"
    KEY_PRESS = "key_press"
    SCREENSHOT = "screenshot"
    WINDOW_FOCUS = "window_focus"
    WINDOW_CLOSE = "window_close"
    WINDOW_LIST = "window_list"
    MOUSE_MOVE = "mouse_move"
    LAUNCH_APP = "launch_app"
    KILL_PROCESS = "kill_process"


@dataclass
class DesktopState:
    """桌面状态快照"""
    screen_width: int = 0
    screen_height: int = 0
    mouse_x: int = 0
    mouse_y: int = 0
    active_window: str = ""
    visible_windows: List[str] = field(default_factory=list)
    screenshot_b64: str = ""
    timestamp: float = 0.0


class DesktopPerception:
    """桌面感知器 — 获取Windows桌面状态"""
    
    def __init__(self, winrm_session=None):
        self.session = winrm_session
        self._last_state: Optional[DesktopState] = None
    
    def _run_ps(self, script: str, timeout_sec: int = 30) -> str:
        """执行PowerShell脚本"""
        if self.session is None:
            return ""
        try:
            shell = self.session.open_shell()
            # Encode script to base64 to avoid escaping
            b64 = base64.b64encode(script.encode('utf-16-le')).decode()
            cmd = f"powershell -EncodedCommand {b64}"
            cmd_id = self.session.run_command(shell, cmd)
            stdout, stderr, ec = self.session.get_command_output(shell, cmd_id)
            self.session.cleanup_command(shell, cmd_id)
            self.session.close_shell(shell)
            return stdout.decode(errors='replace')
        except Exception as e:
            logger.warning(f"PowerShell execute failed: {e}")
            return ""
    
    def get_screen_info(self) -> Tuple[int, int]:
        """获取屏幕分辨率"""
        script = '''
        Add-Type -AssemblyName System.Windows.Forms
        $s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        Write-Output "$($s.Width)x$($s.Height)"
        '''
        result = self._run_ps(script).strip()
        if 'x' in result:
            w, h = result.split('x')
            return int(w), int(h)
        return 1024, 768
    
    def get_mouse_position(self) -> Tuple[int, int]:
        """获取鼠标位置"""
        script = '''
        Add-Type -AssemblyName System.Windows.Forms
        $p = [System.Windows.Forms.Cursor]::Position
        Write-Output "$($p.X),$($p.Y)"
        '''
        result = self._run_ps(script).strip()
        if ',' in result:
            x, y = result.split(',')
            return int(x), int(y)
        return 0, 0
    
    def get_active_window(self) -> str:
        """获取当前激活窗口标题"""
        script = '''
        Add-Type @"
        using System; using System.Runtime.InteropServices; using System.Text;
        public class WinAPI {
            [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
            [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
            [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
        }
"@
        $hwnd = [WinAPI]::GetForegroundWindow()
        $len = [WinAPI]::GetWindowTextLength($hwnd)
        $sb = New-Object System.Text.StringBuilder($len + 1)
        [WinAPI]::GetWindowText($hwnd, $sb, $sb.Capacity)
        Write-Output $sb.ToString()
        '''
        return self._run_ps(script).strip()
    
    def list_windows(self) -> List[str]:
        """列出所有可见窗口"""
        script = '''
        Add-Type @"
        using System; using System.Runtime.InteropServices; using System.Text;
        public class WinEnum {
            public delegate bool EnumDelegate(IntPtr hWnd, int lParam);
            [DllImport("user32.dll")] public static extern bool EnumWindows(EnumDelegate lpEnumFunc, int lParam);
            [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
            [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
        }
"@
        $windows = [System.Collections.ArrayList]::new()
        $callback = {
            param($hwnd, $lparam)
            if ([WinEnum]::IsWindowVisible($hwnd)) {
                $sb = New-Object System.Text.StringBuilder(256)
                [WinEnum]::GetWindowText($hwnd, $sb, 256)
                $title = $sb.ToString()
                if ($title.Length -gt 0) { [void]$windows.Add($title) }
            }
            return $true
        }
        [WinEnum]::EnumWindows($callback, 0)
        Write-Output ($windows -join "|||")
        '''
        result = self._run_ps(script).strip()
        return [w.strip() for w in result.split('|||') if w.strip()] if result else []
    
    def perceive(self) -> DesktopState:
        """完整桌面感知 — 返回状态快照"""
        w, h = self.get_screen_info()
        mx, my = self.get_mouse_position()
        active = self.get_active_window()
        windows = self.list_windows()
        
        state = DesktopState(
            screen_width=w,
            screen_height=h,
            mouse_x=mx,
            mouse_y=my,
            active_window=active,
            visible_windows=windows,
            timestamp=time.time(),
        )
        self._last_state = state
        return state
    
    def get_state_vector(self) -> List[float]:
        """桌面状态→向量 (供JEPA世界模型使用)"""
        state = self.perceive()
        vec = [
            state.screen_width / 2560.0,
            state.screen_height / 1440.0,
            state.mouse_x / max(state.screen_width, 1),
            state.mouse_y / max(state.screen_height, 1),
            len(state.active_window) / 100.0,
            len(state.visible_windows) / 50.0,
        ]
        # Pad to 64 dim
        vec.extend([0.0] * (64 - len(vec)))
        return vec[:64]


class DesktopController:
    """桌面控制器 — 执行桌面操作"""
    
    def __init__(self, winrm_session=None):
        self.session = winrm_session
        self.action_history: List[Dict[str, Any]] = []
    
    def _run_ps(self, script: str, timeout_sec: int = 10) -> str:
        if self.session is None:
            return ""
        try:
            shell = self.session.open_shell()
            b64 = base64.b64encode(script.encode('utf-16-le')).decode()
            cmd_id = self.session.run_command(shell, f"powershell -EncodedCommand {b64}")
            stdout, stderr, ec = self.session.get_command_output(shell, cmd_id)
            self.session.cleanup_command(shell, cmd_id)
            self.session.close_shell(shell)
            return stdout.decode(errors='replace')
        except Exception as e:
            logger.warning(f"Control PS failed: {e}")
            return ""
    
    def click(self, x: int, y: int) -> bool:
        """鼠标点击"""
        script = f'''
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type @"
        using System; using System.Runtime.InteropServices;
        public class MouseOps {{
            [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
            [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, int dwExtraInfo);
            public const uint MOUSEEVENTF_LEFTDOWN = 0x02;
            public const uint MOUSEEVENTF_LEFTUP = 0x04;
        }}
"@
        [MouseOps]::SetCursorPos({x}, {y})
        [MouseOps]::mouse_event([MouseOps]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        Start-Sleep -Milliseconds 50
        [MouseOps]::mouse_event([MouseOps]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        Write-Output "clicked {x},{y}"
        '''
        result = self._run_ps(script)
        self.action_history.append({"action": "click", "x": x, "y": y, "result": result.strip()})
        return "clicked" in result
    
    def type_text(self, text: str) -> bool:
        """模拟键盘输入"""
        # Escape single quotes for PowerShell
        safe_text = text.replace("'", "''")
        script = f'''
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait('{safe_text}')
        Write-Output "typed"
        '''
        result = self._run_ps(script)
        self.action_history.append({"action": "type", "text": text[:50], "result": result.strip()})
        return "typed" in result
    
    def press_key(self, key: str) -> bool:
        """按下键盘按键 (Enter, Tab, Escape, etc.)"""
        key_map = {
            "enter": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}",
            "space": " ", "backspace": "{BS}", "delete": "{DELETE}",
            "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
            "f1": "{F1}", "f2": "{F2}", "f5": "{F5}", "f10": "{F10}",
            "ctrl_c": "^(c)", "ctrl_v": "^(v)", "ctrl_a": "^(a)",
            "alt_f4": "%({F4})", "win_r": "^{ESC}r",
        }
        send_key = key_map.get(key.lower(), "{" + key.upper() + "}")
        script = f'''
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait('{send_key}')
        Write-Output "pressed {key}"
        '''
        result = self._run_ps(script)
        self.action_history.append({"action": "key", "key": key, "result": result.strip()})
        return "pressed" in result
    
    def launch_app(self, app_path: str) -> bool:
        """启动应用"""
        script = f'Start-Process "{app_path}"; Write-Output "launched"'
        result = self._run_ps(script)
        return "launched" in result
    
    def kill_process(self, process_name: str) -> bool:
        """终止进程"""
        script = f'Stop-Process -Name "{process_name}" -Force -ErrorAction SilentlyContinue; Write-Output "killed"'
        result = self._run_ps(script)
        return "killed" in result


class DesktopAgent:
    """桌面Agent — 完整的观察→思考→行动循环
    
    融合:
    - WinRM操控: 键盘/鼠标/窗口
    - JEPA世界模型: 桌面状态→潜空间预测
    - 非生成式决策: 评估行动无需LLM
    """
    
    def __init__(self, winrm_session=None):
        self.session = winrm_session
        self.perception = DesktopPerception(winrm_session)
        self.controller = DesktopController(winrm_session)
        
        # JEPA集成
        try:
            from .jepa_world_model import get_world_model, get_non_generative_router
            self.world_model = get_world_model()
            self.router = get_non_generative_router()
        except ImportError:
            self.world_model = None
            self.router = None
    
    def observe(self) -> DesktopState:
        """观察桌面状态"""
        return self.perception.perceive()
    
    def think(self, state: DesktopState, goal: str) -> Dict[str, Any]:
        """思考: 用JEPA评估最佳行动"""
        if self.world_model and self.router:
            # 桌面状态→潜向量 (pad到world_model维度)
            import numpy as np
            raw = self.perception.get_state_vector()
            state_vec = np.zeros(self.world_model.config.embed_dim)
            state_vec[:len(raw)] = raw
            self.world_model.perceive(state_vec)
            
            # 评估目标 (非生成式)
            result = self.router.evaluate_without_generation(
                state_text=f"desktop:{state.screen_width}x{state.screen_height} active:{state.active_window}",
                action_text=goal,
                expected_outcome_text=f"goal achieved: {goal}",
            )
            return result
        return {"score": 0.5, "recommendation": "neutral"}
    
    def act(self, action: DesktopAction, **params) -> bool:
        """执行行动"""
        if action == DesktopAction.CLICK:
            return self.controller.click(params.get('x', 0), params.get('y', 0))
        elif action == DesktopAction.TYPE:
            return self.controller.type_text(params.get('text', ''))
        elif action == DesktopAction.KEY_PRESS:
            return self.controller.press_key(params.get('key', 'enter'))
        elif action == DesktopAction.LAUNCH_APP:
            return self.controller.launch_app(params.get('app_path', ''))
        elif action == DesktopAction.KILL_PROCESS:
            return self.controller.kill_process(params.get('process_name', ''))
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取Agent状态"""
        state = self._last_state or self.observe()
        return {
            "screen": f"{state.screen_width}x{state.screen_height}",
            "mouse": f"({state.mouse_x}, {state.mouse_y})",
            "active_window": state.active_window,
            "visible_windows": len(state.visible_windows),
            "actions_taken": len(self.controller.action_history),
            "last_actions": self.controller.action_history[-5:],
        }
    
    _last_state: Optional[DesktopState] = None

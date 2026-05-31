"""
meshctx v3.64 — Desktop Agent (桌面Agent)

功能:
  1. 屏幕截图: 全屏/区域
  2. 窗口管理: 枚举/激活/关闭
  3. 键盘鼠标: 模拟点击/输入
  4. 进程管理: 启动/停止/列表
"""
import logging, time, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("meshctx.desktop_agent")

@dataclass
class WindowInfo:
    title: str=""; pid: int=0; handle: str=""; visible: bool=True

@dataclass
class DesktopAction:
    action: str=""; target: str=""; params: Dict=field(default_factory=dict)
    result: Any=None; error: str=""; duration_ms: float=0

class DesktopAgent:
    def __init__(self):
        self._actions: List[DesktopAction]=[]
        self._platform = "linux"  # detect from os
    
    def screenshot(self, path: str="screenshot.png") -> bool:
        try:
            subprocess.run(["import","-window","root",path], timeout=5, check=False)
            return True
        except: return False
    
    def list_windows(self) -> List[WindowInfo]:
        windows = []
        try:
            r = subprocess.run(["wmctrl","-l"], capture_output=True, text=True, timeout=3)
            for line in r.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    windows.append(WindowInfo(handle=parts[0], title=parts[3], pid=0))
        except: pass
        return windows
    
    def activate_window(self, title_contains: str) -> bool:
        try:
            subprocess.run(["wmctrl","-a",title_contains], timeout=3, check=False)
            return True
        except: return False
    
    def type_text(self, text: str):
        try:
            subprocess.run(["xdotool","type",text], timeout=3, check=False)
        except: pass
    
    def click(self, x: int, y: int):
        try:
            subprocess.run(["xdotool","mousemove",str(x),str(y),"click","1"], timeout=3, check=False)
        except: pass
    
    def run_command(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return r.stdout or r.stderr
        except: return ""
    
    def get_stats(self) -> Dict:
        return {"platform": self._platform, "actions": len(self._actions),
                "windows": len(self.list_windows())}

_da = None
def get_desktop_agent():
    global _da
    if _da is None: _da = DesktopAgent()
    return _da

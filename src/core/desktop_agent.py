"""meshctx desktop_agent — desktop automation agent"""

import platform
import subprocess
from dataclasses import dataclass, field


@dataclass
class WindowInfo:
    """Window metadata."""
    title: str = ""
    pid: int = 0
    handle: str = ""
    visible: bool = True


@dataclass
class DesktopAction:
    """Desktop automation action."""
    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    result: str | None = None
    error: str = ""


class DesktopAgent:
    """Cross-platform desktop automation agent.

    Provides window management and command execution
    across Windows, macOS, and Linux.
    """

    def __init__(self):
        self._platform = platform.system()
        self._command_count = 0

    def list_windows(self):
        """List currently open windows.

        Returns a list of window title strings.
        Falls back gracefully on unsupported platforms.
        """
        windows = []
        try:
            if self._platform == "Linux":
                result = subprocess.run(
                    ["wmctrl", "-l"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        parts = line.split(None, 3)
                        if len(parts) >= 4:
                            windows.append(parts[3])
            elif self._platform == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-Process | Where-Object {$_.MainWindowTitle -ne ''}).MainWindowTitle"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        windows.append(line.strip())
            elif self._platform == "Darwin":
                result = subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to get name of every process whose visible is true'],
                    capture_output=True, text=True, timeout=5
                )
                for item in result.stdout.strip().split(", "):
                    if item.strip():
                        windows.append(item.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return windows

    def run_command(self, command):
        """Execute a shell command and return its output."""
        try:
            result = subprocess.run(
                command, shell=True,
                capture_output=True, text=True, timeout=30
            )
            self._command_count += 1
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return ""

    def get_stats(self):
        """Return desktop agent statistics."""
        return {
            "platform": self._platform,
            "commands_executed": self._command_count,
            "actions": self._command_count,
            "supported": self._platform in ("Linux", "Windows", "Darwin"),
        }


_agent = None


def get_desktop_agent():
    """Singleton accessor for DesktopAgent."""
    global _agent
    if _agent is None:
        _agent = DesktopAgent()
    return _agent

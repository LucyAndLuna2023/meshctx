"""
meshctx v1.8 — 平台抽象层 (Platform Abstraction Layer)
PRD §1.3 / §7.1

统一跨平台文件系统接口:
- IFileSystem: 核心接口定义
- WindowsFileSystem: Windows 实现 (\ 分隔符, AppData)
- MacOSFileSystem: macOS 实现 (/ 分隔符, ~/Library)
- LinuxFileSystem: Linux 实现 (/ 分隔符, XDG)
- auto_detect(): 自动检测当前平台
"""
import os
import sys
import platform
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional


class IFileSystem(ABC):
    """跨平台文件系统抽象接口"""
    
    @abstractmethod
    def get_config_dir(self) -> Path:
        """获取配置目录"""
        ...
    
    @abstractmethod
    def get_data_dir(self) -> Path:
        """获取数据目录"""
        ...
    
    @abstractmethod
    def get_cache_dir(self) -> Path:
        """获取缓存目录"""
        ...
    
    @abstractmethod
    def get_log_dir(self) -> Path:
        """获取日志目录"""
        ...
    
    @abstractmethod
    def normalize_path(self, path: str) -> str:
        """标准化路径 (平台分隔符)"""
        ...
    
    @abstractmethod
    def expand_path(self, path: str) -> Path:
        """展开路径 (~, %APPDATA%, 环境变量)"""
        ...


class WindowsFileSystem(IFileSystem):
    """Windows 平台实现 (PRD §3.1)
    
    路径使用反斜杠分隔符，配置存储在 %APPDATA%"""
    
    def get_config_dir(self) -> Path:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(appdata) / "Meshctx"
    
    def get_data_dir(self) -> Path:
        local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(local) / "Meshctx" / "data"
    
    def get_cache_dir(self) -> Path:
        local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(local) / "Meshctx" / "cache"
    
    def get_log_dir(self) -> Path:
        local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return Path(local) / "Meshctx" / "logs"
    
    def normalize_path(self, path: str) -> str:
        """统一使用 \\ 分隔符 (Windows 原生)"""
        return path.replace("/", "\\")
    
    def expand_path(self, path: str) -> Path:
        """展开 %VAR% 和 ~"""
        expanded = os.path.expandvars(path)
        if expanded.startswith("~"):
            expanded = os.path.expanduser(expanded)
        return Path(expanded)


class MacOSFileSystem(IFileSystem):
    """macOS 平台实现 (PRD §3.2)"""
    
    def get_config_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "Meshctx"
    
    def get_data_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "Meshctx" / "data"
    
    def get_cache_dir(self) -> Path:
        return Path.home() / "Library" / "Caches" / "Meshctx"
    
    def get_log_dir(self) -> Path:
        return Path.home() / "Library" / "Logs" / "Meshctx"
    
    def normalize_path(self, path: str) -> str:
        """统一使用 / 分隔符"""
        return path.replace("\\", "/")
    
    def expand_path(self, path: str) -> Path:
        expanded = os.path.expandvars(path)
        if expanded.startswith("~"):
            expanded = os.path.expanduser(expanded)
        return Path(expanded)


class LinuxFileSystem(IFileSystem):
    """Linux 平台实现 (PRD §3.3, XDG 规范)"""
    
    def get_config_dir(self) -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return Path(xdg) / "meshctx"
    
    def get_data_dir(self) -> Path:
        xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return Path(xdg) / "meshctx"
    
    def get_cache_dir(self) -> Path:
        xdg = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        return Path(xdg) / "meshctx"
    
    def get_log_dir(self) -> Path:
        # Linux 日志统一到 data 目录
        return self.get_data_dir() / "logs"
    
    def normalize_path(self, path: str) -> str:
        """统一使用 / 分隔符"""
        return path.replace("\\", "/")
    
    def expand_path(self, path: str) -> Path:
        expanded = os.path.expandvars(path)
        if expanded.startswith("~"):
            expanded = os.path.expanduser(expanded)
        return Path(expanded)


def _detect_platform() -> str:
    """自动检测当前平台"""
    system = platform.system()
    if system == "Windows":
        return "windows"
    elif system == "Darwin":
        return "macos"
    else:
        return "linux"


# 全局单例
_fs_instance: Optional[IFileSystem] = None


def get_filesystem() -> IFileSystem:
    """获取当前平台的 IFileSystem 实例"""
    global _fs_instance
    if _fs_instance is None:
        plat = _detect_platform()
        if plat == "windows":
            _fs_instance = WindowsFileSystem()
        elif plat == "macos":
            _fs_instance = MacOSFileSystem()
        else:
            _fs_instance = LinuxFileSystem()
    return _fs_instance


def get_platform() -> str:
    """获取当前平台标识"""
    return _detect_platform()


def wsl_to_windows(wsl_path: str) -> str:
    """WSL 路径 → Windows 路径 (PRD §7.1 路径互通)"""
    if not wsl_path.startswith("/mnt/"):
        return wsl_path
    parts = wsl_path[5:].split("/", 1)
    drive = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""
    return f"{drive}:\\{rest.replace('/', '\\')}"


def windows_to_wsl(win_path: str) -> str:
    """Windows 路径 → WSL 路径"""
    if len(win_path) < 2 or win_path[1] != ":":
        return win_path
    drive = win_path[0].lower()
    rest = win_path[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"

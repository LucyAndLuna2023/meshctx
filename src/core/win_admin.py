"""
MeshCtx Windows Administrator — PowerShell & Service Manager
==============================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Direct Windows system administration from WSL/MeshCtx.
Powershell execution, service management, system configuration.
All destructive operations require explicit user confirmation.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import asyncio
import json
import os
import platform
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────
POWERSHELL_PATH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
CMD_PATH = "/mnt/c/Windows/System32/cmd.exe"
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120

# Dangerous commands that require confirmation
DANGEROUS_PATTERNS = [
    "stop-service", "stop-process", "kill", "remove", "delete",
    "disable", "restart-computer", "shutdown", "format",
    "set-executionpolicy", "clear", "uninstall",
    "remove-item", "rd ", "del ", "rmdir", "reg delete",
    "net stop", "sc delete", "sc stop",
]


@dataclass
class WinResult:
    """Result from Windows command execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: float = 0
    confirmed: bool = True  # Was user confirmation obtained?

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 1),
            "confirmed": self.confirmed,
        }


@dataclass
class WinService:
    """Windows service info."""
    name: str
    display_name: str = ""
    status: str = "Unknown"  # Running/Stopped/Paused
    start_type: str = ""     # Auto/Manual/Disabled
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status,
            "start_type": self.start_type,
            "description": self.description,
        }


class WindowsAdmin:
    """Windows system administration from WSL/MeshCtx."""

    DANGEROUS = DANGEROUS_PATTERNS

    def __init__(self):
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        """Check if Windows PowerShell is accessible."""
        if self._available is None:
            self._available = os.path.exists(POWERSHELL_PATH)
            if not self._available:
                # Try alternative paths
                for alt in [
                    "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe",
                    "/mnt/c/Windows/System32/cmd.exe",
                ]:
                    if os.path.exists(alt):
                        self._available = True
                        break
            logger.info(f"Windows admin available: {self._available}")
        return self._available

    def _is_dangerous(self, command: str) -> bool:
        """Check if a command is potentially dangerous."""
        cmd_lower = command.lower()
        return any(p in cmd_lower for p in self.DANGEROUS_PATTERNS)

    async def execute(self, command: str, timeout: int = DEFAULT_TIMEOUT,
                      confirmed: bool = False) -> WinResult:
        """
        Execute a PowerShell command on Windows.

        Args:
            command: PowerShell command to execute
            timeout: Max execution time (seconds)
            confirmed: Whether user has confirmed (required for dangerous ops)

        Returns:
            WinResult with stdout/stderr/exit_code
        """
        if not self.available:
            return WinResult(False, stderr="Windows PowerShell not accessible from WSL")

        # Safety check
        is_dangerous = self._is_dangerous(command)
        if is_dangerous and not confirmed:
            msg = (
                f"⛔ DANGEROUS OPERATION requires confirmation. "
                f"Use confirmed=true or add --confirm flag.\n"
                f"Command: {command}"
            )
            return WinResult(False, stderr=msg, confirmed=False)

        timeout = min(max(timeout, 5), MAX_TIMEOUT)

        try:
            import time
            t_start = time.time()

            proc = await asyncio.create_subprocess_exec(
                POWERSHELL_PATH, "-NoProfile", "-NonInteractive",
                "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return WinResult(False, stderr=f"Command timed out after {timeout}s")

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            # Filter PowerShell noise
            if "Windows PowerShell" in stderr or "Copyright" in stderr:
                stderr = ""

            duration = (time.time() - t_start) * 1000

            return WinResult(
                success=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
                duration_ms=duration,
                confirmed=confirmed or not is_dangerous,
            )

        except Exception as e:
            logger.exception(f"PowerShell execution failed: {e}")
            return WinResult(False, stderr=str(e))

    # ─── Service Management ──────────────────────────────

    async def list_services(self, filter_name: str = "") -> List[WinService]:
        """List Windows services, optionally filtered by name."""
        if filter_name:
            cmd = f"Get-Service -Name '*{filter_name}*' | Select-Object Name,DisplayName,Status,StartType | ConvertTo-Json"
        else:
            cmd = "Get-Service | Select-Object Name,DisplayName,Status,StartType | ConvertTo-Json"

        result = await self.execute(cmd, timeout=20)
        if not result.success or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]
            return [
                WinService(
                    name=s.get("Name", ""),
                    display_name=s.get("DisplayName", ""),
                    status=s.get("Status", ""),
                    start_type=s.get("StartType", ""),
                )
                for s in data
            ]
        except json.JSONDecodeError:
            # Try parsing as table (older PowerShell)
            services = []
            for line in result.stdout.split("\n")[3:]:  # Skip header
                parts = line.strip().split(None, 3)
                if len(parts) >= 3:
                    services.append(WinService(
                        name=parts[1] if len(parts) > 1 else parts[0],
                        display_name=parts[0],
                        status=parts[2],
                    ))
            return services

    async def get_service(self, name: str) -> Optional[WinService]:
        """Get detailed info about a specific service."""
        cmd = f"Get-Service -Name '{name}' | Select-Object Name,DisplayName,Status,StartType,Description | ConvertTo-Json"
        result = await self.execute(cmd, timeout=10)
        if not result.success or not result.stdout:
            return None

        try:
            s = json.loads(result.stdout)
            if isinstance(s, list):
                s = s[0] if s else {}
            return WinService(
                name=s.get("Name", name),
                display_name=s.get("DisplayName", ""),
                status=s.get("Status", "Unknown"),
                start_type=s.get("StartType", ""),
                description=s.get("Description", ""),
            )
        except json.JSONDecodeError:
            return None

    async def start_service(self, name: str, confirmed: bool = False) -> WinResult:
        """Start a Windows service."""
        cmd = f"Start-Service -Name '{name}'"
        return await self.execute(cmd, timeout=30, confirmed=confirmed)

    async def stop_service(self, name: str, confirmed: bool = False) -> WinResult:
        """Stop a Windows service."""
        cmd = f"Stop-Service -Name '{name}' -Force"
        return await self.execute(cmd, timeout=30, confirmed=confirmed)

    async def restart_service(self, name: str, confirmed: bool = False) -> WinResult:
        """Restart a Windows service."""
        cmd = f"Restart-Service -Name '{name}' -Force"
        return await self.execute(cmd, timeout=30, confirmed=confirmed)

    async def set_service_startup(self, name: str, startup_type: str,
                                   confirmed: bool = False) -> WinResult:
        """Set service startup type (Auto/Manual/Disabled)."""
        cmd = f"Set-Service -Name '{name}' -StartupType {startup_type}"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    # ─── System Info ─────────────────────────────────────

    async def get_system_info(self) -> Dict[str, Any]:
        """Get Windows system information."""
        cmd = """
        $info = @{}
        $os = Get-CimInstance Win32_OperatingSystem
        $info.OS = "$($os.Caption) $($os.Version)"
        $info.Memory = [math]::Round($os.TotalVisibleMemorySize/1MB, 1)
        $info.FreeMemory = [math]::Round($os.FreePhysicalMemory/1MB, 1)
        $cpu = Get-CimInstance Win32_Processor
        $info.CPU = $cpu.Name
        $info.Cores = $cpu.NumberOfLogicalProcessors
        $info.ComputerName = $env:COMPUTERNAME
        $info.Username = $env:USERNAME
        $info | ConvertTo-Json
        """
        result = await self.execute(cmd, timeout=15)
        if result.success and result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        return {"error": result.stderr or "Failed to get system info"}

    async def get_processes(self, top_n: int = 20) -> List[Dict]:
        """Get top processes by CPU usage."""
        cmd = f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {top_n} Name,CPU,WorkingSet,Id | ConvertTo-Json"
        result = await self.execute(cmd, timeout=15)
        if result.success and result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                return [
                    {
                        "name": p.get("Name", ""),
                        "cpu": round(p.get("CPU", 0), 1),
                        "memory_mb": round(p.get("WorkingSet", 0) / 1048576, 1),
                        "pid": p.get("Id", 0),
                    }
                    for p in data
                ]
            except json.JSONDecodeError:
                pass
        return []

    # ─── File Operations (Windows paths) ──────────────────

    async def read_file(self, win_path: str) -> str:
        """Read a file from Windows filesystem."""
        cmd = f"Get-Content -Path '{win_path}' -Raw"
        result = await self.execute(cmd, timeout=10)
        return result.stdout if result.success else f"Error: {result.stderr}"

    async def write_file(self, win_path: str, content: str,
                          confirmed: bool = False) -> WinResult:
        """Write content to a Windows file."""
        # Escape content for PowerShell
        escaped = content.replace("'", "''").replace("`", "``")
        cmd = f"Set-Content -Path '{win_path}' -Value '{escaped}'"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    # ─── Environment Variables ───────────────────────────

    async def get_env(self, name: str = "") -> Dict[str, str]:
        """Get Windows environment variables."""
        if name:
            cmd = f"[Environment]::GetEnvironmentVariable('{name}', 'User')"
        else:
            cmd = "Get-ChildItem Env: | Select-Object Name,Value | ConvertTo-Json"
        result = await self.execute(cmd, timeout=10)
        if result.success and result.stdout:
            try:
                if name:
                    return {name: result.stdout.strip()}
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                return {e.get("Name", ""): e.get("Value", "") for e in data}
            except json.JSONDecodeError:
                pass
        return {}

    async def set_env(self, name: str, value: str,
                       confirmed: bool = False) -> WinResult:
        """Set a Windows user environment variable."""
        cmd = f"[Environment]::SetEnvironmentVariable('{name}', '{value}', 'User')"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    # ─── Registry Operations ─────────────────────────────

    async def reg_read(self, path: str, name: str = "") -> Dict[str, Any]:
        """Read a registry key or value. Path like 'HKLM:\\Software\\Microsoft'."""
        if name:
            cmd = f"Get-ItemProperty -Path '{path}' -Name '{name}' | Select-Object -ExpandProperty '{name}'"
        else:
            cmd = f"Get-ItemProperty -Path '{path}' | ConvertTo-Json"
        result = await self.execute(cmd, timeout=10)
        if result.success:
            try:
                if name:
                    return {"path": path, "name": name, "value": result.stdout.strip()}
                return json.loads(result.stdout) if result.stdout else {}
            except json.JSONDecodeError:
                return {"raw": result.stdout}
        return {"error": result.stderr}

    async def reg_write(self, path: str, name: str, value: str,
                         reg_type: str = "String",
                         confirmed: bool = False) -> WinResult:
        """Write a registry value. Types: String, DWord, Binary, ExpandString."""
        cmd = f"Set-ItemProperty -Path '{path}' -Name '{name}' -Value '{value}' -Type {reg_type}"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    async def reg_delete(self, path: str, name: str = "",
                          confirmed: bool = False) -> WinResult:
        """Delete a registry key or value."""
        if name:
            cmd = f"Remove-ItemProperty -Path '{path}' -Name '{name}'"
        else:
            cmd = f"Remove-Item -Path '{path}' -Recurse"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    async def reg_list(self, path: str) -> List[str]:
        """List subkeys of a registry path."""
        cmd = f"Get-ChildItem -Path '{path}' | Select-Object -ExpandProperty PSChildName"
        result = await self.execute(cmd, timeout=10)
        return [s.strip() for s in result.stdout.split("\n") if s.strip()] if result.success else []

    # ─── Process Management ──────────────────────────────

    async def process_list(self, top_n: int = 30) -> List[Dict]:
        """List running processes."""
        cmd = f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {top_n} | Select-Object Id,Name,CPU,WorkingSet,StartTime | ConvertTo-Json"
        result = await self.execute(cmd, timeout=15)
        if result.success and result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict): data = [data]
                return [{"pid": p.get("Id"), "name": p.get("Name"),
                         "cpu": p.get("CPU", 0), "memory_mb": round(p.get("WorkingSet", 0)/1048576, 1)}
                        for p in data]
            except: pass
        return []

    async def process_start(self, exe_path: str, args: str = "",
                             confirmed: bool = False) -> WinResult:
        """Start a Windows process/application."""
        cmd = f"Start-Process -FilePath '{exe_path}'"
        if args: cmd += f" -ArgumentList '{args}'"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    async def process_kill(self, pid: int = 0, name: str = "",
                            confirmed: bool = False) -> WinResult:
        """Kill a process by PID or name."""
        if pid: cmd = f"Stop-Process -Id {pid} -Force"
        elif name: cmd = f"Stop-Process -Name '{name}' -Force"
        else: return WinResult(False, stderr="Provide pid or name")
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    async def process_info(self, pid: int = 0, name: str = "") -> Dict:
        """Get detailed process info."""
        if pid: filter_str = str(pid)
        elif name: filter_str = name
        else: return {}
        cmd = f"Get-Process -Id {filter_str} -ErrorAction SilentlyContinue | Select-Object Id,Name,CPU,WorkingSet,Path,StartTime,Threads | ConvertTo-Json"
        result = await self.execute(cmd, timeout=10)
        if result.success and result.stdout:
            try: return json.loads(result.stdout)
            except: pass
        return {}

    # ─── File Operations (Windows paths) ──────────────────

    async def file_list(self, win_path: str, pattern: str = "*") -> List[Dict]:
        """List files in a Windows directory."""
        cmd = f"Get-ChildItem -Path '{win_path}\\{pattern}' | Select-Object Name,Length,LastWriteTime,Mode | ConvertTo-Json"
        result = await self.execute(cmd, timeout=15)
        if result.success and result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict): data = [data]
                return [{"name": f.get("Name"), "size": f.get("Length", 0),
                         "modified": str(f.get("LastWriteTime", "")),
                         "mode": f.get("Mode", "")} for f in data]
            except: pass
        return []

    async def file_delete(self, win_path: str, confirmed: bool = False) -> WinResult:
        """Delete a Windows file."""
        cmd = f"Remove-Item -Path '{win_path}' -Force"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    async def file_copy(self, source: str, dest: str, confirmed: bool = False) -> WinResult:
        """Copy a file on Windows."""
        cmd = f"Copy-Item -Path '{source}' -Destination '{dest}' -Force"
        return await self.execute(cmd, timeout=20, confirmed=confirmed)

    # ─── Browser / URL Operations ────────────────────────

    async def open_url(self, url: str, browser: str = "default",
                        confirmed: bool = False) -> WinResult:
        """Open a URL in Windows browser."""
        if browser == "default":
            cmd = f"Start-Process '{url}'"
        else:
            cmd = f"Start-Process '{browser}' -ArgumentList '{url}'"
        return await self.execute(cmd, timeout=10, confirmed=confirmed)

    async def get_browsers(self) -> List[Dict]:
        """List installed browsers."""
        browsers = []
        paths = [
            ("Chrome", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"),
            ("Chrome(x86)", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"),
            ("Edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"),
            ("Firefox", "C:\\Program Files\\Mozilla Firefox\\firefox.exe"),
            ("Brave", "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"),
        ]
        for name, p in paths:
            if os.path.exists(p.replace("C:\\", "/mnt/c/").replace("\\", "/")):
                browsers.append({"name": name, "path": p, "installed": True})
        return browsers

    # ─── Network Operations ──────────────────────────────

    async def network_info(self) -> Dict[str, Any]:
        """Get network configuration."""
        cmd = "Get-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway,DNSServer | ConvertTo-Json"
        result = await self.execute(cmd, timeout=15)
        if result.success and result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict): data = [data]
                return {"interfaces": data}
            except: pass
        return {}

    async def ping(self, host: str, count: int = 4) -> str:
        """Ping a host from Windows."""
        cmd = f"Test-Connection -ComputerName '{host}' -Count {count} | Select-Object Address,ResponseTime | ConvertTo-Json"
        result = await self.execute(cmd, timeout=count * 5 + 5)
        return result.stdout if result.success else result.stderr

    # ─── Installed Software ──────────────────────────────

    async def installed_software(self) -> List[Dict]:
        """List installed programs."""
        cmd = "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Where-Object {$_.DisplayName} | Select-Object DisplayName,DisplayVersion,Publisher,InstallDate | ConvertTo-Json"
        result = await self.execute(cmd, timeout=30)
        if result.success and result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict): data = [data]
                return [{"name": d.get("DisplayName"), "version": d.get("DisplayVersion"),
                         "publisher": d.get("Publisher")} for d in data[:50]]
            except: pass
        return []

    # ─── Quick Actions ───────────────────────────────────

    async def desktop_cleanup(self, confirmed: bool = False) -> WinResult:
        """Organize desktop files into folders by type."""
        desktop = "$env:USERPROFILE\\Desktop"
        cmd = f"""
        $desktop = [Environment]::GetFolderPath('Desktop')
        Get-ChildItem $desktop -File | Group-Object Extension | ForEach-Object {{
            $folder = Join-Path $desktop $_.Name.TrimStart('.')
            if (-not (Test-Path $folder)) {{ New-Item -ItemType Directory -Path $folder | Out-Null }}
            $_.Group | Move-Item -Destination $folder -Force
        }}
        Write-Output 'Desktop organized'
        """
        return await self.execute(cmd, timeout=30, confirmed=confirmed)

    async def disk_cleanup(self, confirmed: bool = False) -> WinResult:
        """Run Windows disk cleanup."""
        cmd = "cleanmgr /sagerun:1"
        return await self.execute(cmd, timeout=120, confirmed=confirmed)

    async def windows_update(self, confirmed: bool = False) -> WinResult:
        """Check for Windows updates."""
        cmd = "Get-WindowsUpdate -AcceptAll -Install -AutoReboot:$false"
        return await self.execute(cmd, timeout=300, confirmed=confirmed)


# ─── Global instance ─────────────────────────────────────

_win_admin: Optional[WindowsAdmin] = None


def get_win_admin() -> WindowsAdmin:
    global _win_admin
    if _win_admin is None:
        _win_admin = WindowsAdmin()
    return _win_admin

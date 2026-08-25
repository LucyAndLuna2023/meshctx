"""meshctx Windows Admin — real implementation (v3.115.16)"""
import subprocess, logging
from dataclasses import dataclass, field
logger = logging.getLogger("meshctx.win")

@dataclass
class WinResult:
    """Windows 管理操作结果 (2026-08-25 004meshctx 审计补齐, _known 映射契约)"""
    ok: bool = False
    stdout: str = ''
    stderr: str = ''
    exit_code: int = -1
    error: str = ''

    def to_dict(self) -> dict:
        return {"ok": self.ok, "stdout": self.stdout, "stderr": self.stderr,
                "exit_code": self.exit_code, "error": self.error}


@dataclass
class WinService:
    """Windows 服务信息 (契约补齐)"""
    name: str = ''
    status: str = ''
    display_name: str = ''


class WindowsAdmin:
    """Windows system administration via PowerShell."""
    def exec_ps(self, cmd: str, timeout: int = 30) -> dict:
        try:
            r = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True, timeout=timeout)
            return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_services(self) -> list:
        r = self.exec_ps("Get-Service | Select Name,Status,DisplayName | ConvertTo-Json")
        import json
        return json.loads(r.get("stdout", "[]")) if r["ok"] else []

    def get_processes(self, top: int = 30) -> list:
        r = self.exec_ps(f"Get-Process | Sort CPU -Desc | Select -First {top} | Select Id,ProcessName,CPU,WS | ConvertTo-Json")
        import json
        return json.loads(r.get("stdout", "[]")) if r["ok"] else []

    def get_system_info(self) -> dict:
        r = self.exec_ps("Get-ComputerInfo | Select CsName,OsName,TotalPhysicalMemory,CsProcessors | ConvertTo-Json")
        import json
        return json.loads(r.get("stdout", "{}")) if r["ok"] else {}


_win_admin = None


def get_win_admin() -> WindowsAdmin:
    """获取 WindowsAdmin 单例 (2026-08-25 004meshctx 审计补齐 — main.py 直接导入)。"""
    global _win_admin
    if _win_admin is None:
        _win_admin = WindowsAdmin()
    return _win_admin

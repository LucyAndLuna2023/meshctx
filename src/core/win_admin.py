"""meshctx Windows Admin — real implementation (v3.115.16)"""
import subprocess, logging
logger = logging.getLogger("meshctx.win")

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

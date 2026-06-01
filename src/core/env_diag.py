"""Environment Diagnostics — v3.06"""
import os, platform, sys, subprocess, json, time
from pathlib import Path
from typing import Any, Dict, List

class EnvDiagnostics:
    def diagnose(self) -> Dict:
        return {
            "os": platform.system(), "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(), "cwd": str(Path.cwd()),
            "disk_free_gb": self._disk_free(), "ram_total_gb": self._ram_total(),
            "git_installed": self._has_cmd("git"), "docker_installed": self._has_cmd("docker"),
            "pip_packages": self._pip_count(), "venv_active": sys.prefix != sys.base_prefix,
            "meshctx_version": self._get_version(),
        }
    
    def _disk_free(self) -> str:
        try:
            stat = os.statvfs("/"); return f"{stat.f_bavail*stat.f_frsize/1e9:.1f}"
        except OSError:
            return "?"
    def _ram_total(self) -> str:
        try:
            import psutil; return f"{psutil.virtual_memory().total/1e9:.1f}"
        except (ImportError, Exception):
            return "?"
    
    def _has_cmd(self, cmd: str) -> bool:
        return subprocess.run(["which", cmd], capture_output=True).returncode == 0
    
    def _pip_count(self) -> int:
        try:
            return len(subprocess.run([sys.executable,"-m","pip","list"], capture_output=True, text=True).stdout.split("\n"))
        except (subprocess.TimeoutExpired, OSError, Exception):
            return 0
    def _get_version(self) -> str:
        try:
            import re
            init = Path("/home/administrator/meshctx-local/src/core/__init__.py")
            m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text())
            return m.group(1) if m else "?"
        except (OSError, Exception):
            return "?"
    
    def get_stats(self) -> Dict: return self.diagnose()

_diag: Any = None
def get_env_diagnostics() -> EnvDiagnostics:
    global _diag
    if _diag is None: _diag = EnvDiagnostics()
    return _diag

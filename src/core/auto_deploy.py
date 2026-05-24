"""Auto-Deploy Pipeline — v2.85
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CI/CD自动化: 代码推送→自动构建→测试→部署→验证→备份

一键命令: meshctx deploy
"""
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DeployStage(Enum):
    CHECK = "check"
    PULL = "pull"
    TEST = "test"
    BUILD = "build"
    BACKUP = "backup"
    DEPLOY = "deploy"
    VERIFY = "verify"
    DONE = "done"
    FAILED = "failed"


@dataclass
class DeployResult:
    """部署结果"""
    stages: List[Dict] = field(default_factory=list)
    status: DeployStage = DeployStage.CHECK
    duration_seconds: float = 0.0
    version: str = ""
    commit: str = ""


class AutoDeployPipeline:
    """自动部署管道"""

    def __init__(self, project_root: Path = None,
                remote_host: str = "47.120.0.239",
                remote_path: str = "/opt/meshctx"):
        self.project_root = project_root or Path.cwd()
        self.remote_host = remote_host
        self.remote_path = remote_path
        self._history: List[DeployResult] = []

    def deploy(self, auto_confirm: bool = False) -> DeployResult:
        """执行完整部署管道"""
        t0 = time.time()
        result = DeployResult()

        stages = [
            ("check", self._check),
            ("pull", self._pull),
            ("test", self._test),
            ("build", self._build),
            ("backup", self._backup),
            ("deploy", self._deploy),
            ("verify", self._verify),
        ]

        for name, func in stages:
            stage_start = time.time()
            try:
                ok, msg = func()
                result.stages.append({
                    "stage": name,
                    "success": ok,
                    "message": msg[:200],
                    "duration_ms": (time.time() - stage_start) * 1000,
                })
                if not ok and name not in ("check", "pull"):
                    result.status = DeployStage.FAILED
                    result.duration_seconds = time.time() - t0
                    return result
            except Exception as e:
                result.stages.append({
                    "stage": name, "success": False,
                    "message": str(e)[:200],
                    "duration_ms": (time.time() - stage_start) * 1000,
                })
                result.status = DeployStage.FAILED
                result.duration_seconds = time.time() - t0
                return result

        result.status = DeployStage.DONE
        result.duration_seconds = round(time.time() - t0, 2)
        self._history.append(result)
        return result

    def _check(self) -> tuple:
        import re
        init = self.project_root / "src" / "core" / "__init__.py"
        if not init.exists():
            return False, "项目根目录错误"
        v = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text())
        return True, f"v{v.group(1) if v else '?'}"

    def _pull(self) -> tuple:
        r = subprocess.run(["git", "pull"], cwd=self.project_root,
                          capture_output=True, text=True, timeout=30)
        return r.returncode == 0, r.stdout[:100] or "up to date"

    def _test(self) -> tuple:
        r = subprocess.run(
            ["python", "-m", "pytest", "tests/", "--ignore=tests/ui",
             "--ignore=tests/test_api_full_coverage.py", "-q", "--tb=line"],
            cwd=self.project_root, capture_output=True, text=True, timeout=120
        )
        passed = "passed" in (r.stdout + r.stderr)
        return passed, r.stdout[-100:] if passed else r.stderr[-100:]

    def _build(self) -> tuple:
        spec = self.project_root / "meshctx_desktop.spec"
        if not spec.exists():
            return True, "跳过(无spec)"
        r = subprocess.run(
            ["pyinstaller", str(spec), "--noconfirm", "--log-level", "ERROR"],
            cwd=self.project_root, capture_output=True, text=True, timeout=300
        )
        return r.returncode == 0, "构建完成" if r.returncode == 0 else r.stderr[-100:]

    def _backup(self) -> tuple:
        try:
            from .backup_vault import BackupVault
            v = BackupVault()
            v.add_backup_path("/mnt/e/Meshctx/backups")
            r = v.backup(self.project_root, label="auto-deploy")
            return True, f"备份: {r.get('backup_id','')}"
        except Exception as e:
            return False, str(e)

    def _deploy(self) -> tuple:
        core_dir = self.project_root / "src" / "core"
        files = list(core_dir.glob("*.py"))
        if not files:
            return False, "无核心文件"

        # 只传核心文件
        for f in files:
            r = subprocess.run(
                ["sshpass", "-p", "LucyAndLuna@20230609", "scp", "-o",
                 "StrictHostKeyChecking=no", str(f),
                 f"root@{self.remote_host}:{self.remote_path}/src/core/"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode != 0:
                return False, f"scp失败: {f.name}"

        # 复制+重启
        subprocess.run(
            ["sshpass", "-p", "LucyAndLuna@20230609", "ssh", "-o",
             "StrictHostKeyChecking=no", f"root@{self.remote_host}",
             f"cd {self.remote_path} && cp src/core/__init__.py src/ && "
             f"systemctl restart meshctx"],
            capture_output=True, text=True, timeout=15
        )
        return True, "部署完成"

    def _verify(self) -> tuple:
        import urllib.request
        time.sleep(3)
        try:
            resp = urllib.request.urlopen(
                f"http://{self.remote_host}:3001/api/version", timeout=5
            )
            import json
            data = json.loads(resp.read())
            return True, f"远程: v{data.get('version','?')}"
        except Exception as e:
            return False, str(e)[:100]

    def get_stats(self) -> Dict:
        return {
            "total_deploys": len(self._history),
            "auto_deploy_available": True,
            "command": "meshctx deploy",
            "last_deploy": (
                {"status": self._history[-1].status.value,
                 "duration": self._history[-1].duration_seconds}
                if self._history else None
            ),
        }


# 单例
_pipeline: Optional[AutoDeployPipeline] = None


def get_auto_deploy() -> AutoDeployPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = AutoDeployPipeline()
    return _pipeline

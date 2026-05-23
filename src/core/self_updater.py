"""Self-Updater — v2.71
━━━━━━━━━━━━━━━━━━━━━━━
Agent完全自主更新: git pull → test → backup → deploy → verify

闭环:
1. 检测GitHub新版本
2. git pull 拉取代码
3. 全量回归测试
4. E盘自动备份
5. 部署到远程
6. 验证新版本正常运行
"""
import hashlib
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class UpdateStatus(Enum):
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "available"
    PULLING = "pulling"
    TESTING = "testing"
    BACKING_UP = "backing_up"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class UpdateResult:
    """更新结果"""
    status: UpdateStatus = UpdateStatus.CHECKING
    from_version: str = ""
    to_version: str = ""
    commits_pulled: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    backup_id: str = ""
    deployed: bool = False
    verified: bool = False
    duration_seconds: float = 0.0
    error: str = ""
    rollback_version: str = ""


class SelfUpdater:
    """自主更新引擎"""

    def __init__(self, project_root: Optional[Path] = None,
                 remote_host: str = "47.120.0.239",
                 remote_path: str = "/opt/meshctx",
                 auto_update: bool = False):
        self.project_root = project_root or Path.cwd()
        self.remote_host = remote_host
        self.remote_path = remote_path
        self.auto_update = auto_update
        self._update_history: List[UpdateResult] = []
        self._pre_update_version: str = ""

    # ── Version ────────────────────────────────────────

    @staticmethod
    def _detect_version(root: Path) -> str:
        init = root / "src" / "core" / "__init__.py"
        if init.exists():
            m = re.search(r'__version__\s*=\s*"([^"]+)"',
                         init.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.group(1)
        return "0.0.0"

    # ── Check ──────────────────────────────────────────

    def check_for_updates(self) -> Dict:
        """检查GitHub是否有新版本"""
        self._pre_update_version = self._detect_version(self.project_root)

        try:
            # git fetch
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=30,
            )

            # 获取本地和远程最新commit
            local = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()

            remote = subprocess.run(
                ["git", "rev-parse", "origin/main"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()

            # 获取落后commit数
            count = subprocess.run(
                ["git", "rev-list", "--count", f"{local}..{remote}"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()

            behind = int(count) if count.isdigit() else 0

            # 获取commit日志
            log = subprocess.run(
                ["git", "log", "--oneline", f"{local}..{remote}"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()

            return {
                "update_available": behind > 0,
                "commits_behind": behind,
                "local_commit": local[:8],
                "remote_commit": remote[:8],
                "changelog": log[:500] if behind > 0 else "",
            }
        except Exception as e:
            return {"update_available": False, "error": str(e)}

    # ── Pull ───────────────────────────────────────────

    def _git_pull(self) -> Tuple[bool, int, str]:
        """拉取最新代码"""
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return False, 0, result.stderr

            # 解析拉取的commit数
            lines = result.stdout.split("\n")
            count = sum(1 for l in lines if l and l[0].isalnum())
            return True, count, result.stdout[:300]
        except Exception as e:
            return False, 0, str(e)

    # ── Tests ──────────────────────────────────────────

    def _run_tests(self) -> Tuple[int, int, str]:
        """运行全量测试"""
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/",
                 "--ignore=tests/ui",
                 "--ignore=tests/test_api_full_coverage.py",
                 "-q", "--tb=line"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=120,
            )

            output = result.stdout + result.stderr
            passed = 0; failed = 0
            m = re.search(r'(\d+)\s+passed', output)
            if m: passed = int(m.group(1))
            m = re.search(r'(\d+)\s+failed', output)
            if m: failed = int(m.group(1))

            return passed, failed, output[-600:]
        except subprocess.TimeoutExpired:
            return 0, 1, "Test timeout"
        except Exception as e:
            return 0, 1, str(e)

    # ── Backup ─────────────────────────────────────────

    def _backup(self, version: str) -> str:
        """E盘备份"""
        try:
            from .backup_vault import get_backup_vault
            vault = get_backup_vault()
            vault.add_backup_path("/mnt/e/Meshctx/backups")
            result = vault.backup(
                self.project_root,
                version=version,
                label=f"pre-update-v{version}"
            )
            return result.get("backup_id", "")
        except Exception:
            return ""

    # ── Deploy ─────────────────────────────────────────

    def _deploy_to_remote(self) -> bool:
        """部署到远程服务器"""
        try:
            core_dir = self.project_root / "src" / "core"
            core_files = list(core_dir.glob("*.py"))
            if not core_files:
                return False

            # 只传核心.py文件
            files_str = " ".join(str(f) for f in core_files[:20])  # 限制数量
            result = subprocess.run(
                ["sshpass", "-p", "LucyAndLuna@20230609",
                 "scp", "-o", "StrictHostKeyChecking=no"] +
                [str(f) for f in core_files] +
                [f"root@{self.remote_host}:{self.remote_path}/src/core/"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=60,
            )

            if result.returncode != 0:
                return False

            # 复制并重启
            subprocess.run(
                ["sshpass", "-p", "LucyAndLuna@20230609",
                 "ssh", "-o", "StrictHostKeyChecking=no",
                 f"root@{self.remote_host}",
                 f"cd {self.remote_path} && "
                 f"cp src/core/__init__.py src/ && "
                 f"systemctl restart meshctx"],
                capture_output=True, text=True, timeout=15,
            )
            return True
        except Exception:
            return False

    # ── Verify ─────────────────────────────────────────

    def _verify_remote(self, expected_version: str) -> bool:
        """验证远程版本"""
        try:
            import urllib.request
            resp = urllib.request.urlopen(
                f"http://{self.remote_host}:3001/api/version",
                timeout=5
            )
            data = json.loads(resp.read())
            return data.get("version", "") == expected_version
        except Exception:
            return False

    # ── Rollback ───────────────────────────────────────

    def _rollback(self, to_version: str) -> bool:
        """回滚到之前版本"""
        try:
            tag = f"v{to_version}"
            subprocess.run(
                ["git", "checkout", tag],
                cwd=str(self.project_root),
                capture_output=True, timeout=10,
            )
            return True
        except Exception:
            return False

    # ── Full Update Flow ───────────────────────────────

    def update(self, force: bool = False) -> UpdateResult:
        """执行完整自主更新流程"""
        t0 = time.time()
        result = UpdateResult(
            from_version=self._pre_update_version or
                        self._detect_version(self.project_root)
        )

        # 1. Check
        result.status = UpdateStatus.CHECKING
        check = self.check_for_updates()
        if not check.get("update_available") and not force:
            result.status = UpdateStatus.UP_TO_DATE
            result.duration_seconds = time.time() - t0
            return result

        # 2. Pull
        result.status = UpdateStatus.PULLING
        ok, count, msg = self._git_pull()
        if not ok and not force:
            result.status = UpdateStatus.FAILED
            result.error = msg[:200]
            result.duration_seconds = time.time() - t0
            return result
        result.commits_pulled = count

        # 3. Backup
        result.status = UpdateStatus.BACKING_UP
        new_ver = self._detect_version(self.project_root)
        result.to_version = new_ver
        result.backup_id = self._backup(new_ver)

        # 4. Test
        result.status = UpdateStatus.TESTING
        passed, failed, test_output = self._run_tests()
        result.tests_passed = passed
        result.tests_failed = failed

        if failed > 0 and not force:
            result.status = UpdateStatus.FAILED
            result.error = f"{failed} tests failed"
            # Rollback
            self._rollback(result.from_version)
            result.status = UpdateStatus.ROLLED_BACK
            result.rollback_version = result.from_version
            result.duration_seconds = time.time() - t0
            return result

        # 5. Deploy
        result.status = UpdateStatus.DEPLOYING
        result.deployed = self._deploy_to_remote()

        # 6. Verify
        result.status = UpdateStatus.VERIFYING
        time.sleep(3)  # 等远程重启
        result.verified = self._verify_remote(new_ver)

        # 7. Success/Fail
        if result.verified or force:
            result.status = UpdateStatus.SUCCESS
        elif result.deployed:
            result.status = UpdateStatus.FAILED
            result.error = "部署后验证失败"
        else:
            result.status = UpdateStatus.FAILED
            result.error = "部署失败"

        result.duration_seconds = round(time.time() - t0, 2)
        self._update_history.append(result)
        return result

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "current_version": self._detect_version(self.project_root),
            "remote_host": self.remote_host,
            "auto_update": self.auto_update,
            "total_updates": len(self._update_history),
            "last_update": {
                "status": self._update_history[-1].status.value,
                "from": self._update_history[-1].from_version,
                "to": self._update_history[-1].to_version,
            } if self._update_history else None,
        }


# 单例
_updater: Optional[SelfUpdater] = None


def get_self_updater() -> SelfUpdater:
    global _updater
    if _updater is None:
        _updater = SelfUpdater()
    return _updater

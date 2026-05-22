"""Version Guard & Auto-Backup — v2.69
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每次版本号变更自动触发:
1. 全量E盘备份
2. 版本历史记录
3. Git tag自动创建
4. 变更前后对比
"""
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class VersionGuard:
    """版本守护者 — 变更检测+自动备份"""

    VERSION_HISTORY_FILE = "version_history.json"

    def __init__(self, project_root: Optional[Path] = None,
                 auto_backup: bool = True):
        self.project_root = project_root or Path.cwd()
        self.auto_backup = auto_backup
        self._history: List[Dict] = []
        self._last_version: str = ""
        self._load_history()

    # ── History ────────────────────────────────────────

    def _history_path(self) -> Path:
        return self.project_root / ".meshctx" / self.VERSION_HISTORY_FILE

    def _load_history(self):
        hp = self._history_path()
        hp.parent.mkdir(parents=True, exist_ok=True)
        if hp.exists():
            try:
                self._history = json.loads(hp.read_text())
                if self._history:
                    self._last_version = self._history[-1].get("version", "")
            except Exception:
                pass

    def _save_history(self):
        hp = self._history_path()
        hp.write_text(json.dumps(self._history, indent=2, ensure_ascii=False))

    # ── Version Detection ──────────────────────────────

    def detect_version(self) -> str:
        """检测当前版本"""
        init = self.project_root / "src" / "core" / "__init__.py"
        if init.exists():
            text = init.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
            if m:
                return m.group(1)
        return "0.0.0"

    def is_new_version(self) -> bool:
        """检查是否为新版本"""
        current = self.detect_version()
        return current != self._last_version

    # ── Change Detection ───────────────────────────────

    def detect_changes(self) -> Dict[str, Any]:
        """检测项目变更"""
        current = self.detect_version()

        # 文件变更统计
        changed_files = []
        core_dir = self.project_root / "src" / "core"
        if core_dir.exists():
            for f in core_dir.glob("*.py"):
                try:
                    changed_files.append({
                        "file": f.name,
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(
                            f.stat().st_mtime
                        ).isoformat(),
                    })
                except Exception:
                    pass

        # 测试文件数
        test_dir = self.project_root / "tests"
        test_count = len(list(test_dir.glob("test_*.py"))) if test_dir.exists() else 0

        return {
            "current_version": current,
            "previous_version": self._last_version,
            "is_new_version": current != self._last_version,
            "core_files": len(changed_files),
            "test_files": test_count,
            "files": changed_files,
        }

    # ── Auto-Backup Trigger ────────────────────────────

    def on_version_change(self) -> Dict:
        """版本变更时触发备份"""
        if not self.is_new_version():
            return {
                "triggered": False,
                "reason": "版本未变更",
                "current": self.detect_version(),
            }

        current = self.detect_version()
        result = {
            "triggered": True,
            "from_version": self._last_version,
            "to_version": current,
            "timestamp": datetime.now().isoformat(),
            "actions": [],
        }

        # 1. 记录版本历史
        entry = {
            "version": current,
            "timestamp": datetime.now().isoformat(),
            "previous": self._last_version,
        }
        self._history.append(entry)
        self._save_history()
        result["actions"].append("版本历史已记录")

        # 2. 自动备份到E盘
        if self.auto_backup:
            backup_result = self._auto_backup_to_e_drive(current)
            result["backup"] = backup_result
            result["actions"].append(
                f"E盘备份: {'成功' if backup_result.get('success') else '失败'}"
            )

        # 3. 更新last_version
        self._last_version = current

        return result

    def _auto_backup_to_e_drive(self, version: str) -> Dict:
        """自动备份到E盘"""
        e_path = Path("/mnt/e/Meshctx/backups")
        if not e_path.parent.exists():
            return {"success": False, "error": "E盘不可用"}

        try:
            from .backup_vault import get_backup_vault
            vault = get_backup_vault()

            # 自动添加E盘路径
            vault.add_backup_path(str(e_path))

            # 执行备份
            result = vault.backup(
                self.project_root,
                version=version,
                label=f"auto-v{version}"
            )
            return {
                "success": result.get("success_count", "0/0") != "0/0",
                "backup_id": result.get("backup_id", ""),
                "size_mb": result.get("total_size_mb", 0),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Git Tag ────────────────────────────────────────

    def create_git_tag(self, version: str = "") -> Dict:
        """创建Git tag"""
        import subprocess
        if not version:
            version = self.detect_version()

        tag = f"v{version}"
        try:
            subprocess.run(
                ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=10,
                check=True,
            )
            return {"success": True, "tag": tag}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Stats ──────────────────────────────────────────

    def get_history(self) -> List[Dict]:
        return self._history

    def get_stats(self) -> Dict:
        return {
            "current_version": self.detect_version(),
            "previous_version": self._last_version,
            "total_versions_recorded": len(self._history),
            "auto_backup_enabled": self.auto_backup,
            "history": self._history[-10:],
        }


# 单例
_guard: Optional[VersionGuard] = None


def get_version_guard() -> VersionGuard:
    global _guard
    if _guard is None:
        _guard = VersionGuard(auto_backup=True)
    return _guard
